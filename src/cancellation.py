"""Receipt is a hold, never consent to erase. All private state stays protected."""
import base64,copy,hashlib,json,os,re,secrets,shutil,subprocess,time,zipfile
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from public_policy import descriptors

HEX=re.compile('[0-9a-f]{64}')
def validate(p):
    fields={'kind','version','builder','workspace_id','cancellation_id','operations','request_hashes','require_local_authorisation','backup_option','request_id'}
    if isinstance(p,dict) and 'exports' in p:fields.add('exports')
    if not isinstance(p,dict) or set(p)!=fields or p['kind']!='builder_cancel' or type(p['version']) is not int or p['version']!=1 or p['builder'] not in ('wallet','transaction') or p['require_local_authorisation'] is not True or p['backup_option'] is not True:raise ValueError('Invalid builder cancellation.')
    for name in ('workspace_id','cancellation_id'):
        if not isinstance(p[name],str) or not re.fullmatch('[0-9a-f]{32}',p[name]):raise ValueError('Invalid cancellation identity.')
    for name in ('operations','request_hashes'):
        rows=p[name]
        if not isinstance(rows,list) or len(rows)>256 or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{32}|[0-9a-f]{64}',v) or name=='request_hashes' and len(v)!=64 for v in rows) or len(set(rows))!=len(rows):raise ValueError('Invalid cancellation targets.')
    exports=p.get('exports',[])
    if not isinstance(exports,list) or len(exports)>256 or any(not isinstance(e,dict) or set(e)!={'outbox_id','txid','psbt_sha256'} or any(not isinstance(v,str) or not HEX.fullmatch(v) for v in e.values()) for e in exports):raise ValueError('Invalid cancellation export bindings.')
    if len({e['outbox_id'] for e in exports})!=len(exports):raise ValueError('Duplicate cancellation export binding.')
    if not HEX.fullmatch(str(p['request_id'])) or p['request_id']!=digest({k:v for k,v in p.items() if k!='request_id'}):raise ValueError('Cancellation binding differs.')
    return p

def binding(p):
    if p.get('kind')=='wallet_setup':return digest(p)
    if p.get('kind') in ('wallet_setup_policy','wallet_setup_complete'):return digest(p['proposal']) if 'proposal' in p else p.get('proposal_hash')
    return None

def blocked(state,p):
    return digest(p) in state.get('cancelled_requests',{}) or binding(p) in state.get('cancelled_setups',{})

def held_item(state,item):
    payload=item['payload'];message=payload.get('message',{})
    return digest(item) in state.get('cancelled_exports',{}) or payload.get('request_hash') in state.get('cancelled_requests',{}) or isinstance(message,dict) and (message.get('proposal_hash') in state.get('cancelled_setups',{}) or message.get('request_hash') in state.get('cancelled_requests',{}))

