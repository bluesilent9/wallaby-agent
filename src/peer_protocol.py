"""Public peer wire schemas. A server directory is never a trust decision."""
import base64,hashlib,re,time
from wallet_preview import canonical,fingerprint
PROTOCOL='wallaby-wallet-relay'
CIPHER='Noise_IKpsk2_25519_ChaChaPoly_SHA256'
CONTROL='wallaby-wallet-relay-control-v1'
INVITATION='wallaby-wallet-peer-invitation-v1'
HANDSHAKE='wallaby-wallet-peer-handshake-v1'
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def hexid(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None
def binary(value,size=32):
    if not isinstance(value,str) or len(value)>((size+2)//3)*4:raise ValueError('Invalid peer binary field.')
    try:raw=base64.b64decode(value,validate=True)
    except ValueError:raise ValueError('Invalid peer binary encoding.') from None
    if len(raw)!=size or base64.b64encode(raw).decode()!=value:raise ValueError('Invalid peer binary size.')
    return raw
def b64(value):return base64.b64encode(value).decode()
def endpoint(role,key):
    if role not in ('agent','mobile'):raise ValueError('Invalid peer role.')
    fingerprint(key);return digest({'role':role,'identity_key':key})
def participant(value):
    if not isinstance(value,dict) or set(value)!={'endpoint_id','role','identity_key','noise_public_key'} or value['endpoint_id']!=endpoint(value['role'],value['identity_key']):raise ValueError('Invalid peer identity binding.')
    binary(value['noise_public_key']);return value
def transport(p):
    value=p.get('transport');fields={'protocol','version','cipher_suite','sender_endpoint','receiver_endpoint','sender_identity','receiver_identity','sender_noise_key','receiver_noise_key'}
    if not isinstance(value,dict) or set(value)!=fields or value['protocol']!=PROTOCOL or type(value['version']) is not int or value['version']!=1 or value['cipher_suite']!=CIPHER:raise ValueError('Invalid encrypted wallet transport.')
    for side in ('sender','receiver'):
        if value[side+'_endpoint']!=endpoint('agent',value[side+'_identity']):raise ValueError('Wallet transport identity differs from its role.')
        binary(value[side+'_noise_key'])
    if value['sender_endpoint']==value['receiver_endpoint']:raise ValueError('Distinct wallet transfer peers are required.')
    return value
def requirements(value,keys=None):
    if not isinstance(value,dict) or set(value)!={'protocol','version','cipher_suite','required_agent_keys'} or value['protocol']!=PROTOCOL or type(value['version']) is not int or value['version']!=1 or value['cipher_suite']!=CIPHER:raise ValueError('Invalid required Agent mesh.')
    peers=value['required_agent_keys']
    if not isinstance(peers,list) or not 1<=len(peers)<=15 or peers!=sorted(set(peers)):raise ValueError('Invalid required Agent identities.')
    for key in peers:fingerprint(key)
    if keys is not None and peers!=sorted(set(keys)):raise ValueError('Required channels do not match the actual producing Agents.')
    return value
def frame(value):
    fields={'version','id','from','to','channel_id','sequence','kind','ciphertext'}
    if not isinstance(value,dict) or set(value)!=fields or type(value['version']) is not int or value['version']!=1 or any(not hexid(value[k]) for k in ('id','from','to','channel_id')) or type(value['sequence']) is not int or not 0<=value['sequence']<2**53 or value['kind'] not in ('handshake','transport'):raise ValueError('Invalid peer frame.')
    if not isinstance(value['ciphertext'],str) or len(value['ciphertext'])>65536:raise ValueError('Oversized peer frame.')
    try:raw=base64.b64decode(value['ciphertext'],validate=True)
    except ValueError:raise ValueError('Invalid peer ciphertext.') from None
    if not 16<=len(raw)<=49152 or b64(raw)!=value['ciphertext']:raise ValueError('Invalid peer frame size.')
    return value
