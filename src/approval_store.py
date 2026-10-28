"""Private cross-process inbox/outbox. Incoming data is never an RPC command.

Content hashes, rather than remote IDs, identify denials and immutable proposals.
A disconnected/restarted session cannot silently replay a local wallet operation.
"""
import contextlib, copy, fcntl, hashlib, json, os, tempfile, time
from pathlib import Path
from configuration import Config

MAX_ITEMS=128

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

class Store:
    def __init__(self,root=None):
        self.root=Path(root or Config().root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.root/'approvals.json'
    @contextlib.contextmanager
    def edit(self):
        with (self.root/'approvals.lock').open('a') as lock:
            os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
            state={'pending':{},'denied':{},'completed':{},'vaults':{},'outbox':{},'sync':'Waiting for Dashboard extension support.'}
            if self.path.exists():state.update(json.loads(self.path.read_text()))
            yield state
            raw=json.dumps(state,allow_nan=False)
            if len(raw.encode())>16*1024*1024:raise ValueError('Local approval storage is full. Remove completed records before continuing.')
            fd,name=tempfile.mkstemp(dir=self.root)
            try:
                with os.fdopen(fd,'w') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(name,self.path)
            finally:
                if os.path.exists(name):os.unlink(name)
    def read(self):
        with self.edit() as s:return copy.deepcopy(s)
    def receive(self,proposal):
        from vault_policy import validate_proposal
        p=validate_proposal(proposal);key=digest(p)
        with self.edit() as s:
            if key in s['denied'] or key in s['completed'] or key in s['pending']:return False
            if p['kind']=='vault_sync' and digest(p['vault']) in s['vaults']:return False
            if len(s['pending'])>=MAX_ITEMS:raise ValueError('Authorisation queue is full.')
            s['pending'][key]={'proposal':p,'received':time.time(),'state':'pending'}
        return True
    def deny(self,key):
        with self.edit() as s:
            row=s['pending'].pop(key);s['denied'][key]=row
            if len(s['denied'])>MAX_ITEMS:raise ValueError('Denied request list is full; remove a record first.')
    def forget(self,key):
        with self.edit() as s:s['denied'].pop(key,None)
    def queue(self,kind,payload):
        item={'kind':kind,'payload':payload};key=digest(item)
        with self.edit() as s:
            if len(s['outbox'])>=MAX_ITEMS:raise ValueError('Dashboard outbox is full; connect and synchronise first.')
            s['outbox'][key]=item
        return key
