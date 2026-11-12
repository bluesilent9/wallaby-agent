"""Locally reviewed trusted cold-chain cloning, over paired direct SSH only.

Not independent genesis validation and not a substitute for Extinct history sync.
A source behind the receiver is deliberately ineligible: use catch-up and wait.
"""
import hashlib,re,threading,time,secrets
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from peer_wallet import frame_read,frame_write,read_exact
from chain_clone_files import MAX_FILES,MAX_TOTAL,CHUNK,allowed,manifest_hash,validate,CloneError

def chain_info(core):
    return {**rpc(core,'getblockchaininfo'),'core_version':rpc(core,'getnetworkinfo')['version']}

def facts(core):
    c=chain_info(core)
    return {'core_version':c['core_version'],'chain':c['chain'],'height':c['blocks'],'hash':c['bestblockhash'],'pruned':bool(c.get('pruned')),'pruneheight':c.get('pruneheight',0),'headers':c['headers'],'syncing':bool(c.get('initialblockdownload') or c['blocks']!=c['headers'])}

def compatible(receiver,source):
    if not isinstance(source,dict) or source.get('chain')!=receiver['chain'] or type(source.get('height')) is not int or not 0<=source['height']<=2**31 or not isinstance(source.get('hash'),str) or not re.fullmatch('[0-9a-f]{64}',source['hash']) or type(source.get('pruned')) is not bool or type(source.get('pruneheight')) is not int or not 0<=source['pruneheight']<=source['height']:raise CloneError('Invalid clone source chain facts.')
    if type(source.get('core_version')) is not int or not 310000<=source['core_version']<320000 or source['core_version']!=receiver.get('core_version'):raise CloneError('Use the same Bitcoin Core 31 release on both laptops before cloning. No blockchain data was replaced.')
    if source['height']<receiver['blocks']:raise CloneError('Source is behind this receiver. Use block catch-up and wait; cloning will not discard the receiver’s newer validated blocks.')
    if source['pruned'] and not receiver.get('pruned'):raise CloneError('A pruned snapshot cannot supply a full archival node. Use a full source or separately configure pruning locally; cloning does not change your pruning settings.')
    if source['pruned'] and source['pruneheight']>receiver['blocks']+1:raise CloneError('The pruned source lacks blocks needed to advance this receiver’s existing wallet history. Use a source retaining that range, or transfer verified public history separately before cloning.')
    return True

def copy_snapshot(src,dst,hello,progress=lambda n,total:None):
    fields={'operation','core_version','chain','height','hash','pruned','pruneheight','files','bytes'}
    if set(hello)!=fields or hello['operation']!='clone_snapshot' or type(hello['files']) is not int or not 0<hello['files']<=MAX_FILES or type(hello['bytes']) is not int or not 0<hello['bytes']<=MAX_TOTAL:raise CloneError('Invalid blockchain snapshot stream.')
    frame_write(dst,hello)
    if frame_read(dst)!={'status':'clone_space_ready'}:raise CloneError('Receiver helper did not confirm staging space.')
    frame_write(src,{'status':'clone_space_ready'});rows=[];hashes=[];seen=set();total=0
    for _ in range(hello['files']):
        row=frame_read(src)
        if set(row)!={'path','bytes'} or not allowed(row['path']) or row['path'] in seen or type(row['bytes']) is not int or not 0<=row['bytes']<=hello['bytes']-total:raise CloneError('Invalid or duplicate snapshot file.')
        seen.add(row['path']);frame_write(dst,row);left=row['bytes'];h=hashlib.sha256()
        while left:
            part=read_exact(src,min(CHUNK,left));dst.write(part);h.update(part);left-=len(part);total+=len(part);progress(total,hello['bytes'])
        check=frame_read(src)
        if check!={'sha256':h.hexdigest()}:raise CloneError('Blockchain file checksum mismatch.')
        frame_write(dst,check);rows.append(row);hashes.append({**row,'sha256':h.hexdigest()})
    validate(rows);end=frame_read(src)
    if total!=hello['bytes'] or end!={'operation':'clone_end','manifest':manifest_hash(hashes)}:raise CloneError('Incomplete blockchain snapshot.')
    frame_write(dst,end);receipt=frame_read(dst)
    if receipt!={'status':'clone_staged','manifest':manifest_hash(hashes)}:raise CloneError('Receiver did not verify the staged blockchain.')
    frame_write(src,receipt)
    return receipt

