"""Signed initial public review, independently pinned by the receiving user.

The Dashboard is a courier, not a key authority. SSH signatures use an Agent-only
identity (never a Bitcoin key), namespace and fresh per-transfer challenge.
"""
import base64,hashlib,json,re,subprocess,tempfile,time
from pathlib import Path
from approval_store import digest
from build8_policy import descriptors,ipv6

NAMESPACE='wallaby-wallet-preview-v1'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def fingerprint(public_key):
    if not isinstance(public_key,str) or len(public_key)>256:raise ValueError('Invalid Agent identity key.')
    parts=public_key.split()
    if len(parts)!=2 or parts[0]!='ssh-ed25519':raise ValueError('Only an Ed25519 Agent identity is supported.')
    try:raw=base64.b64decode(parts[1],validate=True)
    except ValueError:raise ValueError('Invalid Agent identity encoding.') from None
    if len(raw)!=51 or raw[:19]!=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':raise ValueError('Invalid Ed25519 key format.')
    return 'SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')

def validate_preview(payload):
    from peer_wallet import validate_details
    if not isinstance(payload,dict) or set(payload)!={'preview','public_key','signature'}:raise ValueError('Invalid signed wallet preview.')
    p=payload['preview'];required={'version','transfer_id','challenge','sender_ipv6','receiver_ipv6','public_wallet','chain','funded_outputs','node_tip','generated_at'}
    if not isinstance(p,dict) or (set(p)!=required if p.get('version')==1 else set(p)!=required|{'vaults','address_labels'}) or p['version'] not in (1,2):raise ValueError('Invalid public preview schema.')
    for k in ('transfer_id','challenge'):
        if not re.fullmatch('[0-9a-f]{64}',str(p[k])):raise ValueError('Invalid preview binding.')
    ipv6(p['sender_ipv6']);ipv6(p['receiver_ipv6']);descriptors(p['public_wallet'])
    validate_details({k:p[k] for k in ('public_wallet','chain','funded_outputs','vaults','address_labels') if k in p})
    if not isinstance(p['node_tip'],dict) or set(p['node_tip'])!={'height','hash'} or type(p['node_tip']['height']) is not int or not 0<=p['node_tip']['height']<500000000 or not re.fullmatch('[0-9a-f]{64}',str(p['node_tip']['hash'])):raise ValueError('Invalid preview block reference.')
    if type(p['generated_at']) is not int or not time.time()-900<=p['generated_at']<=time.time()+120:raise ValueError('Wallet preview expired or has a future timestamp. Start a fresh request.')
    fingerprint(payload['public_key'])
    if not isinstance(payload['signature'],str) or len(payload['signature'])>4096:raise ValueError('Invalid preview signature size.')
    try:signature=base64.b64decode(payload['signature'],validate=True)
    except ValueError:raise ValueError('Invalid preview signature encoding.') from None
    if not signature.startswith(b'-----BEGIN SSH SIGNATURE-----'):raise ValueError('Invalid SSH signature.')
    return p

def sign(store,preview):
    key=getattr(store,'identity_root',store.root)/'preview_identity'
    # Store cross-process lock protects first creation; no use of login/Bitcoin keys.
    with store.edit():
        if not key.exists():subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','','-f',str(key)],check=True,capture_output=True,timeout=10)
        from protected_memory import inside
        if inside():
            if key.stat().st_mode&0o077:raise ValueError('Fix the local Agent identity permissions before using its protected workspace.')
        else:key.chmod(0o600)
        public=' '.join(key.with_suffix('.pub').read_text().split()[:2])
    with tempfile.TemporaryDirectory(dir=store.root) as root:
        file=Path(root)/'preview';file.write_bytes(canonical(preview));file.chmod(0o600)
        subprocess.run(['/usr/bin/ssh-keygen','-Y','sign','-f',str(key),'-n',NAMESPACE,str(file)],check=True,capture_output=True,timeout=10)
        return {'preview':preview,'public_key':public,'signature':base64.b64encode(file.with_suffix('.sig').read_bytes()).decode()}

def verify(store,payload):
    p=validate_preview(payload)
    with tempfile.TemporaryDirectory(dir=store.root) as root:
        allowed=Path(root)/'allowed';signature=Path(root)/'signature';allowed.write_text('wallaby-preview '+payload['public_key']+'\n');signature.write_bytes(base64.b64decode(payload['signature'],validate=True))
        result=subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(allowed),'-I','wallaby-preview','-n',NAMESPACE,'-s',str(signature)],input=canonical(p),capture_output=True,timeout=10)
        if result.returncode:raise ValueError('The sending Agent’s public preview signature is invalid.')
    return {'fingerprint':fingerprint(payload['public_key']),'preview_hash':digest(p)}

def prepare(core,store,key,p):
    from peer_wallet import wallet_details,local_ipv6
    from wallet_ops import rpc
    if not p.get('preview_challenge'):return None # Build 8 must be updated before this protocol is enabled.
    own=local_ipv6(p['peer']['ipv6'])
    if own!=p['node_ipv6']:raise ValueError('The local IPv6 route differs from the paired request. Refresh node identity before synchronisation.')
    facts=wallet_details(core,p,store);tip=rpc(core,'getblockchaininfo')
    if tip.get('initialblockdownload') or tip.get('headers',tip['blocks'])!=tip['blocks']:raise ValueError('Wait for the sending node to finish synchronising before preparing a wallet preview.')
    preview={'version':2 if p.get('transfer_version')==2 else 1,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':own,'receiver_ipv6':ipv6(p['peer']['ipv6']),**facts,'node_tip':{'height':tip['blocks'],'hash':tip['bestblockhash']},'generated_at':int(time.time())}
    payload=sign(store,preview);verify(store,payload)
    with store.edit() as s:
        # Only an unchanged currently active request can acquire a verified local snapshot.
        if key not in s['pending'] or s['pending'][key].get('withdrawn'):raise ValueError('Synchronisation request changed during local verification.')
        s.setdefault('transfer_previews',{})[key]=payload;s.get('preview_errors',{}).pop(key,None)
    store.queue('wallet_transfer_preview',{'request_hash':key,**payload});return payload

def receive(store,payload):
    candidates=[(key,row) for key,row in store.read()['pending'].items() if row['proposal']['kind']=='wallet_transfer' and row['proposal']['direction']=='receive' and row['proposal']['transfer_id']==payload.get('preview',{}).get('transfer_id')]
    if len(candidates)!=1:raise ValueError('No unique paired receiving request.')
    key,row=candidates[0]
    if not row or row['proposal']['direction']!='receive':raise ValueError('No paired receiving request is active.')
    p=row['proposal'];proof=verify(store,payload);v=payload['preview']
    if v['version']!=(2 if p.get('transfer_version')==2 else 1):raise ValueError('Preview protocol differs from request.')
    if v['transfer_id']!=p['transfer_id'] or v['challenge']!=p.get('preview_challenge') or v['sender_ipv6']!=p['peer']['ipv6'] or v['receiver_ipv6']!=p.get('node_ipv6') or descriptors(v['public_wallet'])!=descriptors(p['public_wallet']):raise ValueError('Signed preview does not match the active wallet, challenge and peer addresses.')
    with store.edit() as s:
        if key not in s['pending'] or s['pending'][key].get('withdrawn'):raise ValueError('Request was withdrawn.')
        previous=s.setdefault('transfer_previews',{}).get(key)
        if previous and previous!=payload:raise ValueError('A verified request preview cannot be replaced. Cancel and start a fresh synchronisation.')
        s['transfer_previews'][key]=payload
    return proof
