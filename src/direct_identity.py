"""Identity confirmation from local QR trust and a live direct Agent channel.

Server-supplied names, public keys and manually copied hashes confer no trust.
Signatures and operation-specific evidence remain the responsibility of callers.
"""
from wallet_preview import fingerprint

def own_key(store):
    from pathlib import Path
    path=Path(getattr(store,'identity_root',store.root))/'preview_identity.pub'
    try:return ' '.join(path.read_text().split()[:2])
    except OSError:return None

def require(store,key):
    fingerprint(key)
    if key==own_key(store):return key
    from peer_mesh import manager
    peers=manager(store);channel=peers.channel(key,role='agent')
    direct=getattr(peers,'direct',None)
    if direct is None:raise ValueError('Connect the relevant paired Agent in Peer Connections to verify its identity automatically. No operation was authorised.')
    direct.require(channel)
    return key

def require_fingerprint(store,value):
    # Old in-RAM disc records retain a hash rather than a public key. Resolve
    # it only against independently paired local identities, never Server data.
    local=own_key(store)
    if local and fingerprint(local)==value:return local
    from peer_mesh import manager
    peers=manager(store)
    keys={row['peer']['identity_key'] for row in peers.persistence.read()['pairs'].values() if row['peer']['role']=='agent' and fingerprint(row['peer']['identity_key'])==value}
    if len(keys)!=1:raise ValueError('Pair the original Agent in Peer Connections before confirming this operation. Its identity cannot be supplied by Wallet Server or entered manually.')
    return require(store,keys.pop())
