"""Wallet Server-owned rename queue; every mutation requires fresh local approval."""
import copy,re,time,json
from pathlib import Path
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc
from wallet_rename import name,watch_name
HEX=re.compile('[0-9a-f]{64}')

def validate_task(p):
    fields={'kind','version','nonce','request_id','rename_id','chain','wallet','new_name','public_wallet','storage'}
    if isinstance(p,dict) and p.get('storage')=='disc':fields.add('archive_id')
    if not isinstance(p,dict) or set(p)!=fields or p['kind']!='wallet_rename' or type(p['version']) is not int or p['version']!=1 or p['storage'] not in ('node','disc') or p['chain'] not in ('main','test','signet','regtest'):raise ValueError('Invalid wallet rename request.')
    from vault_policy import text
    text(p['wallet'],256);name(p['new_name']);descriptors(p['public_wallet'])
    from agent_rpc import PRIVATE
    if PRIVATE.search(json.dumps(p)):raise ValueError('Private material is forbidden in rename messages.')
    for k in ('nonce','request_id','rename_id')+ (('archive_id',) if p['storage']=='disc' else ()):
        if not HEX.fullmatch(str(p[k])):raise ValueError('Invalid rename identity.')
    if p['request_id']!=digest({k:v for k,v in p.items() if k!='request_id'}):raise ValueError('Rename identifier does not bind its exact request.')
    return p

def validate_queue(p):
    if not isinstance(p,dict) or set(p)!={'kind','version','queue_id','revision','requests'} or p['kind']!='wallet_rename_queue' or type(p['version']) is not int or p['version']!=1 or not HEX.fullmatch(str(p['queue_id'])) or type(p['revision']) is not int or not 0<=p['revision']<2**63 or not isinstance(p['requests'],list) or len(p['requests'])>128:raise ValueError('Invalid full rename queue.')
    seen=set()
    for r in p['requests']:
        validate_task(r)
        if r['request_id'] in seen:raise ValueError('Duplicate rename task.')
        seen.add(r['request_id'])
    return p

def snapshot(store,p):
    validate_queue(p)
    with store.edit() as s:
        old=s.get('rename_queue')
        if old and old['queue_id']==p['queue_id']:
            if p['revision']<old['revision'] or p['revision']==old['revision'] and digest(p)!=old['hash']:raise ValueError('Rename queue revision changed or went backwards.')
        active={digest(r):r for r in p['requests']}
        for k,r in list(s['pending'].items()):
            if r['proposal']['kind']=='wallet_rename' and k not in active:
                if r['state']=='pending':s['pending'].pop(k)
                else:r['withdrawn']=True
        s['rename_queue']={'queue_id':p['queue_id'],'revision':p['revision'],'hash':digest(p)}
        for k,r in active.items():
            if k in s['pending'] or k in s['completed'] or k in s['denied']:continue
            if len(s['pending'])>=128:raise ValueError('Local authorisation queue is full.')
            s['pending'][k]={'proposal':copy.deepcopy(r),'state':'pending','received':time.time()}

def result(store,p,status,**evidence):
    from setup_messages import sign
    message={'version':1,'queue_id':store.read().get('rename_queue',{}).get('queue_id'),'request_id':p['request_id'],'rename_id':p['rename_id'],'status':status,'wallet':p['wallet'],'new_wallet':p['new_name'],'storage':p['storage'],**evidence};store.queue('wallet_rename_result',sign(store,message));return message

