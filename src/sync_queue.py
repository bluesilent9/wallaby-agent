"""Dashboard-owned request list; selection and transfer authority are local only."""
import socket,time
from approval_store import digest,MAX_ITEMS


def apply_snapshot(store,revision,requests):
    from vault_policy import validate_proposal
    if type(revision) is not int or revision<0:raise ValueError('Invalid synchronisation revision.')
    if not isinstance(requests,list) or len(requests)>MAX_ITEMS:raise ValueError('Too many synchronisation requests.')
    rows={}
    ids=set()
    for request in requests:
        p=validate_proposal(request)
        if p['kind']!='wallet_transfer' or p['transfer_id'] in ids:raise ValueError('Duplicate or invalid wallet request.')
        ids.add(p['transfer_id']);rows[digest(p)]=p
    with store.edit() as s:
        previous=s.get('sync_revision',-1)
        if revision<previous:raise ValueError('Stale synchronisation list.')
        content=digest(requests)
        if revision==previous:
            if s.get('sync_snapshot_hash')!=content:raise ValueError('A revision cannot change contents.')
            return
        for key,row in list(s['pending'].items()):
            if row['proposal']['kind']=='wallet_transfer' and key not in rows:
                if key==s.get('active_transfer') or row['state']!='pending':
                    row['withdrawn']=True # Audit an operation already attempted; never erase its outcome.
                else:s['pending'].pop(key);s.get('transfer_previews',{}).pop(key,None);s.get('sync_choices',{}).pop(key,None)
        for key,p in rows.items():
            if key not in s['pending'] and key not in s['completed']:
                if len(s['pending'])>=MAX_ITEMS:raise ValueError('Authorisation queue is full.')
                s['pending'][key]={'proposal':p,'received':time.time(),'state':'pending'}
        s['sync_revision']=revision;s['sync_snapshot_hash']=content


def choose(store,key,selected,watch_only):
    if type(selected) is not bool or type(watch_only) is not bool:raise ValueError('Invalid wallet selection.')
    with store.edit() as s:
        row=s['pending'].get(key)
        if not row or row['proposal']['kind']!='wallet_transfer' or row.get('withdrawn'):raise ValueError('This wallet request was withdrawn.')
        if s.get('active_transfer') or s.get('sync_batch'):raise ValueError('Selections are fixed while an authorised batch is running.')
        if row['state']!='pending':raise ValueError('Inspect the previous operation before retrying this wallet.')
        if not row['proposal']['source_has_private_keys']:watch_only=True
        s.setdefault('sync_choices',{})[key]={'selected':selected,'watch_only':watch_only}


def rows(store):
    s=store.read();result=[]
    for key,row in s['pending'].items():
        p=row['proposal']
        if p['kind']!='wallet_transfer' or row.get('withdrawn'):continue
        choice=s.get('sync_choices',{}).get(key,{'selected':False,'watch_only':not p['source_has_private_keys']})
        preview=s.get('transfer_previews',{}).get(key,{}).get('preview',{})
        own=socket.gethostname();name=preview.get('public_wallet',{}).get('wallet_name') if p['direction']=='send' else p['public_wallet']['wallet_name']
        result.append({'id':key,'peer_id':p['peer']['node_id'],'direction':p['direction'],'sender':own if p['direction']=='send' else p['peer']['hostname'],'receiver':own if p['direction']=='receive' else p['peer']['hostname'],
                       'sender_ipv6':p.get('node_ipv6') if p['direction']=='send' else p['peer']['ipv6'],'receiver_ipv6':p.get('node_ipv6') if p['direction']=='receive' else p['peer']['ipv6'],
                       'wallet_name':name or 'Verify with local node','name_verified':p['direction']=='send' and bool(name),'state':row['state'],'watch_only_locked':not p['source_has_private_keys'],**choice})
    return sorted(result,key=lambda r:(r['wallet_name'].casefold(),r['sender'],r['receiver'],r['id']))


def selected(store,direction):
    return [r['id'] for r in rows(store) if r['selected'] and r['direction']==direction and r['state']=='pending']


def freeze(store,keys,direction):
    if not keys or len(keys)!=len(set(keys)):raise ValueError('Select at least one wallet.')
    with store.edit() as s:
        if s.get('setup_active'):raise ValueError('Finish the current wallet setup and physical backups first.')
        if s.get('active_transfer') or s.get('sync_batch') or s.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'):raise ValueError('Another wallet operation or history recovery is active.')
        options={}
        for key in keys:
            row=s['pending'].get(key);choice=s.get('sync_choices',{}).get(key,{})
            if not row or row.get('withdrawn') or row['state']!='pending' or row['proposal']['direction']!=direction or not choice.get('selected'):raise ValueError('The selected wallet list changed. Review it again.')
            options[key]={'watch_only':choice.get('watch_only',False) or not row['proposal']['source_has_private_keys']}
        s['sync_batch']={'keys':keys,'options':options,'direction':direction,'at':time.time()}
    return options


def release(store):
    with store.edit() as s:
        s.pop('active_transfer',None);s.pop('sync_batch',None)
        for key,row in list(s['pending'].items()):
            if row.get('withdrawn') and row['state']=='pending':s['pending'].pop(key)
