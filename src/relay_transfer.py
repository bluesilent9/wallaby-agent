"""Explicit local sending action through a QR-pinned encrypted channel."""
import hashlib,shutil,tempfile
from pathlib import Path
from approval_store import digest
from public_policy import descriptors
from wallet_ops import rpc
from peer_wallet import active,work_dir,wallet_details,same_facts,validate_details,source_wallet,frame_read,frame_write,MAX_FILE

def send(self,key):
    from peer_mesh import manager
    from relay_stream import Bridge
    with self.lock:
        current,row=active(self.store)
        if key!=current or not row or row['state']!='pending' or row['proposal']['direction']!='send':raise ValueError('Review this exact pending sending request first.')
        p=row['proposal'];peers=manager(self.store);peers.binding(p);saved=self.store.read();payload=saved.get('transfer_previews',{}).get(key)
        if not payload:raise ValueError('The signed initial preview is missing.')
        from wallet_preview import verify_bound
        verify_bound(self.store,payload,p);details=wallet_details(self.core,p,self.store)
        if not same_facts(details,{k:payload['preview'][k] for k in ('public_wallet','chain','funded_outputs','vaults','address_labels')}):raise ValueError('Wallet facts changed; start a fresh review before sending.')
        validate_details(details);choice=saved.get('sync_batch',{}).get('options',{}).get(key,{})
        watch=not p['source_has_private_keys'] or choice.get('watch_only',False);name=None if watch else source_wallet(self.core,p,public_preview=True)
        bridge=getattr(peers,'wallet_bridge',None)
        if bridge is None:bridge=peers.wallet_bridge=Bridge(peers,self.store)
        stream=bridge.open(p)
        try:
            with tempfile.TemporaryDirectory(prefix='relay-send-',dir=work_dir(self.core)) as folder:
                root=Path(folder);backup=root/'wallet.dat'
                return send_contents(self,key,p,peers,stream,details,watch,name,root,backup)
        except Exception:
            with self.store.edit() as state:
                row=state['pending'].get(key)
                if row and row['state']=='attempted':row['state']='recovery_required'
            raise
        finally:
            bridge.remove(stream)

