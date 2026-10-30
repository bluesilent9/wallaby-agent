#!/usr/bin/python3 -I
"""Bind the same volatile RAM into Core Snap's allowed data directory.

The privileged part accepts only a numeric account ID. All destination components
are opened relative to directory FDs with O_NOFOLLOW, so a user's symlink or rename
cannot redirect a privileged mount onto an unrelated host path. No wallet bytes
are read or copied here.
"""
import ctypes,os,pwd,subprocess,sys
from pathlib import Path

def open_directory(parent,name):return os.open(name,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)

def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or not sys.argv[1].isdecimal() or int(sys.argv[1])<1000:raise SystemExit('Invalid protected account.')
    uid=int(sys.argv[1]);account=pwd.getpwuid(uid);source=Path('/run/wallaby-agent-secure')/str(uid)/'ram'
    if not os.path.ismount(source) or source.is_symlink() or source.stat().st_uid!=uid:raise SystemExit('Protected RAM mount is unavailable.')
    info=subprocess.run(['/usr/bin/findmnt','-n','-o','FSTYPE,OPTIONS','--target',str(source)],capture_output=True,text=True,check=True).stdout
    if not info.startswith('tmpfs ') or 'noswap' not in info:raise SystemExit('RAM storage does not have noswap protection.')
    fd=os.open('/',os.O_PATH|os.O_DIRECTORY)
    try:
        try:
            for part in Path(account.pw_dir).parts[1:]+('snap','bitcoin-core','common'):
                next_fd=open_directory(fd,part);os.close(fd);fd=next_fd
        except (FileNotFoundError,NotADirectoryError):return # Native Core: no Snap alias required.
        except OSError:raise SystemExit('Unsafe Core Snap directory; no alias was mounted.') from None
        if os.fstat(fd).st_uid!=uid:raise SystemExit('Core Snap directory is not owned by the selected user.')
        try:os.mkdir('wallaby-agent-volatile',mode=0o700,dir_fd=fd)
        except FileExistsError:pass
        target=open_directory(fd,'wallaby-agent-volatile')
        try:
            src=source.stat();dst=os.fstat(target)
            if (src.st_dev,src.st_ino)==(dst.st_dev,dst.st_ino):return
            if dst.st_uid not in (0,uid):raise SystemExit('Unsafe Core RAM destination.')
            lib=ctypes.CDLL(None,use_errno=True);lib.mount.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_ulong,ctypes.c_void_p]
            if lib.mount(os.fsencode(source),os.fsencode('/proc/self/fd/'+str(target)),None,4096,None):raise SystemExit('Could not expose protected RAM to Core Snap.')
        finally:os.close(target)
    finally:os.close(fd)

if __name__=='__main__':main()
