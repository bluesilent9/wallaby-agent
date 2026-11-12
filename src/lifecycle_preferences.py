"""Separate persistent denials for extinction and direct-SSH restoration."""
from approval_store import digest
from build8_policy import descriptors


def intent(state,p):
    if p.get('kind')=='wallet_retire':purpose='extinction'
    elif p.get('kind')=='wallet_transfer' and p.get('direction')=='receive':
        from signer_restoration import requested,candidates
        row=state.get('local_retirements',{}).get(digest(sorted(descriptors(p['public_wallet']))))
        if not requested(p) and not candidates(state,p['public_wallet']) and (not row or row['state'] not in ('prepared','complete')):return None
        purpose='restoration'
    else:return None
    return purpose,digest({'purpose':purpose,'policy':sorted(descriptors(p['public_wallet']))})


def blocked(state,p):
    value=intent(state,p)
    return bool(value and value[1] in state.get('request_denials',{}))


def deny(store,key):
    with store.edit() as saved:
        row=saved['pending'].get(key)
        if not row or row['state']!='pending' or saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('An attempted, uncertain or active lifecycle operation cannot be relabelled as an unstarted denial.')
        p=row['proposal'];value=intent(saved,p)
        if not value:raise ValueError('This is not an extinction or direct-SSH restoration request.')
        purpose,ident=value
        saved.setdefault('request_denials',{})[ident]={'policy_id':ident,'purpose':purpose,'wallet_name':p['public_wallet']['wallet_name']}
        payload={'request_hash':key,'status':'denied','message':purpose.title()+' denied locally until its deny entry is removed.'}
        if p['kind']=='wallet_retire' and p.get('version')==3:payload.update(phase=p['phase'],manifest_hash=p['manifest_hash'])
        result={'kind':'wallet_retirement_result' if purpose=='extinction' else 'wallet_transfer_result','payload':payload};saved['outbox'][digest(result)]=result
        for k,item in list(saved['pending'].items()):
            if item['state']=='pending' and intent(saved,item['proposal'])==value:saved['pending'].pop(k);saved.get('sync_choices',{}).pop(k,None);saved.get('retirement_continuations',{}).pop(k,None)
    return {'message':purpose.title()+' requests for this exact public wallet policy are denied on this Agent across restarts. Remove the entry from the deny list to allow them again.'}


def enable(store,ident):
    with store.edit() as saved:
        if saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('Finish the active synchronisation first.')
        saved.setdefault('request_denials',{}).pop(ident,None)
    return {'message':'Lifecycle denial removed. Wallet Server may offer the request again; no wallet operation was authorised.'}


def cancel(store,key):
    with store.edit() as saved:
        row=saved['pending'].get(key)
        if not row or row['state']!='pending' or not intent(saved,row['proposal']) or saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('Only an unattempted inactive lifecycle request can be cancelled.')
        saved['pending'].pop(key);saved.get('sync_choices',{}).pop(key,None);saved.get('retirement_continuations',{}).pop(key,None)
    return {'message':'Request dismissed locally without a deny entry. It may return while Wallet Server still requests it. Existing wallet data was retained.'}
