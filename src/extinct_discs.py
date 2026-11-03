"""Retired-disc review; keep current members until replacement readback succeeds."""
import copy,re,time
from approval_store import digest
from archive_format import identity
from archive_inventory import member
from build8_policy import descriptors
from setup_messages import verify
from wallet_preview import fingerprint
HEX=re.compile('[0-9a-f]{64}')

def validate(p):
    from agent_rpc import PRIVATE
    if PRIVATE.search(__import__('json').dumps(p)):raise ValueError('Private material is forbidden in extinction proposals.')
    fields={'kind','version','reason','nonce','operation_id','archive_id','label','archive_inventory','retired_wallet','retired_member_ids','manifest_hash','preservation','require_local_authorisation','require_replacement_if_live_members','require_verified_readback_before_destruction','request_id'}
    if not isinstance(p,dict) or set(p)!=fields or p['kind']!='destroy_disc' or type(p['version']) is not int or p['version']!=2 or p['reason']!='wallet_extinction' or any(p[k] is not True for k in ('require_local_authorisation','require_replacement_if_live_members','require_verified_readback_before_destruction')):raise ValueError('Invalid extinct-disc review task.')
    for k in ('nonce','operation_id','archive_id','manifest_hash','request_id'):
        if not isinstance(p[k],str) or not HEX.fullmatch(p[k]):raise ValueError('Invalid extinct-disc identity.')
    if digest({k:v for k,v in p.items() if k!='request_id'})!=p['request_id']:raise ValueError('Extinct-disc request changed.')
    if not isinstance(p['label'],str) or not 1<=len(p['label'])<=256 or any(ord(c)<32 for c in p['label']):raise ValueError('Invalid extinct-disc label.')
    descriptors(p['retired_wallet']);ids=p['retired_member_ids']
    if not isinstance(ids,list) or not 1<=len(ids)<=15 or len(ids)!=len(set(ids)) or any(not isinstance(i,str) or not HEX.fullmatch(i) for i in ids):raise ValueError('Invalid retired disc member list.')
    if not isinstance(p['archive_inventory'],dict) or not isinstance(p['preservation'],dict):raise ValueError('Signed disc and preservation evidence is required.')
    return p

def proof(ops,p):
    validate(p);own=ops.setup.own_identity()['public_key'];creator=p['archive_inventory'].get('public_key');inventory=verify(ops.store,p['archive_inventory'],creator)
    if inventory.get('archive_id')!=p['archive_id'] or inventory.get('event') not in ('archive_verified','replacement_verified','archive_observed'):raise ValueError('The signed inventory does not identify the proposed old disc.')
    observed=inventory.get('event')=='archive_observed'
    if observed:
        if inventory.get('payload_verified') is not True or inventory.get('payload_sha256')!=p['archive_id'] or inventory.get('readback_verified') is not False:raise ValueError('Old-disc observation is not authenticated package evidence.')
    elif inventory.get('readback_verified') is not True or not HEX.fullmatch(str(inventory.get('image_sha256'))):raise ValueError('Old-disc inventory lacks its original verified readback evidence.')
    catalog=ops.archives.catalogs.get(p['archive_id'])
    if not catalog:raise ValueError('Read and authenticate the old disc in Disc Operations before reviewing its complete membership.')
    actual={k:member(r) for k,r in catalog.items()};offered=inventory.get('members')
    if not isinstance(offered,list) or len(offered)!=len(actual) or {r.get('member_id') for r in offered}!=set(actual) or any(r!=actual[r['member_id']] for r in offered):raise ValueError('Dashboard disc membership differs from the independently read disc.')
    keys=descriptors(p['retired_wallet']);current=[];retired=[]
    for ident,r in actual.items():
        candidates=[r['public_wallet'],*r['related_policies']];matches=[descriptors(raw)==keys for raw in candidates]
        related_other=any(descriptors(raw)!=keys for raw in r['related_policies'])
        if ident in p['retired_member_ids']:
            if not any(matches):raise ValueError('A proposed retired disc key does not match the retired public policy.')
            # Shared signing keys also serving another policy are still current.
            (current if related_other else retired).append(ident)
        else:current.append(ident)
    if not set(p['retired_member_ids'])<=set(actual):raise ValueError('Retired disc member is absent from the actual disc.')
    archive=p['preservation'];envelope=archive.get('receipt',{});message=verify(ops.store,envelope,envelope.get('public_key'))
    required={'version','kind','request_hash','operation_id','manifest_hash','archive_wallet','address_count','wallet_deleted'}
    if set(message)!=required or message['version']!=1 or message['kind']!='wallet_retirement_preservation' or message['operation_id']!=p['operation_id'] or message['manifest_hash']!=p['manifest_hash'] or message['wallet_deleted'] is not False or type(message['address_count']) is not int or message['address_count']<1 or message['request_hash']!=archive.get('request_hash') or message['archive_wallet']!=archive.get('archive_wallet') or archive.get('manifest_hash')!=p['manifest_hash']:raise ValueError('Disc destruction lacks exact signed history-preservation evidence.')
    return {'current':sorted(current),'retired':sorted(retired),'members':actual,'fingerprint':fingerprint(envelope['public_key']),'archive_wallet':message['archive_wallet'],'manifest_hash':p['manifest_hash'],'creator_confirmation_required':creator!=own,'creator_fingerprint':fingerprint(creator)}

