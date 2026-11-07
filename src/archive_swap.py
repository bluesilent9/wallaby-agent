"""Atomic exchange of two unloaded public archive directories; fixed helper gate."""
import ctypes,fcntl,json,os,socket,struct,stat
from pathlib import Path
from wallet_deletion import bases,FILES
from secure_bridge import receive


def exchange(archive,stage,allowed=None):
    allowed=bases() if allowed is None else allowed
    if any(not isinstance(r,dict) or set(r)!={'path','directory','database'} for r in (archive,stage)):raise ValueError('Invalid archive exchange identities.')
    a,b=Path(archive['path']),Path(stage['path'])
    if a.name not in ('Wallaby Extinct','Extinct') or not b.name.startswith('.wallaby-history-') or a.parent!=b.parent or a.parent not in allowed or a==b:raise ValueError('Only the existing Extinct archive and its staged public replacement can be exchanged.')
    for p in (a,b,*a.parents):
        if p.is_symlink():raise ValueError('Archive exchange paths must not contain symlinks.')
    parent=os.open(a.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);fds=[]
    try:
        for path,record in ((a,archive),(b,stage)):
            folder=os.open(path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);fds.append(folder);info=os.fstat(folder)
            if info.st_uid!=os.getuid() or [info.st_dev,info.st_ino]!=record['directory'] or not set(os.listdir(folder))<=FILES:raise ValueError('Archive directory changed or contains unexpected files.')
            for name in os.listdir(folder):
                st=os.stat(name,dir_fd=folder,follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:raise ValueError('Unsafe archive file.')
            db=os.open('wallet.dat',os.O_RDWR|os.O_NOFOLLOW,dir_fd=folder);fds.append(db);info=os.fstat(db)
            if [info.st_dev,info.st_ino]!=record['database']:raise ValueError('Archive database changed after readback.')
            fcntl.lockf(db,fcntl.LOCK_EX|fcntl.LOCK_NB)
        libc=ctypes.CDLL(None,use_errno=True)
        if not hasattr(libc,'renameat2') or libc.renameat2(parent,os.fsencode(a.name),parent,os.fsencode(b.name),2):raise OSError(ctypes.get_errno(),'Atomic archive exchange failed')
        os.fsync(parent);return {'exchanged':True}
    finally:
        for fd in reversed(fds):os.close(fd)
        os.close(parent)


def swap(archive,stage):
    from wallet_deletion import socket_path
    raw=json.dumps({'archive_swap':{'archive':archive,'stage':stage}}).encode()
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(15);s.connect(str(socket_path()));_,uid,_=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=os.getuid():raise ValueError('Unexpected archive helper owner.')
        s.sendall(struct.pack('!I',len(raw))+raw);size=int.from_bytes(receive(s,4),'big')
        if not 0<size<=4096:raise ValueError('Invalid archive exchange response.')
        reply=json.loads(receive(s,size))
    if reply!={'exchanged':True}:raise ValueError('Public archive exchange was not confirmed. Original and staged archives were retained for reconciliation.')
    return reply


def cleanup(stage):
    if not Path(stage['path']).name.startswith('.wallaby-history-'):raise ValueError('Only a verified previous public archive copy can be cleaned up here.')
    from wallet_deletion import delete
    return delete(stage,manual=True)