class Clones:
    def __init__(self,blocks):
        self.operation_lock=threading.RLock();self.guard=lambda:False;self.blocks=blocks;self.peers=blocks.peers;self.store=blocks.store;self.core=blocks.core;self.lock=threading.RLock();self.allowed=False;self.thread=None;self.offer_stream=None;self.plan=None;self.deadline=0;self.running=False;self.message='No trusted clone is active.';self.received=0;self.total=0;self.stage='idle';self.source_stream=None
    def active(self):return bool(self.running and self.deadline>time.monotonic() and (self.thread and self.thread.is_alive() or self.source_stream))
    def state(self):
        with self.lock:return {'allowed':self.allowed,'running':self.running,'stage':self.stage,'message':self.message,'received_bytes':self.received,'total_bytes':self.total,'review':{k:v for k,v in (self.plan or {}).items() if k not in ('stream',)} if self.plan and self.plan['expires']>time.time() else None}
    def idle(self,own_source=None,own_review=False):
        s=self.store.read()
        if self.source_stream and self.source_stream is not own_source or self.offer_stream and not own_review:raise CloneError('Finish or cancel the existing clone review first.')
        if self.guard() or self.running or self.blocks.thread and self.blocks.thread.is_alive() or self.blocks.serving or s.get('active_transfer') or s.get('sync_batch') or s.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning') or s.get('history_jobs'):raise CloneError('Finish wallet transfers, block receiving and pending history recovery before cloning.')
    def arm(self,enabled):
        if type(enabled) is not bool:raise CloneError('Invalid local clone permission.')
        with self.lock:
            if enabled:self.idle()
            self.allowed=enabled
        return {'message':'One trusted clone is allowed in this workspace; Core will briefly stop and restart when the paired receiver confirms.' if enabled else 'Trusted clone sharing disabled.'}
    def helper_read(self,stream):
        frame=frame_read(stream)
        if frame.get('status')=='clone_helper_error':
            message=frame.get('message')
            raise CloneError(message if isinstance(message,str) and len(message)<600 else 'The local blockchain helper refused this operation.')
        return frame
    def local_socket(self,mode,tip):
        from chain_clone_service import connect
        return connect({'mode':mode,'netdir':str(Path(self.core.config['cookie']).expanduser().resolve().parent),'hash':tip,'restore_network':bool(getattr(self,'source_network_before',False)) if mode=='export' else False})
    def review(self,ident):
        with self.lock:
            self.cancel_review();self.idle();channel=self.blocks.peer(ident);self.peers.direct.require(channel)
            stream=self.peers.wallet_bridge.open_clone(channel)
            try:
                source=frame_read(stream)
                if set(source)!={'operation','facts'} or source['operation']!='clone_offer':raise CloneError('Paired source did not offer trusted cloning. Enable it locally on the source Agent.')
                local=chain_info(self.core);compatible(local,source['facts'])
                frame_write(stream,{'operation':'clone_anchor','height':local['blocks']})
                anchor=frame_read(stream)
                if anchor!={'hash':local['bestblockhash']}:raise CloneError('The source does not contain the receiver’s current validated tip. No blockchain replacement is offered.')
                self.plan={'id':secrets.token_hex(32),'source_name':self.peers.persistence.read()['pairs'][ident]['name'],'source':ident,'source_facts':source['facts'],'receiver_height':local['blocks'],'receiver_hash':local['bestblockhash'],'expires':int(time.time())+300};self.offer_stream=stream
                return self.state()
            except Exception:self.peers.wallet_bridge.abort(stream);raise
    def cancel_review(self):
        if self.offer_stream:self.peers.wallet_bridge.abort(self.offer_stream)
        self.offer_stream=None;self.plan=None
    def start(self,ident,confirmed):
        with self.operation_lock,self.lock:
            self.idle(own_review=True);p=self.plan
            if confirmed is not True or not p or p['id']!=ident or p['expires']<time.time() or not self.offer_stream:raise CloneError('Review and explicitly confirm this exact trusted clone first.')
            local=chain_info(self.core);compatible(local,p['source_facts'])
            if local['bestblockhash']!=p['receiver_hash']:self.cancel_review();raise CloneError('Receiver chain changed since review. Review again.')
            stream=self.offer_stream;self.offer_stream=None;self.plan=None
            self.blocks.prepare(p['source']);self.running=True;self.stage='staging';self.deadline=time.monotonic()+3600;self.message='Receiving a verified cold snapshot. Receiver wallets and Internet peers remain separate.'
            self.thread=threading.Thread(target=self.receive,args=(stream,p),daemon=True,name='trusted-chain-clone');self.thread.start()
        return {'message':'Trusted blockchain clone started. Core restarts independently; keep both protected workspaces open.'}
    def progress(self,n,total):
        self.deadline=time.monotonic()+3600;self.received=n;self.total=total
    def accept(self,stream):
        with self.lock:
            if not self.allowed or self.source_stream:return False
            try:self.idle()
            except ValueError:return False
            self.source_stream=stream;self.thread=threading.Thread(target=self.serve,args=(stream,),daemon=True,name='trusted-chain-source');self.thread.start();return True
    def serve(self,stream):
        sock=None;old=None
        try:
            source=facts(self.core);frame_write(stream,{'operation':'clone_offer','facts':source});anchor=frame_read(stream)
            if set(anchor)!={'operation','height'} or anchor['operation']!='clone_anchor' or type(anchor['height']) is not int or not 0<=anchor['height']<=source['height']:raise CloneError('Invalid clone anchor request.')
            frame_write(stream,{'hash':rpc(self.core,'getblockhash',[anchor['height']])});begun=frame_read(stream)
            if begun!={'operation':'clone_begin','hash':source['hash']} or not self.allowed:raise CloneError('Clone was not locally confirmed.')
            with self.operation_lock,self.lock:
                self.idle(own_source=stream);self.allowed=False;self.running=True;self.stage='serving';self.deadline=time.monotonic()+3600
            old=rpc(self.core,'getnetworkinfo')['networkactive'];self.source_network_before=old;rpc(self.core,'setnetworkactive',[False]);rpc(self.core,'syncwithvalidationinterfacequeue',[],timeout=120)
            if facts(self.core)['hash']!=source['hash']:raise CloneError('Source chain advanced after review; review a fresh clone.')
            sock,helper=self.local_socket('export',source['hash']);hello=self.helper_read(helper);copy_snapshot(helper,stream,hello,self.progress)
            # Export helper restarts source after complete staging acknowledgement.
            # Consume its EOF; then wait for RPC before confirming source restart.
            self.wait_core();frame_write(stream,{'operation':'clone_source_restarted','hash':source['hash']});self.stage='complete';self.message='Snapshot served. Source Core restarted; its previous Internet setting was restored.'
        except Exception as error:
            from activity_log import event
            event('chain.clone','Source stopped · exception='+type(error).__name__)
            self.stage='error';self.message='Clone source stopped or became uncertain. Check Core and its independent clone service; no replacement or retry was authorised automatically.'
        finally:
            if sock:sock.close()
            if old is not None:
                try:self.wait_core();rpc(self.core,'setnetworkactive',[old])
                except Exception:pass
            self.running=False;self.deadline=0;self.source_stream=None;self.peers.wallet_bridge.abort(stream)
    def wait_core(self):
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            try:return rpc(self.core,'getblockchaininfo',timeout=3)
            except Exception:time.sleep(1)
        raise CloneError('Independent Core restart is not ready. Inspect its user service and Core log.')
    def receive(self,stream,p):
        sock=None
        try:
            sock,helper=self.local_socket('receive',p['source_facts']['hash'])
            if self.helper_read(helper)!={'status':'clone_receiver_ready'}:raise CloneError('Receiver clone helper preflight refused. Core was not stopped.')
            frame_write(stream,{'operation':'clone_begin','hash':p['source_facts']['hash']});hello=frame_read(stream)
            compatible(chain_info(self.core),hello)
            if any(hello.get(k)!=p['source_facts'].get(k) for k in ('core_version','chain','height','hash','pruned','pruneheight')):raise CloneError('Source snapshot changed after review.')
            copy_snapshot(stream,helper,hello,self.progress)
            if frame_read(stream)!={'operation':'clone_source_restarted','hash':hello['hash']}:raise CloneError('Source did not confirm its independent restart.')
            self.stage='restarting';self.message='Snapshot verified. Restarting receiver Core and checking retained wallets and history.';self.deadline=time.monotonic()+1200
            frame_write(helper,{'operation':'clone_commit','hash':hello['hash']});result=self.helper_read(helper)
            if result!={'status':'clone_complete','height':hello['height'],'hash':hello['hash']}:raise CloneError('Receiver clone startup or wallet checks were not confirmed.')
            self.stage='complete';self.message='Trusted blockchain clone complete. Receiver wallets, keys, labels and existing transaction records were retained. Internet peers remain paused. Synchronise missing Extinct history separately; cloning does not certify it.'
            from chain_sync import publish
            publish(self.store,current_height=hello['height'],source_height=hello['height'],state='cloned',message=self.message)
        except Exception as error:
            from activity_log import event
            event('chain.clone','Receiving stopped · exception='+type(error).__name__)
            self.stage='error';self.message=(str(error) if isinstance(error,CloneError) else 'Trusted clone did not confirm completion. Inspect Core and the local clone helper before retrying.')+' Original wallet data was not replaced; Internet remains paused.'
        finally:
            if sock:sock.close()
            self.running=False;self.deadline=0;self.peers.wallet_bridge.abort(stream)
