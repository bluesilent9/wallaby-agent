"""Public availability notices. Never executable wallet requests or approvals."""
import copy,json
from approval_store import digest
from peer_protocol import hexid
from public_policy import descriptors
from vault_policy import text
STATUSES={'ready','secure_pairing_required','peer_offline','permissions_pending','discovery_pending','review_paused','history_recovery','local_outcome','earlier_operation','peer_changed','preview_changed','preview_expired','invalid_pair','disabled'}

def validate(p):
    if not isinstance(p,dict) or set(p)!={'kind','version','revision','offers'} or p['kind']!='wallet_sync_offers' or type(p['version']) is not int or p['version']!=1 or type(p['revision']) is not int or p['revision']<0 or not isinstance(p['offers'],list) or len(p['offers'])>128:raise ValueError('Invalid public wallet-offer snapshot.')
    from agent_rpc import PRIVATE
    raw=json.dumps(p,allow_nan=False)
    if len(raw.encode())>2*1024*1024 or PRIVATE.search(raw):raise ValueError('Public offers exceed the safe size or contain private material.')
    ids=set()
    for offer in p['offers']:
        if not isinstance(offer,dict) or not {'id','transfer_id','direction','peer','public_wallet','status'}<=set(offer)<={'id','transfer_id','direction','peer','public_wallet','status','source_storage'} or not hexid(offer['id']) or not hexid(offer['transfer_id']) or offer['id'] in ids or offer['direction'] not in ('send','receive') or offer['status'] not in STATUSES:raise ValueError('Invalid public wallet offer.')
        if 'source_storage' in offer and offer['source_storage'] not in ('node','disc'):raise ValueError('Invalid advertised source storage.')
        peer=offer['peer']
        if not isinstance(peer,dict) or set(peer)!={'node_id','hostname'}:raise ValueError('Invalid advertised source node.')
        text(peer['node_id']);text(peer['hostname']);descriptors(offer['public_wallet']);ids.add(offer['id'])
    return p

def apply(store,p,session):
    validate(p)
    with store.edit() as s:
        new=session!=s.get('sync_offer_session')
        if new:
            retired=s.setdefault('sync_offer_retired_sessions',[])
            if session in retired:raise ValueError('Retired wallet-offer session.')
            if s.get('sync_offer_session'):retired.append(s['sync_offer_session'])
            del retired[:-128]
            s['sync_offer_session']=session;s.pop('sync_offer_revision',None);s.pop('sync_offer_snapshot_hash',None)
        previous=s.get('sync_offer_revision',-1);content=digest(p['offers']);changed=new or previous!=p['revision']
        if p['revision']<previous or p['revision']==previous and content!=s.get('sync_offer_snapshot_hash'):raise ValueError('Stale or conflicting public wallet-offer snapshot.')
        s['sync_offers']={o['id']:copy.deepcopy(o) for o in p['offers']};s['sync_offer_revision']=p['revision'];s['sync_offer_snapshot_hash']=content;s['sync_offers_received']=True
        # Withdrawal restricts an unstarted sender selection. Re-enabling may
        # restore visibility, but cannot silently restore a previously ticked
        # recipient. Frozen batches and attempted outcomes remain untouched.
        if not s.get('sync_batch'):
            from sync_table import sender_enabled
            for key,row in s['pending'].items():
                q=row['proposal']
                if q.get('kind')=='wallet_transfer' and q['direction']=='send' and row['state']=='pending' and key!=s.get('active_transfer') and not sender_enabled(s,q):
                    choice=s.get('sync_choices',{}).get(key)
                    if choice:choice['selected']=False

    if changed:
        from collections import Counter
        from activity_log import event
        counts=Counter(o['status'] for o in p['offers'])
        event('sync.offers','Discovery snapshot · offers='+str(len(p['offers']))+' · states='+(','.join(k+':'+str(v) for k,v in sorted(counts.items())) or 'none'))

def rows(store):
    from sync_preferences import policy_id
    saved=store.read();result=[]
    indexed={}
    for key,row in saved['pending'].items():
        p=row['proposal']
        if p.get('kind')=='wallet_transfer' and not row.get('withdrawn'):
            identity=(p.get('transfer_id'),p['direction'],p['peer']['node_id'],policy_id(p));indexed.setdefault(identity,[]).append(key)
    for offer in saved.get('sync_offers',{}).values():
        policy=policy_id(offer)
        linked=indexed.get((offer['transfer_id'],offer['direction'],offer['peer']['node_id'],policy),[])
        result.append({**copy.deepcopy(offer),'request_id':linked[0] if len(linked)==1 else None})
    return sorted(result,key=lambda r:(r['public_wallet']['wallet_name'].casefold(),r['peer']['hostname'].casefold(),r['id']))


def receive_blocker(saved,p):
    matches=[o for o in saved.get('sync_offers',{}).values() if o['direction']=='receive' and o['transfer_id']==p['transfer_id'] and o['peer']['node_id']==p['peer']['node_id']]
    states={o['status'] for o in matches}
    if not states or states=={'ready'}:return None
    if states & {'preview_changed','preview_expired','peer_changed'}:
        return 'Wallet Server must renew the signed receiving request. The source or its review changed; no wallet has been received. Your direct pairing and selection are retained.'
    return 'The source is advertised, but its wallet transfer is not ready ('+', '.join(sorted(states))+'). Wait for current discovery and direct connection checks; no wallet has been received.'
