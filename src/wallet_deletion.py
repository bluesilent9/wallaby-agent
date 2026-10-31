#!/usr/bin/python3
"""Narrow, unprivileged filesystem exception: unlink approved unloaded wallets.

No wallet bytes are read, copied or written. Only the protected worker may call
this service. The worker checks Core history, policy, balances and archive first.
"""
import fcntl,json,os,socket,socketserver,stat,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from secure_bridge import receive

FILES={'wallet.dat','wallet.dat-journal','wallet.dat-wal','wallet.dat-shm'}

def bases(home=None):
    home=Path.home() if home is None else Path(home)
    return [base/net/'wallets' for base in (home/'.bitcoin',home/'snap/bitcoin-core/common/.bitcoin') for net in ('','testnet3','testnet4','signet','regtest')]

def target(core,name):
    if not isinstance(name,str) or not name or name in ('.','..','Wallaby Extinct') or '/' in name or '\\' in name:raise ValueError('Automatic retirement requires a named wallet directory, not a default wallet or path.')
    base=Path(core.config['cookie']).expanduser().resolve().parent/'wallets'
    path=base/name
    if not path.is_dir() or path.is_symlink():raise ValueError('Cannot safely locate this wallet under the Core cookie directory. Custom wallet directories require local review; no wallet was deleted.')
    info=path.stat();db=(path/'wallet.dat').lstat()
    if info.st_uid!=os.getuid() or not stat.S_ISREG(db.st_mode) or db.st_uid!=os.getuid() or db.st_nlink!=1:raise ValueError('Unsafe wallet directory or database ownership.')
    return {'path':str(path),'directory':[info.st_dev,info.st_ino],'database':[db.st_dev,db.st_ino]}

def remove(request,allowed=None):
    if not isinstance(request,dict) or set(request)!={'path','directory','database'}:raise ValueError('Invalid deletion request.')
    path=Path(request['path'])
    if not path.is_absolute() or path.name in ('.','..','Wallaby Extinct') or path.parent not in (bases() if allowed is None else allowed):raise ValueError('Wallet directory is outside the supported Core wallet locations.')
    for parent in (path,*path.parents):
        if parent.is_symlink():raise ValueError('Wallet paths must not contain symbolic links.')
    parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    directory=None;database=None
    try:
        directory=os.open(path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        info=os.fstat(directory)
        if [info.st_dev,info.st_ino]!=request['directory'] or info.st_uid!=os.getuid():raise ValueError('Wallet directory changed since authorisation.')
        names=set(os.listdir(directory))
        if 'wallet.dat' not in names or not names<=FILES:raise ValueError('Unexpected files exist in the wallet directory; no automatic deletion is permitted.')
        for name in names:
            st=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:raise ValueError('Unsafe wallet file.')
        database=os.open('wallet.dat',os.O_RDWR|os.O_NOFOLLOW,dir_fd=directory)
        db=os.fstat(database)
        if [db.st_dev,db.st_ino]!=request['database']:raise ValueError('Wallet database changed since authorisation.')
        # Core SQLite holds an exclusive POSIX lock while loaded. Whole-file
        # locking conflicts with it, including SQLite's high-offset lock bytes.
        fcntl.lockf(database,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if set(os.listdir(directory))!=names:raise ValueError('Wallet files changed during retirement.')
        check=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
        if (check.st_dev,check.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('Wallet directory changed during retirement.')
        for name in sorted(names-{'wallet.dat'}):os.unlink(name,dir_fd=directory)
        os.unlink('wallet.dat',dir_fd=directory);os.fsync(directory)
        os.rmdir(path.name,dir_fd=parent);os.fsync(parent)
        return {'deleted':True}
    finally:
        if database is not None:os.close(database)
        if directory is not None:os.close(directory)
        os.close(parent)

def socket_path():return Path('/run/wallaby-agent-retirement')/str(os.getuid())/'delete.sock'

def delete(request):
    raw=json.dumps(request).encode()
    if len(raw)>4096:raise ValueError('Deletion metadata exceeds its limit.')
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15);sock.connect(str(socket_path()))
            _,uid,_=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=os.getuid():raise ValueError('Unexpected retirement service owner.')
            sock.sendall(struct.pack('!I',len(raw))+raw);size=int.from_bytes(receive(sock,4),'big')
            if not 0<size<=4096:raise ValueError('Invalid retirement response.')
            reply=json.loads(receive(sock,size))
            if reply!={'deleted':True}:raise ValueError('Wallet deletion was not confirmed. The archive is retained; inspect the local retirement service. No automatic retry was made.')
            try:os.lstat(request['path'])
            except FileNotFoundError:return reply
            raise ValueError('The wallet directory still exists after the deletion response. Completion was not confirmed; inspect locally.')
    except OSError:raise ValueError('The local wallet-deletion service is unavailable or refused deletion. The wallet was unloaded and its public archive retained; inspect locally before a fresh request.') from None

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(10);pid,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            group=Path('/proc',str(pid),'cgroup').read_text().splitlines()
            expected='/wallaby-agent-secure@'+str(os.getuid())+'.service'
            if uid!=os.getuid() or not any(line.startswith('0::/system.slice/') and line.endswith(expected) for line in group):return
            size=int.from_bytes(receive(self.request,4),'big')
            if not 0<size<=4096:return
            reply=remove(json.loads(receive(self.request,size)))
        except Exception:reply={'deleted':False}
        try:
            raw=json.dumps(reply).encode();self.request.sendall(struct.pack('!I',len(raw))+raw)
        except OSError:pass

def main():
    os.umask(0o077);path=socket_path();path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(path),Handler) as server:path.chmod(0o600);server.serve_forever()

if __name__=='__main__':main()
