"""Explicit local encrypted export; plaintext never leaves the protected worker."""
import array,fcntl,hashlib,io,json,os,re,secrets,socket,stat,struct,zipfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from disc_backup import MAGIC
from wallet_ops import rpc

MAX_WALLET=256*1024*1024

def create_export(request):
    if not isinstance(request,dict) or set(request)!={'export_directory','export_name'} or not isinstance(request['export_directory'],str) or not isinstance(request['export_name'],str) or not re.fullmatch('wallaby-cancel-[0-9a-f]{32}\\.wallaby',request['export_name']):raise ValueError('Invalid explicit backup destination.')
    directory=Path(request['export_directory']);home=Path.home()
    if not directory.is_absolute() or '..' in directory.parts or directory!=directory.resolve() or not directory.is_relative_to(home):raise ValueError('Choose an existing local backup directory inside your home.')
    for item in (directory,*directory.parents):
        if item.is_symlink():raise ValueError('Backup folder paths must not contain symbolic links.')
    parent=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if os.fstat(parent).st_uid!=os.getuid():raise ValueError('Choose a backup directory owned by this desktop user.')
        return os.open(request['export_name'],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    finally:os.close(parent)

def export_fd(directory,name):
    from wallet_deletion import socket_path
    from secure_bridge import receive
    raw=json.dumps({'export_directory':directory,'export_name':name}).encode()
    if len(raw)>4096:raise ValueError('Backup destination is too long.')
    fd=None
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(15);sock.connect(str(socket_path()))
        _,uid,_=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=os.getuid():raise ValueError('Unexpected local export service owner.')
        sock.sendall(struct.pack('!I',len(raw))+raw)
        head,ancillary,flags,_=sock.recvmsg(4,socket.CMSG_SPACE(array.array('i').itemsize),socket.MSG_CMSG_CLOEXEC)
        fds=[]
        for level,kind,data in ancillary:
            if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
                values=array.array('i');values.frombytes(data[:len(data)//values.itemsize*values.itemsize]);fds.extend(values)
        try:
            if flags&socket.MSG_CTRUNC or len(fds)!=1:raise ValueError('Local export did not supply one protected file handle.')
            fd=fds[0]
            if len(head)<4:head+=receive(sock,4-len(head))
            size=int.from_bytes(head,'big')
            if not 0<size<=4096 or json.loads(receive(sock,size))!={'export':True}:raise ValueError('Local export was refused.')
            info=os.fstat(fd);path=Path(directory)/name;expected=path.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size!=0 or stat.S_IMODE(info.st_mode)!=0o600 or (info.st_dev,info.st_ino)!=(expected.st_dev,expected.st_ino) or fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE!=os.O_WRONLY:raise ValueError('Unsafe backup file handle.')
            fds.remove(fd);return fd
        finally:
            for item in fds:os.close(item)

class EncryptWriter:
    def __init__(self,out,password):
        salt=os.urandom(16);nonce=os.urandom(12);header=MAGIC+salt+nonce
        key=Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password.encode());self.cipher=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor();self.cipher.authenticate_additional_data(header);self.out=out;self.position=0;self.hash=hashlib.sha256();self._write(header)
    def _write(self,data):self.out.write(data);self.hash.update(data)
    def write(self,data):
        self._write(self.cipher.update(bytes(data)));self.position+=len(data);return len(data)
    def tell(self):return self.position
    def seek(self,*args):raise OSError('Non-seekable encrypted export.')
    def flush(self):self.out.flush()
    def finish(self):self._write(self.cipher.finalize());self._write(self.cipher.tag);self.out.flush();os.fsync(self.out.fileno())

def export_bundle(directory,manifest,psbts,wallets,ram,password):
    from protected_memory import enforce
    enforce()
    if not isinstance(password,str) or len(password)<12:raise ValueError('Use a backup passphrase of at least 12 characters.')
    name='wallaby-cancel-'+secrets.token_hex(16)+'.wallaby';fd=export_fd(directory,name);path=Path(directory)/name;temp=None
    try:
        with os.fdopen(fd,'wb',closefd=True) as out:
            encrypted=EncryptWriter(out,password)
            with zipfile.ZipFile(encrypted,'w',compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
                archive.writestr('README.txt','Wallaby cancellation backup v1. Authenticated AES-256-GCM encrypted ZIP. Decrypt with the installed disc_backup.decrypt_file only into verified protected RAM. manifest.json preserves the full locally held proposals, policies and contributions. Restore wallet .dat files through Bitcoin Core restorewallet; private Core wallets may also need their original Core passphrase. PSBT files are under psbts/. Cancelling does not reverse broadcast transactions. Never extract private wallets to an unprotected directory.\n')
                for psbt in psbts:archive.writestr('psbts/'+hashlib.sha256(psbt.encode()).hexdigest()+'.psbt',psbt)
                for i,item in enumerate(wallets):
                    temp=Path(ram)/('cancel-wallet-'+secrets.token_hex(16)+'.dat')
                    from core_ram_path import for_core
                    rpc(item['core'],'backupwallet',[for_core(item['core'],temp)],item['name'])
                    if temp.stat().st_size>MAX_WALLET:raise ValueError('A wallet exceeds the bounded cancellation backup size. Original artifacts were retained.')
                    ident=hashlib.sha256((str(i)+':'+item['name']).encode()).hexdigest();archive.write(temp,'wallets/'+ident+'.dat');temp.unlink();temp=None
            encrypted.finish()
        # Ciphertext is the only data read from/written to persistent storage.
        with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        if sha!=encrypted.hash.hexdigest():raise ValueError('Encrypted backup read-back differs; original artifacts retained.')
        return {'path':str(path),'sha256':sha,'encrypted':True,'format':'wallaby-disc-1 encrypted cancellation ZIP'}
    except Exception:
        raise ValueError('Encrypted backup was not completed. Original wallets and PSBTs were retained; an incomplete encrypted file may remain in the selected folder.') from None
    finally:
        password=None
        if temp is not None:temp.unlink(missing_ok=True)
