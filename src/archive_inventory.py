"""Public verified disc membership; never carries wallet bytes or private keys."""
from approval_store import digest
from archive_format import identity,entry_kind

def member(recovery):
    generic=entry_kind(recovery)=='node_wallet'
    if generic:
        raw=recovery['public_wallet'];related=[recovery['public_policies']] if recovery.get('public_policies') else [];role='node-wallet';label=recovery.get('display_name',recovery['name'])
    else:
        from vendor.embit.descriptor.checksum import checksum
        role=recovery['local_cosigners'][0];contribution=next(e['message'] for e in recovery['contributions'] if e['message']['cosigner_id']==role);label=recovery.get('display_name',recovery['proposal']['name']);rows=[]
        for i,field in enumerate(('receive_key','change_key')):
            body='wpkh('+contribution[field]+')';rows.append({'desc':body+'#'+checksum(body),'timestamp':0,'active':True,'internal':bool(i),'range':[0,999]})
        raw={'wallet_name':label+' · '+role,'descriptors':rows};related=[{'wallet_name':label,'descriptors':[{'desc':recovery[k],'timestamp':0,'internal':bool(i)} for i,k in enumerate(('receive_descriptor','change_descriptor'))]}]
    for ext in recovery.get('policy_extensions',[]):related.append({'wallet_name':label,'descriptors':[{'desc':ext[k],'timestamp':ext['timestamp'],'internal':bool(i)} for i,k in enumerate(('receive_descriptor','change_descriptor'))]})
    return {'member_id':identity(recovery),'policy_hash':recovery['policy_hash'],'name':label,'role_id':role,'public_wallet':raw,'related_policies':related}

def evidence(job):
    rows=job.get('_members') or [(job['id'],job['wallets'],job['recovery'])]
    # Bundled metadata contains the same immutable entries if the burner retained
    # only the compiled container during a completion callback.
    recoveries=[r for _,_,r in rows]
    if len(recoveries)==1 and recoveries[0].get('version')==2:recoveries=[e['recovery'] for e in recoveries[0]['entries']]
    return [member(r) for r in recoveries]

def initial(store,job,image_sha256):
    if job.get('_inventory_notified'):return
    archive_id=job.get('archive_id')
    if not archive_id:return # Legacy/manual fixtures have no verified physical package.
    from setup_messages import sign
    store.queue('archive_inventory',sign(store,{'version':1,'event':'archive_verified','archive_id':archive_id,'image_sha256':image_sha256,'readback_verified':True,'disc_count':job['disc_count'],'replacements':[],'members':evidence(job)}));job['_inventory_notified']=True
