"""Cold blockchain snapshot files. No wallet/config paths, archive extraction or keys.

Runs only in the dedicated desktop-user helper. All incoming paths are selected
from a closed grammar; symlinks, hardlinks and unknown files fail closed.
"""
import fcntl,hashlib,json,os,re,shutil,stat,time
from pathlib import Path
MAX_FILES=200000; CHUNK=1024*1024; MAX_TOTAL=32*1024**4
ROOTS=('blocks','chainstate')

from diagnostics import LocalActionFailure
class CloneError(LocalActionFailure):
    def __init__(self,message):super().__init__('trusted_clone_refused',message)

def allowed(name):
    return bool(isinstance(name,str) and (re.fullmatch(r'blocks/(?:blk|rev)[0-9]{5,8}\.dat',name) or name in ('blocks/xor.dat','blocks/.lock') or re.fullmatch(r'(?:blocks/index|chainstate)/(?:CURRENT|LOCK|LOG(?:\.old)?|MANIFEST-[0-9]+|[0-9]+\.(?:ldb|log|sst))',name)))

def safe_root(root,allowed_roots=None):
    root=Path(root)
    if allowed_roots is None:
        from wallet_deletion import bases
        allowed_roots=[p.parent for p in bases()]
    if root not in allowed_roots or not root.is_absolute():raise CloneError('Unsupported local Core blockchain location.')
    for p in (root,*root.parents):
        if p.is_symlink():raise CloneError('Blockchain location contains a symbolic link.')
    if root.stat().st_uid!=os.getuid():raise CloneError('Unexpected blockchain directory owner.')
    return root

def regular(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1:raise CloneError('Unsafe blockchain snapshot file.')
    return s

def directory_fd(path):
    """Resolve every component with openat/O_NOFOLLOW, not a pathname check."""
    path=Path(path)
    if not path.is_absolute():raise CloneError('Expected an absolute local blockchain directory.')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        return fd
    except BaseException:os.close(fd);raise

def open_relative(base,name,flags,create=False):
    if not allowed(name):raise CloneError('Unsupported blockchain file path.')
    fd=directory_fd(base)
    try:
        parts=name.split('/')
        for part in parts[:-1]:
            if create:
                try:os.mkdir(part,0o700,dir_fd=fd)
                except FileExistsError:pass
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        result=os.open(parts[-1],flags|os.O_NOFOLLOW,0o600,dir_fd=fd);st=os.fstat(result)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1:
            os.close(result);raise CloneError('Unsafe blockchain file ownership or link count.')
        return result
    finally:os.close(fd)

def inventory(root):
    rows=[]
    for folder in ROOTS:
        base=root/folder
        if not base.is_dir() or base.is_symlink():raise CloneError('Core must have one ordinary blocks directory and chainstate directory.')
        for parent,dirs,files in os.walk(base,followlinks=False):
            for d in dirs:
                p=Path(parent)/d
                if p.is_symlink() or p.relative_to(root).as_posix()!='blocks/index':raise CloneError('Unsupported blockchain database layout.')
            for f in files:
                p=Path(parent)/f;name=p.relative_to(root).as_posix();s=regular(p)
                if not allowed(name):raise CloneError('Unsupported file in the blockchain snapshot.')
                rows.append({'path':name,'bytes':s.st_size})
                if len(rows)>MAX_FILES:raise CloneError('Blockchain snapshot has too many files.')
    return validate(sorted(rows,key=lambda r:r['path']))

def validate(rows):
    if not isinstance(rows,list) or not 0<len(rows)<=MAX_FILES:raise CloneError('Invalid blockchain file inventory.')
    seen=set();total=0
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'path','bytes'} or not allowed(r['path']) or r['path'] in seen or type(r['bytes']) is not int or r['bytes']<0:raise CloneError('Invalid or repeated blockchain snapshot path.')
        seen.add(r['path']);total+=r['bytes']
    if total>MAX_TOTAL or not {'chainstate/CURRENT','blocks/index/CURRENT'}<=seen or not any(n.startswith('blocks/blk') for n in seen):raise CloneError('Incomplete or oversized blockchain snapshot.')
    return rows

def manifest_hash(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def space(root,rows):
    total=sum(r['bytes'] for r in validate(rows));free=shutil.disk_usage(root).free
    if free<total+max(512*1024**2,total//20):raise CloneError('Not enough free disk space to stage and verify the complete clone while retaining the current blockchain.')
    return total

def write_journal(stage,value):
    p=stage/'state.json';tmp=stage/'state.tmp'
    with tmp.open('x') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p);syncdir(stage)

def syncdir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def rollback(root,stage):
    # Only a helper-created stage is accepted. Never chase a caller path.
    if stage.parent!=root or not re.fullmatch(r'\.wallaby-chain-[0-9a-f]{32}',stage.name) or stage.is_symlink():raise CloneError('Invalid clone staging directory.')
    state=json.loads((stage/'state.json').read_text())
    if state.get('phase') not in ('installing','installed'):raise CloneError('No recoverable clone installation was recorded.')
    old=stage/'old';incoming=stage/'incoming'
    for name in reversed(ROOTS):
        backup=old/name
        if backup.exists():
            if (root/name).exists():os.rename(root/name,incoming/(name+'-rejected'))
            os.rename(backup,root/name)
    syncdir(root);state['phase']='rolled_back';write_journal(stage,state)

def install(root,stage):
    old=stage/'old';incoming=stage/'incoming';old.mkdir(mode=0o700)
    write_journal(stage,{'phase':'installing'})
    try:
        for name in ROOTS:
            os.rename(root/name,old/name);syncdir(root);syncdir(old)
            os.rename(incoming/name,root/name);syncdir(root);syncdir(incoming)
        write_journal(stage,{'phase':'installed'})
    except BaseException:
        rollback(root,stage);raise

def no_pending(root):
    if any(root.glob('.wallaby-chain-*')):raise CloneError('A previous clone staging directory remains. Reconcile it locally before another clone; no automatic replay or deletion was attempted.')
