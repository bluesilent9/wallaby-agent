"""Dashboard owns task lifetime; local approval, denials and physical evidence stay here."""
import copy,re
from approval_store import digest
from build8_policy import descriptors
from vault_policy import text
HEX=re.compile('[0-9a-f]{64}')

def validate_task(p):
    if not isinstance(p,dict) or p.get('version')!=1 or type(p.get('version')) is not int:raise ValueError('Invalid archive task.')
    if p.get('kind')=='archive_wallet':
        if set(p)!={'kind','version','nonce','request_id','wallet','public_wallet','related_policies','require_local_authorisation'} or p['require_local_authorisation'] is not True:raise ValueError('Invalid archive-wallet fields.')
        text(p['wallet'],256);descriptors(p['public_wallet'])
        if p['public_wallet']['wallet_name']!=p['wallet'] or not isinstance(p['related_policies'],list) or len(p['related_policies'])>32:raise ValueError('Invalid archive wallet identity or related-policy list.')
        for raw in p['related_policies']:descriptors(raw)
    elif p.get('kind')=='destroy_disc':
        required={'kind','version','nonce','request_id','archive_id','label','replacement_image_sha256'}
        if not required<=set(p)<=required|{'replacement_receipt'}:raise ValueError('Invalid disc-destruction fields.')
        text(p['label'],256)
        if any(not HEX.fullmatch(str(p[k])) for k in ('archive_id','replacement_image_sha256')):raise ValueError('Invalid disc identity.')
        if 'replacement_receipt' in p and not isinstance(p['replacement_receipt'],dict):raise ValueError('Invalid replacement receipt.')
    else:raise ValueError('Unsupported archive task.')
    if any(not HEX.fullmatch(str(p[k])) for k in ('nonce','request_id')) or digest({k:v for k,v in p.items() if k!='request_id'})!=p['request_id']:raise ValueError('Archive task identifier does not bind its exact contents.')
    return p

def validate_queue(p):
    if not isinstance(p,dict) or set(p)!={'kind','version','queue_id','revision','requests'} or p['kind']!='wallet_archive_queue' or type(p['version']) is not int or p['version']!=1 or not HEX.fullmatch(str(p['queue_id'])) or type(p['revision']) is not int or not 0<=p['revision']<2**63 or not isinstance(p['requests'],list) or len(p['requests'])>128:raise ValueError('Invalid full archive-queue snapshot.')
    seen=set()
    for row in p['requests']:
        validate_task(row)
        if row['request_id'] in seen:raise ValueError('Duplicate archive task.')
        seen.add(row['request_id'])
    return p

def permission_id(p):return digest({'purpose':'archive','public_descriptors':sorted(descriptors(p['public_wallet']))})

def snapshot(store,p):
    validate_queue(p)
    with store.edit() as s:
        previous=s.get('archive_queue')
        if previous and previous['queue_id']==p['queue_id']:
            if p['revision']<previous['revision']:raise ValueError('Archive snapshot revision went backwards.')
            if p['revision']==previous['revision'] and digest(p)!=previous['hash']:raise ValueError('Archive snapshot changed without a revision.')
        active={digest(row):row for row in p['requests']}
        for key,row in list(s['pending'].items()):
            if row['proposal']['kind'] in ('archive_wallet','destroy_disc') and key not in active:
                if row['state']=='pending':s['pending'].pop(key)
                else:row['withdrawn']=True # never delete authorised/in-flight RAM work
        s['archive_queue']={'queue_id':p['queue_id'],'revision':p['revision'],'hash':digest(p),'requests':copy.deepcopy(p['requests'])}
        for key,row in active.items():
            if key in s['completed'] or key in s['pending']:continue
            if row['kind']=='archive_wallet' and permission_id(row) in s.get('archive_exclusions',{}):continue
            if len(s['pending'])>=128:raise ValueError('Local authorisation queue is full.')
            s['pending'][key]={'proposal':row,'state':'pending','received':__import__('time').time()}

def result(store,p,status,**extra):
    from setup_messages import sign
    queue=store.read().get('archive_queue',{})
    message={'version':1,'queue_id':queue.get('queue_id'),'request_id':p['request_id'],'status':status,**extra}
    message['signed_receipt']=sign(store,copy.deepcopy(message));store.queue('archive_queue_result',message);return message

def delete(store,key,disable=False):
    with store.edit() as s:
        row=s['pending'][key];p=row['proposal']
        if p['kind'] not in ('archive_wallet','destroy_disc') or row['state']!='pending':raise ValueError('Only an unattempted archive task can be removed locally.')
        if disable:
            if p['kind']!='archive_wallet':raise ValueError('Physical destruction tasks cannot be silently disabled.')
            ident=permission_id(p);s.setdefault('archive_exclusions',{})[ident]={'policy_id':ident,'wallet_name':p['wallet'],'purpose':'archive'}
        s['pending'].pop(key)
    if disable:result(store,p,'disabled')
    return {'message':'Archiving disabled locally until you enable it in the denial list.' if disable else 'Removed locally. An active Dashboard request may be offered again.'}
