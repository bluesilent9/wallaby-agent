"""Runtime evidence for fail-closed handling of Bitcoin secrets, not an OS-compromise guarantee."""
import ctypes,json,os,resource,subprocess
from pathlib import Path

def required():return os.environ.get('WALLABY_REQUIRE_PROTECTION')=='1'
def inside():return os.environ.get('WALLABY_PROTECTED_WORKER')=='1'
def root():return Path('/run/wallaby-agent-secure')/str(os.getuid())/'ram'

def noswap_path(path,mountinfo=None):
    target=Path(path).resolve()
    lines=(Path('/proc/self/mountinfo').read_text() if mountinfo is None else mountinfo).splitlines()
    candidates=[]
    for line in lines:
        fields=line.split();sep=fields.index('-');mount=Path(fields[4].replace('\\040',' '))
        if target.is_relative_to(mount):candidates.append((len(str(mount)),fields[sep+1],set((fields[5]+','+fields[sep+3]).split(','))))
    if not candidates:return False
    _,kind,options=max(candidates)
    return kind=='ramfs' or kind=='tmpfs' and 'noswap' in options

def readonly_path(path):
    target=Path(path).resolve();candidates=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields=line.split();mount=Path(fields[4].replace('\\040',' '))
        if target.is_relative_to(mount):candidates.append((len(str(mount)),'ro' in fields[5].split(',')))
    return bool(candidates and max(candidates)[1])

def enforce(path=None):
    if not inside():raise ValueError('Start the protected Bitcoin workspace first. No secret operation was attempted.')
    if not noswap_path(path or root()):raise ValueError('Protected storage is not a verified non-swapping RAM filesystem.')
    group=next((line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')),None)
    if group is None:raise ValueError('Unified memory protection is unavailable.')
    if Path(group).name!='wallaby-agent-secure@'+str(os.getuid())+'.service':raise ValueError('This is not the dedicated protected service.')
    cg=Path('/sys/fs/cgroup')/group.lstrip('/')
    if (cg/'memory.swap.max').read_text().strip()!='0' or (cg/'memory.swap.current').read_text().strip()!='0':raise ValueError('Process-group swap protection could not be verified.')
    if not all(readonly_path(p) for p in ('/',str(Path.home()),'/usr','/etc','/var')):raise ValueError('Persistent filesystem write restrictions could not be verified.')
    if not all(noswap_path(p) for p in ('/tmp','/var/tmp','/dev/shm')):raise ValueError('Temporary or shared memory storage could swap.')
    if resource.getrlimit(resource.RLIMIT_CORE)!=(0,0):raise ValueError('Crash dump protection is unavailable.')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(3,0,0,0,0)!=0:raise ValueError('Process dump protection could not be verified.') # PR_GET_DUMPABLE
    crash=Path('/sys/kernel/kexec_crash_loaded')
    if crash.exists() and crash.read_text().strip()!='0':raise ValueError('Kernel crash dumping is enabled. Disable it in the trusted operating environment before handling physical-only keys.')
    ancestors=set();pid=os.getpid()
    for _ in range(32):
        if pid<=1:break
        ancestors.add(pid)
        try:pid=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):break
    try:
        result=subprocess.run(['/usr/bin/busctl','--system','--json=short','call','org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager','ListInhibitors'],capture_output=True,timeout=5)
        rows=json.loads(result.stdout)['data'][0]
        held=any(set(row[0].split(':'))>={'sleep','shutdown'} and row[3]=='block' and row[4]==os.getuid() and row[5] in ancestors for row in rows)
    except Exception:held=False
    if not held:raise ValueError('An active sleep/hibernation inhibitor for this protected process could not be verified.')
    return {'ram_storage':True,'process_swap_disabled':True,'crash_dumps_disabled':True,'sleep_inhibited':True,'persistent_agent_writes_blocked':True}
