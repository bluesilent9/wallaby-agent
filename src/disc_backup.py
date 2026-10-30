"""Encrypted optical recovery packages. All paths belong to the protected RAM workspace."""
import hashlib,json,mmap,os,re,stat,subprocess,threading,time,zipfile
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

def pack(root,wallets,recovery,password):
    root=Path(root);disc=root/'disc';disc.mkdir(mode=0o700,parents=True,exist_ok=True);plain=root/'recovery.zip'
    with zipfile.ZipFile(plain,'w',zipfile.ZIP_STORED) as z:
        z.writestr('policy.json',json.dumps(recovery,sort_keys=True,indent=2))
        for ident,path in wallets.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or Path(path).stat().st_size>256*1024*1024:raise ValueError('Invalid recovery wallet entry.')
            z.write(path,'wallets/'+ident+'.dat')
    try:encrypt_file(plain,disc/'recovery.wallaby',password)
    finally:plain.unlink(missing_ok=True)
    (disc/'README.txt').write_text('Wallaby encrypted recovery package v1\nAES-256-GCM; scrypt N=131072,r=8,p=1.\nContains encrypted Core signing wallets plus the complete public receive/change policy and authenticated cosigner contributions.\nKeep your backup and Core wallet passphrases separately.\nUse the accompanying recovery.py only in a protected volatile environment.\n')
    (disc/'REDUNDANCY.txt').write_text('Build 10 repeats this exact encrypted recovery package in independently checksummed, sector-aligned raw-track slots after this small ISO filesystem. Disc Operations scans copies and skips unreadable/damaged ones. No giant RAM image or directory listing is needed. The filesystem copy also remains readable by standard tools.\n')
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

def media(device):
    if not isinstance(device,str) or not re.fullmatch(r'/dev/sr[0-9]{1,2}',device):raise ValueError('Select a local optical drive.')
    st=os.stat(device,follow_symlinks=False)
    if not stat.S_ISBLK(st.st_mode) or os.major(st.st_rdev)!=11:raise ValueError('Device is not a Linux optical drive.')
    r=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-indev',device,'-toc','-end'],capture_output=True,timeout=30)
    output=(r.stdout+r.stderr).decode(errors='replace')
    if r.returncode or not re.search(r'Media current\s*:\s*(?:BD-R\b|DVD-R\b)',output) or re.search(r'Media current\s*:.*(?:RW|RE\b)',output) or not re.search(r'Media status\s*:\s*is blank',output):raise ValueError('Insert a blank, write-once DVD-R or BD-R M-Disc in a compatible burner. Used, rewritable and unknown media are refused.')
    blocks=re.search(r'Media blocks\s*:.*?([0-9]+) writable',output)
    capacity=max(0,int(blocks[1])*2048-2*1024*1024) if blocks else None
    return {'device':device,'capacity_bytes':capacity,'estimated_1x_seconds':round(capacity/(4500000 if 'BD-R' in output else 1385000)) if capacity else None,'write_once':True,'blank':True,'message':'Blank write-once media detected. Confirm that the disc and drive support M-Disc; software cannot authenticate the physical media branding.'}

def image(disc,path):
    r=subprocess.run(['/usr/bin/xorriso','-abort_on','FAILURE','-as','mkisofs','-V','WALLABY_RECOVERY','-o',str(path),str(disc)],capture_output=True,timeout=300)
    if r.returncode:raise ValueError('Could not prepare the disc image in protected RAM.')
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def readback(device,size,expected,progress=None):
    # Aligned direct reads bypass the host page cache. No extracted file on disk.
    fd=os.open(device,os.O_RDONLY|os.O_DIRECT);result=hashlib.sha256();remaining=size
    try:
        with mmap.mmap(-1,1024*1024) as buffer:
            while remaining:
                count=min(remaining,len(buffer));view=memoryview(buffer)[:count]
                try:n=os.readv(fd,[view]);result.update(view[:n])
                finally:view.release()
                if n!=count:raise ValueError('Disc read-back ended early.')
                remaining-=n
                if progress:progress(size-remaining)
    finally:os.close(fd)
    if result.hexdigest()!=expected:raise ValueError('Disc read-back differs from the protected RAM image. Keep the RAM session open and use a fresh disc.')