def send_contents(self,key,p,peers,stream,details,watch,name,root,backup):
    manifest={'operation':'manifest','transfer_id':p['transfer_id'],'peer_endpoint':peers.identity['endpoint_id'],'details':details}
    if p.get('transfer_version') in (2,3):manifest['watch_only']=watch
    elif watch:raise ValueError('Watch-only transfer requires the Build 8 direct protocol.')
    frame_write(stream,manifest)
    reply=frame_read(stream)
    if reply.get('status')!='review_required':raise ValueError('Receiver did not accept this paired request. Authorise on the receiving Agent first.')
    reply=frame_read(stream)
    if reply.get('status')!='ready':raise ValueError('Receiver did not approve the direct wallet history.')
    from signer_restoration import requested,validate_offer,permit_backup
    restoration_offer=None
    if requested(p):
        if 'restore_roles_v1' not in reply.get('features',[]):raise ValueError('The receiver needs Build 65 original-role restoration support. No wallet file was created or sent.')
        restoration_offer=validate_offer(p,reply.get('restoration'),reply.get('watch_only',False))
    native_peer='chain_sync_v1' in reply.get('features',[])
    native_history='core_history_v1' in reply.get('features',[])
    if native_peer:
        from chain_sync import send as send_chain
        send_chain(self.core,stream,lambda _:frame_read(stream),frame_write)
    effective_watch=reply.get('watch_only',False)
    if type(effective_watch) is not bool or watch and not effective_watch:raise ValueError('Receiver did not honour watch-only mode. No private wallet file was created or sent.')
    if effective_watch and restoration_offer:
        from watch_snapshot import create
        name=source_wallet(self.core,p,public_preview=True);create(self.core,name,backup);size=backup.stat().st_size
        if not 0<size<=MAX_FILE:raise ValueError('Public recovery snapshot exceeds the transfer limit.')
        checksum=hashlib.sha256(backup.read_bytes()).hexdigest()
        header={'operation':'watch_snapshot','size':size,'sha256':checksum,'restoration':{'permit_hash':digest(restoration_offer),'binding_id':restoration_offer['bindings'][0]['binding_id']}}
        with self.store.edit() as saved:saved['pending'][key]['state']='attempted'
        frame_write(stream,header)
        with backup.open('rb') as f:shutil.copyfileobj(f,stream,65536)
        stream.flush();answer=frame_read(stream)
        if answer.get('status')!='loaded' or answer.get('transfer_id')!=p['transfer_id'] or answer.get('wallet_identity')!=digest(sorted(descriptors(p['public_wallet']))):raise ValueError('Receiver did not verify its complete watch-only restoration snapshot.')
        frame_write(stream,{'status':'confirmed'});self.complete(key);return {'ok':True}
    if effective_watch:
        with self.store.edit() as state:state['pending'][key]['state']='attempted'
        if native_history and __import__('extinct_sync').grouped(p['public_wallet']):
            from history_wire import export
            file,history_header=export(self.core,self.store,p,details,root)
            frame_write(stream,history_header)
            with file.open('rb') as f:
                while True:
                    chunk=f.read(65536)
                    if not chunk:break
                    stream.write(chunk)
            stream.flush()
        else:frame_write(stream,{'operation':'public_wallet'})
        reply=frame_read(stream)
        if reply.get('status')=='history_deferred' and reply.get('transfer_id')==p['transfer_id']:
            frame_write(stream,{'status':'confirmed'})
            with self.store.edit() as state:state['pending'][key]['state']='pending'
            self.error='Extinct history deferred by the receiving Agent until local extinction completes. Core block catch-up completed; no archive import was reported.'
            return {'ok':True,'deferred':True}
        if reply.get('status')=='recovery_required' and reply.get('transfer_id')==p['transfer_id']:
            frame_write(stream,{'status':'confirmed'});self.pending_recovery(key);return {'ok':True,'recovery_required':True}
        if reply.get('status')!='loaded' or reply.get('transfer_id')!=p['transfer_id'] or reply.get('wallet_identity')!=digest(sorted(descriptors(p['public_wallet']))):raise ValueError('Receiver did not confirm a matching watch wallet.')
        frame_write(stream,{'status':'confirmed'});self.complete(key);return {'ok':True}
    # Revalidate the source immediately before making a consistent Core backup.
    source_wallet(self.core,p,require_encrypted=True,restoration_permit=restoration_offer);rpc(self.core,'backupwallet',[__import__('core_ram_path').for_core(self.core,backup)],name)
    size=backup.stat().st_size
    if not 0<size<=MAX_FILE:raise ValueError('Wallet backup exceeds the 256 MiB transfer limit.')
    h=hashlib.sha256()
    with backup.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    header={'size':size,'sha256':h.hexdigest()}
    if restoration_offer:header['restoration']=permit_backup(p,restoration_offer,backup)
    with self.store.edit() as s:s['pending'][key]['state']='attempted'
    frame_write(stream,header)
    with backup.open('rb') as f:shutil.copyfileobj(f,stream,65536)
    stream.flush();reply=frame_read(stream)
    if reply.get('status')=='recovery_required' and reply.get('transfer_id')==p['transfer_id']:
        frame_write(stream,{'status':'confirmed'});self.pending_recovery(key);return {'ok':True,'recovery_required':True}
    if reply.get('status')!='loaded' or reply.get('transfer_id')!=p['transfer_id'] or reply.get('wallet_identity')!=digest(sorted(descriptors(p['public_wallet']))):raise ValueError('Receiver did not confirm a matching, loaded wallet. Check both Core instances before retrying.')
    frame_write(stream,{'status':'confirmed'});self.complete(key);return {'ok':True}
