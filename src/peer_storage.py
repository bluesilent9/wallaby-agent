"""Narrow durable exception for communication keys, never Bitcoin secrets.

The protected worker's filesystem remains read-only. This same-UID helper can
write only its fixed private state directory and accepts a bounded exact schema.
"""
import copy,os,stat
from pathlib import Path
from denial_storage import FileStore as BaseFile,Client as BaseClient,Server
from peer_protocol import binary,hexid,participant

def initial():return {'version':1,'revision':0,'private_key':None,'pairs':{},'used':[]}
def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','revision','private_key','pairs','used'} or type(data['version']) is not int or data['version']!=1 or type(data['revision']) is not int or not 0<=data['revision']<2**63:raise ValueError('Invalid local peer trust record.')
    if data['private_key'] is not None:binary(data['private_key'])
    if not isinstance(data['pairs'],dict) or len(data['pairs'])>64 or not isinstance(data['used'],list) or len(data['used'])>1024 or any(not hexid(x) for x in data['used']):raise ValueError('Peer trust storage limit reached.')
    for ident,p in data['pairs'].items():
        if not isinstance(p,dict) or set(p)!={'peer','psk','invitation_id','initiator','name'} or participant(p['peer'])['endpoint_id']!=ident or not hexid(p['invitation_id']) or type(p['initiator']) is not bool or not isinstance(p['name'],str) or len(p['name'])>128 or any(ord(c)<32 for c in p['name']):raise ValueError('Invalid local peer grant.')
        binary(p['psk'])
    return copy.deepcopy(data)
class FileStore(BaseFile):
    FILENAME='peer-trust.json';validate=staticmethod(validate);initial=staticmethod(initial)
class Client(BaseClient):
    validate=staticmethod(validate)
    def __init__(self,path=None):super().__init__(path or Path('/run/wallaby-agent-peers')/str(os.getuid())/'peers.sock')
    def operation(self,request):
        try:return super().operation(request)
        except ValueError:raise ValueError('Persistent local peer trust is unavailable or its revision changed. Reopen Peer Connections after installing the complete Agent build; no remote trust was accepted.') from None
def main():
    path=Path('/run/wallaby-agent-peers')/str(os.getuid())/'peers.sock';info=path.parent.stat()
    if path.parent.is_symlink() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise SystemExit('Unsafe peer runtime directory.')
    path.unlink(missing_ok=True)
    with Server(path,FileStore(Path('/var/lib/wallaby-agent-peers')/str(os.getuid()))) as server:path.chmod(0o600);server.serve_forever()
if __name__=='__main__':main()
