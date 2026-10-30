"""A server cannot turn incomplete setup into ready without every authenticated proof."""
import re
from approval_store import digest
from setup_messages import verify
from wallet_ops import rpc
from build8_policy import descriptors

PENDING='Wallaby setup pending:'
READY='Wallaby setup ready:'

def mark(core,record,ready):
    expected=descriptors({'wallet_name':'approved','descriptors':[{'desc':record[x]} for x in ('receive_descriptor','change_descriptor')]})
    if descriptors(rpc(core,'listdescriptors',[False],record['monitor_wallet']))!=expected:raise ValueError('Local public monitor no longer matches the approved policy.')
    address=rpc(core,'deriveaddresses',[record['receive_descriptor'],[0,0]])[0]
    rpc(core,'setlabel',[address,(READY if ready else PENDING)+record['policy_hash']],record['monitor_wallet'])

def apply(core,store,p):
    if set(p)!={'kind','version','proposal_hash','policy_hash','acknowledgements'} or p['kind']!='wallet_setup_complete' or p['version']!=1 or any(not re.fullmatch('[0-9a-f]{64}',str(p[k])) for k in ('proposal_hash','policy_hash')) or not isinstance(p['acknowledgements'],list) or len(p['acknowledgements'])>64:raise ValueError('Invalid setup completion proof.')
    record=store.read().get('approved_wallets',{}).get(p['policy_hash'])
    if not record or digest(record['proposal'])!=p['proposal_hash']:raise ValueError('No matching locally approved wallet policy. Completion cannot grant local approval.')
    roles=record['proposal']['cosigners'];producers={r['agent_key'] for r in roles};approved=set();backups=set()
    for e in p['acknowledgements']:
        if not isinstance(e,dict) or e.get('public_key') not in producers:raise ValueError('Unknown completion signer.')
        m=verify(store,e,e['public_key'])
        if m.get('version')!=1 or m.get('session_id')!=record['proposal']['session_id'] or m.get('proposal_hash')!=p['proposal_hash'] or m.get('policy_hash')!=p['policy_hash']:raise ValueError('Acknowledgement belongs to another wallet setup.')
        if m.get('status')=='policy_approved':approved.add(e['public_key'])
        elif m.get('status')=='backup_verified':
            ident=m.get('cosigner_file');matching=[r for r in roles if r['storage']=='disc' and digest_role(r['id'])==ident and r['agent_key']==e['public_key']]
            if len(matching)!=1 or not re.fullmatch('[0-9a-f]{64}',str(m.get('image_sha256'))):raise ValueError('Invalid physical-cosigner completion proof.')
            backups.add(ident)
        else:raise ValueError('Only final policy and verified-backup acknowledgements establish readiness.')
    if approved!=producers or backups!={digest_role(r['id']) for r in roles if r['storage']=='disc'}:raise ValueError('At least one required policy approval or physical backup is still missing.')
    mark(core,record,True)
    with store.edit() as saved:saved['approved_wallets'][p['policy_hash']]['ready']=True
    return True

def digest_role(ident):
    import hashlib
    return hashlib.sha256(ident.encode()).hexdigest()
