"""Bounded diagnostic events. Protected logs stay in RAM until explicit safe closure.

Never pass RPC parameters, results, proposals, secrets or exception text here.
Redaction is defence in depth; callers record fixed action/category names only.
"""
import contextlib,datetime as dt,fcntl,json,os,re,secrets,stat,threading,time
from pathlib import Path
DAYS=7
DAY_BYTES=1024*1024
_lock=threading.RLock()

def redact(value):
    value=' '.join(str(value).split())
    value=re.sub(r'(?i)(?:[a-z]+\s*\()?\b(?:wsh|wpkh|pkh|tr|sh|multi|sortedmulti|raw|addr)\([^\r\n]*','[REDACTED: descriptor]',value)
    value=re.sub(r'(?i)\b(?:[xtyuvz]prv|tprv)[1-9A-HJ-NP-Za-km-z]{30,}','[REDACTED: private key]',value)
    value=re.sub(r'(?i)\b(?:[xtyuvz]pub|tpub)[1-9A-HJ-NP-Za-km-z]{30,}','[REDACTED: public key]',value)
    value=re.sub(r'\b(?:[5KL][1-9A-HJ-NP-Za-km-z]{49,51}|[9c][1-9A-HJ-NP-Za-km-z]{50,51})\b','[REDACTED: private key]',value)
    value=re.sub(r'(?i)\b(?:bc1|tb1|bcrt1)[a-z0-9]{8,90}\b','[REDACTED: Bitcoin address]',value)
    value=re.sub(r'\b[123mn2][1-9A-HJ-NP-Za-km-z]{25,61}\b','[REDACTED: Bitcoin address]',value)
    value=re.sub(r'(?i)\b[0-9a-f]{64,}\b','[REDACTED: key or transaction data]',value)
    value=re.sub(r'\bcHNidP[A-Za-z0-9+/=]*','[REDACTED: PSBT]',value)
    value=re.sub(r'__cookie__:[^\s]+','[REDACTED: credential]',value)
    value=re.sub(r'(?i)(\b(?:password|passphrase|cookie|authorization|token|secret|private[_ -]?key|seed|mnemonic)\s*[:=]\s*)(?:"[^"]*"|\S+) ',r'\1[REDACTED: credential] ',value+' ').strip()
    # Long opaque strings are not useful diagnostic text and can contain key material.
    value=re.sub(r'[A-Za-z0-9+/=_-]{80,}','[REDACTED: opaque data]',value)
    return value[:1600]

def _valid(row):
    if not isinstance(row,dict) or set(row)!={'id','at','origin','source','message'}:raise ValueError('Invalid diagnostic event.')
    if not isinstance(row['id'],str) or not re.fullmatch('[0-9a-f]{32}',row['id']) or type(row['at']) not in (int,float) or not 0<row['at']<time.time()+300:raise ValueError('Invalid diagnostic event identity.')
    if row['origin'] not in ('protected','unprotected') or not isinstance(row['source'],str) or not re.fullmatch('[A-Za-z0-9_.-]{1,64}',row['source']) or not isinstance(row['message'],str) or len(row['message'])>1600:raise ValueError('Invalid diagnostic event fields.')
    return {**row,'message':redact(row['message'])}

