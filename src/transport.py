"""IPv6-only OpenSSH forwarding, isolated from user forwarding directives."""
import os, socket, subprocess, time
from pathlib import Path
from configuration import SERVICES,hostname

def ssh_command(config,kind,local_port,control):
    host=hostname(config['hostname'])
    args=['ssh','-6','-F','/dev/null','-N','-T','-M','-S',str(control),'-p',str(config['ssh_port']),'-l',config['ssh_user'],
          '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes',
          '-o','ConnectTimeout=12','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
          '-o','ControlPersist=no','-o','GatewayPorts=no','-o','ForwardAgent=no','-o','ForwardX11=no',
          '-L',f'127.0.0.1:{local_port}:localhost:{SERVICES[kind]}']
    if config['identity_file']:args+=['-i',str(Path(config['identity_file']).expanduser()),'-o','IdentitiesOnly=yes']
    return args+['--',host]

class Tunnel:
    def __init__(self,config,kind,root):
        self.control=Path(root)/f'{kind}.sock';self.kind=kind;self.config=config;self.process=None
        if kind=='node':
            with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        else:self.port=SERVICES[kind]
    def start(self):
        # Fail visibly on port collisions; never mistake another app's listener for our tunnel.
        with socket.socket() as s:s.bind(('127.0.0.1',self.port))
        self.control.unlink(missing_ok=True)
        self.process=subprocess.Popen(ssh_command(self.config,self.kind,self.port,self.control),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def alive(self):
        if self.process is None or self.process.poll() is not None:return False
        return self.control.exists() and subprocess.run(['ssh','-F','/dev/null','-S',str(self.control),'-O','check','--',self.config['hostname']],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0
    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.control.unlink(missing_ok=True)

def ping(host):
    return subprocess.run(['ping','-6','-n','-c','1','-W','4','--',hostname(host)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8).returncode==0
