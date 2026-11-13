"""Independent producer agreement, never the Server's green status."""
from approval_store import digest
from peer_protocol import requirements

def manager(store):
    peers=getattr(store,'peers',None)
    if peers is None:raise ValueError('Open Peer Connections and connect the independently QR-paired Agents first. No secret operation was started.')
    return peers

def observe(store,p,scope,strict=False):
    base=p['proposal'] if p.get('kind')=='wallet_setup_policy' else p
    if base.get('version')!=2 and base['kind']!='wallet_setup':return {'required':False,'ready':True,'message':'Policy is independently verified against local wallet data.'}
    if base.get('version')==2:required=base['peer_transport']
    else:
        from peer_protocol import PROTOCOL,CIPHER
        required={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted({r['agent_key'] for r in base['cosigners']})}
    if base['kind']=='wallet_setup':
        requirements(required,[r['agent_key'] for r in base['cosigners']]);operation=digest(base)
        value=base if scope=='proposal' else {k:p[k] for k in ('proposal','contributions','receive_descriptor','change_descriptor')}
    else:
        from policy_refresh import transition
        requirements(required);value=transition(base);operation=digest({'kind':'wallet_policy_refresh','policy':value});scope='refresh'
    from direct_identity import own_key
    if required['required_agent_keys']==[own_key(store)]:return {'required':True,'ready':True,'message':'All producing roles belong to this Agent and were independently verified locally.'}
    try:manager(store).agreement(required,operation,scope,value)
    except ValueError as error:
        if strict:raise
        return {'required':True,'ready':False,'message':str(error)}
    return {'required':True,'ready':True,'message':'Every producing Agent agreed on this exact policy through its independently paired direct connection.'}

def pins(store,p):
    base=p.get('proposal',p);keys=sorted({r['agent_key'] for r in base['cosigners']})
    from direct_identity import require
    from wallet_preview import fingerprint
    for key in keys:
        require(store,key)
    return {fingerprint(key):fingerprint(key) for key in keys}
