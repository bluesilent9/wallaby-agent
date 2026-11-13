"""Archive withdrawal is not proof of disc cleanup. All state stays in protected RAM."""
import copy,re,shutil,time
from pathlib import Path
from approval_store import digest
from archive_format import identity
from archive_inventory import evidence,member
from build8_policy import descriptors
from setup_messages import verify
HEX=re.compile('[0-9a-f]{64}')
CAPABILITY='wallet_archive_cancel_v1'

def validate(p):
    required={'kind','version','nonce','request_id','wallet','archive_request','completed_receipt','finish_inflight_burn_and_verify','require_local_destruction_confirmation','preserve_unrelated_members'}
    if not isinstance(p,dict) or set(p)!=required or p.get('kind')!='archive_cancel' or type(p.get('version')) is not int or p['version']!=1 or any(p[k] is not True for k in ('finish_inflight_burn_and_verify','require_local_destruction_confirmation','preserve_unrelated_members')):raise ValueError('Invalid archive cancellation safeguards.')
    from archive_requests import validate_task
    if not isinstance(p['archive_request'],dict) or p['archive_request'].get('kind')!='archive_wallet':raise ValueError('Only an exact original archive-wallet request may be cancelled.')
    original=validate_task(p['archive_request'])
    if original['kind']!='archive_wallet' or p['wallet']!=original['wallet'] or p['completed_receipt'] is not None and not isinstance(p['completed_receipt'],dict):raise ValueError('Archive cancellation is not bound to its source wallet request.')
    if any(not HEX.fullmatch(str(p[k])) for k in ('nonce','request_id')) or digest({k:v for k,v in p.items() if k!='request_id'})!=p['request_id']:raise ValueError('Archive cancellation contents differ from their identifier.')
    return p