class Renames:
    def __init__(self,core,store,archives,archive_ops,guard,reconcile_guard=None):
        self.core=core;self.store=store;self.archives=archives;self.archive_ops=archive_ops;self.guard=guard;self.reconcile_guard=reconcile_guard or (lambda key:guard());self.reviews={};self.attempts={};self.archive_jobs={};archive_ops.rename_complete=self.archive_complete
    def deny(self,key):
        row=self.store.read()['pending'][key];p=validate_task(row['proposal'])
        if row['state']!='pending':raise ValueError('An attempted rename needs local reconciliation; it cannot be denied as unstarted.')
        result(self.store,p,'denied',identity_verified=False)
        with self.store.edit() as s:s['pending'].pop(key,None);s['denied'][key]={'proposal':{'kind':'wallet_rename'},'wallet_name':p['wallet']}
        return {'message':'Rename denied locally. No wallet was changed.'}
    def record(self,p):
        matches=[r for r in self.archives.loaded.values() if r['archive_id']==p['archive_id'] and p['wallet'] in r['routes']]
        if len(matches)!=1:raise ValueError('Read and locally load the matching archive disc, then review its rename request. No disc data was changed.')
        return matches[0]
    def duplicate(self,r):
        # Exact signing-account coverage, never another key in the same quorum.
        wanted=descriptors(rpc(r['node'].core,'listdescriptors',[False],'archive-key'));routes={alias for entry in self.archives.loaded.values() for alias in entry['routes']}
        for candidate in rpc(self.core,'listwallets'):
            if candidate in routes:continue
            info=rpc(self.core,'getwalletinfo',[],candidate)
            if info.get('private_keys_enabled') and not info.get('scanning') and wanted<=descriptors(rpc(self.core,'listdescriptors',[False],candidate)):return candidate
        return None
    def review(self,key):
        row=self.store.read()['pending'][key];p=validate_task(row['proposal'])
        if row['state']=='attempted' and p['storage']=='node':return self.reconciliation(key)
        if row['state']!='pending' or row.get('withdrawn'):raise ValueError('Rename was attempted or withdrawn. Inspect its local outcome before retrying.')
        if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise ValueError('Rename network differs from the connected local node.')
        raw=rpc(self.core,'listdescriptors',[False],p['wallet']);info=rpc(self.core,'getwalletinfo',[],p['wallet'])
        if descriptors(raw)!=descriptors(p['public_wallet']) or info.get('scanning'):raise ValueError('The loaded wallet public policy changed or its scan is unfinished. No rename was authorised.')
        facts={'wallet':p['wallet'],'new_wallet':p['new_name'] if info.get('private_keys_enabled') or p['storage']=='disc' else watch_name(p['new_name']),'public_wallet':raw,'private_keys_enabled':bool(info.get('private_keys_enabled')),'storage':p['storage'],'chain':p['chain'],'policy_identity':digest(sorted(descriptors(raw))),'archive_skip_allowed':False}
        if p['storage']=='node':
            if any(p['wallet'] in r['routes'] for r in self.archives.loaded.values()):raise ValueError('A disc route cannot be renamed as a persistent node wallet.')
            from wallet_deletion import target,bases
            source=target(self.core,p['wallet'])
            if Path(source['path']).parent not in bases():raise ValueError('Automatic rename supports the standard and Snap Core wallet directories. This custom location requires local manual reconciliation.')
            destination=Path(source['path']).with_name(facts['new_wallet'])
            if facts['new_wallet']==p['wallet'] or destination.exists() or destination.is_symlink() or any(w['name']==facts['new_wallet'] for w in rpc(self.core,'listwalletdir')['wallets']):raise ValueError('The target name already exists or is unchanged. No wallet will be overwritten.')
            if info.get('format')!='sqlite':raise ValueError('Automatic rename requires a Core SQLite descriptor wallet.')
            facts['source']=source;facts['balances']=rpc(self.core,'getbalances',[],p['wallet']);facts['encrypted']='unlocked_until' in info
        else:
            r=self.record(p);duplicate=self.duplicate(r)
            from archive_format import identity
            members=[(i,v) for i,v in self.archives.loaded.items() if v['archive_id']==r['archive_id']];expected=set(self.archives.catalogs.get(r['archive_id'],{}));covered={identity(v['recovery']) for i,v in members}
            facts.update(replacement_members=[v['review']['name'] for i,v in members],replacement_ready=bool(expected and expected<=covered),archive_id=r['archive_id'],archive_skip_allowed=bool(duplicate),duplicate_wallet=duplicate,old_display_name=r['review']['name'],archive_required=True)
        self.reviews[key]=(copy.deepcopy(p),copy.deepcopy(facts),time.monotonic());return {'kind':'wallet_rename','id':key,'rename':facts}
    def approve(self,key,skip_archive=False):
        if type(skip_archive) is not bool:raise ValueError('Choose the local archive option explicitly.')
        self.guard();saved=self.reviews.get(key)
        if not saved or time.monotonic()-saved[2]>600:raise ValueError('Review this rename again before approving it.')
        current=self.review(key)['rename'];p=saved[0]
        if self.reviews[key][0]!=p or current!=saved[1]:raise ValueError('Wallet or duplicate-signer evidence changed. Review the rename again.')
        if p['storage']=='node' and skip_archive or skip_archive and not current['archive_skip_allowed']:raise ValueError('A replacement disc may only be skipped for the exact independently verified duplicate local signer.')
        if p['storage']=='node':return self.node_rename(key,p,current)
        r=self.record(p)
        if not skip_archive and not current['replacement_ready']:raise ValueError('Load every wallet member from this original disc before approving its replacement. Unchanged members must also be preserved.')
        if self.archive_ops.busy():raise ValueError('Finish the existing archive staging/writes before renaming a loaded archive.')
        from archive_format import identity
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        # Preserve signed creation policy and the stable member identity.
        stable=identity(r['recovery']);r['recovery']['display_name']=p['new_name'];r['review']['name']=p['new_name']
        label='Disc '+p['new_name']+' '+r['recovery']['policy_hash'][:12]+' '+r['role']['id'];oldkey=r['keys'][0];routes={label+alias[len(oldkey):]:internal for alias,internal in r['routes'].items()};r['routes']=routes;r['keys']=[label];r['monitor']=label+r['monitor'][len(oldkey):]
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        if skip_archive:
            proof=result(self.store,p,'complete',new_wallet=label,identity_verified=True,archive_skipped=True,duplicate_wallet=current['duplicate_wallet'],archive_id=p['archive_id']);self.finish(key,proof)
            return {'message':'Loaded archive display name updated. Replacement skipped by your explicit local choice; the exact signer is also present in the persistent wallet '+current['duplicate_wallet']+'. The old physical disc remains unchanged.'}
        result(self.store,p,'archive_required',new_wallet=label,identity_verified=True,archive_id=p['archive_id'],archive_skipped=False)
        ids=[i for i,v in self.archives.loaded.items() if v['archive_id']==p['archive_id']];self.archive_ops.queue_loaded(ids,True);required=[k for k,v in self.archive_ops.jobs.items() if v.get('source_archive')==p['archive_id'] and v['phase']=='queued'];self.archive_ops.setup.burner.job['_required_members']=required;self.archive_ops.setup.burner.select(required);job=next(k for k,v in self.archive_ops.jobs.items() if identity(v['recovery'])==stable and v.get('source_archive')==p['archive_id'] and v['phase']=='queued');self.archive_jobs[job]={'key':key,'request':p,'new_wallet':label,'member':stable}
        return {'message':'Loaded archive renamed in RAM. Its replacement is queued in Disc Operations; this request completes only after every selected disc passes read-back.','burn_authorised':True}
    def verify_loaded(self,p,facts,wallet,balances=True):
        raw=rpc(self.core,'listdescriptors',[False],wallet);info=rpc(self.core,'getwalletinfo',[],wallet)
        if info.get('walletname')!=wallet or bool(info.get('private_keys_enabled'))!=facts['private_keys_enabled'] or descriptors(raw)!=descriptors(p['public_wallet']) or ('unlocked_until' in info)!=facts['encrypted']:raise ValueError('Loaded wallet identity, key capability or encryption differs from its reviewed source.')
        if balances and rpc(self.core,'getbalances',[],wallet)!=facts['balances']:raise ValueError('Wallet balances changed; fresh local reconciliation is required.')
    def located(self,facts,wallet):
        path=Path(facts['source']['path']).with_name(wallet)
        if path.is_symlink() or not path.is_dir() or (path/'wallet.dat').is_symlink():return False
        folder=path.stat();db=(path/'wallet.dat').stat()
        return [folder.st_dev,folder.st_ino]==facts['source']['directory'] and [db.st_dev,db.st_ino]==facts['source']['database']
    def stage(self,key,stage,code=None):
        with self.store.edit() as s:
            row=s['pending'][key];row['rename_stage']=stage
            if code:row['rename_error_code']=code
        from activity_log import event
        event('wallet.rename','stage='+stage+((' · code='+code) if code else ''))
    def node_rename(self,key,p,facts):
        from wallet_rename import rename
        # Probe the actual authenticated filesystem helper before altering Core's
        # loaded-wallet/startup state. A failed probe leaves the request unstarted.
        try:rename(facts['source'],facts['new_wallet'],check_only=True)
        except Exception as error:
            self.stage(key,'preflight',getattr(error,'code','helper_failure'))
            raise ValueError('Wallet rename preflight failed: '+str(error)+' The original wallet remains loaded; no rename was started.') from None
        self.attempts[key]=(copy.deepcopy(p),copy.deepcopy(facts))
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        stage='lock'
        try:
            self.stage(key,stage)
            if facts['encrypted'] and facts['private_keys_enabled']:rpc(self.core,'walletlock',[],p['wallet'])
            stage='unload';self.stage(key,stage);rpc(self.core,'unloadwallet',{'wallet_name':p['wallet'],'load_on_startup':False})
            stage='move';self.stage(key,stage);rename(facts['source'],facts['new_wallet'])
            stage='reload';self.stage(key,stage);rpc(self.core,'loadwallet',{'filename':facts['new_wallet'],'load_on_startup':True},timeout=600)
            stage='verify';self.stage(key,stage);self.verify_loaded(p,facts,facts['new_wallet'])
            self.update_references(p['wallet'],facts['new_wallet'])
            proof=result(self.store,p,'complete',new_wallet=facts['new_wallet'],identity_verified=True,policy_identity=facts['policy_identity'],archive_skipped=False);self.finish(key,proof)
            return {'message':'Wallet renamed and reloaded. Public policy, key capability, encryption and balances verified unchanged.'}
        except Exception as error:
            code=getattr(error,'code','core_or_verification');self.stage(key,stage,code)
            # Restore only a positively identified unmoved original. Never move
            # files back, retry a rename, overwrite a target or infer success.
            restored=False
            try:
                target=Path(facts['source']['path']).with_name(facts['new_wallet'])
                if self.located(facts,p['wallet']) and not target.exists() and not target.is_symlink():
                    if p['wallet'] not in rpc(self.core,'listwallets'):rpc(self.core,'loadwallet',{'filename':p['wallet'],'load_on_startup':True},timeout=600)
                    self.verify_loaded(p,facts,p['wallet']);restored=True
            except Exception:pass
            if restored:
                with self.store.edit() as s:s['pending'][key]['state']='pending'
                result(self.store,p,'error',identity_verified=True,attempted=False,outcome_uncertain=False,original_wallet_restored=True,stage=stage,error_code=code)
                self.attempts.pop(key,None)
                raise ValueError('Rename failed at '+stage+' ('+code+'). The unchanged original wallet was reloaded and verified, including its startup entry. You can cancel this request or review it before a fresh attempt.') from None
            result(self.store,p,'error',identity_verified=False,attempted=True,outcome_uncertain=True,stage=stage,error_code=code)
            raise ValueError('Rename stopped at '+stage+' ('+code+'). Use Review and reconcile on this request. No file copy, rollback rename or automatic retry was performed.') from None
    def reconciliation(self,key):
        row=self.store.read()['pending'][key];p=validate_task(row['proposal']);saved=self.attempts.get(key)
        if p['storage']!='node' or row['state']!='attempted' or not saved:raise ValueError('No locally reviewed persistent-wallet rename is available for reconciliation. Keep the workspace and inspect both paths locally.')
        facts=saved[1];old=self.located(facts,p['wallet']);new=self.located(facts,facts['new_wallet'])
        other=Path(facts['source']['path']).with_name(facts['new_wallet'] if old else p['wallet'])
        if old==new or other.exists() or other.is_symlink():raise ValueError('Old/new wallet paths are ambiguous or changed. No reconciliation can authorise overwriting or another file move.')
        wallet=p['wallet'] if old else facts['new_wallet'];loaded=wallet in rpc(self.core,'listwallets')
        if loaded:self.verify_loaded(p,facts,wallet,balances=False)
        return {'kind':'wallet_rename','id':key,'rename':{**facts,'reconciliation':True,'actual_wallet':wallet,'loaded':loaded,'applied':new,'withdrawn':bool(row.get('withdrawn')),'stage':row.get('rename_stage','unknown'),'error_code':row.get('rename_error_code','unknown')}}
    def reconcile(self,key,confirmed):
        if confirmed is not True:raise ValueError('Explicitly approve reconciliation of the verified local wallet.')
        self.reconcile_guard(key);shown=self.reconciliation(key)['rename'];p,facts=self.attempts[key]
        if not shown['loaded']:rpc(self.core,'loadwallet',{'filename':shown['actual_wallet'],'load_on_startup':True},timeout=600)
        self.verify_loaded(p,facts,shown['actual_wallet'],balances=False)
        if not self.located(facts,shown['actual_wallet']):raise ValueError('Wallet file identity changed during reconciliation.')
        if shown['applied']:
            self.update_references(p['wallet'],shown['actual_wallet']);proof=result(self.store,p,'complete',new_wallet=shown['actual_wallet'],identity_verified=True,policy_identity=facts['policy_identity'],archive_skipped=False,reconciled=True)
        else:proof=result(self.store,p,'error',identity_verified=True,attempted=False,outcome_uncertain=False,original_wallet_restored=True,reconciled=True,applied=False)
        self.finish(key,proof)
        return {'message':'Local rename reconciled: '+shown['actual_wallet']+' is loaded and its original file identity, public policy, key capability and encryption are verified. No files were renamed during reconciliation. The signed outcome is queued for Wallet Server.'}
    def update_references(self,old,new):
        # Only local mutable routing/history hints; signed proposals stay immutable.
        with self.store.edit() as s:
            for row in s.get('vaults',{}).values():
                for field in ('owner','owner_wallet','monitor_wallet'):
                    if row.get(field)==old:row[field]=new
            for record in s.get('approved_wallets',{}).values():
                if record.get('monitor_wallet')==old:record['monitor_wallet']=new
                for role,wallet in record.get('signing_wallets',{}).items():
                    if wallet==old:record['signing_wallets'][role]=new
            if old in s.get('history_coverage',{}):s['history_coverage'][new]=s['history_coverage'].pop(old)
    def archive_complete(self,job,evidence):
        row=self.archive_jobs.get(job)
        if not row:return
        proof=result(self.store,row['request'],'complete',new_wallet=row['new_wallet'],identity_verified=True,archive_skipped=False,old_archive_id=row['request']['archive_id'],**evidence);self.finish(row['key'],proof);self.archive_jobs.pop(job,None)
    def finish(self,key,proof):
        self.attempts.pop(key,None)
        with self.store.edit() as s:s['pending'].pop(key,None);s['completed'][key]={'kind':'wallet_rename','at':time.time(),'result':proof}
    def busy(self):return bool(self.archive_jobs)
