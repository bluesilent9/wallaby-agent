"""Local preservation approval carried through recovery, never through deletion.

Consent stays inside the protected session. Server rediscovery, Core coverage and
an installer update cannot manufacture a local approval. Uncertain attempts are
not automatically replayed.
"""
import time
from approval_store import digest


def authorise(store,key,p):
    from retirement_phases import validate
    validate(p)
    if p['phase']!='preserve' or digest(p)!=key:raise ValueError('Only exact public-history preservation may continue after recovery.')
    with store.edit() as s:
        row=s['pending'].get(key)
        if not row or row['state']!='pending' or row['proposal']!=p or row.get('withdrawn') or row.get('cancel_requested') or s.get('retirement_cancel_pending',{}).get(key):raise ValueError('The extinction request changed or was withdrawn; no continuation authorised.')
        old=s.setdefault('retirement_continuations',{}).get(key)
        if old and old['state']!='authorised':raise ValueError('An earlier continuation needs local inspection; no automatic replay.')
        s['retirement_continuations'][key]={'state':'authorised','manifest_hash':p['manifest_hash'],'at':time.time()}


def finish(core,store):
    from wallet_retirement import Retirement
    from activity_log import event
    for key,consent in store.read().get('retirement_continuations',{}).items():
        if consent['state']!='authorised':continue
        with store.edit() as s:
            row=s['pending'].get(key)
            from lifecycle_preferences import blocked
            if not row or row['state']!='pending' or row.get('withdrawn') or row.get('cancel_requested') or s.get('retirement_cancel_pending',{}).get(key) or blocked(s,row['proposal']):
                s['retirement_continuations'].pop(key,None);continue
            p=row['proposal']
            if digest(p)!=key or p.get('phase')!='preserve' or p.get('manifest_hash')!=consent['manifest_hash']:raise ValueError('Authorised extinction identity changed; no continuation performed.')
            if digest({'local_retirement_history':key}) in s.get('history_jobs',{}):continue
            s['retirement_continuations'][key]['state']='finishing'
        try:
            owner=Retirement(core,store);review=owner.review(key)
            if review['retirement'].get('history_required'):raise ValueError('Recovered history has not passed extinction verification. Original wallets were retained.')
            owner.approve(key)
        except Exception:
            with store.edit() as s:
                if key in s.get('retirement_continuations',{}):s['retirement_continuations'][key]['state']='uncertain'
            event('extinction.continuation','Stopped for local inspection; no automatic replay or deletion')
            raise
        with store.edit() as s:s['retirement_continuations'].pop(key,None)
        event('extinction.continuation','Locally authorised preservation finished after recovery; separate deletion approval still required')
