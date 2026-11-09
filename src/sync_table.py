"""One public view of local wallets, missing-wallet offers and local denials.

No Core calls or remote labels can grant transfer authority. Selectable routes
come only from immutable requests bound to a live locally paired direct channel.
"""
import copy
from sync_preferences import policy_id

def observe(store,method,wallet,value):
    if method not in ('listwallets','listdescriptors','getwalletinfo'):return
    with store.edit() as s:
        rows=s.setdefault('sync_local_wallets',{})
        if method=='listwallets' and isinstance(value,list):
            s['sync_local_wallets']={name:rows.get(name,{'wallet_name':name}) for name in value if isinstance(name,str)}
        elif wallet in rows and isinstance(value,dict):
            if method=='getwalletinfo':
                rows[wallet]['private_keys_enabled']=value.get('private_keys_enabled')
                if isinstance(value.get('wallaby_managed'),dict):rows[wallet]['managed']=value['wallaby_managed']
            elif value.get('descriptors'):
                try:ident=policy_id({'public_wallet':{'wallet_name':wallet,'descriptors':value['descriptors']}})
                except ValueError:return
                rows[wallet]['policy_id']=ident;rows[wallet]['multisig']=multisig({'descriptors':value['descriptors']})

def multisig(raw):
    from vendor.embit.descriptor import Descriptor
    for row in raw.get('descriptors',[]):
        try:
            if len(Descriptor.from_string(row['desc'].split('#')[0]).keys)>1:return True
        except (ValueError,TypeError,AttributeError):pass
    return False

def direct_ready(store,p):
    if p.get('transfer_version')!=3:return False
    try:
        from peer_mesh import manager
        peers=manager(store);peers.direct.require(peers.binding(p))
        return True
    except (ValueError,AttributeError):return False

def sender_enabled(saved,p):
    """A connected path never substitutes for current receiver permission.

    The Server's authenticated full offer snapshot can restrict a stale frozen
    request, but cannot grant signing/import authority. Re-enabling returns the
    same request after the receiver's current signed preferences are observed.
    """
    if p.get('direction')!='send':return True
    if not saved.get('sync_offers_received'):return False
    ident=policy_id(p)
    return any(o['direction']=='send' and o['transfer_id']==p['transfer_id']
        and o['peer']['node_id']==p['peer']['node_id'] and policy_id(o)==ident
        and o['status'] not in ('disabled','permissions_pending')
        for o in saved.get('sync_offers',{}).values())

def state(store,requests):
    saved=store.read();groups={};denials=saved.get('sync_exclusions',{})
    def group(ident,name):
        return groups.setdefault(ident,{'policy_id':ident,'wallet_name':name,'local_wallets':[],
            'send':[],'receive':[],'offers':[],'signers':[],'denied':ident in denials,'deny_id':None})
    for name,local in saved.get('sync_local_wallets',{}).items():
        row=group(local.get('policy_id','local:'+name),name);row['local_wallets'].append(name)
        managed=local.get('managed',{});row['logical_name']=managed.get('logical_name') or row.get('logical_name');row['wallet_name']=row['logical_name'] or min(row['local_wallets'],key=str.casefold)
        row['multisig']=row.get('multisig',False) or local.get('multisig',False)
        if local.get('private_keys_enabled') is True:row['signers'].append({'account':name,'label':managed.get('role_name') or name})
        row['local_private']=row.get('local_private',False) or local.get('private_keys_enabled') is True
    for offer in saved.get('sync_offers',{}).values():
        if offer['direction']=='send' and offer['status'] in ('disabled','permissions_pending'):continue
        ident=policy_id(offer);row=group(ident,offer['public_wallet']['wallet_name'])
        row['multisig']=row.get('multisig',False) or multisig(offer['public_wallet'])
        row['offers'].append({'direction':offer['direction'],'status':offer['status']})
        if offer['direction']=='receive':row['deny_id']=offer['id']
    for r in requests:
        p=saved['pending'][r['id']]['proposal'];enabled=sender_enabled(saved,p)
        if r['state']=='pending' and not enabled:continue
        ident=policy_id(p);row=group(ident,r['wallet_name'])
        if r['direction']=='receive':row['deny_id']=r['id']
        row['multisig']=row.get('multisig',False) or multisig(p['public_wallet'])
        preview=saved.get('transfer_previews',{}).get(r['id'],{}).get('preview',{})
        option=copy.deepcopy(r);option['signer_label']=preview.get('public_wallet',{}).get('wallet_name');option['direct_ready']=enabled and direct_ready(store,p)
        row[r['direction']].append(option)
    for ident,d in denials.items():group(ident,d['wallet_name'])
    for row in groups.values():
        row['signers'].sort(key=lambda r:(r['label'].casefold(),r['account'].casefold()))
        for direction in ('send','receive'):
            row[direction].sort(key=lambda r:((r['receiver'] if direction=='send' else r['sender']).casefold(),r['id']))
        row['pending']=bool(any(r['state']=='pending' for r in row['send']) or not row['denied'] and any(r['state']=='pending' for r in row['receive']) or any(o['direction']=='send' or not row['denied'] for o in row['offers']))
    # A synchronisation table is not a general local-wallet inventory. Incoming
    # discoveries and persistent local denials remain visible without a sender;
    # outgoing work needs a currently usable recipient. Retain attempted outcomes
    # for inspection rather than hiding work that may already have occurred.
    visible=[]
    for row in groups.values():
        row['send']=[r for r in row['send'] if r['direct_ready'] or r['state']!='pending']
        row['offers']=[o for o in row['offers'] if o['direction']=='receive']
        row['pending']=bool(any(r['state']=='pending' for r in row['send']) or not row['denied'] and (any(r['state']=='pending' for r in row['receive']) or row['offers']))
        if row['denied'] or row['receive'] or row['offers'] or row['send']:visible.append(row)
    rows=sorted(visible,key=lambda r:(r['wallet_name'].casefold(),r['policy_id']))
    return {'wallets':rows,'pending_count':sum(row['pending'] for row in rows)}

def choose(store,key,selected,watch_only):
    """Atomically switch peer for one wallet/direction; never resume stale choices."""
    with store.edit() as s:
        row=s['pending'].get(key)
        if not row or row['proposal'].get('kind')!='wallet_transfer':raise ValueError('Refresh the wallet table; this request changed.')
        p=row['proposal']
        if not sender_enabled(s,p):raise ValueError('The receiver has not enabled this wallet. Wait for its current permission update; no transfer was selected.')
        if not direct_ready(store,p):raise ValueError('No Agent Detected. Reconnect the directly paired Agent before selecting this transfer.')
        if type(selected) is not bool or type(watch_only) is not bool:raise ValueError('Invalid wallet selection.')
        if s.get('active_transfer') or s.get('sync_batch') or row.get('withdrawn') or row['state']!='pending':raise ValueError('Finish the current operation before changing routes.')
        ident=policy_id(p)
        for other,record in s['pending'].items():
            q=record['proposal']
            if other!=key and q.get('kind')=='wallet_transfer' and q['direction']==p['direction'] and policy_id(q)==ident:
                choice=s.setdefault('sync_choices',{}).get(other,{})
                s['sync_choices'][other]={**choice,'selected':False}
        s.setdefault('sync_choices',{})[key]={'selected':selected,'watch_only':watch_only or not p['source_has_private_keys']}
    return {'message':'Wallet route selected. Review and local transfer approval are still required.'}