def metadata(value):
    if isinstance(value,dict):return {k:metadata(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [metadata(v) for v in value]
    if isinstance(value,set):return sorted(metadata(v) for v in value)
    if isinstance(value,Path):return str(value)
    if value is None or type(value) in (str,int,float,bool):return value
    raise ValueError('Unsupported local recovery metadata; originals retained.')

class Cancellations:
    def __init__(self,core,store,setup,ops,environment=None):
        self.core=core;self.store=store;self.setup=setup;self.ops=ops;self.environment=environment or {};self.reviews={};self.archives=None;self.archive_ops=None
    def receive(self,p):
        p=validate(p);key=digest(p)
        with self.store.edit() as s:
            if key not in s['completed']:
                if key not in s['pending'] and len(s['pending'])>=128:raise ValueError('Authorisation queue is full; cancellation receipt was not sent.')
                s['pending'].setdefault(key,{'proposal':copy.deepcopy(p),'received':time.time(),'state':'pending'})
            for export in p.get('exports',[]):s.setdefault('cancelled_exports',{})[export['outbox_id']]=key
            for original in p['request_hashes']:s.setdefault('cancelled_requests',{})[original]=key
            if p['builder']=='wallet':
                for operation in p['operations']:s.setdefault('cancelled_setups',{})[operation]=key
            for original,row in s['pending'].items():
                if original!=key and (original in p['request_hashes'] or p['builder']=='wallet' and binding(row['proposal']) in p['operations']):
                    row['cancel_requested']=key
                    if row['state']=='pending':row['state']='cancellation_requested'
        from activity_log import event
        event('builder.cancellation','Received '+p['builder']+' builder cancellation; local approval required. Creation/signing review superseded; use Review cancellation on Authorise. No artifacts deleted.')
        self.store.queue('builder_cancel_receipt',{'version':1,'cancellation_id':p['cancellation_id'],'request_hash':key,'status':'received'})
        return key
    def _data(self,p):
        saved=self.store.read();keys=set(p['request_hashes']);setups=set(p['operations']) if p['builder']=='wallet' else set();proposals={};psbts=set();txids=set()
        for key,row in {**saved['completed'],**saved['pending']}.items():
            proposal=row.get('proposal',{})
            if key in keys or binding(proposal) in setups:
                keys.add(key)
                if proposal:proposals[key]=proposal
                if row.get('artifact_psbt'):psbts.add(row['artifact_psbt'])
                if row.get('artifact_txid'):txids.add(row['artifact_txid'])
        for key in keys:
            if key in self.ops.prepared:proposals.setdefault(key,self.ops.prepared[key])
        for proposal in proposals.values():
            if proposal.get('psbt'):psbts.add(proposal['psbt'])
        artifacts={**saved.get('legacy_exports',{}),**saved.get('delivered_artifacts',{}),**saved['outbox']}
        for export in p.get('exports',[]):
            item=artifacts.get(export['outbox_id'])
            if not item:continue
            value=item.get('payload',{}).get('psbt')
            if not value or digest(item)!=export['outbox_id'] or hashlib.sha256(base64.b64decode(value,validate=True)).hexdigest()!=export['psbt_sha256']:raise ValueError('The cancellation export differs from its locally held PSBT. No artifacts were removed.')
            decoded=rpc(self.core,'decodepsbt',[value])
            if decoded['tx']['txid']!=export['txid']:raise ValueError('The cancellation transaction identity differs from local Core.')
            psbts.add(value);txids.add(decoded['tx']['txid'])
        for item in saved['outbox'].values():
            if item['payload'].get('request_hash') in keys:
                if item['payload'].get('psbt'):psbts.add(item['payload']['psbt'])
                if item['payload'].get('txid'):txids.add(item['payload']['txid'])
        for name,row in saved.get('vault_proposals',{}).items():
            if name in p['operations']:
                if row.get('psbt'):psbts.add(row['psbt'])
        wallets=[];sessions={}
        for operation in sorted(setups):
            session=self.setup.sessions.get(operation)
            if not session:continue
            if session.get('policy'):keys.add(digest(session['policy']))
            sessions[operation]=metadata({k:v for k,v in session.items() if k not in ('core',)})
            memory=session.get('core')
            if memory and memory.process and memory.process.poll() is None:
                for name in rpc(memory.core,'listwallets'):wallets.append({'core':memory.core,'name':name,'temporary':True})
            for name,expected in session.get('installed_wallets',{}).items():
                present={w['name'] for w in rpc(self.core,'listwalletdir')['wallets']}
                if name not in present and name not in rpc(self.core,'listwallets'):continue # A failed restore/create never installed this reserved name.
                info=rpc(self.core,'getwalletinfo',[],name)
                actual=rpc(self.core,'listdescriptors',[False],name)
                actual_policy=descriptors(actual) if actual.get('descriptors') else set()
                if expected is not None and actual_policy!=descriptors(expected):
                    # Only a positively created wallet from this failed local
                    # installation may have a strict subset of its approved policy.
                    # Unknown/changed descriptors and uncertain creation stay blocked.
                    partial=(session.get('phase')=='installation_failed' and name in session.get('created_wallets',[]) and actual_policy<=descriptors(expected))
                    if not partial:raise ValueError('An installed setup wallet no longer matches its locally recorded public policy. No cancellation cleanup was performed.')
                if expected is None and actual.get('descriptors'):raise ValueError('An unfinished monitor changed since creation. Inspect locally; it was retained.')
                wallets.append({'core':self.core,'name':name,'temporary':False})
        return saved,keys,proposals,sorted(psbts),txids,wallets,sessions
    def _facts(self,p):
        saved,keys,proposals,psbts,txids,wallets,sessions=self._data(p);wallet_facts=[]
        for item in wallets:
            info=rpc(item['core'],'getwalletinfo',[],item['name']);balances=rpc(item['core'],'getbalances',[],item['name'])
            from agent_rpc import clean_json
            balances,_=clean_json(balances,65536)
            wallet_facts.append({'wallet':item['name'],'temporary':item['temporary'],'private_keys_enabled':info['private_keys_enabled'],'balances':balances,'policy':rpc(item['core'],'listdescriptors',[False],item['name'])})
        checks=[];unknown=False
        for psbt in psbts:
            decoded=rpc(self.core,'decodepsbt',[psbt]);txids.add(decoded['tx']['txid'])
            final=rpc(self.core,'finalizepsbt',[psbt])
            if final.get('complete'):txids.add(rpc(self.core,'decoderawtransaction',[final['hex']])['txid'])
        for txid in sorted(txids):
            detected=False;where=None
            result=self.core.call('cancel-mempool','getmempoolentry',[txid])
            if 'result' in result:detected=True;where='mempool'
            elif result.get('error',{}).get('code') not in (-5,-8):unknown=True
            result=self.core.call('cancel-chain','getrawtransaction',[txid,True])
            if 'result' in result:
                detected=True;where='chain' if result['result'].get('confirmations',0)>0 else 'mempool'
            else:
                # Without txindex, the primary node's wallet history may still know it.
                found=False
                for name in rpc(self.core,'listwallets'):
                    row=self.core.call('cancel-wallet','gettransaction',[txid],name)
                    if 'result' in row and row['result'].get('confirmations',0)>=0 and not row['result'].get('abandoned'):
                        if row['result'].get('confirmations',0)>0 or detected:found=True;detected=True;where=where or 'chain';break
                if not found and not detected:unknown=True
            checks.append({'txid':txid,'detected':detected,'location':where})
        burner=self.setup.burner
        busy=bool(burner.thread and burner.thread.is_alive())
        return {'builder':p['builder'],'request_hashes':sorted(keys),'operations':p['operations'],'wallets':wallet_facts,'psbts':[{'sha256':hashlib.sha256(v.encode()).hexdigest(),'bytes':len(v)} for v in psbts],'broadcasts':checks,'broadcast_detected':any(r['detected'] for r in checks),'broadcast_incomplete':unknown,'active_disc_write':busy,'untracked_exports':[e['outbox_id'] for e in p.get('exports',[]) if e['outbox_id'] not in {**saved.get('legacy_exports',{}),**saved.get('delivered_artifacts',{}),**saved['outbox']}],'untracked_operations':[x for x in p['operations'] if p['builder']=='wallet' and x not in sessions]}
    def review(self,key):
        row=self.store.read()['pending'][key]
        from policy_refresh_cancel import handles,review
        if handles(self,row['proposal']):return review(self,key)
        if row['state']!='pending':raise ValueError('Cancellation was already attempted; reconcile the local outcome before retrying.')
        p=validate(row['proposal']);facts=self._facts(p);self.reviews[key]=(digest(facts),time.time())
        return {'kind':'builder_cancel','id':key,'cancellation':facts}
    def reconcile(self,key,confirmed):
        """Explicit local recovery: reload tracked survivors, then require fresh consent.

        This does not repeat deletion or infer ownership from a generated name.
        The live setup supplies the exact wallet names and public policies.
        """
        row=self.store.read()['pending'].get(key)
        if confirmed is not True or not row or row['state']!='attempted':raise ValueError('Confirm reconciliation of this attempted cancellation locally.')
        p=validate(row['proposal'])
        if p['builder']!='wallet':raise ValueError('Inspect the attempted transaction cancellation locally; no transaction operation was repeated.')
        sessions=[self.setup.sessions.get(operation) for operation in p['operations']]
        if not sessions or any(session is None for session in sessions):raise ValueError('The original setup session is unavailable. No wallet was guessed or deleted.')
        burner=self.setup.burner
        if burner.thread and burner.thread.is_alive():raise ValueError('Wait for the active optical write/read-back to finish.')
        loaded=set(rpc(self.core,'listwallets'));present={w['name'] for w in rpc(self.core,'listwalletdir')['wallets']}
        for session in sessions:
            for name in session.get('installed_wallets',{}):
                if name in present and name not in loaded:
                    rpc(self.core,'loadwallet',{'filename':name,'load_on_startup':False});loaded.add(name)
        facts=self._facts(p) # Revalidates every surviving wallet against the retained public policy.
        if facts['active_disc_write']:raise ValueError('Wait for the active optical write/read-back to finish.')
        from wallet_deletion import target,delete
        for item in self._data(p)[5]:
            if not item['temporary']:delete(target(item['core'],item['name']),check_only=True)
        with self.store.edit() as state:
            if state['pending'][key]['state']!='attempted':raise ValueError('Cancellation state changed; inspect the current request.')
            state['pending'][key]['state']='pending'
        from activity_log import event
        event('builder.cleanup','Local reconciliation verified surviving policies and helper access. Fresh review required; no deletion replayed.')
        self.reviews.pop(key,None)
        return {'message':'Surviving setup wallets reconciled. Review cancellation again before choosing cleanup. No wallet was deleted.'}
    def _directory(self):
        env={**os.environ,**self.environment}
        if shutil.which('kdialog'):command=['/usr/bin/kdialog','--title','Wallaby cancellation backup','--getexistingdirectory',str(Path.home())]
        elif shutil.which('zenity'):command=['/usr/bin/zenity','--file-selection','--directory','--title=Choose encrypted cancellation backup folder']
        else:raise ValueError('Install kdialog or zenity for the local backup folder chooser.')
        result=subprocess.run(command,capture_output=True,env=env,timeout=300)
        if result.returncode:raise ValueError('Backup destination selection cancelled. Original artifacts remain intact.')
        return result.stdout.decode().strip()
    def _backup(self,p,key):
        from wallet_setup import secret_dialog
        from cancel_backup import export_bundle
        password=secret_dialog('Cancellation backup passphrase · encrypt all local PSBTs, wallet files and recovery metadata',self.environment,confirm=True)
        try:
            if len(password)<12:raise ValueError('Use at least 12 characters for the cancellation backup passphrase.')
            directory=self._directory();saved,keys,proposals,psbts,txids,wallets,sessions=self._data(p)
            manifest={'format':'wallaby-builder-cancellation','version':1,'cancellation':p,'requests':proposals,'sessions':sessions,'txids':sorted(txids),'wallets':[{'name':w['name'],'temporary':w['temporary'],'file':'wallets/'+hashlib.sha256((str(i)+':'+w['name']).encode()).hexdigest()+'.dat'} for i,w in enumerate(wallets)]}
            return export_bundle(directory,manifest,psbts,wallets,self.store.root,password)
        finally:password=None
    def confirm(self,key,action):
        from policy_refresh_cancel import handles,confirm
        if handles(self,self.store.read()['pending'][key]['proposal']):return confirm(self,key,action)
        if action not in ('delete','backup'):raise ValueError('Choose Delete and Cancel or Backup and Cancel locally.')
        saved=self.store.read();row=saved['pending'][key];p=validate(row['proposal']);review=self.reviews.get(key)
        if row['state']!='pending' or not review or time.time()-review[1]>600:raise ValueError('Review this cancellation again before deleting or backing up artifacts.')
        facts=self._facts(p)
        if facts['active_disc_write']:raise ValueError('Wait for the active optical write/read-back to finish. No active writer was killed.')
        if digest(facts)!=review[0]:raise ValueError('Local artifacts or broadcast status changed. Review the cancellation again.')
        backup=self._backup(p,key) if action=='backup' else None
        # Backup failure never authorises deletion. Recheck after the file dialogue.
        if digest(self._facts(p))!=review[0]:raise ValueError('Local state changed while backing up. Originals were retained; review again before cleanup.')
        _,keys,proposals,psbts,txids,wallets,sessions=self._data(p)
        from wallet_deletion import target,delete
        planned=[(item,target(item['core'],item['name'])) for item in wallets if not item['temporary']]
        # Verify the helper's actual mount view before unloading any Core wallet.
        for item,metadata in planned:delete(metadata,check_only=True)
        with self.store.edit() as state:state['pending'][key]['state']='attempted'
        stage='unload'
        try:
            for item,metadata in planned:rpc(item['core'],'unloadwallet',{'wallet_name':item['name'],'load_on_startup':False})
            stage='delete'
            for item,metadata in planned:delete(metadata)
            stage='ram_cleanup'
            for operation in sessions:
                session=self.setup.sessions[operation]
                if session.get('core'):
                    session['core'].close()
                    if session['core'].root.exists():shutil.rmtree(session['core'].root)
                self.setup.sessions.pop(operation,None)
            burner=self.setup.burner
            ids={job for job,(operation,role) in self.setup.disc_sessions.items() if operation in sessions}
            burner.cancel_members(ids)
            for ident in ids:
                self.setup.disc_sessions.pop(ident,None)
                path=burner.root/ident
                if path.exists():shutil.rmtree(path)
            with self.store.edit() as state:
                for original in keys:
                    state['pending'].pop(original,None);state['completed'].pop(original,None);self.ops.prepared.pop(original,None);self.setup.reviews.pop(original,None)
                for ident,record in list(state.get('approved_wallets',{}).items()):
                    if digest(record['proposal']) in sessions:state['approved_wallets'].pop(ident)
                for ident,item in list(state['outbox'].items()):
                    if held_item(state,item):state['outbox'].pop(ident)
                for collection in ('legacy_exports','delivered_artifacts'):
                    for ident,item in list(state.get(collection,{}).items()):
                        if held_item(state,item):state[collection].pop(ident)
                if state.get('setup_active') in p['operations']:state.pop('setup_active',None)
                for operation in p['operations']:state.get('vault_proposals',{}).pop(operation,None)
                state['pending'].pop(key,None);state['completed'][key]={'kind':'builder_cancel','at':time.time()}
            self.reviews.pop(key,None)
            return {'message':'Local builder artifacts '+('backed up in an encrypted recovery bundle and ' if backup else '')+'cancelled. Broadcast transactions remain on the network.','backup':backup}
        except Exception as error:
            from activity_log import event
            code=getattr(error,'errno',None)
            code=str(code) if type(code) is int else 'unclassified'
            event('builder.cleanup','Cleanup incomplete; stage='+stage+'; errno='+code+'; originals or remaining artifacts retained. Local reconciliation required.')
            raise ValueError('Cancellation cleanup is incomplete or uncertain. Retained artifacts were not replayed; inspect this protected workspace before a fresh local recovery action.') from None
