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

def move(request,allowed=None,check_only=False):
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
        if check_only:
            if os.fstatvfs(parent).f_flag & os.ST_RDONLY or not os.access(path.parent,os.W_OK,effective_ids=True):raise PermissionError(errno.EACCES,'Wallet parent is not writable by the local rename helper')
            if os.path.lexists(path.parent/dest):raise FileExistsError(errno.EEXIST,'Target wallet already exists')
            return {'ready':True}
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

class RenameFailure(ValueError):
    def __init__(self,code,message):self.code=code;super().__init__(message)

def failure(error):
    code={errno.EACCES:'permission_denied',errno.EPERM:'permission_denied',errno.EROFS:'read_only',errno.EEXIST:'destination_exists',errno.ENOENT:'source_missing',errno.EAGAIN:'wallet_busy',errno.EBUSY:'wallet_busy'}.get(getattr(error,'errno',None),'validation' if isinstance(error,ValueError) else 'helper_failure')
    messages={'permission_denied':'The local rename helper lacks permission to access or rename this wallet.','read_only':'The local rename helper sees the wallet directory as read-only.','destination_exists':'The requested target wallet already exists.','source_missing':'The reviewed source wallet directory is missing.','wallet_busy':'Bitcoin Core or another process still holds the wallet database lock.','validation':'The local rename helper rejected changed or unsupported wallet files.','helper_failure':'The local rename helper failed its safety checks.'}
    return code,messages[code]

def rename(source,new_name,check_only=False):
    new_name=name(new_name);raw=json.dumps({'source':source,'new_name':new_name,**({'check_only':True} if check_only else {})}).encode()
    if len(raw)>4096:raise ValueError('Wallet rename metadata is too large.')
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(15);s.connect(str(socket_path()));_,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():raise ValueError('Unexpected local rename service owner.')
            s.sendall(struct.pack('!I',len(raw))+raw);size=int.from_bytes(receive(s,4),'big')
            if not 0<size<=4096:raise ValueError('Invalid rename response.')
            reply=json.loads(receive(s,size))
        if isinstance(reply,dict) and reply.get('renamed') is False:
            code=reply.get('code','helper_failure');allowed={'permission_denied','read_only','destination_exists','source_missing','wallet_busy','validation','helper_failure'}
            raise RenameFailure(code if code in allowed else 'helper_failure',reply.get('message','Local rename helper refused the operation.') if code in allowed else 'Local rename helper refused the operation.')
        if check_only:
            if reply!={'ready':True}:raise RenameFailure('helper_protocol','Local rename helper preflight was not confirmed. Restart the workspace after upgrading the Agent.')
            return reply
        expected={'renamed':True,'path':str(Path(source['path']).with_name(new_name)),'directory':source['directory'],'database':source['database']}
        if reply!=expected:raise ValueError('Local wallet rename was not confirmed. Inspect Core before retrying.')
        path=Path(reply['path']);folder=path.lstat();db=(path/'wallet.dat').lstat()
        if [folder.st_dev,folder.st_ino]!=source['directory'] or [db.st_dev,db.st_ino]!=source['database'] or path.is_symlink() or (path/'wallet.dat').is_symlink():raise ValueError('Renamed wallet identity was not verified. Inspect locally before retrying.')
        return reply
    except OSError as error:
        code,message=failure(error)
        if error.errno in (errno.ENOENT,errno.ECONNREFUSED):code,message='helper_unavailable','The local rename service is unavailable. Reconnect the protected workspace before trying again.'
        raise RenameFailure(code,message) from None

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(10);pid,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12));group=Path('/proc',str(pid),'cgroup').read_text().splitlines();expected='/wallaby-agent-secure@'+str(os.getuid())+'.service'
            if uid!=os.getuid() or not any(line.startswith('0::/system.slice/') and line.endswith(expected) for line in group):return
            size=int.from_bytes(receive(self.request,4),'big')
            if not 0<size<=4096:return
            request=json.loads(receive(self.request,size));check=isinstance(request,dict) and request.get('check_only') is True
            if check:request={k:v for k,v in request.items() if k!='check_only'}
            reply=move(request,check_only=check)
        except Exception as error:
            code,message=failure(error);reply={'renamed':False,'code':code,'message':message}
            from activity_log import event
            event('rename.helper','Refused · code='+code+' · type='+type(error).__name__)
        raw=json.dumps(reply).encode()
        try:self.request.sendall(struct.pack('!I',len(raw))+raw)
        except OSError:pass

def main():
    os.umask(0o077);path=socket_path();path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(path),Handler) as server:path.chmod(0o600);server.serve_forever()
if __name__=='__main__':main()
