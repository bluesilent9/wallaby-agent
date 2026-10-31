"""Dashboard Build 18 result validator snapshot for integration regression."""
def result(state,node,p):
    allowed={'request_hash','status','message','archive_verified','history_verified','zero_balance_verified','wallet_deleted','archive_wallet','address_count','deleted_wallets'}
    if not isinstance(p,dict) or not {'request_hash','status'}<=set(p) or set(p)-allowed or p['status'] not in ('complete','denied','cancelled','error'):raise ValueError('Invalid retirement result.')
    row=state['requests'].get(p['request_hash'])
    if not row or row['kind']!='wallet_retire' or row['node_id']!=node or not row.get('delivered') or row['proposal'].get('version')!=2:raise ValueError('Unsolicited or obsolete retirement result.')
    if row['state']!='pending':
        if row.get('result')==p:return
        raise ValueError('A retirement outcome cannot change.')
    if p['status']=='complete':
        if not all(p.get(k) is True for k in ('archive_verified','history_verified','zero_balance_verified','wallet_deleted')):raise ValueError('Retirement completion requires archival and deletion confirmation.')
        if not isinstance(p.get('archive_wallet'),str) or not p['archive_wallet'] or type(p.get('address_count')) is not int or p['address_count']<0:raise ValueError('Missing verified historical archive details.')
        deleted=p.get('deleted_wallets')
        if not isinstance(deleted,list) or not deleted or any(not isinstance(n,str) or not n or len(n)>256 for n in deleted) or set(deleted)!={w['wallet'] for w in row['proposal']['delete_wallets']} or p['archive_wallet'] in deleted:raise ValueError('The original wallet deletion was not confirmed.')
    row.update(state=p['status'],result=p,message=str(p.get('message',''))[:1000])