class DiagnosticLog:
    def __init__(self,path=None):
        if path is None:
            from protected_memory import inside,root
            from configuration import Config
            path=(root() if inside() else Config().root)/'diagnostics'
        self.path=Path(path)
    @contextlib.contextmanager
    def opened(self):
        # The protected parent is verified by its supervisor; the ordinary parent
        # is the user's existing configuration directory. Refuse symlink components.
        for parent in (self.path,*self.path.parents):
            if parent.is_symlink():raise ValueError('Diagnostic storage must not follow symbolic links.')
        self.path.mkdir(parents=True,mode=0o700,exist_ok=True)
        fd=os.open(self.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        lock=None
        try:
            info=os.fstat(fd)
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('Diagnostic directory ownership or permissions are unsafe.')
            lock=os.open('.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=fd)
            self.checked(lock)
            with _lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                try:yield fd
                finally:fcntl.flock(lock,fcntl.LOCK_UN)
        finally:
            if lock is not None:os.close(lock)
            os.close(fd)
    @staticmethod
    def checked(fd):
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('Unsafe diagnostic file.')
    def _days(self,fd):
        today=dt.datetime.now(dt.timezone.utc).date();days={(today-dt.timedelta(days=i)).isoformat() for i in range(DAYS)}
        files=[]
        for name in os.listdir(fd):
            if re.fullmatch(r'\.write-[0-9a-f]{32}',name):
                os.unlink(name,dir_fd=fd);continue # The exclusive log lock excludes an active writer.
            match=re.fullmatch(r'diagnostics-(\d{4}-\d\d-\d\d)\.log',name)
            if not match:continue
            if match[1] not in days:os.unlink(name,dir_fd=fd)
            else:files.append(name)
        return sorted(files)
    def _read(self,fd,name):
        file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            self.checked(file)
            if os.fstat(file).st_size>DAY_BYTES:raise ValueError('Diagnostic file exceeds its daily limit.')
            data=os.read(file,DAY_BYTES+1)
        finally:os.close(file)
        result=[]
        for line in data.splitlines():
            try:result.append(_valid(json.loads(line)))
            except (ValueError,TypeError,UnicodeError):continue
        return result
    def records(self):
        with self.opened() as fd:
            return sorted((row for name in self._days(fd) for row in self._read(fd,name)),key=lambda r:(r['at'],r['id']))
    def merge(self,rows):
        if not isinstance(rows,list) or len(rows)>60000:raise ValueError('Diagnostic handoff exceeds its limit.')
        rows=[_valid(row) for row in rows]
        with self.opened() as fd:
            self._days(fd);today=dt.datetime.now(dt.timezone.utc).date();groups={}
            for row in rows:
                day=dt.datetime.fromtimestamp(row['at'],dt.timezone.utc).date()
                if 0<=(today-day).days<DAYS:groups.setdefault(day.isoformat(),[]).append(row)
            for day,incoming in groups.items():
                name='diagnostics-'+day+'.log'
                try:existing=self._read(fd,name)
                except FileNotFoundError:existing=[]
                unique={r['id']:r for r in existing}
                for row in incoming:unique.setdefault(row['id'],row)
                lines=[json.dumps(row,separators=(',',':'),ensure_ascii=True).encode()+b'\n' for row in sorted(unique.values(),key=lambda r:(r['at'],r['id']))]
                size=sum(map(len,lines))
                while lines and size>DAY_BYTES:size-=len(lines.pop(0))
                temp='.write-'+secrets.token_hex(16);out=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                try:
                    with os.fdopen(out,'wb') as f:f.write(b''.join(lines));f.flush();os.fsync(f.fileno())
                    # Never replace an existing linked/unsafe log.
                    try:check=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
                    except FileNotFoundError:pass
                    else:
                        try:self.checked(check)
                        finally:os.close(check)
                    os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
                finally:
                    try:os.unlink(temp,dir_fd=fd)
                    except FileNotFoundError:pass
    def text(self):
        lines=[]
        for row in self.records():
            stamp=dt.datetime.fromtimestamp(row['at'],dt.timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')
            lines.append(f"{stamp} · {row['origin']} · {row['source']} · {row['message']}\n")
        return ''.join(lines)

def event(source,message):
    """Best effort: logging failure must never replay or misreport a wallet action."""
    try:
        from protected_memory import inside
        DiagnosticLog().merge([{'id':secrets.token_hex(16),'at':time.time(),'origin':'protected' if inside() else 'unprotected','source':source,'message':redact(message)}])
    except Exception:pass

def handoff():
    from secure_bridge import call,WorkspaceFailure
    from worker_upgrade import unsupported
    try:rows=call('diagnostics.export',timeout=15)
    except WorkspaceFailure as error:
        # Pre-Build19 workers had no diagnostic stream to preserve.
        if unsupported(error):
            state=call('service_status',timeout=8)
            version=state.get('worker_version')
            match=re.fullmatch(r'2\.0\.0~dev(\d+)',version) if isinstance(version,str) else None
            if version is None or match and int(match[1])<19:return
        raise WorkspaceFailure('log_handoff','Protected diagnostics could not be handed over. RAM was retained; retry safe closure.') from None
    if not isinstance(rows,list) or any(not isinstance(r,dict) or r.get('origin')!='protected' for r in rows):raise WorkspaceFailure('log_origin','Invalid protected diagnostic origin. RAM was retained.')
    try:DiagnosticLog().merge(rows)
    except (OSError,ValueError,TypeError):raise WorkspaceFailure('log_storage','Sanitized diagnostics could not be saved. RAM was retained; check ordinary Agent log storage before closing.') from None
