"""Per-user worker, private status files and rootless systemd control."""
import copy, json, os, random, signal, subprocess, tempfile, threading, time, sys
from pathlib import Path
from configuration import Config,SERVICES,discover_cookie
from transport import Tunnel,ping
from node_client import NodeClient
from diagnostics import ConnectionFailure,describe

def runtime_dir():
    base=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    if not base.is_dir():base=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))
    p=base/'wallaby-agent';p.mkdir(parents=True,exist_ok=True,mode=0o700);return p

def write_status(kind,color,message,**extra):
    root=runtime_dir();fd,name=tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd,'w') as f:json.dump({'color':color,'message':message,'updated':time.time(),**extra},f)
        os.replace(name,root/(kind+'.json'))
    finally:
        if os.path.exists(name):os.unlink(name)

def read_status(kind):
    try:
        d=json.loads((runtime_dir()/(kind+'.json')).read_text())
        if time.time()-d['updated']<50 or time.time()<d.get('retry_at',0)+10:return d
    except (OSError,ValueError,KeyError):pass
    return {'color':'red','message':'Off' if kind!='server' else 'Server name not configured.'}

def ctl(*args):
    p=subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=20)
    if p.returncode:raise RuntimeError('User service manager could not apply the change. Check the session supports systemd --user.')

def retire_jellyfin():
    """Stop V1's retired tunnel in the current user's session, including cached units."""
    unit='wallaby-agent-jellyfin.service'
    # Stop separately: disable may fail first if dpkg has already removed the unit file.
    result=subprocess.run(['systemctl','--user','stop',unit],capture_output=True,text=True,timeout=20)
    if result.returncode:
        # A fresh installation has no such unit. A bus/stop failure must not be hidden.
        state=subprocess.run(['systemctl','--user','is-active',unit],capture_output=True,text=True,timeout=20)
        if state.returncode not in (3,4):raise RuntimeError('Could not stop the retired Jellyfin user service.')
    result=subprocess.run(['systemctl','--user','disable',unit],capture_output=True,text=True,timeout=20)
    if result.returncode:
        state=subprocess.run(['systemctl','--user','is-enabled',unit],capture_output=True,text=True,timeout=20)
        if state.returncode not in (1,4):raise RuntimeError('Could not disable the retired Jellyfin user service.')
    link=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'systemd/user/default.target.wants'/unit
    if link.is_symlink():link.unlink()
    ctl('daemon-reload')
    Config()  # Persist migration of a V1 config, without enabling either remaining service.
    (runtime_dir()/'jellyfin.json').unlink(missing_ok=True)

def apply_config(config,new):
    """Persist desired state first; report service failures so they are never hidden."""
    old=copy.deepcopy(config.values);config.save(new)
    changed=any(old[k]!=new[k] for k in ('hostname','ssh_user','ssh_port','identity_file','cookie','rpc_port'))
    for kind in SERVICES:
        unit='wallaby-agent-'+kind+'.service'
        if new['enabled'][kind]:
            ctl('enable',unit)
            ctl('restart' if changed else 'start',unit)
        else:
            ctl('disable','--now',unit);write_status(kind,'red','Off',tunnel=False)
    ctl('enable','--now','wallaby-agent-monitor.service')
    # Monitor notices config changes itself and pings immediately.

def worker(kind):
    stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    delay=15;last_failure=None
    def publish(color,message,**extra):
        nonlocal last_failure
        if color=='green':last_failure=None
        write_status(kind,color,message,last_error=last_failure,**extra)
    while not stop.is_set():
        tunnel=None;session_stop=None;stage='configuration';failure=None
        try:
            config=Config().values
            if not config['enabled'][kind]:break
            if not config['hostname']:
                publish('red','Set the server name first.',tunnel=False);stop.wait(5);continue
            if kind=='node' and not config['cookie']:
                config['cookie']=discover_cookie()
            stage='ssh'
            publish('amber','Connecting SSH over IPv6…',tunnel=False,stage=stage)
            tunnel=Tunnel(config,kind,runtime_dir());tunnel.start()
            deadline=time.monotonic()+16
            while not stop.is_set() and not tunnel.alive():
                if tunnel.process.poll() is not None or time.monotonic()>deadline:raise tunnel.failure()
                stop.wait(.3)
            if stop.is_set():break
            stable_since=time.monotonic()
            if kind=='node':
                stage='node';session_stop=threading.Event();node_errors=[]
                def status(color,message,event=session_stop):
                    if not event.is_set():publish(color,message,tunnel=True,stage='node')
                status('amber','SSH connected. Checking local Bitcoin Core RPC…')
                node=NodeClient(config,tunnel.port,session_stop,status)
                def run_node(client=node,event=session_stop,errors=node_errors):
                    try:client.run()
                    except Exception as error:errors.append(describe('dashboard',error))
                    finally:event.set()
                thread=threading.Thread(target=run_node,daemon=True);thread.start()
            else:publish('green',f'Connected · [::1]:{tunnel.port}',tunnel=True,stage='ssh')
            while not stop.wait(2):
                if not tunnel.alive():raise tunnel.failure()
                if time.monotonic()-stable_since>=60:delay=15
                if kind=='node':
                    if session_stop.is_set():raise node_errors[0] if node_errors else ConnectionFailure('dashboard','session','Dashboard node session ended unexpectedly.')
                    current=read_status(kind);publish(current['color'],current['message'],tunnel=True,stage='node')
                else:publish('green',f'Connected · [::1]:{tunnel.port}',tunnel=True,stage='ssh')
        except Exception as error:
            failure=describe(stage,error)
            if failure.stage=='dashboard' and tunnel is not None:
                forwarded=tunnel.failure()
                if forwarded.stage=='ssh_forward':failure=forwarded
            last_failure=failure.detail()
            print(f'Wallaby Agent: stage={failure.stage} code={failure.code} type={type(error).__name__}: {failure}',file=sys.stderr,flush=True)
        finally:
            if session_stop is not None:session_stop.set()
            if tunnel is not None:tunnel.close()
        if stop.is_set():break
        retry=delay+random.uniform(0,3)
        publish('red',str(failure)+' Retrying automatically.',tunnel=False,stage=failure.stage,code=failure.code,retry_at=time.time()+retry)
        stop.wait(retry);delay=min(300,delay*2)
    publish('red','Off',tunnel=False)

def monitor():
    retire_jellyfin()
    stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());last_host=None;due=0;color='red';message='Server name not configured.'
    while not stop.is_set():
        host=Config().values['hostname'];active=any(read_status(k).get('tunnel',False) for k in SERVICES)
        if host!=last_host:last_host=host;due=0;color='red'
        if not host:color='red';message='Enter your server hostname or domain.'
        elif active:color='green';message='SSH tunnel established.';due=0
        elif time.monotonic()>=due:
            write_status('server','amber','Checking server over IPv6…')
            try:ok=ping(host)
            except Exception:ok=False
            color='green' if ok else 'red';message='Server responds over IPv6.' if ok else 'Server did not respond to IPv6 ping.';due=time.monotonic()+60
        write_status('server',color,message);stop.wait(2)
