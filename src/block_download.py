"""Locally armed, block-only direct SSH download. Never changes a Core chain by fiat."""
import threading,time,secrets
from approval_store import digest
from peer_protocol import hexid
from wallet_ops import rpc
from chain_sync import publish

class SourceUnavailable(ValueError):
    def __init__(self,reason):self.reason=reason;super().__init__('Direct block source unavailable.')

def checked_read(stream):
    from peer_wallet import frame_read
    frame=frame_read(stream)
    if frame.get('operation')=='chain_unavailable':
        if set(frame)!={'operation','reason'} or frame['reason'] not in ('pruned','unavailable'):raise ValueError('Invalid source availability reply.')
        raise SourceUnavailable(frame['reason'])
    return frame

class Blocks:
    def __init__(self,peers,store,core):
        self.peers=peers;self.store=store;self.core=core;self.lock=threading.RLock();self.stop=threading.Event();self.thread=None;self.stream=None;self.serving={};self.allow=False
        # Local permissions and receiving intent expire with the protected worker.
        with store.edit() as s:
            old=s.get('block_download',{})
            s['block_download']={**old,'running':False,'serving':False}
        from chain_clone import Clones
        self.clones=Clones(self)
        self.guard=threading.Thread(target=self.guard_network,daemon=True,name='ssh-only-network-guard');self.guard.start()
    def state(self):
        saved=self.store.read();return {**saved.get('block_download',{}),'allowed':self.allow,'serving':bool(self.serving),'chain':saved.get('chain_sync',{}),'clone':self.clones.state()}
    def update(self,**data):
        with self.store.edit() as s:s.setdefault('block_download',{}).update(data)
    def guard_network(self):
        while not self.peers.stop.wait(2):
            if self.store.read().get('chain_sync',{}).get('mode')!='ssh_only':continue
            try:
                if rpc(self.core,'getnetworkinfo',timeout=3)['networkactive']:rpc(self.core,'setnetworkactive',[False],timeout=3)
            except Exception:pass # Core can be deliberately restarting with -networkactive=0.
    def peer(self,ident):
        if not hexid(ident):raise ValueError('Choose a locally paired Agent.')
        pair=self.peers.persistence.read()['pairs'].get(ident)
        if not pair or pair['peer']['role']!='agent':raise ValueError('Only a locally paired Agent can supply blocks; Mobile permission is insufficient.')
        return self.peers.channel(pair['peer']['identity_key'])
    def prepare(self,ident):
        # A disconnected but permanently pinned peer can be selected before it starts.
        pair=self.peers.persistence.read()['pairs'].get(ident)
        if not hexid(ident) or not pair or pair['peer']['role']!='agent':raise ValueError('Choose a locally paired Agent source.')
        with self.lock:
            if self.clones.running:raise ValueError('Finish trusted cloning before changing block reception.')
            if self.thread and self.thread.is_alive():raise ValueError('Stop existing block transfer before changing its source.')
            saved=self.store.read()
            if saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'):raise ValueError('Prepare SSH-only reception before starting wallet transfer or history recovery.')
            chain=rpc(self.core,'getblockchaininfo');active=rpc(self.core,'getnetworkinfo')['networkactive'];previous=saved.get('chain_sync',{})
            rpc(self.core,'setnetworkactive',[False])
            publish(self.store,mode='ssh_only',network_paused=True,network_was_active=previous.get('network_was_active',False) if previous.get('network_paused') else active,current_height=chain['blocks'],target_height=max(chain['blocks'],chain.get('headers',0)),state='prepared',message='Prepared for direct SSH blocks. Core Internet peers are paused. Existing valid blocks are retained; preparing does not reindex or erase them.')
            self.update(source=ident,prepared=True,running=False,error=None,message='Ready. If history recovery is needed, authorise it first; then click Start receiving blocks.')
        return {'message':'Receiver prepared. Internet peers are paused; no reindex or block deletion was requested.'}
    def start(self):
        with self.lock:
            if self.clones.running:raise ValueError('Finish trusted cloning before block catch-up.')
            saved=self.store.read();state=saved.get('block_download',{})
            if not state.get('prepared') or saved.get('chain_sync',{}).get('mode')!='ssh_only':raise ValueError('Prepare the receiving node first.')
            if self.thread and self.thread.is_alive():raise ValueError('Direct block receiving is already running.')
            self.stop.clear();self.update(running=True,error=None,message='Waiting for the paired source. A source behind this node will not reset or shorten its chain.')
            self.thread=threading.Thread(target=self.download,args=(state['source'],),daemon=True,name='direct-block-download');self.thread.start()
        return {'message':'Direct block receiving started. No Internet fallback is enabled.'}
    def end(self):
        with self.lock:
            self.stop.set()
            if self.stream:self.peers.wallet_bridge.abort(self.stream)
            self.update(message='Stopping block reception. Internet peers remain paused; validated blocks are retained.')
            if not self.thread or not self.thread.is_alive():self.update(running=False)
        return {'message':'Block reception is stopping. Use Resume Core Internet connections only if you want Internet downloads.'}
    def sharing(self,enabled):
        if type(enabled) is not bool:raise ValueError('Invalid block sharing choice.')
        with self.lock:
            self.allow=enabled
            if not enabled:
                for stream in list(self.serving.values()):self.peers.wallet_bridge.abort(stream)
        return {'message':'Block serving '+('enabled for locally paired Agents in this workspace.' if enabled else 'disabled.')}
    def accept(self,stream):
        with self.lock:
            if not self.allow or self.serving or self.clones.running:return False
            self.serving[stream.id]=stream
            threading.Thread(target=self.serve,args=(stream,),daemon=True,name='direct-block-source').start();return True
    def serve(self,stream):
        from peer_wallet import frame_read,frame_write
        from chain_sync import send
        try:
            while self.allow and not stream.dead and not self.peers.stop.is_set():
                send(self.core,stream,frame_read,frame_write,progressive=True)
                if frame_read(stream)!={'operation':'chain_next'}:raise ValueError('Invalid next block request.')
        except Exception as error:
            reason='pruned' if str(error).startswith('The sending node has pruned blocks needed by the receiver.') else 'unavailable'
            try:frame_write(stream,{'operation':'chain_unavailable','reason':reason})
            except Exception:pass
        finally:
            self.serving.pop(stream.id,None);self.peers.wallet_bridge.abort(stream)
    def download(self,ident):
        from peer_wallet import frame_read,frame_write,read_exact
        from chain_sync import receive,finish
        try:
            while not self.stop.is_set() and not self.peers.stop.is_set():
                try:
                    saved=self.store.read();recovery=saved.get('recovery',{})
                    if saved.get('chain_sync',{}).get('mode')!='ssh_only':raise ValueError('SSH-only mode ended.')
                    if recovery.get('state') in ('starting','stopping') or recovery.get('plan',{}).get('replay') and not recovery.get('replay_ready') and recovery.get('state') in ('downloading','rescanning'):
                        self.update(message='Waiting for local history wallets to be registered before receiving blocks.');self.stop.wait(2);continue
                    rpc(self.core,'setnetworkactive',[False],timeout=3)
                    channel=self.peer(ident);self.peers.direct.require(channel)
                    stream=self.peers.wallet_bridge.open_blocks(channel,self.stop);self.stream=stream
                    while not self.stop.is_set() and not stream.dead:
                        hello=checked_read(stream)
                        receive(self.core,self.store,stream,hello,checked_read,frame_write,read_exact);finish(self.core,self.store)
                        self.update(message='Available source blocks validated. Waiting for more; a behind or still-downloading source does not replace this node’s valid chain.')
                        if self.stop.wait(5):break
                        frame_write(stream,{'operation':'chain_next'})
                except SourceUnavailable as error:
                    if error.reason=='pruned':
                        self.update(error='source_pruned',message='The source has pruned blocks this receiver needs. Receiving stopped. Choose a source retaining that range, or prepare both nodes before replay. Internet peers remain paused.');self.stop.set()
                    elif not self.stop.is_set():self.update(message='Source Core is unavailable or restarting. Waiting to reconnect; Internet peers remain paused.')
                except Exception:
                    if not self.stop.is_set():self.update(message='Waiting for direct SSH/source blocks or local Core preparation. Check source block-serving permission and retained block range. Internet peers remain paused; no valid receiver blocks were deleted.')
                finally:
                    if self.stream:self.peers.wallet_bridge.abort(self.stream);self.stream=None
                self.stop.wait(5)
        finally:
            if self.store.read().get('block_download',{}).get('error')=='source_pruned':self.update(running=False)
            else:self.update(running=False,message='Direct block receiving stopped. Internet peers remain paused; validated blocks were retained.')
