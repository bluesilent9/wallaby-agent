"""Encrypted optical recovery packages. All paths belong to the protected RAM workspace."""
import hashlib,json,mmap,os,re,stat,subprocess,threading,time,zipfile,shutil
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'WALLABY-DISC-1\n'

def encrypt_file(source,target,password):
    if not isinstance(password,str) or len(password)<12:raise ValueError('Use a backup passphrase of at least 12 characters.')
    salt=os.urandom(16);nonce=os.urandom(12);header=MAGIC+salt+nonce
    key=Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password.encode());enc=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor();enc.authenticate_additional_data(header)
    with open(source,'rb') as inp,open(target,'wb') as out:
        os.chmod(target,0o600);out.write(header)
        while chunk:=inp.read(1024*1024):out.write(enc.update(chunk))
        out.write(enc.finalize());out.write(enc.tag);out.flush()
    key=None;password=None

def decrypt_file(source,target,password):
    size=Path(source).stat().st_size
    with open(source,'rb') as inp:
        header=inp.read(len(MAGIC)+28)
        if not header.startswith(MAGIC) or size<len(header)+16:raise ValueError('Invalid recovery package.')
        salt=header[len(MAGIC):len(MAGIC)+16];nonce=header[-12:];inp.seek(-16,2);tag=inp.read(16);inp.seek(len(header));remain=size-len(header)-16
        key=Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password.encode());dec=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor();dec.authenticate_additional_data(header)
        try:
            with open(target,'wb') as out:
                os.chmod(target,0o600)
                while remain:
                    chunk=inp.read(min(remain,1024*1024))
                    if not chunk:raise ValueError('Truncated recovery package.')
                    remain-=len(chunk);out.write(dec.update(chunk))
                out.write(dec.finalize())
        except Exception:Path(target).unlink(missing_ok=True);raise ValueError('Backup passphrase or authentication check failed.') from None
    key=None;password=None

def require_space(root,amount):
    if shutil.disk_usage(root).free<amount:raise ValueError('Protected RAM has insufficient free space for this operation. Finish or unload other work first; no disk fallback is allowed.')
    from protected_memory import required
    if required():memory_budget(amount+128*1024*1024)

