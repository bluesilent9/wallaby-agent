"""Public-only UI and network bridge to the protected local Bitcoin worker."""
import json,os,socket,struct,subprocess,time
from pathlib import Path
from protected_memory import root

class WorkspaceFailure(ValueError):
    """A local workspace failure; remains compatible with existing ValueError callers."""
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)

ENV=('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','LANG')

def call(method,*args,timeout=40):
    request={'method':method,'args':args,'environment':{k:os.environ[k] for k in ENV if k in os.environ}}
    data=json.dumps(request,allow_nan=False).encode()
    if len(data)>20*1024*1024:raise ValueError('Protected request is too large.')
    sock=socket.socket(socket.AF_UNIX);sock.settimeout(timeout)
    try:
        sock.connect(str(root()/'worker.sock'));sock.sendall(struct.pack('!I',len(data))+data)
        size=int.from_bytes(receive(sock,4),'big')
        if not 0<size<=20*1024*1024:raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid response length.')
        try:reply=json.loads(receive(sock,size))
        except WorkspaceFailure:raise
        except (ValueError,UnicodeError):raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid response. Close and restart the protected workspace after finishing sensitive work.') from None
        if not isinstance(reply,dict):raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid response.')
        if set(reply)=={'error'}:
            message=reply['error']
            if not isinstance(message,str) or not 0<len(message)<=2048 or any(ord(c)<32 for c in message):message='The local protected worker rejected the request. Check the protected workspace status.'
            raise WorkspaceFailure('worker_rejected',message)
        if set(reply)!={'result'}:raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid response.')
        return reply['result']
    except (OSError,TimeoutError):raise WorkspaceFailure('worker_unreachable','Protected Bitcoin workspace is not running or did not respond. Use the node interface toggle on Services to retry; no secret operation was replayed.') from None
    finally:sock.close()

def receive(sock,count):
    parts=[]
    while count:
        part=sock.recv(count)
        if not part:raise WorkspaceFailure('worker_closed','The local protected worker connection ended. Inspect the workspace before retrying; no secret operation was replayed.')
        parts.append(part);count-=len(part)
    return b''.join(parts)

def ensure_running():
    try:result=subprocess.run(['/usr/bin/systemctl','--no-ask-password','start','wallaby-agent-secure@'+str(os.getuid())+'.service'],capture_output=True,timeout=20)
    except subprocess.TimeoutExpired:raise WorkspaceFailure('start_timeout','Starting the local protected Bitcoin workspace timed out. Check its system-service status before retrying.') from None
    except OSError:raise WorkspaceFailure('service_manager','The local system service manager could not be reached to start the protected Bitcoin workspace.') from None
    if result.returncode:raise WorkspaceFailure('start_failed','The local protected Bitcoin workspace could not start. Retry the node interface toggle on Services, or inspect its system-service status if it was already set up.')
    return wait_ready()

def wait_ready():
    deadline=time.monotonic()+15;last=None
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        try:return call('service_status',timeout=min(8,remaining))
        except WorkspaceFailure as error:
            if error.code in ('worker_rejected','worker_protocol'):raise
            last=error
        except ValueError:pass
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        time.sleep(min(.25,remaining))
    if last is not None:raise last
    raise WorkspaceFailure('not_ready','The local protected Bitcoin workspace did not become ready. Check its system-service status.')

def ram_prepared():
    from protected_memory import noswap_path
    try:return root().is_dir() and root().stat().st_uid==os.getuid() and os.path.ismount(root()) and noswap_path(root())
    except OSError:return False

def start():
    from capabilities import require_node
    require_node()
    # Permission is requested by the native OS dialogue for this fixed helper only.
    from configuration import Config
    config=Config();config.root.mkdir(parents=True,mode=0o700,exist_ok=True)
    key=config.root/'preview_identity'
    if not key.exists():
        result=subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-C','','-f',str(key)],capture_output=True,timeout=10)
        if result.returncode:raise ValueError('Could not initialise the local Agent identity.')
    key.chmod(0o600)
    try:return call('service_status',timeout=8)
    except WorkspaceFailure as error:
        # A responding worker's protection refusal is not a request for another
        # administrator password. Neither is a malformed local protocol reply.
        if error.code in ('worker_rejected','worker_protocol'):raise
    if ram_prepared():
        # Only first-time RAM preparation needs the fixed privileged helper.
        # An existing protected mount does not justify re-authorising setup
        # whenever the unprivileged worker fails to start.
        return ensure_running()
    result=subprocess.run(['/usr/bin/pkexec','/usr/lib/wallaby-agent/secure-start',str(os.getuid())],capture_output=True,timeout=180)
    if result.returncode:raise WorkspaceFailure('setup_failed','Protected workspace setup was cancelled, denied or failed. No automatic authorisation retry was made; SSH services remain available.')
    return wait_ready()

def stop():
    from configuration import Config
    if Config().values['enabled']['node']:raise ValueError('Switch off Bitcoin Core Node Dashboard Interface before closing its protected workspace.')
    if call('service_status')['busy']:raise ValueError('Finish the wallet setup, physical discs, transfer or history recovery before closing the protected workspace.')
    result=subprocess.run(['/usr/bin/systemctl','--no-ask-password','stop','wallaby-agent-secure@'+str(os.getuid())+'.service'],capture_output=True,timeout=100)
    if result.returncode:raise ValueError('Protected cleanup did not confirm completion. Keep the computer awake and inspect the protected service before hibernating.')
    from protected_memory import noswap_path
    if not noswap_path(root()) or any(root().iterdir()):raise ValueError('Protected service stopped, but empty protected RAM could not be verified. Keep the computer awake and inspect the workspace; cleanup was not confirmed.')
    return {'message':'Protected workspace closed after its temporary processes and RAM data were cleared.'}

class Proxy:
    def __init__(self,prefix):self.prefix=prefix
    def __getattr__(self,name):
        if self.prefix=='transfer' and name=='recovery':return Proxy('recovery')
        return lambda *args,**kwargs:call(self.prefix+'.'+name,*args,timeout=kwargs.get('timeout',40))
