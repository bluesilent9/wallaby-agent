#!/usr/bin/python3
"""Rename an approved unloaded wallet directory; never read or copy wallet bytes."""
import ctypes,errno,fcntl,json,os,socket,socketserver,stat,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from secure_bridge import receive
from wallet_deletion import bases,FILES

def name(value):
    if not isinstance(value,str) or not 1<=len(value)<=100 or len(value.encode('utf-8'))>200 or value.strip()!=value or value.casefold() in ('.','..','extinct','wallaby extinct') or '/' in value or '\\' in value or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Use a wallet name of 1–100 characters (at most 200 UTF-8 bytes), without paths, surrounding spaces or reserved Extinct names.')
    return value

def watch_name(value):
    value=name(value);return value if value.endswith('_watch') else name(value+'_watch')

def move(request,allowed=None):
    if not isinstance(request,dict) or set(request)!={'source','new_name'}:raise ValueError('Invalid wallet rename request.')
    source=request['source'];dest=name(request['new_name'])
    if not isinstance(source,dict) or set(source)!={'path','directory','database'}:raise ValueError('Invalid source identity.')
    path=Path(source['path'])
    if not path.is_absolute() or path.name in ('.','..','Extinct','Wallaby Extinct') or path.parent not in (bases() if allowed is None else allowed) or dest==path.name:raise ValueError('Unsupported wallet rename location or unchanged name.')
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('Wallet rename paths must not contain symbolic links.')
    parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);folder=None;database=None
    try:
        folder=os.open(path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);info=os.fstat(folder)
        if [info.st_dev,info.st_ino]!=source['directory'] or info.st_uid!=os.getuid():raise ValueError('Wallet directory changed after review.')
        names=set(os.listdir(folder))
        if 'wallet.dat' not in names or not names<=FILES:raise ValueError('Unexpected files in the wallet directory; rename refused.')
        for entry in names:
            st=os.stat(entry,dir_fd=folder,follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:raise ValueError('Unsafe wallet file.')
        database=os.open('wallet.dat',os.O_RDWR|os.O_NOFOLLOW,dir_fd=folder);db=os.fstat(database)
        if [db.st_dev,db.st_ino]!=source['database']:raise ValueError('Wallet database identity changed.')
        fcntl.lockf(database,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if set(os.listdir(folder))!=names:raise ValueError('Wallet directory changed during rename.')
        st=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
        if (st.st_dev,st.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('Source directory changed during rename.')
        libc=ctypes.CDLL(None,use_errno=True)
        if not hasattr(libc,'renameat2'):raise ValueError('Atomic no-overwrite rename is unavailable; no fallback copy is allowed.')
        if libc.renameat2(parent,os.fsencode(path.name),parent,os.fsencode(dest),1):raise OSError(ctypes.get_errno(),'Atomic wallet rename refused')
        os.fsync(parent)
        return {'renamed':True,'path':str(path.parent/dest),'directory':source['directory'],'database':source['database']}
    finally:
        if database is not None:os.close(database)
        if folder is not None:os.close(folder)
        os.close(parent)

def socket_path():return Path('/run/wallaby-agent-renames')/str(os.getuid())/'rename.sock'

def rename(source,new_name):
    new_name=name(new_name);raw=json.dumps({'source':source,'new_name':new_name}).encode()
    if len(raw)>4096:raise ValueError('Wallet rename metadata is too large.')
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(15);s.connect(str(socket_path()));_,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():raise ValueError('Unexpected local rename service owner.')
            s.sendall(struct.pack('!I',len(raw))+raw);size=int.from_bytes(receive(s,4),'big')
            if not 0<size<=4096:raise ValueError('Invalid rename response.')
            reply=json.loads(receive(s,size))
        expected={'renamed':True,'path':str(Path(source['path']).with_name(new_name)),'directory':source['directory'],'database':source['database']}
        if reply!=expected:raise ValueError('Local wallet rename was not confirmed. Inspect Core before retrying.')
        path=Path(reply['path']);folder=path.lstat();db=(path/'wallet.dat').lstat()
        if [folder.st_dev,folder.st_ino]!=source['directory'] or [db.st_dev,db.st_ino]!=source['database'] or path.is_symlink() or (path/'wallet.dat').is_symlink():raise ValueError('Renamed wallet identity was not verified. Inspect locally before retrying.')
        return reply
    except OSError:raise ValueError('Local wallet rename failed or is uncertain. Inspect the unloaded wallet and target name before a new request; no wallet operation was replayed.') from None

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(10);pid,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12));group=Path('/proc',str(pid),'cgroup').read_text().splitlines();expected='/wallaby-agent-secure@'+str(os.getuid())+'.service'
            if uid!=os.getuid() or not any(line.startswith('0::/system.slice/') and line.endswith(expected) for line in group):return
            size=int.from_bytes(receive(self.request,4),'big')
            if not 0<size<=4096:return
            reply=move(json.loads(receive(self.request,size)))
        except Exception:reply={'renamed':False}
        raw=json.dumps(reply).encode()
        try:self.request.sendall(struct.pack('!I',len(raw))+raw)
        except OSError:pass

def main():
    os.umask(0o077);path=socket_path();path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(path),Handler) as server:path.chmod(0o600);server.serve_forever()
if __name__=='__main__':main()
