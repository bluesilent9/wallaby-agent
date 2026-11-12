#!/usr/bin/python3
"""Fixed desktop-user cold-chain helper, callable only by the protected worker.

Core restarts in an independent user service even if the stream/worker fails.
Only blocks/ and chainstate/ cross the helper boundary. Wallet files stay put.
"""
import fcntl,hashlib,json,os,secrets,shutil,socket,socketserver,struct,subprocess,time
from pathlib import Path
from chain_clone_files import *
from wallet_ops import rpc
from peer_wallet import frame_read,frame_write,read_exact

class SocketStream:
    def __init__(self,s):self.s=s
    def read(self,n):return self.s.recv(n)
    def write(self,b):self.s.sendall(b);return len(b)
    def flush(self):pass

def socket_path():return Path('/run/wallaby-agent-chain')/str(os.getuid())/'clone.sock'

def connect(request):
    s=socket.socket(socket.AF_UNIX);s.settimeout(2400);s.connect(str(socket_path()))
    _,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    if uid!=os.getuid():s.close();raise CloneError('Unexpected blockchain helper owner.')
    stream=SocketStream(s);frame_write(stream,request);return s,stream

class ColdNode:
    def __init__(self,core,root):
        from wallet_recovery import process_launch,Recovery
        self.core=core;self.root=root;self.launch=process_launch(core);self.lock=None;self.locked=False;self.stopped=False;self.unit='wallaby-core-clone-'+str(time.time_ns());self.command=lambda args,suffix='',wait=False:Recovery.launch_command(None,self.launch,args,self.unit+suffix,wait)
        if Path(self.launch['netdir'])!=root:raise CloneError('Clone helper and reviewed Core do not use the same data directory.')
        for args,suffix in ((['/usr/bin/true'],'-check'),(self.launch['argv']+['-version'],'-version')):
            if subprocess.run(self.command(args,suffix,True),capture_output=True,timeout=30).returncode:raise CloneError('Independent Core restart preflight failed. Core was not stopped.')
    def stop(self):
        from wallet_recovery import process_launch
        current=process_launch(self.core)
        if (current['pid'],current['started'])!=(self.launch['pid'],self.launch['started']):raise CloneError('Core process changed after restart preflight.')
        rpc(self.core,'stop');self.stopped=True
        self.lock=(self.root/'.lock').open('r+b')
        deadline=time.monotonic()+300
        while True:
            try:
                fcntl.lockf(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                proc=Path('/proc',str(self.launch['pid']),'stat')
                try:exited=proc.read_text().rsplit(')',1)[1].split()[0]=='Z'
                except FileNotFoundError:exited=True
                if exited:self.locked=True;return
                fcntl.lockf(self.lock,fcntl.LOCK_UN)
                if time.monotonic()>deadline:raise CloneError('Core still has a live process after shutdown; no snapshot or second Core was started.')
                time.sleep(.1)
            except BlockingIOError:
                if time.monotonic()>deadline:raise CloneError('Core did not release its data-directory lock. It was not killed.')
                time.sleep(.5)
    def start(self):
        if not self.stopped:return
        if not self.locked:
            # A timed-out clean shutdown may still own the lock. Never launch a duplicate.
            if self.lock:self.lock.close();self.lock=None
            self.stopped=False
            raise CloneError('Core shutdown was not confirmed. No duplicate Core launch was attempted.')
        if self.lock:self.lock.close();self.lock=None
        args=list(self.launch['argv'])+['-datadir='+str(self.root if self.chain=='main' else self.root.parent),'-networkactive=0']
        if Path(self.launch['executable']).name=='bitcoind':args.append('-daemon=0')
        # Never replay a service launch if its result is uncertain.
        self.stopped=False
        if subprocess.run(self.command(args),capture_output=True,timeout=30).returncode:raise CloneError('Independent Core restart failed. Inspect the Core clone user service; no duplicate launch was attempted.')
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            try:
                tip=rpc(self.core,'getblockchaininfo',timeout=3)
                if tip['chain']!=self.chain:raise CloneError('Restarted Core changed networks.')
                return tip
            except Exception:time.sleep(1)
        raise CloneError('Core clone service did not become ready. Inspect its user journal; no duplicate launch was attempted.')

def checked_core(root):
    from configuration import Config,discover_cookie
    from node_client import Core
    config=Config().values;config['cookie']=config['cookie'] or discover_cookie()
    if Path(config['cookie']).expanduser().resolve().parent!=root:raise CloneError('The local desktop Core configuration changed.')
    return Core(config)

def guard_layout(root,core,receiver=False):
    no_pending(root)
    if (root/'chainstate_snapshot').exists() or (root/'chainstate'/'base_blockhash').exists():raise CloneError('AssumeUTXO snapshot chainstates are not supported for trusted cloning.')
    if receiver and rpc(core,'getindexinfo'):raise CloneError('This receiver has optional Core indexes. Rebuild/reconcile those indexes locally before cloning; existing indexes were not replaced.')
    if receiver and (root/'indexes').exists() and any((root/'indexes').iterdir()):raise CloneError('Receiver has an existing optional index directory. Cloning will not silently invalidate it.')
    # Reject custom blocks directories, symlinked databases and unreadable files.
    inventory(root)

def export(root,core,stream,review):
    guard_layout(root,core);node=ColdNode(core,root);before={**rpc(core,'getblockchaininfo'),'core_version':rpc(core,'getnetworkinfo')['version']};node.chain=before['chain']
    if before['bestblockhash']!=review['hash']:raise CloneError('Source tip changed. Review a new clone before stopping Core.')
    try:
        node.stop();rows=inventory(root);total=sum(r['bytes'] for r in rows)
        frame_write(stream,{'operation':'clone_snapshot','core_version':before['core_version'],'chain':before['chain'],'height':before['blocks'],'hash':before['bestblockhash'],'pruned':bool(before.get('pruned')),'pruneheight':before.get('pruneheight',0),'files':len(rows),'bytes':total})
        if frame_read(stream)!={'status':'clone_space_ready'}:raise CloneError('Receiver did not confirm enough staging space.')
        hashes=[]
        for row in rows:
            frame_write(stream,row);h=hashlib.sha256();p=root/row['path'];st=regular(p)
            fd=open_relative(root,row['path'],os.O_RDONLY)
            with os.fdopen(fd,'rb') as f:
                if (os.fstat(f.fileno()).st_ino,os.fstat(f.fileno()).st_size)!=(st.st_ino,row['bytes']):raise CloneError('Cold snapshot file changed.')
                left=row['bytes']
                while left:
                    part=f.read(min(CHUNK,left))
                    if not part:raise CloneError('Cold snapshot file ended early.')
                    stream.write(part);h.update(part);left-=len(part)
            value=h.hexdigest();frame_write(stream,{'sha256':value});hashes.append({**row,'sha256':value})
        frame_write(stream,{'operation':'clone_end','manifest':manifest_hash(hashes)})
        if frame_read(stream)!={'status':'clone_staged','manifest':manifest_hash(hashes)}:raise CloneError('Receiver did not verify the complete staged snapshot.')
    finally:
        node.start()
        if review.get('restore_network') is True:rpc(core,'setnetworkactive',[True])
        # Runs independently of Agent; source never stays stopped after a failed stream.

def receive_snapshot(root,stream,hello):
    fields={'operation','core_version','chain','height','hash','pruned','pruneheight','files','bytes'}
    if set(hello)!=fields or hello['operation']!='clone_snapshot' or type(hello['files']) is not int or not 0<hello['files']<=MAX_FILES or type(hello['bytes']) is not int or not 0<hello['bytes']<=MAX_TOTAL:raise CloneError('Invalid cold snapshot header.')
    free=shutil.disk_usage(root).free
    if free<hello['bytes']+max(512*1024**2,hello['bytes']//20):raise CloneError('Insufficient space to stage this clone and retain the current blockchain.')
    stage=root/('.wallaby-chain-'+secrets.token_hex(16));stage.mkdir(mode=0o700);incoming=stage/'incoming';incoming.mkdir(mode=0o700)
    write_journal(stage,{'phase':'receiving'});frame_write(stream,{'status':'clone_space_ready'});rows=[];hashes=[];seen=set();total=0
    try:
        for _ in range(hello['files']):
            row=frame_read(stream)
            if set(row)!={'path','bytes'} or not allowed(row['path']) or row['path'] in seen or type(row['bytes']) is not int or row['bytes']<0 or total+row['bytes']>hello['bytes']:raise CloneError('Invalid snapshot file or advertised size.')
            seen.add(row['path']);total+=row['bytes'];p=incoming/row['path'];h=hashlib.sha256()
            fd=open_relative(incoming,row['path'],os.O_WRONLY|os.O_CREAT|os.O_EXCL,create=True)
            with os.fdopen(fd,'wb') as f:
                left=row['bytes']
                while left:
                    part=read_exact(stream,min(CHUNK,left));f.write(part);h.update(part);left-=len(part)
                f.flush();os.fsync(f.fileno())
            expected=frame_read(stream)
            if expected!={'sha256':h.hexdigest()}:raise CloneError('Cold snapshot file checksum mismatch.')
            rows.append(row);hashes.append({**row,'sha256':h.hexdigest()})
        validate(rows)
        if total!=hello['bytes'] or frame_read(stream)!={'operation':'clone_end','manifest':manifest_hash(hashes)}:raise CloneError('Cold snapshot inventory or final checksum mismatch.')
        for parent,dirs,files in os.walk(incoming,topdown=False):syncdir(Path(parent))
        write_journal(stage,{'phase':'staged','tip':hello['hash'],'manifest':manifest_hash(hashes)})
        frame_write(stream,{'status':'clone_staged','manifest':manifest_hash(hashes)})
        return stage
    except BaseException:
        shutil.rmtree(stage);raise

def receive_clone(root,core,stream,review):
    guard_layout(root,core,receiver=True);before={**rpc(core,'getblockchaininfo'),'core_version':rpc(core,'getnetworkinfo')['version']};node=ColdNode(core,root);node.chain=before['chain']
    frame_write(stream,{'status':'clone_receiver_ready'});hello=frame_read(stream)
    from chain_clone import compatible
    compatible(before,hello)
    if hello['hash']!=review['hash']:raise CloneError('Snapshot differs from the reviewed source tip.')
    stage=receive_snapshot(root,stream,hello)
    try:
        # Source has restarted before the receiver is stopped. A broken connection
        # at this point cannot silently commit a partial or unacknowledged clone.
        if frame_read(stream)!={'operation':'clone_commit','hash':hello['hash']}:raise CloneError('Clone commit was not confirmed.')
        now={**rpc(core,'getblockchaininfo'),'core_version':rpc(core,'getnetworkinfo')['version']}
        compatible(now,hello)
        if rpc(core,'getnetworkinfo')['networkactive']:raise CloneError('Receiver Internet peers resumed during clone staging.')
        wallets={n:{'descriptors':rpc(core,'listdescriptors',[False],n),'txcount':rpc(core,'getwalletinfo',[],n)['txcount']} for n in rpc(core,'listwallets')}
        node.stop();install(root,stage)
        try:
            actual=node.start()
            if actual['bestblockhash']!=hello['hash'] or actual['blocks']!=hello['height'] or bool(actual.get('pruned'))!=bool(before.get('pruned')):raise CloneError('Cloned Core did not reopen the exact reviewed chain and pruning mode.')
            for name,old in wallets.items():
                if name not in rpc(core,'listwallets'):rpc(core,'loadwallet',{'filename':name,'load_on_startup':True},timeout=600)
                if rpc(core,'listdescriptors',[False],name)!=old['descriptors'] or rpc(core,'getwalletinfo',[],name)['txcount']<old['txcount']:raise CloneError('A receiver wallet did not retain its descriptors and transaction records.')
        except BaseException:
            # If Core is live, stop it cleanly before restoring the old directories.
            try:
                node=ColdNode(core,root);node.chain=before['chain'];node.stop();rollback(root,stage);node.start()
            except Exception:raise CloneError('Clone startup could not be verified. Original blockchain backup is retained in the clone staging directory. Inspect Core locally before further changes.') from None
            raise
        write_journal(stage,{'phase':'complete','tip':hello['hash']});shutil.rmtree(stage);syncdir(root)
        frame_write(stream,{'status':'clone_complete','height':actual['blocks'],'hash':actual['bestblockhash']})
    except BaseException:
        # Uncommitted stage contains no unique receiver data.
        state=json.loads((stage/'state.json').read_text()) if stage.exists() else {}
        if state.get('phase')=='staged':shutil.rmtree(stage)
        raise
    finally:node.start()

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(2400);stream=SocketStream(self.request)
        try:
            pid,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            group=Path('/proc',str(pid),'cgroup').read_text().splitlines();expected='/wallaby-agent-secure@'+str(os.getuid())+'.service'
            if uid!=os.getuid() or not any(line.startswith('0::/system.slice/') and line.endswith(expected) for line in group):return
            r=frame_read(stream)
            if set(r)!={'mode','netdir','hash','restore_network'} or type(r['restore_network']) is not bool or r['mode'] not in ('export','receive') or not isinstance(r['hash'],str) or not re.fullmatch('[0-9a-f]{64}',r['hash']):raise CloneError('Invalid local cold-clone request.')
            root=safe_root(r['netdir']);core=checked_core(root)
            (export if r['mode']=='export' else receive_clone)(root,core,stream,r)
        except Exception as error:
            from activity_log import event
            event('chain.clone','Helper stopped · exception='+type(error).__name__)
            try:frame_write(stream,{'status':'clone_helper_error','message':str(error) if isinstance(error,CloneError) else 'The local blockchain helper stopped. Inspect Core and its independent clone service before retrying.'})
            except Exception:pass

class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=False
    # One clone per node; reject parallel helper sessions, including source/receiver.
    gate=__import__('threading').Lock()
    def process_request_thread(self,request,client_address):
        if not self.gate.acquire(False):request.close();return
        try:super().process_request_thread(request,client_address)
        finally:self.gate.release()

def main():
    os.umask(0o077);path=socket_path();path.unlink(missing_ok=True)
    with Server(str(path),Handler) as server:path.chmod(0o600);server.serve_forever()
if __name__=='__main__':main()
