"""Bounded, acknowledged byte stream inside authenticated Agent-only Noise records.

Existing Core/file/hash/history checks consume this stream unchanged. No partial
file reaches Core. A broken stream is never automatically replayed or approved.
"""
import base64,hashlib,queue,secrets,socket,threading,time
from approval_store import digest
from peer_protocol import hexid
CHUNK=16384

def wire_hash(p):return digest({k:v for k,v in p.items() if k not in ('direction','peer','node_ipv6')})

class Stream:
    def __init__(self,bridge,channel,operation,ident):
        self.bridge=bridge;self.channel=channel;self.operation=operation;self.id=ident;self.rx=0;self.tx=0;self.incoming=queue.Queue(maxsize=4);self.buffer=bytearray();self.acks={};self.dead=False;self.lock=threading.Lock();self.opened=threading.Event()
    def message(self,kind,body):self.channel.send(kind,self.operation,{'stream_id':self.id,**body})
    def wait(self,event):
        deadline=time.monotonic()+2400
        while not event.wait(.1):
            if self.dead or self.bridge.peers.stop.is_set() or time.monotonic()>deadline:raise ValueError('Encrypted transfer interrupted. No automatic retry; inspect both Agents before continuing.')
    def write(self,data):
        raw=bytes(data)
        with self.lock:
            pending=[]
            def finish():
                position,done=pending.pop(0)
                try:self.wait(done)
                finally:self.acks.pop(position,None)
            try:
                for offset in range(0,len(raw),CHUNK):
                    if len(pending)>=4:finish()
                    part=raw[offset:offset+CHUNK];done=threading.Event();position=self.tx;self.acks[position]=done;pending.append((position,done))
                    self.message('stream_data',{'offset':position,'data':base64.b64encode(part).decode(),'sha256':hashlib.sha256(part).hexdigest()});self.tx+=len(part)
                while pending:finish()
            finally:
                for position,_ in pending:self.acks.pop(position,None)
        return len(raw)
    def read(self,size=-1):
        if not 0<=size<=1024*1024:raise ValueError('Bounded encrypted reads are required.')
        deadline=time.monotonic()+2400
        while len(self.buffer)<size:
            if self.dead:raise ValueError('Encrypted peer stream closed before completion.')
            try:part,position=self.incoming.get(timeout=.2)
            except queue.Empty:
                if time.monotonic()>deadline:raise ValueError('Encrypted peer data timed out; wallet outcome was not replayed.')
                continue
            self.buffer.extend(part);self.message('stream_ack',{'offset':position})
        result=bytes(self.buffer[:size]);del self.buffer[:size];return result
    def flush(self):pass
    def close(self):self.dead=True

