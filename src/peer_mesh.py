"""Independent producer agreement, never the Server's green status."""
from approval_store import digest
from peer_protocol import requirements

def manager(store):
    peers=getattr(store,'peers',None)
    if peers is None:raise ValueError('Open Peer Connections and connect the independently QR-paired Agents first. No secret operation was started.')
    return peers

def observe(store,p,scope,strict=False):
    base=p['proposal'] if p.get('kind')=='wallet_setup_policy' else p
    if base.get('version')!=2:return {'required':False,'ready':True,'message':'Existing saved protocol; original immutable request retained.'}
    required=base['peer_transport']
    if base['kind']=='wallet_setup':
        requirements(required,[r['agent_key'] for r in base['cosigners']]);operation=digest(base)
        value=base if scope=='proposal' else {k:p[k] for k in ('proposal','contributions','receive_descriptor','change_descriptor')}
    else:
        from policy_refresh import transition
        requirements(required);value=transition(base);operation=digest({'kind':'wallet_policy_refresh','policy':value});scope='refresh'
    try:manager(store).agreement(required,operation,scope,value)
    except ValueError as error:
        if strict:raise
        return {'required':True,'ready':False,'message':str(error)}
    return {'required':True,'ready':True,'message':'Every producing Agent agreed on this exact policy through its independently paired encrypted channel.'}

def pins(store,p):
    base=p.get('proposal',p);peers=manager(store);own=peers.identity['identity_key'];keys=base['peer_transport']['required_agent_keys']
    from wallet_preview import fingerprint
    for key in keys:
        if key!=own:peers.channel(key)
    return {fingerprint(key):fingerprint(key) for key in keys}
