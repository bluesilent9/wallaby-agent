"""IPv6-only OpenSSH forwarding, isolated from user forwarding directives."""
import errno, os, socket, subprocess, time, threading
from collections import deque
from pathlib import Path
from configuration import SERVICES,hostname
from diagnostics import ConnectionFailure,ssh_failure

def ssh_command(config,kind,local_port,control):
    host=hostname(config['hostname'])
    args=['ssh','-6','-F','/dev/null','-N','-T','-M','-S',str(control),'-p',str(config['ssh_port']),'-l',config['ssh_user'],
          '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes',
          '-o','ConnectTimeout=12','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
          '-o','ControlPersist=no','-o','GatewayPorts=no','-o','ForwardAgent=no','-o','ForwardX11=no',
          '-L',f'[::1]:{local_port}:[::1]:{SERVICES[kind]}']
    if config['identity_file']:args+=['-i',str(Path(config['identity_file']).expanduser()),'-o','IdentitiesOnly=yes']
    return args+['--',host]

class Tunnel:
    def __init__(self,config,kind,root):
        self.control=Path(root)/f'{kind}.sock';self.kind=kind;self.config=config;self.process=None
        self.errors=deque(maxlen=32);self.error_thread=None
        if kind=='node':
            with socket.socket(socket.AF_INET6) as s:s.bind(('::1',0));self.port=s.getsockname()[1]
        else:self.port=SERVICES[kind]
    def start(self):
        # Fail visibly on port collisions; never mistake another app's listener for our tunnel.
        try:
            with socket.socket(socket.AF_INET6) as s:s.bind(('::1',self.port))
        except OSError as error:
            if error.errno==errno.EADDRINUSE:raise ConnectionFailure('ssh_local','port_busy',f'Local IPv6 tunnel port {self.port} is already in use. Stop the conflicting listener or old tunnel.') from None
            raise
        self.control.unlink(missing_ok=True)
        try:self.process=subprocess.Popen(ssh_command(self.config,self.kind,self.port,self.control),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        except FileNotFoundError:raise ConnectionFailure('ssh_local','client_missing','OpenSSH client was not found. Install openssh-client before enabling a tunnel.') from None
        self.error_thread=threading.Thread(target=self._read_errors,daemon=True);self.error_thread.start()
    def _read_errors(self):
        # Drain continuously so SSH cannot block; retain only bounded private memory.
        for line in iter(lambda:self.process.stderr.readline(2048),b''):
            self.errors.append(line.decode('utf-8',errors='replace'))
    def failure(self):
        if self.process and self.process.poll() is not None and self.error_thread:self.error_thread.join(timeout=.2)
        return ssh_failure(list(self.errors),SERVICES[self.kind],self.process.poll() if self.process else None)
    def alive(self):
        if self.process is None or self.process.poll() is not None:return False
        return self.control.exists() and subprocess.run(['ssh','-F','/dev/null','-S',str(self.control),'-O','check','--',self.config['hostname']],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0
    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        if self.error_thread:self.error_thread.join(timeout=.5)
        if self.process and self.process.stderr:self.process.stderr.close()
        self.control.unlink(missing_ok=True)

def ping(host):
    return subprocess.run(['ping','-6','-n','-c','1','-W','4','--',hostname(host)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8).returncode==0
