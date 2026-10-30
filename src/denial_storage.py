"""The sole persistent Bitcoin preference exception: bounded, inert denial metadata.

The protected worker never gains a writable disk mount. A separate unprivileged
service accepts this exact schema and writes only its fixed state directory.
"""
import copy,fcntl,json,os,re,secrets,socket,socketserver,stat,struct,threading
from pathlib import Path

LIMIT=256*1024
HEX=re.compile('[0-9a-f]{64}')

def initial():return {'version':1,'revision':0,'wallets':{}}

def label(value):
    if not isinstance(value,str) or len(value)>256 or any(ord(c)<32 for c in value):raise ValueError('Invalid denial display name.')
    return value

def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','revision','wallets'} or type(data['version']) is not int or data['version']!=1 or type(data['revision']) is not int or not 0<=data['revision']<2**63:raise ValueError('Invalid persistent denial list.')
    records=data['wallets']
    if not isinstance(records,dict) or len(records)>128:raise ValueError('Denial list is full; remove an entry before adding another.')
    for key,row in records.items():
        if not isinstance(key,str) or not HEX.fullmatch(key) or not isinstance(row,dict) or set(row)!={'policy_id','wallet_name'} or row['policy_id']!=key:raise ValueError('Only disabled wallet identifiers and display names may be persisted.')
        label(row['wallet_name'])
    if len(json.dumps(data,allow_nan=False).encode())>LIMIT:raise ValueError('Denial list exceeds its storage limit.')
    return copy.deepcopy(data)

def display(p):
    value=p.get('wallet',p.get('public_wallet',{}).get('wallet_name',p.get('name',p.get('proposal',{}).get('name',''))))
    # A name is a human hint, never authority. It cannot carry entire proposals.
    return label(value)

def project(state,revision):
    return validate({'version':1,'revision':revision,'wallets':copy.deepcopy(state.get('sync_exclusions',{}))})

def overlay(state,data):
    data=validate(data)
    state['sync_exclusions']=data['wallets'];state['sync_preferences_revision']=data['revision']
    from sync_preferences import policy_id
    for key,row in list(state.get('pending',{}).items()):
        p=row['proposal']
        if row['state']=='pending' and p['kind']=='wallet_transfer' and p['direction']=='receive' and policy_id(p) in data['wallets']:
            state['pending'].pop(key);state.get('sync_choices',{}).pop(key,None);state.get('transfer_previews',{}).pop(key,None)

def strict_json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('Duplicate denial fields.')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Invalid number.')))

class FileStore:
    """Fixed filenames; directory-FD operations reject symlink and path redirection."""
    def __init__(self,directory):self.directory=Path(directory)
    def directory_fd(self):
        fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        info=os.fstat(fd)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:os.close(fd);raise ValueError('Denial storage must be a private user-owned directory.')
        return fd
    def read_at(self,parent):
        try:fd=os.open('denials.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        except FileNotFoundError:return initial()
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size>LIMIT or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('Unsafe persistent denial file. Repair it locally before Bitcoin work can resume.')
            with os.fdopen(os.dup(fd),'rb') as f:raw=f.read(LIMIT+1)
            if len(raw)>LIMIT:raise ValueError('Denial file is too large.')
            return validate(strict_json(raw))
        finally:os.close(fd)
    def operation(self,request):
        if not isinstance(request,dict):raise ValueError('Invalid denial operation.')
        parent=self.directory_fd();lock=None
        try:
            lock=os.open('denials.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
            info=os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('Unsafe denial lock.')
            fcntl.flock(lock,fcntl.LOCK_EX);old=self.read_at(parent)
            if request=={'method':'read'}:return old
            if set(request)!={'method','expected_revision','record'} or request['method']!='commit' or type(request['expected_revision']) is not int:raise ValueError('Only fixed denial read/commit operations are allowed.')
            data=validate(request['record'])
            if request['expected_revision']!=old['revision'] or data['revision']!=old['revision']+1:raise ValueError('Denial list changed. Refresh and try again.')
            name='.denials-'+secrets.token_hex(16)
            try:
                fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                with os.fdopen(fd,'wb') as f:f.write(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode());f.flush();os.fsync(f.fileno())
                os.replace(name,'denials.json',src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
            finally:
                try:os.unlink(name,dir_fd=parent)
                except FileNotFoundError:pass
            return data
        finally:
            if lock is not None:os.close(lock)
            os.close(parent)
    def read(self):return self.operation({'method':'read'})
    def commit(self,old,new):return self.operation({'method':'commit','expected_revision':old,'record':new})

def receive(sock,n):
    chunks=[]
    while n:
        chunk=sock.recv(n)
        if not chunk:raise ValueError('Denial storage connection ended.')
        chunks.append(chunk);n-=len(chunk)
    return b''.join(chunks)

def socket_path():return Path('/run/wallaby-agent-denials')/str(os.getuid())/'denials.sock'

class Client:
    def __init__(self,path=None):self.path=Path(path or socket_path())
    def operation(self,request):
        raw=json.dumps(request,allow_nan=False).encode()
        if len(raw)>LIMIT:raise ValueError('Denial request exceeds its limit.')
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(10);s.connect(str(self.path));_,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid():raise ValueError('Unexpected denial storage service owner.')
                s.sendall(struct.pack('!I',len(raw))+raw);n=int.from_bytes(receive(s,4),'big')
                if not 0<n<=LIMIT:raise ValueError('Invalid denial storage response.')
                reply=strict_json(receive(s,n))
                if set(reply)=={'error'}:raise ValueError('Denial storage refused the operation: '+str(reply['error']))
                if set(reply)!={'result'}:raise ValueError('Invalid denial storage response.')
                return validate(reply['result'])
        except (OSError,TimeoutError):raise ValueError('Persistent denial storage is unavailable. Restart the protected workspace after installing the complete Build 11 package; requests remain blocked until the list can be read.') from None
    def read(self):return self.operation({'method':'read'})
    def commit(self,old,new):return self.operation({'method':'commit','expected_revision':old,'record':new})

class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    def __init__(self,path,storage):self.storage=storage;super().__init__(str(path),Handler)

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(10);_,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():return
            n=int.from_bytes(receive(self.request,4),'big')
            if not 0<n<=LIMIT:raise ValueError('Denial request exceeds its limit.')
            reply={'result':self.server.storage.operation(strict_json(receive(self.request,n)))}
        except (ValueError,OSError,TypeError,KeyError):reply={'error':'Denial storage validation or atomic update failed. Inspect the local denial storage service; no wallet operation was authorised.'}
        try:
            raw=json.dumps(reply,allow_nan=False).encode();self.request.sendall(struct.pack('!I',len(raw))+raw)
        except OSError:pass

def main():
    path=socket_path();info=path.parent.stat()
    if path.parent.is_symlink() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise SystemExit('Unsafe denial service runtime directory.')
    path.unlink(missing_ok=True)
    with Server(path,FileStore(Path('/var/lib/wallaby-agent-denials')/str(os.getuid()))) as server:
        path.chmod(0o600);server.serve_forever()

if __name__=='__main__':main()