class Bridge:
    def __init__(self,peers,store):self.peers=peers;self.store=store;self.streams={};self.sockets={};self.retired={};self.lock=threading.RLock();peers.listeners.append(self)
    def open(self,p):
        channel=self.peers.binding(p);self.peers.direct.require(channel);stream=Stream(self,channel,wire_hash(p),secrets.token_hex(32))
        with self.lock:
            if len(self.streams)>=4:raise ValueError('Another encrypted wallet stream is active.')
            self.streams[stream.id]=stream
        stream.message('stream_open',{'transfer_id':p['transfer_id']});stream.wait(stream.opened);return stream
    def open_blocks(self,channel,cancel=None,*,clone=False):
        self.peers.direct.require(channel)
        if channel.peer['role']!='agent':raise ValueError('Block transfer requires paired Agent permission.')
        token=secrets.token_hex(32);stream=Stream(self,channel,digest({('chain_clone_v1' if clone else 'chain_download_v2'):token}),secrets.token_hex(32))
        with self.lock:
            if len(self.streams)>=4:raise ValueError('Encrypted stream limit reached.')
            self.streams[stream.id]=stream
        try:
            stream.message('stream_open',{('clone_request' if clone else 'block_request'):token})
            deadline=time.monotonic()+20
            while not stream.opened.wait(.1):
                if stream.dead or cancel and cancel.is_set() or time.monotonic()>=deadline:raise ValueError('Direct block source did not accept this request.')
            if stream.dead:raise ValueError('Source has not enabled block serving.')
            return stream
        except Exception:self.abort(stream);raise
    def open_clone(self,channel):return self.open_blocks(channel,clone=True)
    def abort(self,stream):
        if not stream.dead:
            try:stream.message('stream_close',{})
            except Exception:pass
        self.remove(stream)
    def closed(self,peer):
        for stream in list(self.streams.values()):
            if stream.channel.peer['endpoint_id']==peer:self.remove(stream)
    def remove(self,stream):
        now=time.monotonic()
        with self.lock:
            self.retired={i:v for i,v in self.retired.items() if now-v[2]<60}
            self.retired[stream.id]=(stream.channel,stream.operation,now)
            while len(self.retired)>64:self.retired.pop(next(iter(self.retired)))
        stream.close();self.streams.pop(stream.id,None);sock=self.sockets.pop(stream.id,None)
        if sock:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            sock.close()
    def __call__(self,channel,record):
        kind=record['payload_type']
        if not kind.startswith('stream_'):return False
        self.peers.direct.require(channel)
        if channel.peer['role']!='agent':raise ValueError('Private wallet transfers require Agent permission.')
        body=record['body']
        if not isinstance(body,dict) or not hexid(body.get('stream_id')):raise ValueError('Invalid encrypted stream identity.')
        ident=body['stream_id'];stream=self.streams.get(ident)
        retired=self.retired.get(ident)
        if not stream and retired and retired[0] is channel and retired[1]==record['operation_hash'] and time.monotonic()-retired[2]<60 and kind in ('stream_ack','stream_data','stream_ready','stream_close'):return True
        if kind=='stream_open' and retired:raise ValueError('A closed stream identity cannot be reused.')
        if kind=='stream_open':
            if set(body) in ({'stream_id','block_request'},{'stream_id','clone_request'}):
                clone='clone_request' in body;token=body['clone_request' if clone else 'block_request']
                if stream or not hexid(token) or record['operation_hash']!=digest({('chain_clone_v1' if clone else 'chain_download_v2'):token}):raise ValueError('Invalid direct block request.')
                if len(self.streams)>=4:raise ValueError('Encrypted stream limit reached.')
                stream=Stream(self,channel,record['operation_hash'],ident);self.streams[ident]=stream
                blocks=getattr(self.peers,'blocks',None)
                if not blocks or not (blocks.clones.accept(stream) if clone else blocks.accept(stream)):self.abort(stream)
                else:stream.message('stream_ready',{})
                return True
            if set(body)!={'stream_id','transfer_id'} or stream:raise ValueError('Duplicate or invalid encrypted stream request.')
            state=self.store.read();batch=state.get('sync_batch',{});keys=batch.get('keys',[]) if batch.get('direction')=='receive' else [state.get('active_transfer')]
            rows=[state['pending'][k]['proposal'] for k in keys if k in state['pending'] and state['pending'][k]['state']=='pending' and not state['pending'][k].get('withdrawn') and state['pending'][k]['proposal'].get('transfer_version')==3 and state['pending'][k]['proposal']['transfer_id']==body['transfer_id']]
            if len(rows)!=1 or record['operation_hash']!=wire_hash(rows[0]) or self.peers.binding(rows[0]) is not channel:raise ValueError('No exact local receiving approval exists for this encrypted transfer.')
            if len(self.streams)>=4:raise ValueError('Encrypted wallet stream limit reached.')
            stream=Stream(self,channel,record['operation_hash'],ident);self.streams[ident]=stream
            # Bridge only after exact independent pairing + receiving authorisation.
            from peer_wallet import socket_path
            sock=socket.socket(socket.AF_UNIX);sock.settimeout(2400);sock.connect(str(socket_path(self.store)));self.sockets[ident]=sock
            threading.Thread(target=self.local_bridge,args=(stream,sock),daemon=True,name='authenticated-wallet-stream').start();stream.message('stream_ready',{});return True
        if not stream or stream.channel is not channel or record['operation_hash']!=stream.operation:raise ValueError('Stream belongs to another operation or channel.')
        if kind=='stream_ready' and set(body)=={'stream_id'}:stream.opened.set();return True
        if kind=='stream_ack' and set(body)=={'stream_id','offset'}:
            done=stream.acks.get(body['offset'])
            if done is None:raise ValueError('Unexpected encrypted stream acknowledgement.')
            done.set();return True
        if kind=='stream_data' and set(body)=={'stream_id','offset','data','sha256'}:
            if type(body['offset']) is not int or body['offset']!=stream.rx or not isinstance(body['data'],str) or len(body['data'])>22000:raise ValueError('Encrypted stream offset changed or data exceeded its bound.')
            part=base64.b64decode(body['data'],validate=True)
            if not 0<len(part)<=CHUNK or base64.b64encode(part).decode()!=body['data'] or hashlib.sha256(part).hexdigest()!=body['sha256']:raise ValueError('Encrypted stream chunk integrity check failed.')
            stream.incoming.put_nowait((part,stream.rx));stream.rx+=len(part);return True
        if kind=='stream_close' and set(body)=={'stream_id'}:self.remove(stream);return True
        raise ValueError('Invalid encrypted wallet stream record.')
    def local_bridge(self,stream,sock):
        def incoming():
            try:
                while not stream.dead:
                    try:part,position=stream.incoming.get(timeout=.2)
                    except queue.Empty:continue
                    sock.sendall(part);stream.message('stream_ack',{'offset':position})
            except Exception:self.remove(stream)
        threading.Thread(target=incoming,daemon=True).start()
        try:
            while not stream.dead:
                part=sock.recv(CHUNK)
                if not part:break
                stream.write(part)
        except Exception:pass
        finally:self.remove(stream)
