"""A courier cannot downgrade a new multisig/transfer operation to legacy trust."""
from approval_store import digest

def require_current(store,p):
    if p.get('kind')=='wallet_sync_queue':
        for request in p['requests']:require_current(store,request)
        return
    saved=store.read();known=set(saved['pending'])|set(saved['completed'])
    known.update(digest(r) for r in saved.get('sync_snapshot_requests',[]))
    if digest(p) in known:return
    base=p.get('proposal',p);kind=base.get('kind');legacy=False
    if p.get('kind')=='wallet_setup_policy' and digest(base) in known:return
    if kind=='wallet_transfer':legacy=base.get('transfer_version')!=3
    elif kind=='wallet_setup':legacy=len(base['cosigners'])>1 and base.get('version')!=2
    elif kind=='wallet_policy_refresh':
        from wallet_setup_signing import restricted
        parsed=restricted(base['receive_descriptor']);legacy=bool(parsed and parsed['total']>1 and base.get('version')!=2)
    if legacy:raise ValueError('New multisig and wallet transfers require Wallet Server Build 2 encrypted peer protocols. A new request cannot silently fall back to IP-based trust. Previously delivered immutable work must be reconciled separately.')
