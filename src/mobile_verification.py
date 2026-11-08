"""Public local facts and exact review bindings. Mobile never approves an action."""
import socket,time
from pathlib import Path
from peer_protocol import digest,hexid
from wallet_preview import fingerprint
from setup_messages import sign
NAMESPACE='wallaby-wallet-verification-v1'

def legacy_facts_available():
    from peer_wallet import local_ipv6
    return Path('/etc/ssh/ssh_host_ed25519_key.pub').is_file() and bool(local_ipv6())

def facts(store,challenge):
    from peer_wallet import local_ipv6
    path=Path('/etc/ssh/ssh_host_ed25519_key.pub')
    public=' '.join(path.read_text().split()[:2]) if path.is_file() else None
    own=sign(store,{'purpose':'identity-initialisation','version':1})['public_key'];now=int(time.time())
    return sign(store,{'protocol':'wallaby-wallet-verification','version':1,'kind':'agent_facts','challenge':challenge,'agent_public_key':own,'agent_fingerprint':fingerprint(own),'ssh_host_public_key':public,'ssh_host_fingerprint':fingerprint(public) if public else None,'ipv6':local_ipv6(),'hostname':socket.gethostname(),'generated_at':now,'expires_at':now+120},NAMESPACE)

def validate(p):
    if not isinstance(p,dict) or set(p)!={'kind','version','challenge','peer_facts'} or p['kind']!='wallet_mobile_verification' or type(p['version']) is not int or p['version']!=1 or not hexid(p['challenge']) or not isinstance(p['peer_facts'],list) or len(p['peer_facts'])>64:raise ValueError('Invalid mobile verification challenge.')
    # Peer facts are untrusted discovery only. They are not installed as grants.
    if len(__import__('json').dumps(p))>65536:raise ValueError('Oversized mobile verification challenge.')
    return p

def review(store,key):
    saved=store.read();row=saved['pending'].get(key)
    if not hexid(key) or not row or row.get('withdrawn') or row['state'] not in ('pending','awaiting_backups'):raise ValueError('The current operation review changed or is no longer available.')
    own=sign(store,{'purpose':'identity-initialisation','version':1})['public_key'];now=int(time.time())
    local=facts(store,'0'*64)['message'];route={k:local[k] for k in ('ssh_host_public_key','ssh_host_fingerprint','ipv6','hostname')}
    return sign(store,{'protocol':'wallaby-wallet-verification','version':1,'kind':'operation_review','request_digest':key,'operation_kind':row['proposal']['kind'],'agent_public_key':own,'agent_fingerprint':fingerprint(own),'proposal_digest':digest(row['proposal']),'local_route':route,'legacy_peer':row['proposal'].get('peer') if row['proposal'].get('transfer_version')!=3 else None,'peer_transport':row['proposal'].get('transport') or row['proposal'].get('peer_transport') or row['proposal'].get('proposal',{}).get('peer_transport'),'generated_at':now,'expires_at':now+120,'approval_authority':False},NAMESPACE)

def respond(peers,channel,record):
    if record['payload_type']!='verification_request' or record['body']!={'request_digest':record['operation_hash']}:raise ValueError('Mobile grant permits verification reads only, not wallet changes or signing.')
    envelope=review(peers.store,record['operation_hash']);channel.send('verification_record',record['operation_hash'],envelope)

def qr(envelope):
    from vendor.qrcodegen import QrCode
    from wallet_preview import canonical
    code=QrCode.encode_text(canonical(envelope).decode(),QrCode.Ecc.LOW);border=4;size=code.get_size();parts=[]
    for y in range(size):
        for x in range(size):
            if code.get_module(x,y):parts.append('M'+str(x+border)+','+str(y+border)+'h1v1h-1z')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+str(size+border*2)+' '+str(size+border*2)+'"><rect width="100%" height="100%" fill="white"/><path d="'+''.join(parts)+'" fill="black"/></svg>'
