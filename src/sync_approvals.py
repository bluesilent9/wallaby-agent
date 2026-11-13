"""Local receiving selections grouped by source; never Server transfer authority."""
from approval_store import digest
from sync_queue import rows

def groups(store):
    peers={};saved=store.read()
    for row in rows(store):
        if row['direction']!='receive' or not row['selected']:continue
        transport=saved['pending'][row['id']]['proposal'].get('transport',{})
        source=transport.get('sender_identity',row['peer_id'])
        peers.setdefault(source,[]).append(row)
    result=[]
    for peer,items in peers.items():
        items.sort(key=lambda r:(r['wallet_name'].casefold(),r['id']))
        binding=[{'id':r['id'],'watch_only':r['watch_only']} for r in items]
        result.append({'id':digest({'receive_from':peer,'wallets':binding}),'kind':'wallet_sync_receive','state':'pending','direction':'receive','peer_id':peer,'source':items[0]['sender'],'wallet_name':', '.join(r['wallet_name'] for r in items),'keys':[r['id'] for r in items],'wallets':binding})
    return sorted(result,key=lambda g:(g['source'].casefold(),g['id']))

def find(store,ident):
    found=next((g for g in groups(store) if g['id']==ident),None)
    if not found:raise ValueError('The selected wallets or watch-only choices changed. Review the current receiving request on Authorise.')
    return found

def binding(store,group):
    saved=store.read()
    return digest({'group':group,'previews':{key:saved.get('transfer_previews',{}).get(key) for key in group['keys']}})
