"""A courier cannot downgrade a new multisig/transfer operation to legacy trust."""
from approval_store import digest

def require_current(store,p):
    if p.get('kind')=='wallet_sync_queue':
        for request in p['requests']:require_current(store,request)
        return
    base=p.get('proposal',p);kind=base.get('kind');legacy=False
    if p.get('kind')=='wallet_setup_policy' and digest(base) in known:return
    if kind=='wallet_transfer':legacy=base.get('transfer_version')!=3
    elif kind=='wallet_setup':legacy=len(base['cosigners'])>1 and base.get('version')!=2
    elif kind=='wallet_policy_refresh':
        from wallet_setup_signing import restricted
        parsed=restricted(base['receive_descriptor']);legacy=bool(parsed and parsed['total']>1 and base.get('version')!=2)
    if legacy:raise ValueError('This operation requires the current direct Agent protocol. Obsolete IP-based wallet transfer or multisig requests are not accepted.')