class Cancellations:
    def __init__(self,ops):self.ops=ops;self.store=ops.store;self.plans={};self.detached={};self.written_sets={};self.coverage={};self.retired={};self.foreign_authors={}
    def task(self,key):
        row=self.store.read()['pending'].get(key)
        if not row or row['proposal']['kind']!='archive_cancel':raise ValueError('This archive cancellation is no longer pending.')
        return validate(row['proposal'])
    def original_key(self,p):return digest(p['archive_request'])
    def own_receipt(self,p):
        original=self.original_key(p);local=self.store.read()['completed'].get(original,{}).get('result');choices=[]
        for envelope in (p['completed_receipt'],local.get('signed_receipt') if local else None):
            if envelope is None:continue
            author=envelope.get('public_key');value=verify(self.store,envelope,author)
            if author!=self.ops.setup.own_identity()['public_key']:
                from wallet_preview import fingerprint
                self.foreign_authors.setdefault(original,set()).add(fingerprint(author))
            if value.get('version')!=1 or value.get('request_id')!=p['archive_request']['request_id']:raise ValueError('Archive evidence belongs to another request.')
            if value.get('status')=='complete':
                if value.get('readback_verified') is not True or not HEX.fullmatch(str(value.get('archive_id'))) or not HEX.fullmatch(str(value.get('image_sha256'))) or type(value.get('disc_count')) is not int or not 1<=value['disc_count']<=99:raise ValueError('Invalid completed archive evidence.')
                if 'attempted_disc_count' in value and (type(value['attempted_disc_count']) is not int or not value['disc_count']<=value['attempted_disc_count']<=100000):raise ValueError('Invalid physical disc attempt count.')
                choices.append(value)
        for value in choices:self.remember_receipt(value,original)
        return choices[0] if choices else None
    def remember_receipt(self,value,original):
        physical={'archive_id':value['archive_id'],'members':value['members'],'disc_count':max(value['disc_count'],value.get('attempted_disc_count',value['disc_count'])),'verified_discs':value['disc_count'],'verification_finished':True,'verification_succeeded':True}
        self.remember(physical,{original})
    def remember(self,physical,requests,job=None):
        key=physical['archive_id'];old=self.written_sets.get(key)
        if old and old['physical']['members']!=physical['members']:raise ValueError('One encrypted archive identity has contradictory member evidence.')
        if old:
            old['requests'].update(requests);old['physical'].update(physical)
            if job is not None:old['job']=job
        else:self.written_sets[key]={'physical':copy.deepcopy(physical),'requests':set(requests),'job':job}
    def remember_job(self,job):
        requests=set()
        for key,files,recovery in self.members(job):requests.add(self.ops.jobs.get(key,{}).get('source_original') or key)
        physical={'archive_id':job.get('archive_id'),'members':evidence(job),'disc_count':job.get('_attempts',job.get('discs_verified',0) or 1),'verified_discs':job.get('discs_verified',0),'verification_finished':bool(job.get('_verification_finished',job['phase'] in ('complete','completing'))),'verification_succeeded':bool(job.get('_verification_succeeded',job['phase'] in ('complete','completing')))}
        self.remember(physical,requests,job)
        return physical
    def current_job(self,original):
        job=self.ops.setup.burner.job
        if job and any(i==original for i,w,r in self.members(job)):return job
        return self.detached.get(original)
    def members(self,job):return job.get('_members') or [(job['id'],job['wallets'],job['recovery'])]
    def finish(self,key,p,**facts):
        from archive_requests import result
        receipt=result(self.store,p,'complete',request_cancelled=True,**facts)
        with self.store.edit() as s:
            s['pending'].pop(key,None);s['completed'][key]={'kind':'archive_cancel','at':time.time(),'result':receipt}
        self.plans.pop(key,None)
        from activity_log import event
        event('archive.cancellation','Completed locally · disc_created='+str(facts.get('disc_created'))+' · destroyed_discs='+str(facts.get('destroyed_disc_count',0)))
        return {'message':'Archive cancellation completed. Its signed cleanup result is queued for Wallet Server.'}
    def observe(self,mark_only=False):
        for key,row in list(self.store.read()['pending'].items()):
            if row['proposal']['kind']!='archive_cancel':continue
            p=validate(row['proposal']);original=self.original_key(p);job=self.current_job(original);source=self.ops.jobs.get(original)
            burner=self.ops.setup.burner;active=bool(job is burner.job and burner.thread and burner.thread.is_alive())
            if job and job['phase']!='complete' and (job.get('_write_started') or active):job['_cancel_pending']=True
            if mark_only:continue
            if source and source['phase']=='queued' and not self.own_receipt(p) and not self.foreign_authors.get(original) and (burner.removable(original) or job is not None and not job.get('_write_started') and not active):
                burner.cancel_members({original})
                if source.get('folder') and source['folder'].exists():shutil.rmtree(source['folder'])
                source['phase']='complete'
                with self.store.edit() as s:s['pending'].pop(original,None);s['completed'][original]={'kind':'archive_wallet','at':time.time(),'cancelled_unused':True}
                self.finish(key,p,disc_created=False,unused_capture_removed=True);continue
            if not source and row.get('source_unattempted') is True and not self.own_receipt(p) and not self.foreign_authors.get(original):self.finish(key,p,disc_created=False,unattempted_request_removed=True)
    def facts(self,key):
        p=self.task(key);original=self.original_key(p);job=self.current_job(original);receipt=self.own_receipt(p)
        burner=self.ops.setup.burner;active=bool(job is burner.job and burner.thread and burner.thread.is_alive())
        if job and job.get('_write_started'):
            physical=self.remember_job(job)
        elif receipt:physical={'archive_id':receipt['archive_id'],'members':receipt['members'],'disc_count':max(receipt['disc_count'],receipt.get('attempted_disc_count',receipt['disc_count'])),'verified_discs':receipt['disc_count'],'verification_finished':True,'verification_succeeded':True}
        else:physical=self.plans.get(key,{}).get('manual_physical')
        if active:return p,job,{'wallet':p['wallet'],'waiting':True,'message':'A local disc operation is still running. It will finish writing and verification; cancellation never terminates the writer.'}
        # A shared-disc replacement may itself later need cancellation. Follow
        # its local provenance, retaining every still-unrelated member again.
        changed=True
        while changed:
            changed=False
            roots={a for a,r in self.written_sets.items() if original in r['requests']}
            for record in self.written_sets.values():
                if original not in record['requests'] and roots & record.get('parents',set()) and any(descriptors(m['public_wallet'])==descriptors(p['archive_request']['public_wallet']) for m in record['physical']['members']):record['requests'].add(original);changed=True
        destroyed=self.plans.get(key,{}).get('destroyed',set())
        if physical and physical['archive_id'] in destroyed:physical=None
        if physical is None:
            candidate=next((r for a,r in self.written_sets.items() if original in r['requests'] and a not in destroyed),None)
            if candidate:physical=copy.deepcopy(candidate['physical']);job=candidate['job']
        if physical:
            rows=physical['members']
            if not isinstance(rows,list) or not 1<=len(rows)<=15 or len({m.get('member_id') for m in rows})!=len(rows):raise ValueError('Archive member evidence is incomplete or duplicated.')
            targets=[m['member_id'] for m in rows if descriptors(m['public_wallet'])==descriptors(p['archive_request']['public_wallet'])]
            if len(targets)!=1:raise ValueError('The cancelled wallet cannot be uniquely matched to the original disc membership.')
            for m in rows:
                if not HEX.fullmatch(str(m['member_id'])):raise ValueError('Invalid original archive member identity.')
                descriptors(m['public_wallet'])
            targets=set(targets)|self.retired.get(physical['archive_id'],set())
            for row in self.store.read()['pending'].values():
                other=row['proposal']
                if other['kind']=='archive_cancel' and self.original_key(other) in self.written_sets.get(physical['archive_id'],{}).get('requests',{original}):targets.update(m['member_id'] for m in rows if descriptors(m['public_wallet'])==descriptors(other['archive_request']['public_wallet']))
            targets=sorted(targets);others=[m for m in rows if m['member_id'] not in targets];plan=self.plans.get(key,{})
            cover=self.coverage.get(physical['archive_id'],{});wanted={m['member_id']:m for m in others}
            cover_ready=bool(cover and not (burner.thread and burner.thread.is_alive()) and all(self.ops.jobs.get(k,{}).get('phase')=='complete' for k in cover.get('jobs',[])) and all(i in cover['members'] and member(cover['members'][i])==m for i,m in wanted.items()))
            current={'wallet':p['wallet'],'waiting':False,'disc_created':True,'archive_id':physical['archive_id'],'disc_count':physical['disc_count'],'verified_discs':physical['verified_discs'],'verification_finished':physical['verification_finished'],'verification_succeeded':physical['verification_succeeded'],'members':rows,'cancelled_members':targets,'remaining_members':others,'replacement_required':bool(others),'replacement_verified':cover_ready,'replacement_image_sha256':cover.get('image_sha256') if cover_ready else None,'replacement_queued':bool(plan.get('replacement_jobs'))}
            return p,job,current
        source=self.ops.jobs.get(original)
        if source and source['phase'] not in ('complete','queued'):raise ValueError('The source capture outcome needs local reconciliation; it cannot be reported as an unattempted archive.')
        return p,job,{'wallet':p['wallet'],'waiting':False,'disc_created':False,'unknown_prior_disc':True,'available_archives':[{'archive_id':a,'names':[m.get('name','Account') for m in [member(r) for r in entries.values()]]} for a,entries in self.ops.archives.catalogs.items() if any(descriptors(r.get('public_wallet',{}))==descriptors(p['archive_request']['public_wallet']) for r in entries.values() if r.get('kind')=='node_wallet')],'message':'No local burn evidence survives in this workspace. Confirm that no disc or partial disc was ever written for this exact request. If a disc exists, read it here; do not confirm no disc.'}
    def display_author(self,p,facts):
        authors=self.foreign_authors.get(self.original_key(p),set())
        if len(authors)>1:raise ValueError('Several external disc authors need local reconciliation; no physical cleanup is authorised.')
        facts['creator_confirmation_required']=bool(authors);facts['creator_fingerprint']=next(iter(authors),'')
        if authors and facts.get('disc_created'):
            catalog=self.ops.archives.catalogs.get(facts['archive_id'],{})
            actual={k:member(r) for k,r in catalog.items()};offered={r['member_id']:r for r in facts['members']}
            facts['disc_read_verified']=bool(actual and actual==offered)
        else:facts['disc_read_verified']=True
        return facts
    def authorise(self,p,facts,pin,require_disc=True):
        facts=self.display_author(p,facts)
        if facts['creator_confirmation_required']:
            from direct_identity import require_fingerprint
            require_fingerprint(self.store,facts['creator_fingerprint'])
        if require_disc and not facts['disc_read_verified']:raise ValueError('Read the original disc in Disc Operations on this Agent and verify its complete membership before cleanup.')
    def review(self,key):
        p,job,facts=self.facts(key)
        self.plans.setdefault(key,{}).update(facts=copy.deepcopy(facts))
        return {'kind':'archive_cancel','id':key,'cancellation':self.display_author(p,facts)}
    def detach(self,original,job):
        burner=self.ops.setup.burner
        if job is not burner.job:return
        if burner.thread and burner.thread.is_alive():raise ValueError('Wait for the running writer and read-back to finish.')
        self.detached[original]=job
        for ident,files,recovery in self.members(job):self.detached[self.ops.jobs.get(ident,{}).get('source_original') or ident]=job
        burner.job=None;burner.selected=None
    def sources(self,job,facts):
        wanted={m['member_id']:m for m in facts['remaining_members']};found={}
        if job:
            for i,files,recovery in self.members(job):
                ident=identity(recovery)
                if ident in wanted and files and all(Path(v).is_file() for v in files.values()):found[ident]={'wallet':next(iter(files.values())),'recovery':recovery,'original':i}
        if set(found)!=set(wanted):
            if set(self.ops.archives.catalogs.get(facts['archive_id'],{}))!={m['member_id'] for m in facts['members']}:raise ValueError('Read the original disc in Disc Operations first. Its full authenticated membership must match before preparing a replacement.')
            for r in [*self.ops.archives.staged.values(),*self.ops.archives.loaded.values()]:
                ident=identity(r['recovery'])
                if r.get('archive_id')==facts['archive_id'] and ident in wanted:found[ident]={'wallet':str(r['wallet']),'recovery':r['recovery'],'original':None}
        if set(found)!=set(wanted):raise ValueError('The unrelated wallets are not all available in protected RAM. Read the original disc before making its replacement.')
        for ident,r in found.items():
            if member(r['recovery'])!=wanted[ident]:raise ValueError('Replacement source differs from the authenticated original member.')
        return found
    def stage(self,key,confirmed,pin=None):
        self.ops.enforce();p,job,facts=self.facts(key)
        if confirmed is not True or facts.get('waiting') or not facts.get('disc_created') or not facts.get('verification_finished') or not facts['replacement_required']:raise ValueError('Wait for writing/verification, then explicitly approve preserving every unrelated member.')
        self.authorise(p,facts,pin)
        plan=self.plans.setdefault(key,{})
        if plan.get('replacement_jobs'):raise ValueError('This replacement is already queued. Finish it in Disc Operations.')
        found=self.sources(job,facts);original=self.original_key(p);burner=self.ops.setup.burner
        if burner.job and burner.job['phase']=='complete' and not (burner.thread and burner.thread.is_alive()):burner.job=None;burner.selected=None
        if job is not burner.job and burner.job:raise ValueError('Finish the current disc set before preparing this replacement.')
        self.detach(original,job) if job else None
        waiting=list(burner.pending);burner.pending=[];ids=[]
        for ident,r in found.items():
            new=digest({'archive_cancel':key,'source_archive':facts['archive_id'],'member':ident});ids.append(new);recovery=copy.deepcopy(r['recovery'])
            self.ops.jobs[new]={'request':None,'folder':None,'phase':'queued','recovery':recovery,'source_archive':facts['archive_id'],'source_original':r['original']}
            burner.queue(new,{new:r['wallet']},recovery)
        for row in waiting:burner.queue(*row)
        burner.job['_required_members']=ids;burner.select(ids)
        plan.update(facts=facts,replacement_jobs=ids,sources=found,replacement_verified=False)
        from activity_log import event
        event('archive.cancellation','Replacement queued · unrelated_members='+str(len(found)))
        return {'message':'All unrelated members are queued for a replacement disc. Burn and verify it in Disc Operations before confirming destruction.'}
    def completed(self,image_sha256):
        job=self.ops.setup.burner.job;self.remember_job(job);actual={identity(r):r for i,w,r in self.members(job)}
        for key,plan in list(self.plans.items()):
            sources=plan.get('sources',{})
            if not sources or not set(sources)<=set(actual) or not all(self.ops.covers(actual[i],r['recovery']) for i,r in sources.items()):continue
            plan.update(replacement_verified=True,replacement_image_sha256=image_sha256)
            self.written_sets[job['archive_id']].setdefault('parents',set()).add(plan['facts']['archive_id'])
            self.coverage[plan['facts']['archive_id']]={'members':copy.deepcopy(actual),'image_sha256':image_sha256,'jobs':list(plan['replacement_jobs'])}
            # Original unrelated requests complete only when this replacement has
            # actually passed read-back, never when the cancelled disc is discarded.
            for r in sources.values():
                old=r['original']
                if old in self.ops.jobs and self.ops.jobs[old]['phase']!='complete':self.ops.complete(old,image_sha256,notify_cancel=False)
    def bind(self,key,archive_id,confirmed,pin=None):
        self.ops.enforce();p,job,facts=self.facts(key)
        if confirmed is not True or facts.get('disc_created') or facts.get('waiting') or not isinstance(archive_id,str) or not HEX.fullmatch(archive_id):raise ValueError('Explicitly select the original authenticated disc after reading it in Disc Operations.')
        self.authorise(p,facts,pin,require_disc=False)
        catalog=self.ops.archives.catalogs.get(archive_id,{})
        rows=[member(r) for r in catalog.values()]
        if sum(descriptors(r['public_wallet'])==descriptors(p['archive_request']['public_wallet']) for r in rows)!=1:raise ValueError('This read disc does not uniquely contain the cancelled wallet.')
        self.plans.setdefault(key,{})['manual_physical']={'archive_id':archive_id,'members':rows,'disc_count':1,'verified_discs':0,'verification_finished':True,'verification_succeeded':False}
        return {'message':'Read disc selected for local cleanup. Account for every copy and partial disc; the package read does not claim full-medium read-back.'}
    def check(self,key,confirmed,pin=None):
        self.ops.enforce();p,job,facts=self.facts(key)
        if confirmed is not True or facts.get('waiting') or not job or not facts.get('disc_created'):raise ValueError('Keep the cancelled disc in its original optical drive and confirm a read-only check.')
        self.authorise(p,facts,pin)
        return self.ops.setup.burner.verify_cancellation(job)
    def confirm(self,key,confirmed,no_disc=False,destroyed_disc_count=None,pin=None):
        self.ops.enforce();p,job,facts=self.facts(key)
        if confirmed is not True or facts.get('waiting'):raise ValueError('Finish any active writer/read-back and explicitly confirm the local cancellation outcome.')
        original=self.original_key(p)
        self.authorise(p,facts,pin)
        if not facts['disc_created']:
            if no_disc is not True:raise ValueError('Confirm that no disc or partial disc was ever written; missing local state is not proof of that.')
            return self.finish(key,p,disc_created=False,confirmed_no_disc_locally=True)
        if not facts['verification_finished']:raise ValueError('Verification has not finished. Check the cancelled disc before recording physical destruction.')
        if facts['replacement_required'] and not facts['replacement_verified']:raise ValueError('Preserve every unrelated member on a read-back-verified replacement before destroying this shared disc.')
        count=facts['disc_count'] if destroyed_disc_count is None else destroyed_disc_count
        if type(count) is not int or not facts['disc_count']<=count<=100000:raise ValueError('Confirm the number of every created, partial and duplicate disc; the count cannot be less than the known written set.')
        if job:self.detach(original,job)
        plan=self.plans.setdefault(key,{})
        plan.setdefault('destroyed_counts',{})[facts['archive_id']]=count;plan.setdefault('primary_archive',facts['archive_id']);plan['replacement_required_any']=plan.get('replacement_required_any',False) or facts['replacement_required']
        if facts['replacement_verified']:plan['last_replacement_image']=facts['replacement_image_sha256']
        plan.setdefault('destroyed',set()).add(facts['archive_id']);self.retired.setdefault(facts['archive_id'],set()).update(facts['cancelled_members'])
        more=[a for a,r in self.written_sets.items() if original in r['requests'] and a not in plan['destroyed']]
        if more:
            for field in ('replacement_jobs','sources','replacement_verified'):plan.pop(field,None)
            return {'more_cleanup':True,'message':'Destruction of this disc set recorded locally. A replacement also contains this cancelled account; review the next disc set before cancellation can finish.'}
        source=self.ops.jobs.get(original)
        if source:
            if source.get('folder') and source['folder'].exists():shutil.rmtree(source['folder'])
            source['phase']='complete'
        burner=self.ops.setup.burner
        if not burner.job and burner.pending:burner.authorise(*burner.pending.pop(0))
        if job:
            directory=burner.root/job['id']
            if directory.exists():shutil.rmtree(directory)
        return self.finish(key,p,disc_created=True,archive_id=(self.own_receipt(p) or {}).get('archive_id',plan['primary_archive']),destruction_confirmed_locally=True,unrelated_members_preserved=True,burn_finished=True,verification_finished=True,verification_succeeded=facts['verification_succeeded'],replacement_required=plan['replacement_required_any'],replacement_readback_verified=bool(plan.get('last_replacement_image')),replacement_image_sha256=plan.get('last_replacement_image'),disc_count=sum(plan['destroyed_counts'].values()),destroyed_disc_count=sum(plan['destroyed_counts'].values()),destroyed_disc_sets=plan['destroyed_counts'],destroyed_archives=sorted(plan['destroyed']),cancelled_member_ids=facts['cancelled_members'])
