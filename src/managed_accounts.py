"""Public account roles; a signer is not an independently synchronised asset wallet."""
import re
from approval_store import digest
from diagnostics import LocalActionFailure
from build8_policy import descriptors
from vendor.embit.descriptor.checksum import checksum

KEY=re.compile(r'Wallaby key [0-9a-f]{12} [0-9a-f]{8}(?:_watch)?')
POLICY=re.compile(r'Wallaby policy [0-9a-f]{20}(?:_watch)?')
REASON='Managed signing accounts are not ordinary wallet synchronisation targets. Keep each signer on its assigned Agent or disc; share the complete public policy instead. No wallet file was sent or received.'

def raw_keys(values):
    return descriptors({'wallet_name':'public account','descriptors':[{'desc':body+'#'+checksum(body)} for body in values]})

def classify(state,name,raw):
    actual=descriptors(raw)
    if not isinstance(state,dict):state={}
    for record in state.get('approved_wallets',{}).values():
        if not isinstance(record,dict) or not {'proposal','policy_hash','receive_descriptor','change_descriptor','contributions'}<=set(record):continue
        proposal=record['proposal'];base={'version':1,'setup_id':digest(proposal),'policy_hash':record['policy_hash'],'logical_name':proposal['name'],'threshold':proposal['threshold'],'total':len(proposal['cosigners'])}
        if actual==raw_keys([record['receive_descriptor'].split('#')[0],record['change_descriptor'].split('#')[0]]):
            return {**base,'kind':'policy','display_name':proposal['name'],'ready':record.get('ready',False)}
        for envelope in record['contributions']:
            contribution=envelope['message'];expected=raw_keys(['wpkh('+contribution[k]+')' for k in ('receive_key','change_key')])
            if expected<=actual:
                role=next(r for r in proposal['cosigners'] if r['id']==contribution['cosigner_id'])
                return {**base,'kind':'signer','role_id':role['id'],'role_name':role['name'],'display_name':proposal['name']+' · '+role['name']+' (signer)'}
    # Conservative reserved-name recognition also protects legacy accounts after
    # their RAM setup records have gone. It never authorises deletion or signing.
    if KEY.fullmatch(name):return {'version':1,'kind':'signer','display_name':'Managed signing account','legacy':True}
    if POLICY.fullmatch(name):return {'version':1,'kind':'policy','display_name':'Managed public policy','legacy':True}
    return None

def blocked(state,p):
    if p.get('kind')!='wallet_transfer':return False
    raw=p['public_wallet'];info=classify(state,raw['wallet_name'],raw)
    return bool(info and info['kind']=='signer')

def guard(core,p,store=None,actual_name=None):
    from wallet_ops import rpc
    state=store.read() if store is not None else getattr(core,'managed_store',None).read() if getattr(core,'managed_store',None) is not None else {}
    if blocked(state,p) or actual_name is not None and KEY.fullmatch(actual_name):raise LocalActionFailure('managed_signer_transfer',REASON)
    # Match public keys against persisted Core policies too. A Dashboard rename
    # cannot bypass the check, including after a protected RAM session restarts.
    wanted=descriptors(p['public_wallet'])
    if not isinstance(getattr(core,'config',None),dict):return
    from wallet_setup_signing import restricted
    for monitor in rpc(core,'listwallets'):
        if not POLICY.fullmatch(monitor):continue
        for row in rpc(core,'listdescriptors',[False],monitor)['descriptors']:
            parsed=restricted(row['desc'])
            if not parsed:continue
            if any(raw_keys(['wpkh('+str(key)+')'])<=wanted for key in parsed['keys']):raise LocalActionFailure('managed_signer_transfer',REASON)
