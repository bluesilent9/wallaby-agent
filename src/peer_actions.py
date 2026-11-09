"""Protected local controls. Server messages never call these actions."""
from peer_protocol import hexid

def route(config):
    from pathlib import Path
    from wallet_preview import fingerprint
    import subprocess,base64,hashlib
    # Use only the host key already accepted by the user's existing Server tunnel.
    known=Path.home()/'.ssh/known_hosts';host=config['hostname'];port=config['ssh_port'];label=host if port==22 else '['+host+']:'+str(port)
    result=subprocess.run(['/usr/bin/ssh-keygen','-F',label,'-f',str(known)],capture_output=True,text=True,timeout=5);keys=[]
    for line in result.stdout.splitlines():
        parts=line.split()
        if len(parts)>=3 and parts[1]=='ssh-ed25519':keys.append(' '.join(parts[1:3]))
    if len(set(keys))!=1:raise ValueError('The Server SSH host identity is not uniquely pinned yet. Connect the Server service and verify its Ed25519 host key first.')
    return {'host':host,'port':port,'user':config['ssh_user'],'host_public_key':keys[0],'host_fingerprint':fingerprint(keys[0]),'agent_port':56443,'mobile_port':56444}

def action(workspace,name,data):
    from configuration import Config
    from mobile_verification import qr,review,facts
    peers=workspace.peers
    if name=='status' and not data:return peers.status()
    if name.startswith('block-'):
        blocks=peers.blocks
        if name=='block-status' and not data:return {**blocks.state(),'pairs':[{k:p[k] for k in ('id','name','role')} for p in peers.status()['pairs'] if p['role']=='agent']}
        if name=='block-prepare' and set(data)=={'id'}:return blocks.prepare(data['id'])
        if name=='block-serve' and set(data)=={'enabled'}:return blocks.sharing(data['enabled'])
        if name=='block-start' and not data:return blocks.start()
        if name=='block-stop' and not data:return blocks.end()
        raise ValueError('Invalid local block action.')
    if name=='decode-qr' and set(data)=={'image'}:
        from peer_qr import decode
        try:return decode(data['image'])
        except ValueError as error:
            if str(error) in ('Choose an image containing exactly one clear pairing QR.','This is not a device pairing QR.'):return {'found':False}
            raise
    if name in ('direct-delete','direct-reconnect') and set(data)=={'id'}:
        if not hexid(data['id']) or data['id'] not in peers.persistence.read()['pairs']:raise ValueError('Unknown paired device.')
        return peers.direct.delete(data['id']) if name=='direct-delete' else peers.direct.reconnect(data['id'])
    if name=='invite' and (not data or set(data)=={'role'}):
        envelope=peers.create_invitation(data.get('role','connect'),route(Config().values));return {'envelope':envelope,'qr_svg':qr(envelope),'expires_at':envelope['message']['expires_at']}
    if name=='import' and set(data)=={'envelope','independent'}:
        if data['independent'] is not True:raise ValueError('Import only a QR obtained directly from the other Agent, independently of Server.')
        try:return peers.import_invitation(data['envelope'])
        except ValueError:
            from diagnostics import LocalActionFailure
            raise LocalActionFailure('pairing_qr_refused','The pairing QR could not be accepted. It may be expired, already used or from an incompatible device. Generate a fresh QR on the updated device and scan again. Existing saved connections were retained.') from None
    if name in ('approve','revoke') and set(data)=={'id'}:
        if not hexid(data['id']):raise ValueError('Invalid peer identity.')
        return getattr(peers,name)(data['id'])
    if name=='review' and set(data)=={'id'}:
        envelope=review(workspace.store,data['id']);return {'envelope':envelope,'qr_svg':qr(envelope)}
    if name=='facts' and not data:
        import secrets
        envelope=facts(workspace.store,secrets.token_hex(32));return {'envelope':envelope,'qr_svg':qr(envelope)}
    raise ValueError('Invalid local peer action.')
