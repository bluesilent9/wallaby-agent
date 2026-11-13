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

def compatible(receiver,source,recovery_floor=None):
    if not isinstance(source,dict) or source.get('chain')!=receiver['chain'] or type(source.get('height')) is not int or not 0<=source['height']<=2**31 or not isinstance(source.get('hash'),str) or not re.fullmatch('[0-9a-f]{64}',source['hash']) or type(source.get('pruned')) is not bool or type(source.get('pruneheight')) is not int or not 0<=source['pruneheight']<=source['height']:raise CloneError('Invalid clone source chain facts.')
    if type(source.get('core_version')) is not int or not 310000<=source['core_version']<320000 or source['core_version']!=receiver.get('core_version'):raise CloneError('Use the same Bitcoin Core 31 release on both laptops before cloning. No blockchain data was replaced.')
    if source['height']<receiver['blocks']:raise CloneError('Source is behind this receiver. Use block catch-up and wait; cloning will not discard the receiver’s newer validated blocks.')
    if source['pruned'] and not receiver.get('pruned'):raise CloneError('A pruned snapshot cannot supply a full archival node. Use a full source or separately configure pruning locally; cloning does not change your pruning settings.')
    if source['pruned'] and source['pruneheight']>max(receiver['blocks'],recovery_floor if type(recovery_floor) is int else 0)+1:raise CloneError('The pruned source lacks blocks needed to advance this receiver’s existing wallet history. Use a source retaining that range, or transfer verified public history separately before cloning.')
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
        self.operation_lock=threading.RLock();self.guard=lambda:False;self.handoff_guard=lambda:False;self.recovery=None;self.handoff=None;self.plan_floor=None;self.preparing=False;self.blocks=blocks;self.peers=blocks.peers;self.store=blocks.store;self.core=blocks.core;self.lock=threading.RLock();self.allowed=True;self.thread=None;self.offer_stream=None;self.plan=None;self.deadline=0;self.running=False;self.message='No trusted clone is active.';self.received=0;self.total=0;self.stage='idle';self.source_stream=None
    def active(self):return bool(self.running and self.deadline>time.monotonic() and (self.thread and self.thread.is_alive() or self.source_stream))
    def state(self):
        with self.lock:return {'handoff_preparing':self.preparing,'handoff_ready':bool(self.handoff and self.store.read().get('recovery',{}).get('state')=='clone_paused'),'handoff_available':bool(self.store.read().get('history_jobs')),'allowed':self.allowed,'running':self.running,'stage':self.stage,'message':self.message,'received_bytes':self.received,'total_bytes':self.total,'review':{k:v for k,v in (self.plan or {}).items() if k not in ('stream',)} if self.plan and self.plan['expires']>time.time() else None}
    def idle(self,own_source=None,own_review=False,allow_history=False):
        s=self.store.read()
        if self.source_stream and self.source_stream is not own_source or self.offer_stream and not own_review:raise CloneError('Finish or cancel the existing clone review first.')
        handover=bool(allow_history and self.handoff and self.recovery and self.recovery.clone_paused.is_set() and not (self.recovery.thread and self.recovery.thread.is_alive()) and s.get('recovery',{}).get('state')=='clone_paused' and self.handoff['jobs_hash']==digest(s.get('history_jobs',{})))
        if (self.handoff_guard() if handover else self.guard()) or self.running or self.blocks.thread and self.blocks.thread.is_alive() or self.blocks.serving or s.get('active_transfer') or s.get('sync_batch') or s.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning') or s.get('history_jobs') and not handover:raise CloneError('Finish wallet transfers, block receiving and pending history recovery before cloning.')
    def prepare_handoff(self):
        with self.operation_lock,self.lock:
            if self.running or self.preparing or self.source_stream or self.offer_stream or not self.recovery or self.handoff_guard():raise CloneError('Finish other wallet or direct-transfer work before preparing recovery handover.')
            from clone_history import requests
            requests(self.core,self.store) # Exact supported jobs; no changes on refusal.
            self.handoff=None;self.preparing=True;self.stage='pausing';self.message='Pausing the existing recovery safely. Pending history and extinction approval are retained.'
            def pause():
                try:
                    self.recovery.request_clone_pause();deadline=time.monotonic()+1200
                    while self.recovery.thread and self.recovery.thread.is_alive():
                        if time.monotonic()>deadline:raise CloneError('Recovery has not reached a safe pause. No clone was started; inspect its current stage.')
                        self.recovery.thread.join(.25)
                    requested=requests(self.core,self.store)
                    self.recovery.request_clone_pause() # Confirm a terminal safe pause even if the old worker exited with an RPC error.
                    rpc(self.core,'setnetworkactive',[False])
                    from chain_sync import publish
                    publish(self.store,mode='ssh_only',network_paused=True,state='recovery_clone_paused',message='Recovery Internet download paused for a trusted clone. Pending history work is retained.')
                    self.handoff={'requests':requested,'jobs_hash':digest(self.store.read().get('history_jobs',{}))};self.stage='ready';self.message='Recovery paused. Select the trusted source and review its clone plus complete Extinct history. No Internet download will resume automatically.'
                except Exception as error:
                    self.stage='error';self.message=str(error) if isinstance(error,CloneError) else 'Recovery could not be paused safely. Pending work was retained; no clone was started.'
                finally:self.preparing=False
            self.thread=threading.Thread(target=pause,daemon=True,name='pause-recovery-for-clone');self.thread.start()
        return {'message':self.message}
    def helper_read(self,stream):
        frame=frame_read(stream)
        if frame.get('status')=='clone_helper_error':
            message=frame.get('message')
            raise CloneError(message if isinstance(message,str) and len(message)<600 else 'The local blockchain helper refused this operation.')
        return frame
    def local_socket(self,mode,tip):
        from chain_clone_service import connect
        return connect({'mode':mode,'netdir':str(Path(self.core.config['cookie']).expanduser().resolve().parent),'hash':tip,'restore_network':bool(getattr(self,'source_network_before',False)) if mode=='export' else False,'recovery_floor':(self.plan_floor if mode=='receive' else None),'wallet_checkpoints':(getattr(self,'wallet_checkpoints',[]) if mode=='receive' else [])})
    def review(self,ident):
        with self.lock:
            self.cancel_review();self.idle(allow_history=True);channel=self.blocks.peer(ident);self.peers.direct.require(channel)
            stream=self.peers.wallet_bridge.open_clone(channel)
            try:
                source=frame_read(stream)
                if set(source) not in ({'operation','facts'},{'operation','facts','features'}) or source['operation']!='clone_offer':raise CloneError('Paired source did not offer trusted cloning. Update both Agents and check that the source is idle.')
                local=chain_info(self.core)
                from recovery_checkpoint import floor
                checkpoint=floor(self.core,self.store) if self.handoff else None
                recovery_floor=checkpoint['height'] if checkpoint else None
                compatible(local,source['facts'],recovery_floor)
                history=self.handoff['requests'] if self.handoff else []
                if history and 'recovery_history_v1' not in source.get('features',[]):raise CloneError('Install Build 83 on the source Agent for recovery handover. No recovery work was cleared.')
                frame_write(stream,{'operation':'clone_anchor','height':local['blocks'],**({'history_requests':history} if history else {}),**({'recovery_anchor':{'height':checkpoint['height'],'hash':checkpoint['hash']}} if checkpoint else {})})
                anchor=frame_read(stream)
                if anchor.get('operation')=='clone_refused':raise CloneError('The source could not supply the exact complete recovery history. Check its Blockchain status. Pending history work was retained; no clone was started.')
                offers=anchor.get('history_offers',[])
                if anchor.get('hash')!=local['bestblockhash'] or set(anchor)!=({'hash'}|({'history_offers'} if history else set())|({'recovery_hash'} if checkpoint else set())):raise CloneError('The source does not contain the receiver’s current validated tip. No blockchain replacement is offered.')
                if checkpoint and anchor['recovery_hash']!=checkpoint['hash']:raise CloneError('The source does not contain the receiver’s pre-reindex validated chain checkpoint.')
                if history:
                    if len(offers)!=len(history) or any(not isinstance(o,dict) or set(o)!={'request_hash','sha256','bytes','addresses','transactions'} or type(o['addresses']) is not int or not 1<=o['addresses']<=10000 or type(o['transactions']) is not int or not 0<=o['transactions']<=10000 or o.get('request_hash')!=digest(r) or type(o.get('bytes')) is not int or not 0<o['bytes']<=256*1024*1024 or not isinstance(o.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',o['sha256']) for r,o in zip(history,offers)):raise CloneError('The source did not offer exact complete history for every pending recovery job.')
                self.plan={'recovery_floor':recovery_floor,'recovery_checkpoint':checkpoint,'history_requests':history,'history_offers':offers,'jobs_hash':self.handoff['jobs_hash'] if self.handoff else None,'id':secrets.token_hex(32),'source_name':self.peers.persistence.read()['pairs'][ident]['name'],'source':ident,'source_facts':source['facts'],'receiver_height':local['blocks'],'receiver_hash':local['bestblockhash'],'expires':int(time.time())+300};self.offer_stream=stream
                return self.state()
            except Exception:self.peers.wallet_bridge.abort(stream);raise
    def cancel_review(self):
        if self.offer_stream:self.peers.wallet_bridge.abort(self.offer_stream)
        self.offer_stream=None;self.plan=None
    def start(self,ident,confirmed):
        with self.operation_lock,self.lock:
            self.idle(own_review=True,allow_history=True);p=self.plan
            if confirmed is not True or not p or p['id']!=ident or p['expires']<time.time() or not self.offer_stream:raise CloneError('Review and explicitly confirm this exact trusted clone first.')
            local=chain_info(self.core);compatible(local,p['source_facts'],p.get('recovery_floor'))
            if p.get('recovery_checkpoint'):
                from recovery_checkpoint import floor
                if floor(self.core,self.store)!=p['recovery_checkpoint']:raise CloneError('The original wallet checkpoint changed after clone review.')
            if local['bestblockhash']!=p['receiver_hash']:self.cancel_review();raise CloneError('Receiver chain changed since review. Review again.')
            stream=self.offer_stream;self.offer_stream=None;self.plan=None
            self.plan_floor=p.get('recovery_floor');checkpoint=p.get('recovery_checkpoint');self.wallet_checkpoints=[{'wallet':name,'anchor':checkpoint['hash'],'locators':row['locators'],'policy':row['db_policy'],'private':row['private']} for name,row in checkpoint['wallets'].items()] if checkpoint else [];self.blocks.prepare(p['source']);self.running=True;self.stage='staging';self.deadline=time.monotonic()+3600;self.message='Receiving a verified cold snapshot. Receiver wallets and Internet peers remain separate.'
            self.thread=threading.Thread(target=self.receive,args=(stream,p),daemon=True,name='trusted-chain-clone');self.thread.start()
        return {'message':'Trusted blockchain clone started. Core restarts independently; keep both protected workspaces open.'}
    def progress(self,n,total):
        self.deadline=time.monotonic()+3600;self.received=n;self.total=total
    def accept(self,stream):
        with self.lock:
            if self.source_stream:return False
            try:self.idle()
            except ValueError:return False
            self.source_stream=stream;self.thread=threading.Thread(target=self.serve,args=(stream,),daemon=True,name='trusted-chain-source');self.thread.start();return True
    def serve(self,stream):
        sock=None;old=None
        try:
            source=facts(self.core);frame_write(stream,{'operation':'clone_offer','facts':source,'features':['recovery_history_v1']});anchor=frame_read(stream)
            if set(anchor) not in ({'operation','height'},{'operation','height','history_requests'},{'operation','height','history_requests','recovery_anchor'}) or anchor['operation']!='clone_anchor' or type(anchor['height']) is not int or not 0<=anchor['height']<=source['height']:raise CloneError('Invalid clone anchor request.')
            checkpoint=anchor.get('recovery_anchor')
            if checkpoint is not None and (not isinstance(checkpoint,dict) or set(checkpoint)!={'height','hash'} or type(checkpoint['height']) is not int or not 0<=checkpoint['height']<=source['height']):raise CloneError('The source has not reached the original recovery checkpoint. Wait for it to catch up; no receiver history was discarded.')
            histories=anchor.get('history_requests',[])
            if not isinstance(histories,list) or len(histories)>3:raise CloneError('Invalid number of recovery archives.')
            from clone_history import export
            packets=[export(self.core,self.store,r) for r in histories]
            frame_write(stream,{'hash':rpc(self.core,'getblockhash',[anchor['height']]),**({'history_offers':[offer for raw,offer in packets]} if histories else {}),**({'recovery_hash':rpc(self.core,'getblockhash',[checkpoint['height']])} if checkpoint else {})});begun=frame_read(stream)
            if begun!={'operation':'clone_begin','hash':source['hash']}:raise CloneError('The receiver did not confirm this exact clone.')
            with self.operation_lock,self.lock:
                self.idle(own_source=stream);self.allowed=True;self.running=True;self.stage='serving';self.deadline=time.monotonic()+3600
            old=rpc(self.core,'getnetworkinfo')['networkactive'];self.source_network_before=old;rpc(self.core,'setnetworkactive',[False]);rpc(self.core,'syncwithvalidationinterfacequeue',[],timeout=120)
            if facts(self.core)['hash']!=source['hash']:raise CloneError('Source chain advanced after review; review a fresh clone.')
            sock,helper=self.local_socket('export',source['hash']);hello=self.helper_read(helper);copy_snapshot(helper,stream,hello,self.progress)
            # Export helper restarts source after complete staging acknowledgement.
            # Consume its EOF; then wait for RPC before confirming source restart.
            self.wait_core();frame_write(stream,{'operation':'clone_source_restarted','hash':source['hash']});
            if packets:
                if frame_read(stream)!={'operation':'clone_history_ready'}:raise CloneError('Receiver did not request its exact reviewed recovery history.')
                for raw,offer in packets:
                    frame_write(stream,{'operation':'clone_history',**offer});stream.write(raw)
                if frame_read(stream)!={'status':'clone_history_applied'}:raise CloneError('Receiver did not verify recovery history; no recovery success was assumed.')
            self.stage='complete';self.message='Snapshot served. Source Core restarted; its previous Internet setting was restored.'
        except Exception as error:
            from activity_log import event
            event('chain.clone','Source stopped · exception='+type(error).__name__)
            try:frame_write(stream,{'operation':'clone_refused'})
            except Exception:pass
            self.stage='error';self.message=str(error) if isinstance(error,CloneError) else 'Clone source stopped or became uncertain. Check Core and its independent clone service; no replacement or retry was authorised automatically.'
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
            compatible(chain_info(self.core),hello,p.get('recovery_floor'))
            if any(hello.get(k)!=p['source_facts'].get(k) for k in ('core_version','chain','height','hash','pruned','pruneheight')):raise CloneError('Source snapshot changed after review.')
            copy_snapshot(stream,helper,hello,self.progress)
            if frame_read(stream)!={'operation':'clone_source_restarted','hash':hello['hash']}:raise CloneError('Source did not confirm its independent restart.')
            self.stage='restarting';self.message='Snapshot verified. Restarting receiver Core and checking retained wallets and history.';self.deadline=time.monotonic()+1200
            if p.get('recovery_checkpoint'):
                from recovery_checkpoint import floor
                if floor(self.core,self.store)!=p['recovery_checkpoint']:raise CloneError('Original wallet evidence changed during staging. The clone was not committed.')
            frame_write(helper,{'operation':'clone_commit','hash':hello['hash']});result=self.helper_read(helper)
            if result!={'status':'clone_complete','height':hello['height'],'hash':hello['hash']}:raise CloneError('Receiver clone startup or wallet checks were not confirmed.')
            if p.get('history_requests'):
                self.stage='verifying_history';self.message='Blockchain clone opened. Verifying and merging the exact pending Extinct history from the same source.'
                if p['jobs_hash']!=digest(self.store.read().get('history_jobs',{})):raise CloneError('Recovery changed during cloning. Pending work was retained.')
                frame_write(stream,{'operation':'clone_history_ready'});proofs=[]
                from clone_history import apply,finish
                for request,offer in zip(p['history_requests'],p['history_offers']):
                    if frame_read(stream)!={'operation':'clone_history',**offer}:raise CloneError('Recovery history changed after review.')
                    raw=read_exact(stream,offer['bytes'])
                    if hashlib.sha256(raw).hexdigest()!=offer['sha256']:raise CloneError('Recovery history checksum failed. No pending jobs were cleared.')
                    proofs.append(apply(self.core,self.store,request,raw))
                finish(self.core,self.store,p['history_requests'],proofs);frame_write(stream,{'status':'clone_history_applied'});self.handoff=None
                if self.recovery:self.recovery.clone_pause.clear();self.recovery.clone_paused.clear();self.recovery.cache_at=0
            self.stage='complete';self.message=('Trusted blockchain clone and required Extinct history verification complete. Previously approved preservation continues; original wallet deletion still needs separate approval. Internet peers remain paused.' if p.get('history_requests') else 'Trusted blockchain clone complete. Receiver wallets, keys, labels and existing transaction records were retained. Internet peers remain paused. Synchronise missing Extinct history separately; cloning does not certify it.')
            if p.get('history_requests'):self.message='Recovery completed from the trusted clone and verified Extinct history. Internet downloading remains paused. Original wallets remain until separate deletion approval.'
            from chain_sync import publish
            publish(self.store,current_height=hello['height'],source_height=hello['height'],state='cloned',message=self.message)
        except Exception as error:
            from activity_log import event
            event('chain.clone','Receiving stopped · exception='+type(error).__name__)
            self.stage='error';self.message=(str(error) if isinstance(error,CloneError) else 'Trusted clone did not confirm completion. Inspect Core and the local clone helper before retrying.')+' Original wallet data was not replaced; Internet remains paused.'
        finally:
            if sock:sock.close()
            self.running=False;self.deadline=0;self.peers.wallet_bridge.abort(stream)