def memory_budget(amount):
    from diagnostics import LocalActionFailure
    try:
        group=next(line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        folder=Path('/sys/fs/cgroup')/group.lstrip('/');raw=(folder/'memory.max').read_text().strip();current=int((folder/'memory.current').read_text())
        limit=None if raw=='max' else int(raw)
    except (OSError,ValueError,StopIteration):raise LocalActionFailure('memory_budget_unavailable','The protected memory budget could not be checked. Disc preparation was not started; keep this workspace open.') from None
    from activity_log import event
    event('disc.memory','Preparation budget · current_bytes='+str(current)+' · limit_bytes='+str(limit)+' · reserve_bytes='+str(amount))
    if limit is not None and current+amount>limit:raise LocalActionFailure('protected_memory_pressure','Protected memory is too full to prepare this backup safely. Keep this workspace open, finish or unload other RAM work, and retry after memory is available. No disc write was started and no disk fallback was used.')

def pack(root,wallets,recovery,password):
    if recovery.get('version')==2:
        from archive_format import validate
        validate(recovery)
        if set(wallets)!={e['id'] for e in recovery['entries']}:raise ValueError('Archive files differ from the reviewed wallet set.')
    if sum(Path(v).stat().st_size for v in wallets.values())>480*1024*1024:raise ValueError('Selected wallets exceed the bounded RAM archive size. Choose fewer wallets for this disc.')
    root=Path(root);root.mkdir(mode=0o700,parents=True,exist_ok=True);require_space(root,2*sum(Path(v).stat().st_size for v in wallets.values())+256*1024*1024);disc=root/'disc';disc.mkdir(mode=0o700,parents=True,exist_ok=True);plain=root/'recovery.zip'
    with zipfile.ZipFile(plain,'w',zipfile.ZIP_STORED) as z:
        z.writestr('policy.json',json.dumps(recovery,sort_keys=True,indent=2))
        for ident,path in wallets.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or Path(path).stat().st_size>256*1024*1024:raise ValueError('Invalid recovery wallet entry.')
            z.write(path,'wallets/'+ident+'.dat')
    try:encrypt_file(plain,disc/'recovery.wallaby',password)
    finally:plain.unlink(missing_ok=True)
    with (disc/'recovery.wallaby').open('rb') as stream:archive_id=hashlib.file_digest(stream,'sha256').hexdigest()
    (disc/'ARCHIVE-ID.txt').write_text('Wallaby archive '+archive_id+'\nLabel every physical copy with this archive ID. Compare it in Disc Operations before confirming destruction.\n')
    (disc/'README.txt').write_text('Wallaby encrypted recovery package v1\nAES-256-GCM; scrypt N=131072,r=8,p=1.\nContains encrypted Core signing wallets plus the complete public receive/change policy and authenticated cosigner contributions.\nKeep your backup and Core wallet passphrases separately.\nUse the accompanying recovery.py only in a protected volatile environment.\n')
    (disc/'REDUNDANCY.txt').write_text('Wallaby repeats this exact encrypted recovery package in independently checksummed, sector-aligned raw-track slots after this small ISO filesystem. Disc Operations scans copies and skips unreadable/damaged ones. No giant RAM image or directory listing is needed. The filesystem copy also remains readable by standard tools.\n')
    # Independent, inspectable decryption utility; it refuses an ordinary disk output.
    (disc/'recovery.py').write_text(RECOVERY_TOOL)
    (disc/'redundancy.py').write_text(Path(__file__).with_name('disc_archive.py').read_text())
    return disc

RECOVERY_TOOL='''#!/usr/bin/python3
"""Decrypt inside a non-swapping RAM filesystem; never silently use an HDD/SSD."""
import getpass,os,resource,ctypes,json,subprocess
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
lib=ctypes.CDLL(None,use_errno=True)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
if lib.prctl(4,0,0,0,0):raise SystemExit('Cannot disable process dumps.')
if lib.mlockall(3):raise SystemExit('Cannot lock memory. Use a protected environment with sufficient locked-memory allowance.')
out=Path(input('Existing protected RAM output directory: ')).resolve(strict=True)
mounts=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
ok=False
for m in sorted(mounts,key=lambda m:len(m[4]),reverse=True):
 if out.is_relative_to(m[4]):
  i=m.index('-');ok=m[i+1]=='ramfs' or m[i+1]=='tmpfs' and 'noswap' in (m[5]+','+m[i+3]).split(',');break
if not ok:raise SystemExit('Output must be ramfs or tmpfs mounted noswap.')
if out.stat().st_uid!=os.getuid() or out.stat().st_mode&0o077:raise SystemExit('Use an owner-only protected RAM directory.')
ancestors=set();pid=os.getpid()
for _ in range(32):
 if pid<=1:break
 ancestors.add(pid);pid=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[1])
try:
 rows=json.loads(subprocess.run(['/usr/bin/busctl','--system','--json=short','call','org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager','ListInhibitors'],capture_output=True,check=True).stdout)['data'][0]
 inhibited=any(set(r[0].split(':'))>={'sleep','shutdown'} and r[3]=='block' and r[5] in ancestors for r in rows)
except Exception:inhibited=False
if not inhibited:raise SystemExit('Run this tool under systemd-inhibit --what=sleep:shutdown --mode=block. No decryption attempted.')
crash=Path('/sys/kernel/kexec_crash_loaded')
if crash.exists() and crash.read_text().strip()!='0':raise SystemExit('Disable kernel crash dumping in this trusted environment first.')
raw=Path(__file__).with_name('recovery.wallaby').read_bytes();magic=b'WALLABY-DISC-1\\n';h=raw[:len(magic)+28]
if not h.startswith(magic):raise SystemExit('Invalid package')
password=getpass.getpass('Backup passphrase: ');key=Scrypt(salt=h[len(magic):len(magic)+16],length=32,n=2**17,r=8,p=1).derive(password.encode())
d=Cipher(algorithms.AES(key),modes.GCM(h[-12:],raw[-16:])).decryptor();d.authenticate_additional_data(h)
try:plain=d.update(raw[len(h):-16])+d.finalize()
except Exception:raise SystemExit('Wrong passphrase or damaged package')
fd=os.open(out/'recovery.zip',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f:f.write(plain)
print('Authenticated recovery.zip written in protected RAM. It contains sensitive material; retain sleep inhibition and extract only in protected RAM.')
'''

def parse_speeds(text,kind):
    from decimal import Decimal
    values={Decimal(m[1]) for m in re.finditer(r'^Write speed[^\n]*?([0-9]+(?:\.[0-9]+)?)x'+kind+r'\b',text,re.M|re.I) if 0<Decimal(m[1])<=64}
    return [format(x.normalize(),'f') for x in sorted(values)]

def speed_value(speed):
    if speed=='slowest':return '-1'
    if not isinstance(speed,str) or not re.fullmatch(r'(?:[1-9][0-9]?(?:\.[0-9]{1,2})?|0\.[0-9]{1,2})',speed):raise ValueError('Choose slowest supported speed or a reported numeric speed.')
    from decimal import Decimal
    if not 0<Decimal(speed)<=64:raise ValueError('Unsupported optical write speed.')
    return speed

def disc_status(device):
    """Read-only medium classification; never selects an output drive or writes."""
    if not shutil.which('xorriso'):raise ValueError('Install xorriso to check the optical disc.')
    if not isinstance(device,str) or not re.fullmatch(r'/dev/sr[0-9]{1,2}',device):raise ValueError('Select a local optical drive.')
    st=os.stat(device,follow_symlinks=False)
    if not stat.S_ISBLK(st.st_mode) or os.major(st.st_rdev)!=11:raise ValueError('Device is not a Linux optical drive.')
    result=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-indev',device,'-toc','-end'],capture_output=True,timeout=30)
    output=(result.stdout+result.stderr).decode(errors='replace')
    current=re.search(r'Media current\s*:\s*([^\r\n]+)',output)
    medium=current[1].strip()[:100] if current else ''
    status=re.search(r'Media status\s*:\s*([^\r\n]+)',output)
    status=status[1].strip().lower() if status else ''
    if result.returncode==0 and re.search(r'\bis blank\b',status):
        kind='blank';message='Blank disc — the drive reports no recorded session. It can be selected for a new burn if its type and capacity are supported.'
    elif result.returncode==0 and re.search(r'\b(is written|is closed|is appendable|is full|contains data)\b',status):
        kind='written';message='Already written — do not use this disc as a fresh blank. This status does not verify its files or recovery backup.'
    elif re.search(r'no (?:media|medium)(?: present| found)?|medium not present',output,re.I):
        kind='no_disc';message='No disc detected. Insert the disc and check again.'
    else:
        kind='unknown';message='Disc status could not be determined. Check the inserted disc and drive; no write was started.'
    from activity_log import event
    event('disc.status','Read-only check · status='+kind+' · exit_code='+str(result.returncode))
    return {'status':kind,'message':message,'media':medium,'read_only':True}

def media(device):
    if not shutil.which('xorriso'):raise ValueError('Disc Operations requires the optional xorriso package. Install it with: sudo apt install xorriso. SSH tunnels and node reporting do not require it.')
    if not isinstance(device,str) or not re.fullmatch(r'/dev/sr[0-9]{1,2}',device):raise ValueError('Select a local optical drive.')
    st=os.stat(device,follow_symlinks=False)
    if not stat.S_ISBLK(st.st_mode) or os.major(st.st_rdev)!=11:raise ValueError('Device is not a Linux optical drive.')
    r=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-indev',device,'-toc','-end'],capture_output=True,timeout=30)
    output=(r.stdout+r.stderr).decode(errors='replace')
    if r.returncode or not re.search(r'Media current\s*:\s*(?:BD-R\b|DVD-R\b)',output) or re.search(r'Media current\s*:.*(?:RW|RE\b)',output) or not re.search(r'Media status\s*:\s*is blank',output):raise ValueError('Insert a blank, write-once DVD-R or BD-R M-Disc in a compatible burner. Used, rewritable and unknown media are refused.')
    blocks=re.search(r'Media blocks\s*:.*?([0-9]+) writable',output)
    capacity=max(0,int(blocks[1])*2048-2*1024*1024) if blocks else None
    speeds=[]
    try:
        query=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-outdev',device,'-list_speeds','-end'],capture_output=True,timeout=30)
        text=(query.stdout+query.stderr).decode(errors='replace')
        if query.returncode==0:speeds=parse_speeds(text,'BD' if 'BD-R' in output else 'DVD')
    except (OSError,subprocess.TimeoutExpired):pass
    return {'speeds':speeds,'device':device,'capacity_bytes':capacity,'estimated_1x_seconds':round(capacity/(4500000 if 'BD-R' in output else 1385000)) if capacity else None,'write_once':True,'blank':True,'message':'Blank write-once media detected. Confirm that the disc and drive support M-Disc; software cannot authenticate the physical media branding.'}

def image(disc,path):
    r=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-as','mkisofs','-V','WALLABY_RECOVERY','-o',str(path),str(disc)],capture_output=True,timeout=300)
    if r.returncode:raise ValueError('Could not prepare the disc image in protected RAM.')
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def optical_readback(device,size,expected,progress=None):
    """Read the full raw track through libburn, independent of stale block size."""
    import collections,selectors
    from activity_log import event,redact
    from diagnostics import LocalActionFailure
    if type(size) is not int or size<=0 or size%2048:raise ValueError('Invalid complete optical track length.')
    command=['/usr/bin/xorriso','-abort_on','FAILURE','-return_with','FAILURE','32','-indev',device,'-check_media','use=indev','what=disc','min_lba=0','max_lba='+str(size//2048-1),'data_to=-','patch_lba0=off','retry=on','bad_limit=partial','event=FAILURE','time_limit=172800','item_limit=1024','chunk_size=1m','async_chunks=0','--','-end']
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    tail=collections.deque(maxlen=8)
    def drain():
        try:
            while line:=process.stderr.readline(4096):tail.append(line.decode(errors='replace').strip()[:600])
        finally:process.stderr.close()
    reader=threading.Thread(target=drain,daemon=True);reader.start();result=hashlib.sha256();count=0
    event('disc.readback','Drive-level read started · expected_bytes='+str(size)+' · Linux block capacity is not used')
    try:
        os.set_blocking(process.stdout.fileno(),False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while True:
                if not selector.select(180):raise LocalActionFailure('disc_readback_unavailable','The drive stopped reporting readable data. Keep this workspace open and retry verification of the same disc; no burn was started.')
                try:data=os.read(process.stdout.fileno(),1024*1024)
                except BlockingIOError:continue
                if not data:break
                count+=len(data)
                if count>size:raise LocalActionFailure('disc_readback_length','The drive returned more data than the original track. No verification result was accepted.')
                result.update(data)
                if progress:progress(count)
        code=process.wait(timeout=60);reader.join(2)
        event('disc.readback','Drive-level read ended · read_bytes='+str(count)+' · expected_bytes='+str(size)+' · exit_code='+str(code))
        if code or count!=size:
            event('disc.readback','Reader detail · '+redact(' | '.join(tail))[-1600:])
            raise LocalActionFailure('disc_readback_unavailable','Complete drive-level verification could not finish: read '+str(count)+' of '+str(size)+' bytes; reader exit '+str(code)+'. Keep this workspace open. The disc has not been marked verified.')
        if result.hexdigest()!=expected:raise LocalActionFailure('disc_readback_mismatch','The complete disc checksum differs from the original protected RAM image. The disc has not passed verification.')
        event('disc.readback','Full-track checksum matched · transport=drive · total_bytes='+str(size))
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        process.stdout.close();reader.join(2)

def readback(device,size,expected,progress=None):
    """Compare the entire track using one aligned buffer; tolerate initial readiness lag."""
    if stat.S_ISBLK(os.stat(device,follow_symlinks=False).st_mode):
        import fcntl,struct
        from activity_log import event
        fd=None
        try:
            fd=os.open(device,os.O_RDONLY|os.O_NONBLOCK)
            capacity=struct.unpack('<Q',fcntl.ioctl(fd,0x80081272,bytes(8)))[0]
            event('disc.readback','Capacity observation · kernel_bytes='+str(capacity)+' · expected_bytes='+str(size)+' · verification uses drive-level reads')
        except OSError as error:event('disc.readback','Kernel capacity unavailable · errno='+str(error.errno)+' · verification uses drive-level reads')
        finally:
            if fd is not None:os.close(fd)
        return optical_readback(device,size,expected,progress)
    from diagnostics import LocalActionFailure
    from activity_log import event
    result=hashlib.sha256();offset=0;deadline=time.monotonic()+30;attempt=0
    with mmap.mmap(-1,1024*1024) as buffer:
        while offset<size:
            fd=None
            try:
                fd=os.open(device,os.O_RDONLY|os.O_DIRECT);os.lseek(fd,offset,os.SEEK_SET)
                while offset<size:
                    count=min(size-offset,len(buffer));view=memoryview(buffer)[:count]
                    try:
                        n=os.readv(fd,[view])
                        if n>0 and n%2048==0:result.update(view[:n])
                    finally:view.release()
                    if n<=0 or n%2048:
                        event('disc.readback','Short read · offset_bytes='+str(offset)+' · requested_bytes='+str(count)+' · returned_bytes='+str(n))
                        raise OSError(5,'Disc returned no complete sector')
                    offset+=n
                    if progress:progress(offset)
                    if n<count:event('disc.readback','Partial read accepted · offset_bytes='+str(offset)+' · returned_bytes='+str(n))
            except OSError as error:
                attempt+=1
                event('disc.readback','Read unavailable · offset_bytes='+str(offset)+' · errno='+str(error.errno)+' · attempt='+str(attempt))
                # Only initial drive readiness is retried automatically. A later
                # error keeps its exact offset and requires a deliberate retry.
                if offset or time.monotonic()>=deadline:
                    raise LocalActionFailure('disc_readback_unavailable','Disc read-back stopped at byte '+str(offset)+' of '+str(size)+'. No complete verification was recorded. Reinsert the same disc and choose Verify written disc; this will not burn again.') from None
            finally:
                if fd is not None:os.close(fd)
            if offset<size:time.sleep(min(2,max(0,deadline-time.monotonic())))
    if result.hexdigest()!=expected:
        event('disc.readback','Full-track checksum mismatch · total_bytes='+str(size))
        raise LocalActionFailure('disc_readback_mismatch','The complete disc checksum differs from the protected RAM image. Keep this workspace open. The disc has not passed verification.')
    event('disc.readback','Full-track checksum matched · total_bytes='+str(size))

def writer_bytes(line,total):
    """Drive-reported written MB, not bytes merely accepted by its input pipe."""
    from decimal import Decimal
    message=re.sub(r'^\s*xorriso\s*:\s*UPDATE\s*:\s*','',line)
    match=re.match(r'\s*(?:Track\s+\d+:\s*)?([0-9]+(?:\.[0-9]+)?)\s+of\s+[0-9]+(?:\.[0-9]+)?\s+MB\s+written\b',message)
    return min(total,int(Decimal(match[1])*1024*1024)) if match else None

class StageProgress:
    """Constant-size throughput estimate from actual progress in this stage."""
    def __init__(self,job,field,stage):
        self.job=job;self.field=field;self.started=self.tick=time.monotonic();self.count=0;self.rate=None
        job['_eta_seen_bytes']=0;job[field]=0
        job.update(eta_stage=stage,eta_seconds=None,eta_updated_at=None,eta_last_progress_at=None)
    def __call__(self,count):
        if count<self.count:return
        now=time.monotonic();self.job[self.field]=count
        if count>self.job.get('_eta_seen_bytes',0):self.job['eta_last_progress_at']=time.time()
        self.job['_eta_seen_bytes']=count
        elapsed=now-self.tick
        if elapsed>=1:
            rate=(count-self.count)/elapsed
            if rate>0:self.rate=rate if self.rate is None else .25*rate+.75*self.rate
            self.tick=now;self.count=count
            if now-self.started>=5 and self.rate:
                remaining=max(0,self.job.get('total_bytes',0)-count)
                self.job.update(eta_seconds=remaining/self.rate,eta_updated_at=time.time())

class WriterProgress(StageProgress):
    """Public counters only; accepting pipe bytes never advances disc percent."""
    def __init__(self,job):
        job['_eta_seen_bytes']=0
        super().__init__(job,'written_bytes','burning')
    def __call__(self,count):super().__call__(count);self.job.update(writer_last_progress_at=time.time())
    def writer_report(self,**facts):self.job.update(facts)

def write_stream(device,source,total,progress,speed='slowest'):
    selected=speed_value(speed)
    import selectors,collections
    process=subprocess.Popen(['/usr/bin/xorriso','-abort_on','FAILURE','-as','cdrecord','-v','-sao','speed='+selected,'fs=16m','dev='+device,'tsize='+str(total//2048)+'s','-data','-'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    from activity_log import event
    observer=getattr(progress,'writer_report',lambda **facts:None)
    observer(writer_started_at=time.time(),writer_input_bytes=0,writer_input_complete=False,writer_last_progress_at=None,writer_last_output_at=None,writer_status='starting')
    event('disc.writer','Writer launched · total_bytes='+str(total))
    tail=collections.deque(maxlen=12);reported=0;logged_bucket=-1
    def read_status():
        nonlocal reported,logged_bucket
        pending=b''
        try:
            while data:=os.read(process.stderr.fileno(),4096):
                pending=(pending+data).replace(b'\r',b'\n');lines=pending.split(b'\n');pending=lines.pop()[-4096:]
                for raw in lines:
                    line=raw.decode(errors='replace')[:600];tail.append(line)
                    observer(writer_last_output_at=time.time())
                    if 'Beginning to write data track' in line:observer(writer_status='writing')
                    if 'Closing track/session' in line:observer(writer_status='closing')
                    amount=writer_bytes(line,total)
                    if amount is not None and amount>reported:
                        reported=amount;progress(min(amount,max(0,total-1)))
                        bucket=min(10,int(10*amount/max(1,total)))
                        if bucket>logged_bucket:
                            logged_bucket=bucket;event('disc.writer','Progress report recognised · written_bytes='+str(amount)+' · total_bytes='+str(total))
            if pending:tail.append(pending.decode(errors='replace')[:600])
        finally:process.stderr.close()
    reader=threading.Thread(target=read_status,daemon=True);reader.start()
    digest=hashlib.sha256();written=0;deadline=time.monotonic()+48*3600
    try:
        os.set_blocking(process.stdin.fileno(),False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin,selectors.EVENT_WRITE)
            for chunk in source:
                view=memoryview(chunk)
                try:
                    while view:
                        if process.poll() is not None:raise ValueError('The optical writer exited before accepting the complete image.')
                        if time.monotonic()>deadline or not selector.select(120):raise ValueError('The optical writer stopped accepting data. The disc is incomplete; use a fresh blank disc after checking the drive.')
                        try:count=os.write(process.stdin.fileno(),view)
                        except BlockingIOError:continue
                        if count<=0:raise ValueError('The optical writer stopped.')
                        digest.update(view[:count]);written+=count;observer(writer_input_bytes=written);view=view[count:]
                finally:view.release()
        process.stdin.close();observer(writer_input_complete=True)
        event('disc.writer','All image bytes handed to writer; awaiting process completion · input_bytes='+str(written))
        if written!=total or process.wait(timeout=1800)!=0:raise ValueError('Optical writing failed or is uncertain. Keep the RAM session open and use a fresh blank disc.')
        reader.join(2);progress(total);observer(writer_status='finished')
        event('disc.writer','Writer exited successfully; physical read-back still required')
        return digest.hexdigest()
    except Exception:
        if process.poll() is None:process.terminate();process.wait(timeout=30)
        reader.join(2)
        from activity_log import event,redact
        event('disc.writer','Writer failed · exit_code='+str(process.returncode)+' · '+redact(' | '.join(tail))[-1100:])
        raise
    finally:
        if not process.stdin.closed:process.stdin.close()

class Burner:
    def __init__(self,root,on_complete):self.root=Path(root);self.root.mkdir(mode=0o700,parents=True,exist_ok=True);self.on_complete=on_complete;self.job=None;self.lock=threading.Lock();self.pending=[];self.thread=None;self.selected=None;self.replacement_resolver=None;self.completed_sets=[];self.outcomes=[]
    def state(self):
        if self.job and self.job['phase']=='complete' and time.time()-self.job['finished']>5:
            self.job=None
            if self.pending:self.authorise(*self.pending.pop(0))
        result={k:v for k,v in (self.job or {}).items() if k not in ('recovery','wallets') and not k.startswith('_')}
        rows=list(self.job.get('_members') or [(self.job['id'],self.job['wallets'],self.job['recovery'])]) if self.job else []
        rows+=self.pending
        if result.get('writer_started_at'):
            result['writer_elapsed_seconds']=max(0,int(time.time()-result['writer_started_at']))
        if result.get('writer_last_progress_at'):
            result['writer_progress_age_seconds']=max(0,int(time.time()-result['writer_last_progress_at']))
        if result.get('phase')==result.get('eta_stage'):
            age=max(0,time.time()-(result.get('eta_last_progress_at') or time.time()))
            result['eta_waiting_for_progress']=age>=30
            result['estimated_remaining_seconds']=max(0,int(__import__('math').ceil(result['eta_seconds']-max(0,time.time()-result['eta_updated_at'])))) if result.get('eta_seconds') is not None else None
        result['completed_sets']=list(self.completed_sets)
        result['outcomes']=list(self.outcomes)
        result['queue']=[]
        for i,w,r in rows:
            row={'id':i,'name':r.get('display_name',r.get('name',r.get('proposal',{}).get('name','Wallet'))),'policy_hash':r['policy_hash'],'selected':i in (self.selected if self.selected is not None else [self.job['id']] if self.job else [])}
            role=next((role for role in r.get('proposal',{}).get('cosigners',[]) if hashlib.sha256(role['id'].encode()).hexdigest()==r.get('physical_cosigner_file')),None)
            if role:row.update(signer_name=role['name'],signer_id=role['id'])
            result['queue'].append(row)
        return result
    def outcome(self,job,kind):
        import secrets
        row={'id':secrets.token_hex(12),'job_id':job['id'],'disc':job.get('discs_verified',0)+(0 if kind in ('verified','completion_failed') else 1),'kind':kind}
        self.outcomes.append(row);self.outcomes=self.outcomes[-32:]
        from activity_log import event
        event('disc.result','outcome='+kind+' · disc='+str(row['disc'])+' · job='+job['id'][:12])
    def stage(self,job,phase,**values):
        job.update(phase=phase,**values)
        from activity_log import event
        event('disc.stage','stage='+phase+' · disc='+str(job.get('discs_verified',0)+1)+' · job='+job['id'][:12])
    def authorise(self,job_id,wallets,recovery):
        if self.job:raise ValueError('Finish the current disc session first.')
        self.selected=None
        self.job={'id':job_id,'phase':'authorised','policy_hash':recovery['policy_hash'],'wallets':wallets,'recovery':recovery,'disc_count':1,'discs_verified':0,'speed':'slowest','message':'Authorised locally. Choose the number of discs and write speed. Defaults: one disc, slowest supported speed.'}
    def queue(self,job_id,wallets,recovery):
        if self.job:self.pending.append((job_id,wallets,recovery))
        else:self.authorise(job_id,wallets,recovery)
    def select(self,ids,job_id=None):
        if job_id is not None and (not self.job or self.job['id']!=job_id):raise ValueError('The disc job changed. Review its wallet selection again before burning.')
        if not self.job or self.job['phase']!='authorised' or self.job.get('_prepared'):raise ValueError('Select wallets before preparing the first disc.')
        available={self.job['id']}|{i for i,w,r in self.pending}
        if not isinstance(ids,list) or not 1<=len(ids)<=15 or len(set(ids))!=len(ids) or not set(ids)<=available:raise ValueError('Choose 1 to 15 approved archive rows.')
        if not set(self.job.get('_required_members',[]))<=set(ids):raise ValueError('Every wallet from the original disc must remain selected for this replacement.')
        self.selected=list(ids);return {'ok':True}
    def combine(self):
        required=self.job.get('_required_members',[])
        if required and not set(required)<=set(self.selected or []):raise ValueError('Every wallet from the original disc must remain selected for this replacement.')
        if self.job.get('_members'):return
        if self.selected is None and self.job['recovery'].get('kind')=='node_wallet':self.selected=[self.job['id']]
        if self.job.get('_prepared') or self.selected is None:return
        rows=[(self.job['id'],self.job['wallets'],self.job['recovery'])]+self.pending
        chosen=[v for v in rows if v[0] in self.selected]
        from archive_format import bundle
        replacements=self.replacement_resolver(chosen) if self.replacement_resolver else []
        wallets,recovery=bundle(chosen,replacements)
        self.pending=[v for v in rows if v[0] not in self.selected]
        self.job=None;self.authorise(chosen[0][0],wallets,recovery);self.job['_members']=tuple(chosen);self.job['_required_members']=required;self.selected=[v[0] for v in chosen]
    def cancel_members(self,ids):
        if self.thread and self.thread.is_alive():raise ValueError('Wait for optical writing and verification to finish before cancelling archive members.')
        self.pending=[r for r in self.pending if r[0] not in ids]
        if not self.job:return
        members=self.job.get('_members') or [(self.job['id'],self.job['wallets'],self.job['recovery'])]
        if not any(r[0] in ids for r in members):return
        keep=[r for r in members if r[0] not in ids];directory=self.root/self.job['id']
        if directory.exists():shutil.rmtree(directory)
        self.job=None;self.selected=None
        waiting=keep+self.pending;self.pending=[]
        for r in waiting:self.queue(*r)
    def removable(self,key):
        if self.thread and self.thread.is_alive():return False
        if not self.job:return False
        members=self.job.get('_members') or [(self.job['id'],self.job['wallets'],self.job['recovery'])]
        if key in {r[0] for r in members}:
            return self.job['phase']=='authorised' and not self.job.get('_prepared') and not self.job.get('discs_verified') and not self.job.get('_required_members')
        return any(r[0]==key for r in self.pending)
    def verify_cancellation(self,job):
        with self.lock:
            if job is not self.job or self.thread and self.thread.is_alive() or not job.get('_write_started') or not job.get('_layout') or not job.get('_device'):raise ValueError('Wait for the writer to finish; this cancelled medium cannot be checked automatically yet.')
            job['_cancel_pending']=True;job.update(phase='verifying',message='Checking the cancelled medium without writing anything. Keep the original disc inserted.')
            def check():
                try:
                    from disc_archive import chunks
                    directory=self.root/job['id'];checksum=hashlib.sha256()
                    for part in chunks(directory/'disc.iso',directory/'disc/recovery.wallaby',job['_layout']):checksum.update(part)
                    readback(job['_device'],job['_layout']['total_bytes'],checksum.hexdigest(),StageProgress(job,'verified_bytes','verifying'));job['_verification_succeeded']=True
                except Exception:job['_verification_succeeded']=False
                finally:job['_verification_finished']=True;job.update(phase='cancel_cleanup',message='Cancelled-disc verification attempt finished. Complete the local cleanup checklist on Authorise.')
            self.thread=threading.Thread(target=check,daemon=True);self.thread.start()
            return {'message':'Read-only verification started. No additional disc is being written.'}
    def finish_verified(self,job,sha,disc_count):
        # Verify membership against the prepared bundle before any receipt can
        # acknowledge a pending wallet that was never put on this disc.
        members=job.get('_members') or [(job['id'],job['wallets'],job['recovery'])]
        if job.get('_members'):
            from archive_format import bundle
            wallets,recovery=bundle(members,job['recovery'].get('replaces',[]))
            if wallets!=job['wallets'] or recovery!=job['recovery']:raise ValueError('Prepared disc members differ from the encrypted recovery bundle. Completion was withheld.')
        job['discs_verified']+=1;self.outcome(job,'verified');job.setdefault('verified_discs',[]).append({'disc':job['discs_verified'],'sha256':sha,'bytes':job['_layout']['total_bytes']})
        if job.get('_cancel_pending'):
            job.update(phase='cancel_cleanup',message='Cancellation received. The current burn and read-back finished. Review disc cleanup on Authorise; no additional copy will be written.');return
        if job['discs_verified']<disc_count:
            job.update(phase='awaiting_disc',message='Disc '+str(job['discs_verified'])+' verified. Remove it, insert a fresh blank disc, then explicitly continue. The remaining recovery material stays in protected RAM.');return
        job['phase']='completing'
        for member in job.get('_members') or [(job['id'],None,None)]:self.on_complete(member[0],sha)
        self.completed_sets.append({'archive_id':job.get('archive_id'),'discs_verified':job['discs_verified'],'image_sha256':sha,'wallet_names':[r.get('display_name',r.get('name',r.get('proposal',{}).get('name','Wallet'))) for i,w,r in job.get('_members') or [(job['id'],None,job['recovery'])]]});self.completed_sets=self.completed_sets[-32:]
        import shutil
        shutil.rmtree(self.root/job['id']);job.update(phase='complete',message='Success! All '+str(disc_count)+' requested disc(s) passed complete direct read-back verification.',finished=time.time())
    def verify_written(self,job_id):
        with self.lock:
            job=self.job
            if not job or job['id']!=job_id or job['phase']!='uncertain' or job.get('failed_stage')!='verifying' or job.get('_cancel_pending') or self.thread and self.thread.is_alive():raise ValueError('Only an idle failed verification can be retried. No write was started.')
            if not job.get('_image_sha256') or not job.get('_layout') or not job.get('_device'):raise ValueError('The original written image is unavailable. No verification claim was made.')
            job.update(phase='verifying',verified_bytes=0,message='Checking the same written disc against its original RAM image. No disc is being written.')
            def check():
                try:
                    readback(job['_device'],job['_layout']['total_bytes'],job['_image_sha256'],StageProgress(job,'verified_bytes','verifying'))
                    job['_verification_succeeded']=True
                    self.finish_verified(job,job['_image_sha256'],job['disc_count'])
                except Exception as error:
                    from activity_log import event
                    from diagnostics import action_code,action_detail
                    event('disc.failure','Read-only retry · '+action_code(error)+' · '+action_detail(error))
                    complete=job.get('discs_verified',0)>=job['disc_count']
                    self.outcome(job,'completion_failed' if complete else 'verification_interrupted' if getattr(error,'code',None)=='disc_readback_unavailable' else 'verification_failed')
                    job.update(phase='completion_uncertain' if complete else 'uncertain',failed_stage='completing' if complete else 'verifying',message=str(error) if isinstance(error,ValueError) else 'Verification stopped. Keep the workspace open; no disc was written.')
                finally:job['_verification_finished']=True
            job['_verification_finished']=False
            self.thread=threading.Thread(target=check,daemon=True);self.thread.start()
            return {'message':'Read-only verification started for the original written disc. No additional burn was started.'}
    def validate_options(self,device,confirmed,disc_count=1,speed='slowest'):
        if self.job and self.job.get('_cancel_pending'):raise ValueError('This disc set was cancelled. Review its cleanup on Authorise; no further copy will be burned.')
        if not self.job or self.job['phase'] not in ('authorised','awaiting_disc','error','uncertain') or confirmed is not True:raise ValueError('Authorise and confirm a fresh blank M-Disc before writing.')
        if type(disc_count) is not int or not 1<=disc_count<=99:raise ValueError('Choose between 1 and 99 separate discs.')
        speed_value(speed)
        if self.job.get('_options') and (disc_count,speed)!=self.job['_options']:raise ValueError('Disc count and speed are fixed for this authorised set.')
        details=media(device)
        if speed!='slowest' and (not details['speeds'] or speed not in details['speeds']):raise ValueError('That speed is not reported for the current drive and disc. Refresh media details or choose slowest supported.')
        return details
    def start(self,device,confirmed,password=None,disc_count=1,speed='slowest'):
        with self.lock:
            self.validate_options(device,confirmed,disc_count,speed)
            self.combine()
            job=self.job;job['_options']=(disc_count,speed);job.update(disc_count=disc_count,speed=speed,phase='preparing',preparation_percent=0,preparation_detail='Encrypting the approved recovery package',message='Preparing disc '+str(job['discs_verified']+1)+' of '+str(disc_count)+' in protected RAM.')
            def work():
                nonlocal password
                written=False;all_verified=False;burn_finished=False;verification_started=False
                try:
                    directory=self.root/job['id'];directory.mkdir(mode=0o700,exist_ok=True);disc=directory/'disc';iso=directory/'disc.iso'
                    if not job.get('_prepared'):
                        disc=pack(directory,job['wallets'],job['recovery'],password);password=None;job.update(preparation_percent=25,preparation_detail='Creating the recovery filesystem');image(disc,iso);job.update(preparation_percent=50,preparation_detail='Checking the encrypted package');job['_prepared']=True
                        with (disc/'recovery.wallaby').open('rb') as stream:job['archive_id']=hashlib.file_digest(stream,'sha256').hexdigest()
                    password=None;job.update(preparation_percent=75,preparation_detail='Checking drive, medium and recovery layout')
                    details=media(device)
                    if speed!='slowest' and speed not in details['speeds']:raise ValueError('The inserted medium no longer supports the chosen speed. No write was started.')
                    capacity=details['capacity_bytes']
                    if capacity is None:raise ValueError('The drive did not report writable capacity. No write was started.')
                    from disc_archive import plan,chunks
                    layout=plan(iso,disc/'recovery.wallaby',capacity)
                    job['preparation_percent']=100
                    self.stage(job,'burning',copies=layout['copies'],total_bytes=layout['total_bytes'],written_bytes=0,verified_bytes=0,message='Burning disc '+str(job['discs_verified']+1)+' of '+str(disc_count)+' with '+str(layout['copies'])+' repeated recovery copies. Speed: '+('slowest supported' if speed=='slowest' else speed+'×')+'. Full read-back follows writing.')
                    job['_write_started']=True;job['_device']=device;job['_layout']=layout;job['_verification_finished']=False;job['_verification_succeeded']=False;job['_attempts']=job.get('_attempts',0)+1
                    written=True;sha=write_stream(device,chunks(iso,disc/'recovery.wallaby',layout),layout['total_bytes'],WriterProgress(job),speed);job['_image_sha256']=sha;burn_finished=True
                    verification_started=True;self.stage(job,'verifying',message='Checking every recorded byte on disc '+str(job['discs_verified']+1)+' of '+str(disc_count)+'.')
                    try:readback(device,layout['total_bytes'],sha,StageProgress(job,'verified_bytes','verifying'));job['_verification_succeeded']=True
                    finally:job['_verification_finished']=True
                    self.finish_verified(job,sha,disc_count);all_verified=True
                except Exception as error:
                    all_verified=all_verified or job.get('discs_verified',0)>=disc_count
                    self.outcome(job,'completion_failed' if all_verified else ('verification_interrupted' if getattr(error,'code',None)=='disc_readback_unavailable' else 'verification_failed') if burn_finished and verification_started else 'burn_failed' if written else 'preparation_failed')
                    from activity_log import event
                    from diagnostics import action_code,action_detail
                    event('disc.failure','stage='+job.get('phase','unknown')+' · '+action_code(error)+' · '+action_detail(error))
                    job['failed_stage']=job.get('phase','preparing')
                    phase='completion_uncertain' if all_verified else 'uncertain' if written else 'error'
                    message=str(error) if isinstance(error,ValueError) else 'Disc work stopped. Inspect the local drive and outcome; no operation was repeated.'
                    job.update(phase=phase,message=message+(' All requested discs were verified; reconcile completion before doing anything else.' if all_verified else ' Keep the RAM workspace open. Reinsert the same disc and choose Verify written disc to retry verification without burning.' if burn_finished and verification_started else ' Keep the RAM workspace open. A new burn requires a fresh blank disc and your confirmation.'))
                finally:
                    password=None
                    if job.get('_cancel_pending') and job.get('_write_started') and job['phase']!='complete':
                        if not job.get('_verification_finished'):
                            verification_started=True;self.stage(job,'verifying',message='Cancellation received. Checking the medium after the writer stopped; an incomplete disc must still be destroyed locally.')
                            try:
                                expected=job.get('_image_sha256')
                                if not job.get('_image_sha256'):
                                    checksum=hashlib.sha256()
                                    for part in chunks(iso,disc/'recovery.wallaby',job['_layout']):checksum.update(part)
                                    expected=checksum.hexdigest()
                                readback(device,job['_layout']['total_bytes'],expected,StageProgress(job,'verified_bytes','verifying'));job['_verification_succeeded']=True
                            except Exception:job['_verification_succeeded']=False
                            finally:job['_verification_finished']=True
                        job.update(phase='cancel_cleanup',message='The writer and verification attempt have finished. Review cancellation on Authorise and account for every written or partial disc. No further copy will be burned.')
            self.thread=threading.Thread(target=work,daemon=True);self.thread.start();return {'message':'Disc '+str(job['discs_verified']+1)+' preparation started. No additional disc will be written without a new local confirmation.'}
