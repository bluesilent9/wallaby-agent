"""Local archive approval and RAM-only backup staging. No Wallet Server-selected paths."""
import copy,hashlib,shutil,time
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from public_policy import descriptors
from wallet_setup import MemoryCore,secret_dialog
from wallet_setup_signing import signers_for_policy
from archive_format import identity,bundle
from archive_requests import validate_task,result

class Operations:
    def __init__(self,core,store,setup,archives,enforce):
        self.core=core;self.store=store;self.setup=setup;self.archives=archives;self.enforce=enforce;self.reviews={};self.jobs={};self.verified_replacements={}
        from archive_cancel import Cancellations
        self.cancellations=Cancellations(self)
        setup.external_burn_complete=self.complete;setup.burner.replacement_resolver=self.replacements
    def regular(self,name):return not any(name in r['routes'] for r in self.archives.loaded.values())
    def review(self,key):
        p=validate_task(self.store.read()['pending'][key]['proposal'])
        if p['kind']=='archive_cancel':return self.cancellations.review(key)
        job=self.jobs.get(key)
        if p['kind']=='archive_wallet' and job and job['phase']=='queued':
            return {'kind':'archive_wallet','id':key,'archive':{**job['facts'],'staged':True,'removable':self.setup.burner.removable(key)}}
        if p['kind']=='destroy_disc':
            if p.get('version')==2:
                from extinct_discs import review
                return review(self,key)
            proof=self.destruction_proof(p)
            return {'kind':'destroy_disc','id':key,'destruction':{'archive_id':p['archive_id'],'label':p['label'],'replacement_image_sha256':p['replacement_image_sha256'],'coverage':proof['members'],'physical_confirmation_only':True,'creator_confirmation_required':proof.get('creator_confirmation_required',False),'creator_fingerprint':proof.get('creator_fingerprint','')}}
        if not self.regular(p['wallet']):raise ValueError('Wallet Server archival is only for persistent node wallets. Use the explicit loaded-disc refresh operation for an archive.')
        info=rpc(self.core,'getwalletinfo',[],p['wallet']);raw=rpc(self.core,'listdescriptors',[False],p['wallet'])
        if not info.get('private_keys_enabled') or info.get('scanning') or descriptors(raw)!=descriptors(p['public_wallet']):raise ValueError('A matching, fully loaded private-key wallet is required. Watch-only, extinct and disc-only sources cannot authorise archiving.')
        policies=[]
        for supplied in p['related_policies']:
            matches=[]
            for name in rpc(self.core,'listwallets'):
                if not self.regular(name):continue
                candidate=rpc(self.core,'listdescriptors',[False],name)
                if descriptors(candidate)==descriptors(supplied):matches.append((name,candidate))
            if len(matches)!=1 or p['wallet'] not in signers_for_policy(self.core,matches[0][1]):raise ValueError('A proposed shared policy cannot be independently matched to this local signing account.')
            policies.append(matches[0][1])
        facts={'wallet':p['wallet'],'chain':rpc(self.core,'getblockchaininfo')['chain'],'encrypted': 'unlocked_until' in info,'public_wallet':raw,'related_policies':policies,'policy_hash':digest(raw),'backup_only':True,'source_unchanged':True}
        self.reviews[key]=(copy.deepcopy(p),facts,time.monotonic());return {'kind':'archive_wallet','id':key,'archive':facts}
    def approve(self,key):
        self.enforce();old=self.reviews.get(key)
        if not old or time.monotonic()-old[2]>600:raise ValueError('Review this exact local wallet before approving its archive.')
        current=self.review(key)
        if old[0]!=self.reviews[key][0] or old[1]!=current['archive']:raise ValueError('Wallet or public policy changed; review again.')
        p=old[0];facts=old[1];row=self.store.read()['pending'].get(key)
        if not row or row['state']!='pending' or row.get('withdrawn'):raise ValueError('Archive request is no longer active. No backup was repeated.')
        folder=self.store.root/'archive-jobs'/key;folder.mkdir(mode=0o700,parents=True,exist_ok=False);path=folder/'wallet.dat'
        with self.store.edit() as saved:saved['pending'][key]['state']='attempted'
        self.jobs[key]={'request':p,'folder':folder,'phase':'capturing'}
        try:
            rpc(self.core,'backupwallet',[__import__('core_ram_path').for_core(self.core,path)],p['wallet'],timeout=600)
            if not facts['encrypted']:
                temp=MemoryCore(folder/'encryption-node',facts['chain'],self.setup.binary)
                try:
                    rpc(temp.core,'restorewallet',{'wallet_name':'archive','backup_file':str(path),'load_on_startup':False});password=secret_dialog('New archive signing-wallet passphrase · source wallet remains unchanged',self.setup.environment,confirm=True)
                    if len(password)<12:raise ValueError('Use at least 12 characters for the archival signing wallet.')
                    try:rpc(temp.core,'encryptwallet',[password],'archive')
                    finally:password=None
                    path.unlink();rpc(temp.core,'backupwallet',[str(path)],'archive')
                finally:temp.close();shutil.rmtree(temp.root)
            from wallet_labels import read_labels
            labels=read_labels(self.core,p['wallet'],facts['public_wallet'],[])
            recovery={'version':1,'kind':'node_wallet','chain':facts['chain'],'name':p['wallet'],'policy_hash':facts['policy_hash'],'public_wallet':facts['public_wallet'],'labels':labels}
            if facts['related_policies']:
                # A single signing account can serve several generations. All old
                # public descriptors are retained, not only the latest vault.
                rows=[];address_labels={}
                for public in facts['related_policies']:
                    rows.extend(public['descriptors'])
                    for label in read_labels(self.core,public['wallet_name'],public,[]):
                        if label['address'] in address_labels and address_labels[label['address']]!=label:raise ValueError('Related policies contain conflicting labels for one address.')
                        address_labels[label['address']]=label
                recovery['policy_labels']=list(address_labels.values())
                recovery['public_policies']={'wallet_name':p['wallet'],'descriptors':rows}
            self.setup.burner.queue(key,{key:str(path)},recovery);self.jobs[key].update(phase='queued',recovery=recovery,facts=copy.deepcopy(facts))
            result(self.store,p,'queued')
            return {'message':'Wallet backup staged in protected RAM. Select it with other approved wallets in Disc Operations; verified completion is reported only after every requested disc passes read-back.','burn_authorised':True}
        except Exception:self.jobs[key]['phase']='error';raise
    def delete(self,key):
        self.enforce()
        from archive_requests import delete
        job=self.jobs.get(key)
        if job:
            if job['request'] is None or job['phase']!='queued' or not self.setup.burner.removable(key):raise ValueError('Only an unused staged archive can be removed. Finish or reconcile any disc write and read-back first.')
            self.setup.burner.cancel_members({key})
            # Do not mark a partially cleaned capture as unattempted.
            job['phase']='discarding'
            if job['folder']:shutil.rmtree(job['folder'])
            with self.store.edit() as saved:saved['pending'][key]['state']='pending'
            self.jobs.pop(key);self.reviews.pop(key,None)
        return delete(self.store,key)
    def queue_loaded(self,ids,confirmed):
        self.enforce()
        if confirmed is not True or not isinstance(ids,list) or not ids or len(ids)>15 or len(set(ids))!=len(ids):raise ValueError('Select and explicitly approve loaded archive accounts for the replacement disc.')
        records=[]
        for ident in ids:
            r=self.archives.loaded.get(ident)
            if not r:raise ValueError('A selected archive is no longer loaded.')
            key=digest({'refresh_archive':r['archive_id'],'identity':identity(r['recovery']),'recovery':r['recovery']})
            if key in self.jobs:raise ValueError('That exact archive revision is already queued.')
            records.append((key,r))
        for key,r in records:
            self.setup.burner.queue(key,{key:str(r['wallet'])},copy.deepcopy(r['recovery']));self.jobs[key]={'request':None,'folder':None,'phase':'queued','recovery':copy.deepcopy(r['recovery']),'source_archive':r['archive_id']}
        return {'message':'Loaded accounts queued for a replacement archive. Select every member of an old disc before requesting its destruction.'}
    def replacements(self,items):
        available={identity(r):r for i,w,r in items};safe=[]
        for archive_id,old in self.archives.catalogs.items():
            if set(old)<=set(available) and all(self.covers(available[k],r) for k,r in old.items()):safe.append(archive_id)
        return safe
    def covers(self,new,old):
        if identity(new)!=identity(old):return False
        a=old.get('policy_extensions',[]);b=new.get('policy_extensions',[])
        from policy_refresh import transition
        if [transition(v) for v in b[:len(a)]]!=[transition(v) for v in a]:return False
        if old.get('kind')=='node_wallet':
            if not {digest(v) for v in old.get('labels',[])}<={digest(v) for v in new.get('labels',[])}:return False
            old_raw=old.get('public_policies',old['public_wallet']);new_raw=new.get('public_policies',new['public_wallet'])
            if not descriptors(old_raw)<=descriptors(new_raw):return False
            if not {digest(v) for v in old.get('policy_labels',[])}<={digest(v) for v in new.get('policy_labels',[])}:return False
        return True
    def complete(self,key,image_sha256,notify_cancel=True):
        row=self.jobs[key];job=self.setup.burner.job;container=job['recovery'];members=sorted(identity(r) for i,w,r in job.get('_members') or [(key,None,row['recovery'])])
        replacements=container.get('replaces',[])
        from policy_refresh import validate_extensions
        policies={identity(r):digest(validate_extensions(r)) for _,_,r in (job.get('_members') or [(key,None,row['recovery'])]) if r.get('policy_extensions')}
        for old in replacements:self.verified_replacements[old]={'image_sha256':image_sha256,'members':members,'member_policies':policies,'old_policies_retained':True,'readback_verified':True}
        evidence={'members':__import__('archive_inventory').evidence(job),'archive_id':job.get('archive_id'),'disc_count':job['disc_count'],'attempted_disc_count':job.get('_attempts',job['disc_count']),'readback_verified':True,'image_sha256':image_sha256,'archive_members':members,'replacements':[{ 'archive_id':old,**self.verified_replacements[old]} for old in replacements]}
        if evidence.get('archive_id'):
            with self.store.edit() as saved:saved.setdefault('verified_archive_discs',{})[evidence['archive_id']]={'members':evidence['members'],'disc_count':job['disc_count'],'image_sha256':image_sha256,'retired_members':{identity(recovery):recovery.get('retired_policy_hashes',[]) for _,_,recovery in job.get('_members') or [(key,None,row['recovery'])]}}
        from policy_refresh_backups import verified
        verified(self,[r for _,_,r in job.get('_members') or [(key,None,row['recovery'])]],image_sha256)
        if row['request']:receipt=result(self.store,row['request'],'complete',**evidence)
        else:
            from setup_messages import sign
            self.store.queue('archive_inventory',sign(self.store,{'version':1,'event':'replacement_verified',**evidence}))
        from extinct_discs import completed
        completed(self,{identity(r):r for _,_,r in job.get('_members') or [(key,None,row['recovery'])]},image_sha256)
        if getattr(self,'rename_complete',None):self.rename_complete(key,evidence)
        row['phase']='complete'
        if row['folder']:shutil.rmtree(row['folder'])
        with self.store.edit() as s:
            s['pending'].pop(key,None);s['completed'][key]={'kind':'archive_wallet','at':time.time(),**({'result':receipt} if row['request'] else {})}
        if notify_cancel:self.cancellations.completed(image_sha256)
    def destruction_proof(self,p):
        local=self.verified_replacements.get(p['archive_id'])
        if not local and p.get('replacement_receipt'):
            from setup_messages import verify
            own=self.setup.own_identity()['public_key'];creator=p['replacement_receipt'].get('public_key');message=verify(self.store,p['replacement_receipt'],creator)
            if message.get('readback_verified') is True:
                local=next((r for r in message.get('replacements',[]) if r.get('archive_id')==p['archive_id']),None)
                if local:
                    local={**local,'members':local.get('members',message.get('archive_members',[]))}
                    if creator!=own:
                        from wallet_preview import fingerprint
                        old=self.archives.catalogs.get(p['archive_id'],{});new=self.archives.catalogs.get(message.get('archive_id'),{})
                        if not old or not new or not all(k in new and self.covers(new[k],v) for k,v in old.items()):raise ValueError('Read the original and replacement discs here and verify full coverage before accepting another Agent replacement proof.')
                        local.update(creator_confirmation_required=True,creator_fingerprint=fingerprint(creator))
        if not local or local.get('image_sha256')!=p['replacement_image_sha256'] or local.get('old_policies_retained') is not True or local.get('readback_verified') is not True or not local.get('members'):raise ValueError('No locally verified full replacement covers this old disc. Do not destroy it.')
        from policy_refresh_backups import check_destruction
        check_destruction(self,p['archive_id'],local)
        return local
    def destroyed(self,key,confirmed,creator_pin=None):
        self.enforce();p=validate_task(self.store.read()['pending'][key]['proposal'])
        if p.get('version')==2:raise ValueError('Use the extinct-disc checklist and connect the preserving Agent.')
        if p['kind']!='destroy_disc' or confirmed is not True:raise ValueError('Confirm physical destruction locally before completing the task.')
        proof=self.destruction_proof(p)
        if proof.get('creator_confirmation_required'):
            from direct_identity import require_fingerprint
            require_fingerprint(self.store,proof['creator_fingerprint'])
        result(self.store,p,'complete',destruction_confirmed_locally=True,archive_id=p['archive_id'],image_sha256=p['replacement_image_sha256'])
        with self.store.edit() as s:s['pending'].pop(key,None);s['completed'][key]={'kind':'destroy_disc','at':time.time()}
        from policy_refresh_backups import destroyed
        destroyed(self,p['archive_id'])
        return {'message':'Physical disc destruction recorded from your local confirmation.'}
    def busy(self):return any(v['phase']!='complete' for v in self.jobs.values())
