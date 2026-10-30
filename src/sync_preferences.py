"""Local receive-policy exclusions. Never a signing exception or remote authority."""
from approval_store import digest
from build8_policy import descriptors

def policy_id(proposal):return digest(sorted(descriptors(proposal['public_wallet'])))

def change(store,key,disable):
    with store.edit() as s:
        if s.get('active_transfer') or s.get('sync_batch'):raise ValueError('Finish or end the active transfer before changing synchronisation requests.')
        p=s['pending'].get(key,{}).get('proposal')
        if not p or p['kind']!='wallet_transfer' or p['direction']!='receive':raise ValueError('Only incoming wallet synchronisation can be disabled. Signing authority is unchanged.')
        ident=policy_id(p)
        s.setdefault('sync_exclusions',{})[ident]={'wallet_name':p['public_wallet']['wallet_name'],'policy_id':ident}
        for item,row in list(s['pending'].items()):
            if row['proposal']['kind']=='wallet_transfer' and row['proposal']['direction']=='receive' and policy_id(row['proposal'])==ident:
                if row['state']!='pending':raise ValueError('Inspect the previously attempted wallet transfer before disabling it.')
                s['pending'].pop(item)
        s['sync_preferences_changed']=True
    return {'message':'Incoming synchronisation disabled for that exact public wallet policy on this Agent. Dashboard Build 11 needs the Build 10 preference protocol to suppress its missing-wallet notification. This local list is volatile until that protocol is implemented.'}

def enable(store,ident):
    with store.edit() as s:
        if s.get('active_transfer') or s.get('sync_batch'):raise ValueError('Finish the active transfer first.')
        s.setdefault('sync_exclusions',{}).pop(ident,None);s['sync_preferences_changed']=True
        for p in s.get('sync_snapshot_requests',[]):
            key=digest(p)
            if p['direction']=='receive' and policy_id(p)==ident and key not in s['completed']:s['pending'].setdefault(key,{'proposal':p,'received':__import__('time').time(),'state':'pending'})
    return {'message':'Synchronisation enabled for that wallet again.'}

def cancel(store,key):
    with store.edit() as s:
        row=s['pending'].get(key)
        if not row or row['proposal']['kind']!='wallet_transfer' or row['state']!='pending' or s.get('active_transfer') or s.get('sync_batch'):raise ValueError('Only an unattempted, inactive synchronization request can be cancelled.')
        s['pending'].pop(key);s.get('sync_choices',{}).pop(key,None)
    return {'message':'Request cancelled locally. A later Dashboard queue revision may offer it again. Disable synchronisation to suppress this incoming policy instead.'}

NAMESPACE='wallaby-sync-preferences-v1'

def exchange(store,p):
    """Only a future Dashboard explicitly requesting this kind gets a new outbox.

    Build 11 rejects unknown outbox kinds; never break its ordinary connection.
    A returned previous snapshot requires this Agent's own signature.
    """
    from setup_messages import sign,verify
    from pathlib import Path
    own=' '.join((getattr(store,'identity_root',store.root)/'preview_identity.pub').read_text().split()[:2])
    previous=p['previous'];record=None
    if previous is not None:
        record=verify(store,previous,own,namespace=NAMESPACE)
        if not isinstance(record,dict) or set(record)!={'version','purpose','agent_key','revision','policies'} or record['version']!=1 or record['purpose']!='wallet_sync_preferences' or record['agent_key']!=own or type(record['revision']) is not int or record['revision']<0 or not isinstance(record['policies'],list) or len(record['policies'])>128 or len(set(record['policies']))!=len(record['policies']) or any(not __import__('re').fullmatch('[0-9a-f]{64}',str(k)) for k in record['policies']):raise ValueError('Invalid signed synchronisation preferences.')
    with store.edit() as s:
        if record and 'sync_exclusions' not in s and not s.get('sync_preferences_changed'):
            s['sync_exclusions']={k:{'policy_id':k,'wallet_name':'Public policy '+k[:16]} for k in record['policies']}
            s['sync_preferences_revision']=record['revision']
        revision=max(s.get('sync_preferences_revision',0),record['revision'] if record else 0)+(1 if s.get('sync_preferences_changed') else 0)
        payload={'version':1,'purpose':'wallet_sync_preferences','agent_key':own,'revision':revision,'policies':sorted(s.get('sync_exclusions',{}))}
        s['sync_preferences_revision']=revision;s['sync_preferences_changed']=False
    envelope=sign(store,payload,namespace=NAMESPACE)
    store.queue('wallet_sync_preferences',{'version':1,'challenge':p['challenge'],'snapshot':envelope})
    # Remove pending receive rows only after the signed preferences have loaded.
    with store.edit() as s:
        for key,row in list(s['pending'].items()):
            q=row['proposal']
            if q['kind']=='wallet_transfer' and q['direction']=='receive' and row['state']=='pending' and policy_id(q) in s.get('sync_exclusions',{}) and key!=s.get('active_transfer') and not s.get('sync_batch'):s['pending'].pop(key)
