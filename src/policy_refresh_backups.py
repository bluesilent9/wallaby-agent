"""A refreshed disc role is ready only after preserving and replacing its disc."""
import copy
from approval_store import digest
from archive_format import identity


def plan(ops,targets):
    archive_ops=getattr(ops,'archive_ops',None)
    ids={r['archive'] for r in targets if r.get('archive')}
    if not ids:return {}
    if archive_ops is None:raise ValueError('Loaded disc policy approval requires the local replacement-disc service.')
    sources={ops.archives.loaded[k]['archive_id'] for k in ids}
    answer={}
    for source in sources:
        catalog=ops.archives.catalogs.get(source)
        if not catalog:raise ValueError('Read the original disc catalogue before approving its replacement policy.')
        updated=sorted({identity(ops.archives.loaded[k]['recovery']) for k in ids if ops.archives.loaded[k]['archive_id']==source})
        if not set(updated)<=set(catalog):raise ValueError('The original disc catalogue does not contain its loaded signer.')
        answer[source]={'members':sorted(catalog),'updated_members':updated,'names':{k:r.get('display_name',r.get('name',r.get('proposal',{}).get('name','Account '+k[:12]))) for k,r in catalog.items()},'destroyed':False}
    return answer


def stage(ops,required):
    # Only affected signers are automatic. Additional archives remain optional
    # and can be selected freely, including wallets absent from the old disc.
    ids=[k for k,r in ops.archives.loaded.items() if r['archive_id'] in required and identity(r['recovery']) in required[r['archive_id']]['updated_members'] and digest({'refresh_archive':r['archive_id'],'identity':identity(r['recovery']),'recovery':r['recovery']}) not in ops.archive_ops.jobs]
    if ids:ops.archive_ops.queue_loaded(ids,True)


def hold(ops,key,facts,outcome,required):
    with ops.store.edit() as saved:
        row=saved['pending'][key]
        row.update(state='awaiting_backups',backup_facts=copy.deepcopy(facts),backup_outcome=copy.deepcopy(outcome),backup_discs=required)


def review(ops,key):
    row=ops.store.read()['pending'][key];facts=copy.deepcopy(row['backup_facts'])
    facts['backups_pending']=True
    facts['backup_discs']=[]
    for archive,v in row['backup_discs'].items():
        proof=getattr(ops.archive_ops,'policy_replacements',{}).get(archive,ops.archive_ops.verified_replacements.get(archive,{}))
        ready=True
        try:check_proof(row,v,proof)
        except ValueError:ready=False
        omitted=[v.get('names',{}).get(k,k) for k in v['members'] if k not in proof.get('members',[])] if ready else []
        facts['backup_discs'].append({'archive_id':archive,'members':len(v['members']),'destroyed':v['destroyed'],'replacement_verified':ready,'omitted':omitted,'token':digest(proof) if ready else None})
    return {'kind':'wallet_policy_refresh','id':key,'refresh':facts}


def destroyed(archive_ops,archive):
    """Called only after local destruction confirmation with verified coverage."""
    ready=[]
    with archive_ops.store.edit() as saved:
        for key,row in saved['pending'].items():
            if row.get('state')!='awaiting_backups' or archive not in row.get('backup_discs',{}):continue
            disc=row['backup_discs'][archive];proof=getattr(archive_ops,'policy_replacements',{}).get(archive,archive_ops.verified_replacements.get(archive,{}))
            check_proof(row,disc,proof)
            disc['destroyed']=True
            cancelled=any(r.get('proposal',{}).get('kind')=='builder_cancel' and key in r['proposal'].get('request_hashes',[]) for r in saved['pending'].values())
            if all(d['destroyed'] for d in row['backup_discs'].values()) and not cancelled:ready.append((key,copy.deepcopy(row)))
    from policy_refresh_group import result
    from types import SimpleNamespace
    for key,row in ready:
        result(SimpleNamespace(store=archive_ops.store),key,row['proposal'],row['backup_outcome']['status'],**row['backup_outcome']['extra'])


def check_proof(row,disc,proof):
    required=disc.get('updated_members',disc['members'])
    if proof.get('readback_verified') is not True or proof.get('old_policies_retained') is not True or not set(required)<=set(proof.get('members',[])):raise ValueError('Every affected disc signer needs a fully verified replacement before policy completion.')
    expected=digest([row['proposal']['receive_descriptor'],row['proposal']['change_descriptor']])
    if any(proof.get('member_policies',{}).get(member)!=expected for member in disc.get('updated_members',[])):raise ValueError('Verify a replacement carrying the approved new policy for every affected disc signer before destroying its old disc.')


def check_destruction(archive_ops,archive,proof):
    for row in archive_ops.store.read()['pending'].values():
        if row.get('state')=='awaiting_backups' and archive in row.get('backup_discs',{}):check_proof(row,row['backup_discs'][archive],proof)


def verified(archive_ops,recoveries,image_sha256):
    """Local refresh evidence can intentionally omit optional old archives.

    It is separate from the full-coverage proof sent to Dashboard for generic
    archive replacement, whose stronger preservation contract is unchanged.
    """
    from policy_refresh import validate_extensions
    if not hasattr(archive_ops,'policy_replacements'):archive_ops.policy_replacements={}
    available={identity(r):r for r in recoveries}
    proof={'image_sha256':image_sha256,'members':sorted(available),'member_policies':{k:digest(validate_extensions(r)) for k,r in available.items() if r.get('policy_extensions')},'old_policies_retained':True,'readback_verified':True}
    for row in archive_ops.store.read()['pending'].values():
        if row.get('state')!='awaiting_backups':continue
        for archive,disc in row['backup_discs'].items():
            try:check_proof(row,disc,proof)
            except ValueError:continue
            catalog=archive_ops.archives.catalogs.get(archive,{})
            if all(k in catalog and archive_ops.covers(available[k],catalog[k]) for k in disc['updated_members']):archive_ops.policy_replacements[archive]=copy.deepcopy(proof)


def confirm(ops,key,archive,token,confirmed):
    row=ops.store.read()['pending'][key]
    if row['state']!='awaiting_backups' or archive not in row['backup_discs'] or confirmed is not True:raise ValueError('Review and confirm physical destruction of this exact old disc locally.')
    proof=getattr(ops.archive_ops,'policy_replacements',{}).get(archive,ops.archive_ops.verified_replacements.get(archive,{}))
    check_proof(row,row['backup_discs'][archive],proof)
    if token!=digest(proof):raise ValueError('Replacement disc choices changed. Review the included and omitted wallets again.')
    destroyed(ops.archive_ops,archive)
    return {'message':'Physical destruction of the old copies recorded locally. Any listed omitted archives were not carried onto this replacement.'}


def guard(store,review):
    """Also refuse premature funding on this Agent, independently of Dashboard."""
    waiting=[r for r in store.read()['pending'].values() if r.get('state')=='awaiting_backups']
    for row in waiting:
        pair={row['proposal']['receive_descriptor'],row['proposal']['change_descriptor']}
        if any(pair & set(o.get('vault_policy',{}).get('descriptors',[])) for o in review['outputs']):raise ValueError('Finish replacement-disc burning, full verification and old-disc destruction confirmation before funding this refreshed vault.')
