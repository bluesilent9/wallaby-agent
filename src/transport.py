"""One authenticated IPv6 OpenSSH master; services add/cancel multiplexed forwards."""
import errno, hashlib, json, os, socket, subprocess, time, threading, uuid
from collections import deque
from pathlib import Path
from configuration import SERVICES,hostname
from diagnostics import ConnectionFailure,ssh_failure

SSH_FIELDS=('hostname','ssh_user','ssh_port','identity_file')
def fingerprint(config):
    return hashlib.sha256(json.dumps({k:config[k] for k in SSH_FIELDS},sort_keys=True).encode()).hexdigest()

def ssh_command(config,kind,local_port,control):
    host=hostname(config['hostname'])
    args=['ssh','-6','-F','/dev/null','-N','-T','-M','-S',str(control),'-p',str(config['ssh_port']),'-l',config['ssh_user'],
          '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes',
          '-o','ConnectTimeout=12','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
          '-o','ControlPersist=no','-o','GatewayPorts=no','-o','ForwardAgent=no','-o','ForwardX11=no']
    if kind is not None:args+=['-L',f'[::1]:{local_port}:[::1]:{SERVICES[kind]}']
    if config['identity_file']:args+=['-i',str(Path(config['identity_file']).expanduser()),'-o','IdentitiesOnly=yes']
    return args+['--',host]

def control_command(config,control,operation,forward=None):
    args=['ssh','-6','-F','/dev/null','-S',str(control),'-O',operation]
    if forward:args+=['-L',forward]
    return args+['--',config['hostname']]

def master_info(root,config):
    try:
        d=json.loads((Path(root)/'master.json').read_text());control=Path(d['control'])
        if d['config_hash']!=fingerprint(config) or control.parent!=Path(root) or not control.name.startswith('ssh-') or not control.name.endswith('.sock'):raise ValueError()
        return d
    except (OSError,ValueError,KeyError,TypeError):raise ConnectionFailure('ssh','master_wait','Waiting for the authenticated server SSH connection.') from None

class MasterConnection:
    def __init__(self,config,root):
        self.root=Path(root);self.config=config;self.control=self.root/('ssh-'+uuid.uuid4().hex[:12]+'.sock');self.process=None
        self.errors=deque(maxlen=32);self.error_thread=None
    def start(self):
        try:self.process=subprocess.Popen(ssh_command(self.config,None,None,self.control),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        except FileNotFoundError:raise ConnectionFailure('ssh_local','client_missing','OpenSSH client was not found. Install openssh-client before connecting.') from None
        self.error_thread=threading.Thread(target=self._read_errors,daemon=True);self.error_thread.start()
    def _read_errors(self):
        for line in iter(lambda:self.process.stderr.readline(2048),b''):self.errors.append(line.decode('utf-8',errors='replace'))
    def failure(self):
        if self.process and self.process.poll() is not None and self.error_thread:self.error_thread.join(timeout=.2)
        error=ssh_failure(list(self.errors),0,self.process.poll() if self.process else None)
        if error.stage=='ssh_forward':return ConnectionFailure('ssh','transport','The authenticated server SSH connection closed.')
        return error
    def alive(self):
        try:return bool(self.process is not None and self.process.poll() is None and self.control.exists() and subprocess.run(control_command(self.config,self.control,'check'),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0)
        except (OSError,subprocess.TimeoutExpired):return False
    def info(self):return {'control':str(self.control),'config_hash':fingerprint(self.config)}
    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        if self.error_thread:self.error_thread.join(timeout=.5)
        if self.process and self.process.stderr:self.process.stderr.close()
        self.control.unlink(missing_ok=True)

class Tunnel:
    """Does not create an SSH login or own the master process."""
    def __init__(self,config,kind,root):
        self.config=config;self.kind=kind;self.root=Path(root);self.control=None;self.added=False;self.errors=[]
        if kind=='node':
            with socket.socket(socket.AF_INET6) as s:s.bind(('::1',0));self.port=s.getsockname()[1]
        else:self.port=SERVICES[kind]
    @property
    def forward(self):return f'[::1]:{self.port}:[::1]:{SERVICES[self.kind]}'
    def start(self):
        self.control=Path(master_info(self.root,self.config)['control'])
        try:
            with socket.socket(socket.AF_INET6) as s:s.bind(('::1',self.port))
        except OSError as error:
            if error.errno==errno.EADDRINUSE:raise ConnectionFailure('ssh_local','port_busy',f'Local IPv6 tunnel port {self.port} is already in use. Stop the conflicting listener or old tunnel.') from None
            raise
        result=subprocess.run(control_command(self.config,self.control,'forward',self.forward),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=5)
        if result.returncode:
            self.errors=[result.stderr[:4096].decode(errors='replace')];raise self.failure()
        self.added=True
    def alive(self):
        if not self.added:return False
        try:
            if master_info(self.root,self.config)['control']!=str(self.control):return False
            return self.control.exists() and subprocess.run(control_command(self.config,self.control,'check'),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0
        except ConnectionFailure:return False
    def failure(self):
        if self.errors:return ssh_failure(self.errors,SERVICES[self.kind],255)
        return ConnectionFailure('ssh','master_lost','The shared server SSH connection dropped. The service will reconnect after SSH returns.')
    def close(self):
        if self.added and self.control.exists():
            try:subprocess.run(control_command(self.config,self.control,'cancel',self.forward),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4)
            except (OSError,subprocess.TimeoutExpired):pass
        self.added=False
