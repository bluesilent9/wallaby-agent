"""Cold local-only scan-locator rebinding after verified recovery checkpoint.

Never imports keys, descriptors or transactions. Only Core's two public chain
locator records may change; every other database record is hashed before/after.
This is not callable through the peer stream or Wallet Server.
"""
import fcntl,hashlib,io,os,sqlite3,struct,stat
from pathlib import Path
from chain_clone_files import CloneError,directory_fd
from core_history import compact_read,compact_write
KINDS={'bestblock','bestblock_nomerkle'}

def locator(value):
    if not isinstance(value,str) or len(value)>16384:raise CloneError('Invalid local wallet scan checkpoint.')
    try:
        raw=bytes.fromhex(value);f=io.BytesIO(raw);version=struct.unpack('<i',f.read(4))[0];n=compact_read(f)
        if n>101:raise ValueError()
        hashes=[f.read(32) for _ in range(n)]
        if not 0<=version<=1000000 or n>101 or any(len(h)!=32 for h in hashes) or f.read():raise ValueError()
        return raw,[h[::-1].hex() for h in hashes]
    except Exception:raise CloneError('Unsupported Core wallet chain-locator record.') from None

def other_hash(db):
    h=hashlib.sha256()
    excluded={compact_write(len(k))+k.encode() for k in KINDS}
    for key,value in db.execute('select key,value from main order by key'):
        if key in excluded:continue
        for part in (key,value):h.update(struct.pack('<Q',len(part)));h.update(part)
    return h.digest()

def modify(root,rows,undo=False):
    if not isinstance(rows,list) or len(rows)>128 or len({r.get('wallet') for r in rows if isinstance(r,dict)})!=len(rows):raise CloneError('Too many original wallet checkpoints.')
    changed=[]
    try:
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'wallet','anchor','locators','policy','private'} or not isinstance(row['wallet'],str) or row['wallet'] in ('','.','..') or '/' in row['wallet'] or '\\' in row['wallet'] or not isinstance(row['locators'],dict) or not row['locators'] or not set(row['locators'])<=KINDS:raise CloneError('Invalid locally approved wallet checkpoint identity.')
            parsed={k:locator(v) for k,v in row['locators'].items()}
            if not undo and not any(h and h[0]==row['anchor'] for raw,h in parsed.values()):raise CloneError('The saved wallet locator is not anchored at the reviewed pre-reindex tip.')
            folder=directory_fd(Path(root)/'wallets'/row['wallet']);fd=None;db=None
            try:
                fd=os.open('wallet.dat',os.O_RDWR|os.O_NOFOLLOW,dir_fd=folder);st=os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1 or st.st_size>256*1024*1024:raise CloneError('Wallet checkpoint file ownership or link count changed.')
                fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                db=sqlite3.connect('file:/proc/self/fd/'+str(fd)+'?mode=rw',uri=True)
                if db.execute('pragma integrity_check').fetchone()!=('ok',):raise CloneError('Wallet checkpoint database integrity check failed.')
                from approval_store import digest
                public=[];private=None
                for key,value in db.execute('select key,value from main'):
                    if key==b'\x05flags':
                        if len(value)!=8:raise CloneError('Unsupported original wallet capability flags.')
                        private=not bool(struct.unpack('<Q',value)[0]&(1<<32))
                    elif key.startswith(b'\x10walletdescriptor') and len(key)==49:
                        f=io.BytesIO(value);public.append(hashlib.sha256(f.read(compact_read(f))).hexdigest())
                if type(row['private']) is not bool or private is not row['private'] or digest(sorted(public))!=row['policy']:raise CloneError('Original wallet policy or signing capability changed before its cold checkpoint. No scan locator was rebound.')
                keys={k:compact_write(len(k))+k.encode() for k in parsed};before={}
                for k,key in keys.items():
                    old=db.execute('select value from main where key=?',(key,)).fetchone()
                    if old is None:raise CloneError('The wallet scan-locator schema changed; no checkpoint was rebound.')
                    before[k]=old[0].hex()
                baseline=other_hash(db)
                with db:
                    for k,(raw,_) in parsed.items():db.execute('update main set value=? where key=?',(raw,keys[k]))
                    if other_hash(db)!=baseline:raise CloneError('A wallet record outside the scan locator changed. Transaction rolled back; no keys or history were replaced.')
                db.close();db=None;os.fsync(fd);changed.append({'wallet':row['wallet'],'anchor':row['anchor'],'locators':before,'policy':row['policy'],'private':row['private']})
            finally:
                if db:db.close()
                if fd is not None:os.close(fd)
                os.close(folder)
        return changed
    except BaseException:
        if changed and not undo:modify(root,list(reversed(changed)),undo=True)
        raise
