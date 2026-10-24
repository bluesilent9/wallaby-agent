"""Per-user worker, private status files and rootless systemd control."""
import copy, json, os, random, signal, subprocess, tempfile, threading, time
from pathlib import Path
from configuration import Config,SERVICES,discover_cookie
from transport import Tunnel,ping
from node_client import NodeClient

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
        if time.time()-d['updated']<50:return d
    except (OSError,ValueError,KeyError):pass
    return {'color':'red','message':'Off' if kind!='server' else 'Server name not configured.'}

def ctl(*args):
    p=subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=20)
    if p.returncode:raise RuntimeError('User service manager could not apply the change. Check the session supports systemd --user.')

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
    delay=15
    while not stop.is_set():
        config=Config().values
        if not config['enabled'][kind]:return
        if not config['hostname']:
            write_status(kind,'red','Set the server name first.',tunnel=False);stop.wait(5);continue
        if kind=='node' and not config['cookie']:
            cookie=discover_cookie()
            if cookie:
                config['cookie']=cookie
        tunnel=Tunnel(config,kind,runtime_dir())
        connected=threading.Event()
        try:
            write_status(kind,'amber','Connecting over IPv6…',tunnel=False);tunnel.start()
            deadline=time.monotonic()+16
            while not stop.is_set() and not tunnel.alive():
                if tunnel.process.poll() is not None or time.monotonic()>deadline:raise ConnectionError()
                stop.wait(.3)
            if stop.is_set():break
            connected.set();stable_since=time.monotonic()
            if kind=='node':
                session_stop=threading.Event()
                def status(color,message,event=session_stop,ready=connected):
                    if not event.is_set():write_status(kind,color,message,tunnel=ready.is_set())
                status('amber','SSH connected. Checking Bitcoin Core and Dashboard…')
                node=NodeClient(config,tunnel.port,session_stop,status)
                def run_node(client=node,event=session_stop,ready=connected):
                    try:client.run()
                    except Exception:
                        if not event.is_set():write_status(kind,'red','Bitcoin Core or Dashboard unavailable; retrying shortly.',tunnel=ready.is_set())
                        event.set()
                thread=threading.Thread(target=run_node,daemon=True);thread.start()
            else:write_status(kind,'green',f'Connected · [::1]:{tunnel.port}',tunnel=True)
            while not stop.wait(2):
                if not tunnel.alive():raise ConnectionError()
                if time.monotonic()-stable_since>=60:delay=15
                if kind=='node':
                    if session_stop.is_set():raise ConnectionError()
                    current=read_status(kind);write_status(kind,current['color'],current['message'],tunnel=True)
                else:write_status(kind,'green',f'Connected · [::1]:{tunnel.port}',tunnel=True)
        except Exception:
            write_status(kind,'red','Connection failed. Check IPv6, SSH key and trusted server key. Retrying shortly.',tunnel=False)
        finally:
            connected.clear()
            if kind=='node' and 'session_stop' in locals():session_stop.set()
            tunnel.close()
        if stop.is_set():break
        stop.wait(delay+random.uniform(0,3));delay=min(300,delay*2)
    write_status(kind,'red','Off',tunnel=False)

def monitor():
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
