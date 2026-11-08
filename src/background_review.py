"""Read-only policy reviews must not monopolise workspace status or inventory."""
import copy,threading,time
from approval_store import digest


class Reviews:
    def __init__(self,owner):self.owner=owner;self.jobs={};self.active=None
    def start(self,key,kind,review):
        row=self.owner.store.read()['pending'][key];proposal=digest({'proposal':row['proposal'],'state':row['state'],'destroyed_archives':row.get('destroyed_archives',[]),'cancel_requested':row.get('cancel_requested')})
        old=self.jobs.get(key)
        if old and old['proposal']==proposal:
            if old['state']=='running':return self.pending(key,old)
            if old['state']=='done' and time.monotonic()-old['finished']<540:
                result=copy.deepcopy(old['result'])
                if row['proposal']['kind']=='wallet_policy_refresh':
                    from peer_mesh import observe
                    result['refresh']['peer_mesh']=observe(self.owner.store,row['proposal'],'refresh')
                return result
            if old['state']=='error':
                self.jobs.pop(key)
                from diagnostics import LocalActionFailure
                raise LocalActionFailure('public_review_failed',old['error'])
        if self.active:raise ValueError('Another local policy review is checking the blockchain. Wait for it to finish.')
        job={'proposal':proposal,'kind':kind,'state':'running','started':time.monotonic()};self.jobs[key]=job;self.active=key
        # Bound retained public results independently of the request queue.
        for previous in list(self.jobs):
            if len(self.jobs)<=16:break
            if previous!=key and self.jobs[previous]['state']!='running':self.jobs.pop(previous)
        def run():
            from activity_log import event
            event('policy.review','Read-only review started; status and public inventory remain available.')
            try:
                result=review(key)
                with self.owner.lock:
                    saved=self.owner.store.read();current=saved['pending'].get(key)
                    from cancellation import blocked
                    if not current or digest({'proposal':current['proposal'],'state':current['state'],'destroyed_archives':current.get('destroyed_archives',[]),'cancel_requested':current.get('cancel_requested')})!=proposal or current.get('cancel_requested') or blocked(saved,current['proposal']):raise __import__('diagnostics').LocalActionFailure('public_review_withdrawn','This review was withdrawn or cancelled. Review the current cancellation instead; no policy was approved.')
                    job.update(state='done',result=result,finished=time.monotonic())
                event('policy.review','Read-only review completed · elapsed_ms='+str(round((time.monotonic()-job['started'])*1000)))
            except Exception as error:
                from diagnostics import action_code,action_detail
                detail=action_detail(error)
                # All errors returned here are authored locally; raw Core data
                # and arbitrary exception strings never become browser content.
                if detail.startswith('No safe error'):detail='The public policy review could not finish. Keys and policies were unchanged. Check sanitised diagnostics and review again.'
                with self.owner.lock:job.update(state='error',error=detail,finished=time.monotonic())
                event('policy.review','Read-only review stopped · '+action_code(error)+' · '+detail)
            finally:
                with self.owner.lock:self.active=None
        threading.Thread(target=run,daemon=True,name='policy-review').start()
        return self.pending(key,job)
    def pending(self,key,job):
        return {'kind':'public_review_pending','id':key,'review_kind':job['kind'],'elapsed_seconds':round(time.monotonic()-job['started']),'message':'Checking local wallet policies and blockchain funding. This can take several minutes. Status and Wallet Server inventory remain available; no policy is being installed.'}
