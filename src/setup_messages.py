"""Domain-separated Agent signatures; identities are pinned independently by users."""
import base64,subprocess,tempfile
from pathlib import Path
from wallet_preview import canonical,fingerprint

NAMESPACE='wallaby-wallet-setup-v1'

def sign(store,message,namespace=NAMESPACE):
    key=getattr(store,'identity_root',store.root)/'preview_identity'
    if not key.exists():
        with store.edit():
            if not key.exists():subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','','-f',str(key)],check=True,capture_output=True,timeout=10)
    with tempfile.TemporaryDirectory(dir=store.root) as path:
        f=Path(path)/'message';f.write_bytes(canonical(message));f.chmod(0o600)
        subprocess.run(['/usr/bin/ssh-keygen','-Y','sign','-f',str(key),'-n',namespace,str(f)],check=True,capture_output=True,timeout=10)
        return {'message':message,'public_key':' '.join(key.with_suffix('.pub').read_text().split()[:2]),'signature':base64.b64encode(f.with_suffix('.sig').read_bytes()).decode()}

def verify(store,envelope,expected,namespace=NAMESPACE):
    if not isinstance(envelope,dict) or set(envelope)!={'message','public_key','signature'} or envelope['public_key']!=expected:raise ValueError('Contribution comes from a different Agent identity.')
    fingerprint(expected)
    if not isinstance(envelope['signature'],str) or len(envelope['signature'])>4096:raise ValueError('Invalid contribution signature.')
    with tempfile.TemporaryDirectory(dir=store.root) as path:
        allow=Path(path)/'allowed';sig=Path(path)/'signature';allow.write_text('wallaby '+expected+'\n')
        try:sig.write_bytes(base64.b64decode(envelope['signature'],validate=True))
        except Exception:raise ValueError('Invalid contribution signature encoding.') from None
        r=subprocess.run(['/usr/bin/ssh-keygen','-Y','verify','-f',str(allow),'-I','wallaby','-n',namespace,'-s',str(sig)],input=canonical(envelope['message']),capture_output=True,timeout=10)
        if r.returncode:raise ValueError('Authenticated contribution verification failed.')
    return envelope['message']
