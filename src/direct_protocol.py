"""Noise-only direct SSH negotiation. No private credentials enter these records."""
import ipaddress,re,time
from peer_protocol import canonical,digest,hexid
KINDS={'client-key','offer','accept','ready','select','selected','retire','retired','disconnect'}
FIELDS={'type','negotiation_id','epoch_id','endpoints','created_utc','expires_utc','body'}
def address(value,loopback=False):
    if not isinstance(value,str) or '%' in value:raise ValueError('A literal peer address is required.')
    ip=ipaddress.ip_address(value)
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved or ip.is_loopback and not loopback or str(ip)=='255.255.255.255':raise ValueError('Unsafe direct peer address.')
    return str(ip)
def public_key(value):
    import base64,struct
    if not isinstance(value,str) or len(value)>128 or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}',value):raise ValueError('An Ed25519 public key is required.')
    raw=base64.b64decode(value.split()[1],validate=True)
    if len(raw)!=51 or raw[:19]!=struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',32):raise ValueError('Invalid Ed25519 public key.')
    return value

def validate(record,own,peer,loopback=False):
    if not isinstance(record,dict) or set(record)!=FIELDS or record['type'] not in {'peer.direct.'+k for k in KINDS}:raise ValueError('Invalid direct negotiation record.')
    if not hexid(record['negotiation_id']) or not hexid(record['epoch_id']):raise ValueError('Invalid direct epoch.')
    endpoints=sorted([{'endpoint_id':p['endpoint_id'],'role':p['role']} for p in (own,peer)],key=lambda p:p['endpoint_id'])
    if record['endpoints']!=endpoints or type(record['created_utc']) is not int or type(record['expires_utc']) is not int or not time.time()-120<=record['created_utc']<=time.time()+15 or not time.time()<record['expires_utc']<=record['created_utc']+120:raise ValueError('Direct negotiation identity, role or expiry changed.')
    b=record['body'];kind=record['type'].split('.')[-1]
    if not isinstance(b,dict):raise ValueError('Invalid direct negotiation body.')
    if kind=='client-key':
        if set(b)!={'client_public_key'}:raise ValueError('Invalid client key offer.')
        public_key(b['client_public_key'])
    elif kind=='offer':
        if set(b)!={'server_endpoint','client_endpoint','candidates','host_public_key','login_id','client_public_key','credential_max_age_seconds'} or {b['server_endpoint'],b['client_endpoint']}!={own['endpoint_id'],peer['endpoint_id']} or b['credential_max_age_seconds']!=86400 or type(b['credential_max_age_seconds']) is not int or not isinstance(b['login_id'],str) or not re.fullmatch('[a-z0-9]{16,48}',b['login_id']):raise ValueError('Invalid direct SSH offer.')
        if own['role']!=peer['role'] and b['server_endpoint']!=next(p['endpoint_id'] for p in (own,peer) if p['role']=='agent'):raise ValueError('An Agent must serve an Agent–Mobile connection.')
        public_key(b['host_public_key']);public_key(b['client_public_key'])
        if not isinstance(b['candidates'],list) or not 1<=len(b['candidates'])<=8:raise ValueError('Invalid direct candidates.')
        ports=set()
        for c in b['candidates']:
            if not isinstance(c,dict) or set(c)!={'ip','port'} or type(c['port']) is not int or not 1<=c['port']<=65535:raise ValueError('Invalid direct service candidate.')
            address(c['ip'],loopback);ports.add(c['port'])
        if len(ports)!=1:raise ValueError('Candidates must identify one application service port.')
    elif kind in ('accept','select','selected'):
        if set(b)!={'offer_hash'} or not hexid(b['offer_hash']):raise ValueError('Invalid direct offer acknowledgement.')
    elif kind=='ready':
        if set(b)!={'offer_hash','ssh_session_binding'} or not all(hexid(v) for v in b.values()):raise ValueError('Invalid direct binding.')
    elif kind in ('retire','retired'):
        if set(b)!={'old_epoch_id','new_epoch_id','reason'} or not all(hexid(b[k]) for k in ('old_epoch_id','new_epoch_id')) or b['reason'] not in ('rotation','location-change','expired'):raise ValueError('Invalid credential retirement.')
    elif kind=='disconnect':
        if b!={}:raise ValueError('Invalid disconnect record.')
    return kind

def make(kind,negotiation,epoch,own,peer,body):
    now=int(time.time())
    return {'type':'peer.direct.'+kind,'negotiation_id':negotiation,'epoch_id':epoch,'endpoints':sorted([{'endpoint_id':p['endpoint_id'],'role':p['role']} for p in (own,peer)],key=lambda p:p['endpoint_id']),'created_utc':now,'expires_utc':now+120,'body':body}