def review(ops,key):
    p=validate(ops.store.read()['pending'][key]['proposal']);facts=proof(ops,p);replacement=getattr(ops,'extinction_replacements',{}).get(key)
    return {'kind':'destroy_disc','id':key,'destruction':{'extinction':True,'archive_id':p['archive_id'],'label':p['label'],'current_members':[facts['members'][i]['name'] for i in facts['current']],'retired_members':[facts['members'][i]['name'] for i in facts['retired']],'creator_confirmation_required':facts['creator_confirmation_required'],'creator_fingerprint':facts['creator_fingerprint'],'preservation_fingerprint':facts['fingerprint'],'archive_wallet':facts['archive_wallet'],'manifest_hash':facts['manifest_hash'],'replacement_required':bool(facts['current']),'replacement_verified':bool(replacement),'replacement_image_sha256':(replacement or {}).get('image_sha256')}}

def stage(ops,key,confirmed,pin,creator_pin=None):
    ops.enforce();p=validate(ops.store.read()['pending'][key]['proposal']);facts=proof(ops,p)
    if facts['creator_confirmation_required'] and creator_pin!=facts['creator_fingerprint']:raise ValueError('Independently compare the original disc Agent fingerprint before handling a disc created elsewhere.')
    row=ops.store.read()['pending'].get(key,{})
    if row.get('state')!='pending' or row.get('withdrawn') or row.get('cancel_requested'):raise ValueError('This disc review was withdrawn or already attempted; no replacement was started.')
    if confirmed is not True or pin!=facts['fingerprint']:raise ValueError('Authorise replacement and independently compare the preserving Agent fingerprint first.')
    if not facts['current']:raise ValueError('This disc contains no remaining current signing accounts; no replacement is needed.')
    available={identity(r['recovery']):r for r in [*ops.archives.staged.values(),*ops.archives.loaded.values()] if r.get('archive_id')==p['archive_id']}
    plans=[]
    for ident in facts['current']:
        r=available.get(ident)
        if not r or not ops.covers(r['recovery'],ops.archives.catalogs[p['archive_id']][ident]):raise ValueError('Read every current account from the old disc before preparing its replacement.')
        binding=digest({'extinction_replacement':key,'member':ident,'recovery':r['recovery']})
        if binding in ops.jobs:raise ValueError('That account is already queued; finish or reconcile its existing burn job.')
        plans.append((binding,r))
    ops.extinction_plans=getattr(ops,'extinction_plans',{});ops.extinction_plans[key]={'proposal':copy.deepcopy(p),'current':facts['current'],'pin':pin}
    for binding,r in plans:
        ops.setup.burner.queue(binding,{binding:str(r['wallet'])},copy.deepcopy(r['recovery']));ops.jobs[binding]={'request':None,'folder':None,'phase':'queued','recovery':copy.deepcopy(r['recovery']),'extinction_task':key}
    from activity_log import event
    event('disc.retirement','Replacement staged · current_members='+str(len(facts['current']))+' · retired_only_members='+str(len(facts['retired'])))
    from archive_requests import result
    result(ops.store,p,'queued',message='Replacement staged locally with current accounts only; destruction remains blocked until verified readback.')
    return {'message':'Current accounts are queued in Disc Operations. Burn and verify the new disc, then return to this Authorisation to confirm physical destruction. Retired-only accounts are omitted.','burn_authorised':True}

def completed(ops,container_members,image_sha256):
    for key,plan in getattr(ops,'extinction_plans',{}).items():
        catalog=ops.archives.catalogs.get(plan['proposal']['archive_id'],{})
        if not all(i in container_members and i in catalog and ops.covers(container_members[i],catalog[i]) for i in plan['current']):continue
        ops.extinction_replacements=getattr(ops,'extinction_replacements',{});ops.extinction_replacements[key]={'image_sha256':image_sha256,'members':sorted(container_members),'readback_verified':True}

def destroyed(ops,key,confirmed,pin,creator_pin=None):
    ops.enforce();p=validate(ops.store.read()['pending'][key]['proposal']);facts=proof(ops,p)
    if facts['creator_confirmation_required'] and creator_pin!=facts['creator_fingerprint']:raise ValueError('Independently compare the original disc Agent fingerprint before handling a disc created elsewhere.')
    row=ops.store.read()['pending'].get(key,{})
    if row.get('state')!='pending' or row.get('withdrawn') or row.get('cancel_requested'):raise ValueError('This disc review is no longer active; destruction cannot be recorded from it.')
    if confirmed is not True or pin!=facts['fingerprint']:raise ValueError('Independently compare the preserving Agent fingerprint and confirm physical destruction locally.')
    extra={};replacement=getattr(ops,'extinction_replacements',{}).get(key)
    if facts['current']:
        if not replacement or replacement.get('readback_verified') is not True or not set(facts['current'])<=set(replacement['members']):raise ValueError('Every current disc account must have a locally read-back-verified replacement before destruction can be recorded.')
        extra={'replacement_readback_verified':True,'replacement_image_sha256':replacement['image_sha256']}
    from activity_log import event
    event('disc.retirement','Physical destruction confirmed locally · replacement_required='+str(bool(facts['current'])).lower())
    from archive_requests import result
    result(ops.store,p,'complete',destruction_confirmed_locally=True,archive_id=p['archive_id'],**extra)
    with ops.store.edit() as s:s['pending'].pop(key,None);s['completed'][key]={'kind':'destroy_disc','at':time.time()}
    return {'message':'Physical destruction recorded locally. Extinct history stays in its verified archive; any current disc accounts were retained on a verified replacement.'}
