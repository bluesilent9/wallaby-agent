"""Constant-memory optical redundancy: a small ISO followed by self-describing copies.

The ISO stays readable by ordinary tools. Repeated encrypted packages occupy the
remaining track, outside its filesystem, avoiding huge directory trees/images.
Each sector-aligned copy has an independent bounded header and ciphertext checksum.
"""
import hashlib,json,mmap,os,struct
from pathlib import Path

ALIGN=1024*1024
HEADER=4096
MAGIC=b'WALLABY-REDUNDANT-DISC-2\n'
MAX_PACKAGE=272*1024*1024
MAX_MEDIA=1024**4

def align(n):return (n+ALIGN-1)//ALIGN*ALIGN
def slot_size(n):return (n+4095)//4096*4096

def plan(iso,package,capacity):
    size=Path(package).stat().st_size;start=align(Path(iso).stat().st_size);stride=slot_size(HEADER+size)
    if not 64<=size<=MAX_PACKAGE or type(capacity) is not int or not 0<capacity<=MAX_MEDIA:raise ValueError('Invalid optical package size or capacity.')
    total=capacity//2048*2048;count=(total-start)//stride
    if count<2:raise ValueError('This blank medium does not have room for two complete redundant copies plus its recovery filesystem.')
    with open(package,'rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    return {'version':2,'package_bytes':size,'package_sha256':sha,'start':start,'stride':stride,'copies':count,'total_bytes':total}

def copy_header(p,index):
    data={**p,'index':index,'offset':p['start']+index*p['stride']};raw=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    return MAGIC+struct.pack('<I',len(raw))+raw+hashlib.sha256(raw).digest()+bytes(HEADER-len(MAGIC)-4-len(raw)-32)

def chunks(iso,package,p):
    def zeros(n):
        while n:part=min(n,ALIGN);yield bytes(part);n-=part
    with open(iso,'rb') as f:
        while data:=f.read(ALIGN):yield data
    yield from zeros(p['start']-Path(iso).stat().st_size)
    for i in range(p['copies']):
        yield copy_header(p,i)
        with open(package,'rb') as f:
            while data:=f.read(ALIGN):yield data
        yield from zeros(p['stride']-HEADER-p['package_bytes'])
    yield from zeros(p['total_bytes']-p['start']-p['copies']*p['stride'])

def decode_header(raw,offset,capacity):
    if not raw.startswith(MAGIC) or len(raw)!=HEADER:return None
    try:
        n=struct.unpack('<I',raw[len(MAGIC):len(MAGIC)+4])[0]
        if not 0<n<=2048:return None
        body=raw[len(MAGIC)+4:len(MAGIC)+4+n];saved=raw[len(MAGIC)+4+n:len(MAGIC)+4+n+32]
        if hashlib.sha256(body).digest()!=saved:return None
        p=json.loads(body)
        if set(p)!={'version','package_bytes','package_sha256','start','stride','copies','total_bytes','index','offset'} or any(type(p[k]) is not int for k in p if k!='package_sha256'):return None
        if p['version']!=2 or not 64<=p['package_bytes']<=MAX_PACKAGE or p['stride']!=slot_size(HEADER+p['package_bytes']) or p['start']%ALIGN or not 0<=p['index']<p['copies']<=MAX_MEDIA//4096 or p['offset']!=offset or offset!=p['start']+p['index']*p['stride'] or not p['start']<p['total_bytes']<=capacity<=MAX_MEDIA or p['start']+p['copies']*p['stride']>p['total_bytes']:return None
        if not isinstance(p['package_sha256'],str) or len(p['package_sha256'])!=64 or any(c not in '0123456789abcdef' for c in p['package_sha256']):return None
        return p
    except (ValueError,TypeError,KeyError,struct.error):return None

def direct_read(fd,offset,count):
    # Optical sectors and buffers are aligned; bypass the ordinary page cache.
    length=(count+4095)//4096*4096
    with mmap.mmap(-1,length) as memory:
        os.lseek(fd,offset,os.SEEK_SET);view=memoryview(memory)
        try:
            got=os.readv(fd,[view]);return bytes(view[:min(got,count)])
        finally:view.release()

def recover(fd,capacity,target,read=None,progress=None,start_hint=None):
    """Read one valid copy; skip bad headers, I/O errors and damaged ciphertext.

    fd must have O_DIRECT for real optical media; tests supply an isolated reader.
    No decryption is attempted until a complete ciphertext checksum matches.
    """
    if not 0<capacity<=MAX_MEDIA:raise ValueError('Unsupported optical capacity.')
    read=read or (lambda offset,count:direct_read(fd,offset,count));progress=progress or (lambda text:None);p=None;seen=0
    # Discover one independently checksummed layout header. Once found, jump
    # straight between exact slot locations; no huge file listing or per-copy
    # filesystem metadata is required. Header loss in any slot is tolerated.
    from itertools import chain
    hint=start_hint if type(start_hint) is int and 0<=start_hint<capacity and start_hint%4096==0 else 0
    for offset in chain(range(hint,capacity-HEADER+1,4096),range(0,hint,4096)):
        try:raw=read(offset,HEADER)
        except OSError:continue
        p=decode_header(raw,offset,capacity)
        if p is not None:break
    if p is None:raise ValueError('No intact recovery headers were found. Try another disc or drive.')
    for turn in range(p['copies']):
        index=(p['index']+turn)%p['copies'];offset=p['start']+index*p['stride']
        try:candidate=decode_header(read(offset,HEADER),offset,capacity)
        except OSError:continue
        if candidate is None or any(candidate[k]!=p[k] for k in ('package_bytes','package_sha256','start','stride','copies','total_bytes')):continue
        seen+=1;progress('Checking recovery copy '+str(index+1)+' of '+str(p['copies'])+'.')
        result=hashlib.sha256();position=offset+HEADER;remain=p['package_bytes']
        try:
            with open(target,'wb') as out:
                os.chmod(target,0o600)
                while remain:
                    count=min(remain,ALIGN);data=read(position,count)
                    if len(data)!=count:raise OSError('Short optical read')
                    out.write(data);result.update(data);position+=count;remain-=count
            if result.hexdigest()==p['package_sha256']:return candidate
        except OSError:pass
        Path(target).unlink(missing_ok=True)
    raise ValueError('No intact redundant copy was found. '+str(seen)+' readable copy headers were checked. Try another disc/drive; no wallet was loaded.')
