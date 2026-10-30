"""Private, atomic user configuration and local Bitcoin Core discovery."""
import configparser, ipaddress, json, os, re, shlex, tempfile
from pathlib import Path

SERVICES={'ddns':9876,'dashboard':38951,'node':56443}

def hostname(value):
    value=value.strip().rstrip('.')
    try: ipaddress.ip_address(value)
    except ValueError: pass
    else: raise ValueError('Enter a hostname or domain, not an IP address.')
    try: value=value.encode('idna').decode('ascii').lower()
    except UnicodeError: raise ValueError('Invalid server name.') from None
    if not value or len(value)>253 or all(p.isdigit() for p in value.split('.')) or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in value.split('.')):
        raise ValueError('Enter a valid hostname or domain without a protocol, port or path.')
    return value

class Config:
    def __init__(self,root=None):
        self.root=Path(root or Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'wallaby-agent')
        self.path=self.root/'config.cfg'
        self.values={'hostname':'','ssh_user':os.environ.get('USER',''),'ssh_port':22,'identity_file':'','cookie':'','rpc_port':8332,'enabled':{k:False for k in SERVICES}}
        retired=False
        if self.path.exists():
            c=configparser.ConfigParser(interpolation=None);c.read(self.path)
            for k in ('hostname','ssh_user','identity_file','cookie'):self.values[k]=c.get('agent',k,fallback=self.values[k])
            for k in ('ssh_port','rpc_port'):self.values[k]=c.getint('agent',k,fallback=self.values[k])
            self.values['enabled']={k:c.getboolean('services',k,fallback=False) for k in SERVICES}
            retired=c.has_option('services','jellyfin')
        self.validate(self.values)
        # Drop the retired V1 switch while preserving both remaining service settings.
        if retired:self.save(self.values)
    def validate(self,v):
        if v['hostname']:v['hostname']=hostname(v['hostname'])
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}',v['ssh_user']):raise ValueError('Invalid SSH username.')
        for k in ('ssh_port','rpc_port'):
            if type(v[k]) is not int or not 1<=v[k]<=65535:raise ValueError('Port must be between 1 and 65535.')
        for k in ('cookie','identity_file'):
            if not isinstance(v[k],str) or any(ord(c)<32 for c in v[k]):raise ValueError('Invalid file path.')
            if v[k] and not Path(v[k]).expanduser().is_absolute():raise ValueError('Select an absolute file path.')
        if set(v['enabled'])!=set(SERVICES) or any(type(x) is not bool for x in v['enabled'].values()):raise ValueError('Invalid service settings.')
    def save(self,v):
        self.validate(v);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        c=configparser.ConfigParser(interpolation=None);c['agent']={k:str(x) for k,x in v.items() if k!='enabled'};c['services']={k:str(x).lower() for k,x in v['enabled'].items()}
        fd,name=tempfile.mkstemp(dir=self.root,prefix='.config-')
        try:
            with os.fdopen(fd,'w') as f:c.write(f);f.flush();os.fsync(f.fileno())
            os.replace(name,self.path);self.values=v
        finally:
            if os.path.exists(name):os.unlink(name)

def discover_cookie(home=None,proc=Path('/proc')):
    """Core has no standard datadir environment variable. Inspect owned processes first."""
    home=Path(home or Path.home());roots=[];explicit=[]
    for p in proc.glob('[0-9]*'):
        try:
            if p.stat().st_uid!=os.getuid():continue
            args=(p/'cmdline').read_bytes().decode().strip('\0').split('\0')
            if Path(args[0]).name not in ('bitcoind','bitcoin-qt'):continue
            opts={a.split('=',1)[0]:a.split('=',1)[1] for a in args[1:] if '=' in a}
            if opts.get('-datadir','').startswith('/run/wallaby-agent-secure/'):continue
            if '-datadir' in opts:roots.append(Path(opts['-datadir']).expanduser())
            if '-rpccookiefile' in opts:
                q=Path(opts['-rpccookiefile']).expanduser()
                explicit.append(q if q.is_absolute() else Path(opts.get('-datadir',home/'.bitcoin'))/q)
        except (OSError,UnicodeError,IndexError):continue
    roots.extend([home/'snap/bitcoin-core/common/.bitcoin',home/'snap/bitcoin-core/current/.bitcoin',home/'.bitcoin'])
    for root in list(roots):
        try:
            for line in (root/'bitcoin.conf').read_text().splitlines():
                key,sep,value=line.strip().partition('=')
                if key=='datadir' and sep:roots.append(Path(value).expanduser())
                if key=='rpccookiefile' and sep:
                    q=Path(value).expanduser();explicit.append(q if q.is_absolute() else root/q)
        except OSError:pass
        try:
            settings=json.loads((root/'settings.json').read_text())
            if isinstance(settings.get('datadir'),str):roots.append(Path(settings['datadir']).expanduser())
        except (OSError,ValueError):pass
    for q in explicit+[root/'.cookie' for root in roots]:
        if q.is_file() and os.access(q,os.R_OK):return str(q.resolve())
    return ''
