"""Durable local extinction decisions; no transaction history or signing authority."""
from approval_store import digest
from wallet_ops import rpc
from build8_policy import descriptors
from wallet_labels import address_only


def prepare(store,p,names,core=None):
    ident=digest(sorted(descriptors(p['public_wallet'])))
    row={'policy_id':ident,'address_ids':sorted(digest({'address':r['address']}) for r in p['manifest']['addresses']),'wallet_names':sorted(names),'request_hash':digest(p),'operation_id':p['operation_id'],'state':'prepared'}
    if core is not None:
        from signer_restoration import capture
        row['wallet_bindings']=capture(core,names)
    with store.edit() as saved:saved.setdefault('local_retirements',{})[ident]=row
    return ident


def complete(store,ident):
    with store.edit() as saved:saved['local_retirements'][ident]['state']='complete'


def eligible(core,store,raw,verified_history=None):
    from wallet_labels import fixed_address
    addresses={fixed_address(r['desc']) for r in raw['descriptors']}
    if None in addresses:raise ValueError('Automatic Extinct history synchronisation accepts fixed historical addresses only.')
    wanted={digest({'address':a}) for a in addresses};records=store.read().get('local_retirements',{})
    blocked={a for row in records.values() if row['state']!='complete' for a in row['address_ids']}
    if wanted & blocked:raise ValueError('Extinct history deferred: local restoration or unfinished retirement must be resolved before importing these addresses.')
    from extinct_sync import ALIASES
    approved={a for row in records.values() if row['state']=='complete' for a in row['address_ids']}
    if not wanted<=approved:
        # A whole-history-upgraded legacy archive is itself local evidence for
        # entries extinguished before this Agent recorded individual decisions.
        # Server summaries/addresses never supply that evidence. A restoration
        # or unfinished local extinction overrides the old archive membership.
        loaded=rpc(core,'listwallets');directories={r['name'] for r in rpc(core,'listwalletdir')['wallets']}
        if directories-set(loaded)-set(ALIASES):raise ValueError('Load every local wallet before checking legacy Extinct ownership; no history was imported.')
        blocked={a for row in records.values() if row['state']!='complete' for a in row['address_ids']}
        from extinct_upgrade import snapshot,valid
        for wallet in ALIASES:
            if wallet not in loaded:continue
            state=snapshot(core,wallet)
            if valid(core,state):approved.update(digest({'address':a}) for a in state['addresses'] if digest({'address':a}) not in blocked)
    if verified_history is not None:
        # Only the authenticated direct packet's locally anchored complete coverage
        # can support first-time import. A Server offer or summary is insufficient.
        from extinct_history_sync import validate_coverage
        validate_coverage(core,verified_history,addresses,set(verified_history.get('txids',[])))
        approved.update(wanted)
    if not wanted<=approved:raise ValueError('Extinct history deferred: these exact addresses have not completed extinction locally. Approve the local extinction request first; no history was imported.')
    names={n for row in records.values() if row['state']=='complete' and set(row['address_ids'])&wanted for n in row['wallet_names']}
    directories={r['name'] for r in rpc(core,'listwalletdir')['wallets']}
    if names&directories:raise ValueError('Extinct history deferred: a previously retired local wallet exists again. Complete its local extinction before importing history.')
    for name in rpc(core,'listwallets'):
        policy=rpc(core,'listdescriptors',[False],name)
        if address_only(policy):continue
        for address in addresses:
            info=rpc(core,'getaddressinfo',[address],name)
            if info.get('ismine') or info.get('iswatchonly'):raise ValueError('Extinct history deferred: an active local wallet still owns these addresses. No history was imported.')
    return True


def restoration(store,raw):
    """A local fact, never a Wallet Server flag or permission to regenerate keys."""
    if address_only(raw):return None
    ident=digest(sorted(descriptors(raw)))
    state=store.read()
    from signer_restoration import candidates
    bound=candidates(state,raw)
    if bound:return bound[0][0]
    row=state.get('local_retirements',{}).get(ident)
    return ident if row and row['state'] in ('prepared','complete') else None


def restored_from_ssh(core,store,raw,wallet,*,validated_ssh=False):
    ident=restoration(store,raw)
    if not ident:return
    if not validated_ssh:raise ValueError('Restore this extinct wallet through a Build 64 direct SSH synchronisation; a Wallet Server request alone cannot restore it.')
    actual=rpc(core,'listdescriptors',[False],wallet);info=rpc(core,'getwalletinfo',[],wallet);tip=rpc(core,'getblockchaininfo')
    if descriptors(actual)!=descriptors(raw) or info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<tip['blocks']:raise ValueError('The SSH-restored wallet has not passed its local policy and current-chain checks.')
    with store.edit() as saved:saved['local_retirements'][ident]['state']='restored'