def write_stream(device,source,total,progress):
    import selectors
    process=subprocess.Popen(['/usr/bin/xorriso','-abort_on','FAILURE','-as','cdrecord','-sao','speed=1','fs=16m','dev='+device,'tsize='+str(total//2048)+'s','-data','-'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    digest=hashlib.sha256();written=0;deadline=time.monotonic()+48*3600
    try:
        os.set_blocking(process.stdin.fileno(),False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin,selectors.EVENT_WRITE)
            for chunk in source:
                view=memoryview(chunk)
                try:
                    while view:
                        if time.monotonic()>deadline or not selector.select(120):raise ValueError('The optical writer stopped accepting data. The disc is incomplete; use a fresh blank disc after checking the drive.')
                        try:count=os.write(process.stdin.fileno(),view)
                        except BlockingIOError:continue
                        if count<=0:raise ValueError('The optical writer stopped.')
                        digest.update(view[:count]);written+=count;progress(written);view=view[count:]
                finally:view.release()
        process.stdin.close()
        if written!=total or process.wait(timeout=1800)!=0:raise ValueError('Optical writing failed or is uncertain. Keep the RAM session open and use a fresh blank disc.')
        return digest.hexdigest()
    except Exception:
        if process.poll() is None:process.terminate();process.wait(timeout=30)
        raise

class Burner:
    def __init__(self,root,on_complete):self.root=Path(root);self.root.mkdir(mode=0o700,parents=True,exist_ok=True);self.on_complete=on_complete;self.job=None;self.lock=threading.Lock();self.pending=[]
    def state(self):
        if self.job and self.job['phase']=='complete' and time.time()-self.job['finished']>5:
            self.job=None
            if self.pending:self.authorise(*self.pending.pop(0))
        return {k:v for k,v in (self.job or {}).items() if k not in ('recovery','wallets')}
    def authorise(self,job_id,wallets,recovery):
        if self.job:raise ValueError('Finish or explicitly discard the current disc session first.')
        self.job={'id':job_id,'phase':'authorised','policy_hash':recovery['policy_hash'],'wallets':wallets,'recovery':recovery,'message':'Authorised locally. Insert a blank M-Disc and choose the optical drive.'}
    def queue(self,job_id,wallets,recovery):
        if self.job:self.pending.append((job_id,wallets,recovery))
        else:self.authorise(job_id,wallets,recovery)
    def start(self,device,confirmed,password):
        with self.lock:
            if not self.job or self.job['phase'] not in ('authorised','error') or confirmed is not True:raise ValueError('Authorise and confirm M-Disc media before burning.')
            media(device);self.job.update(phase='preparing',message='Encrypting the complete recovery package in protected RAM.')
            def work():
                nonlocal password
                try:
                    directory=self.root/self.job['id'];directory.mkdir(mode=0o700,exist_ok=True)
                    disc=pack(directory,self.job['wallets'],self.job['recovery'],password);password=None;iso=directory/'disc.iso';image(disc,iso)
                    capacity=media(device)['capacity_bytes']
                    if capacity is None:raise ValueError('The drive did not report writable capacity. No write was started.')
                    from disc_archive import plan,chunks
                    layout=plan(iso,disc/'recovery.wallaby',capacity)
                    self.job.update(phase='burning',copies=layout['copies'],total_bytes=layout['total_bytes'],written_bytes=0,message='Writing '+str(layout['copies'])+' redundant encrypted copies. Requesting 1×; the drive may use its lowest supported speed. Read-back follows writing.')
                    sha=write_stream(device,chunks(iso,disc/'recovery.wallaby',layout),layout['total_bytes'],lambda count:self.job.update(written_bytes=count))
                    self.job.update(phase='verifying',message='Reading the complete recorded track directly and checking every byte. This can take as long as writing.')
                    readback(device,layout['total_bytes'],sha,lambda count:self.job.update(verified_bytes=count));self.on_complete(self.job['id'],sha)
                    import shutil
                    shutil.rmtree(directory)
                    self.job.update(phase='complete',message='Success! Every recorded byte, including every redundant copy, passed direct read-back verification.',finished=time.time())
                except Exception as error:self.job.update(phase='error',message=str(error) if isinstance(error,ValueError) else 'Disc work stopped. Keep the RAM session open and inspect the drive before a fresh attempt.')
                finally:password=None
            threading.Thread(target=work,daemon=True).start();return {'message':'Disc preparation started.'}
