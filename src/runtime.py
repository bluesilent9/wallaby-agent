"""Per-user worker, private status files and rootless systemd control."""
import copy, json, os, random, signal, subprocess, tempfile, threading, time, sys
from pathlib import Path
from configuration import Config,SERVICES,discover_cookie
from transport import Tunnel,MasterConnection,fingerprint,SSH_FIELDS
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
    return {'color':'red','message':'Off' if kind!='server' else 'Server SSH connection is not active.'}

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
    rpc_changed=any(old[k]!=new[k] for k in ('cookie','rpc_port'))
    for kind in SERVICES:
        unit='wallaby-agent-'+kind+'.service'
        if new['enabled'][kind]:
            if not old['enabled'][kind]:ctl('enable','--now',unit)
            elif kind=='node' and rpc_changed:ctl('restart',unit)
        elif old['enabled'][kind]:ctl('disable','--now',unit);write_status(kind,'red','Off',tunnel=False)
    ctl('enable','--now','wallaby-agent-monitor.service')
    # The monitor observes SSH setting changes. Workers reattach to its new generation.

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
            if kind=='node':
                from capabilities import node_support
                support=node_support(config)
                if not support['available']:raise ConnectionFailure('configuration','node_prerequisites',support['message'])
            stage='ssh'
            publish('amber','Connecting SSH over IPv6…',tunnel=False,stage=stage)
            tunnel=Tunnel(config,kind,runtime_dir());tunnel.start()
            deadline=time.monotonic()+16
            while not stop.is_set() and not tunnel.alive():
                if time.monotonic()>deadline:raise tunnel.failure()
                stop.wait(.3)
            if stop.is_set():break
            stable_since=time.monotonic()
            if kind=='node':
                stage='node';session_stop=threading.Event();node_errors=[]
                def status(color,message,event=session_stop):
                    if not event.is_set():publish(color,message,tunnel=True,stage='node')
                status('amber','SSH connected. Checking local Bitcoin Core RPC…')
                from protected_memory import required
                if required():
                    from protected_node import ProtectedNode
                    node=ProtectedNode(config,tunnel.port,session_stop,status)
                else:node=NodeClient(config,tunnel.port,session_stop,status)
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
        if failure and failure.code=='master_wait':
            publish('amber',str(failure),tunnel=False,stage='ssh');stop.wait(2);continue
        if fingerprint(Config().values)!=fingerprint(config):continue
        retry=delay+random.uniform(0,3)
        publish('red',str(failure)+' Retrying automatically.',tunnel=False,stage=failure.stage,code=failure.code,retry_at=time.time()+retry)
        stop.wait(retry);delay=min(300,delay*2)
    publish('red','Off',tunnel=False)

def monitor():
    retire_jellyfin()
    (runtime_dir()/'monitor-build.json').write_text(json.dumps({'version':'2.0.0~dev15','pid':os.getpid()}))
    stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    master=None;current=None;attempt_started=0;due=0;delay=15;notice=None;reconciled=None;last_rpc=None;status=('red','Enter your server hostname or domain.');extra={}
    try:
        while not stop.is_set():
            cfg=Config().values;identity=fingerprint(cfg)
            try:request=(runtime_dir()/'connect-request.json').read_text()
            except OSError:request=None
            if identity!=current or (request!=notice and (master is None or not master.alive())):
                if master:master.close();master=None
                (runtime_dir()/'master.json').unlink(missing_ok=True)
                current=identity;due=0;delay=15;extra={}
            notice=request
            if reconciled!=cfg['enabled']:
                for kind,on in cfg['enabled'].items():
                    if reconciled is None or reconciled[kind]!=on:
                        try:ctl('enable' if on else 'disable','--now','wallaby-agent-'+kind+'.service')
                        except RuntimeError:pass  # UI apply reports manager errors; keep SSH monitoring alive.
                reconciled=copy.deepcopy(cfg['enabled'])
            rpc_settings=(cfg['cookie'],cfg['rpc_port'])
            if last_rpc is not None and last_rpc!=rpc_settings and cfg['enabled']['node']:
                try:ctl('restart','wallaby-agent-node.service')
                except RuntimeError:pass
            last_rpc=rpc_settings
            now=time.monotonic()
            if not cfg['hostname']:
                status=('red','Enter your server hostname or domain.');extra={}
            elif master is None and now>=due:
                status=('amber','Authenticating SSH over IPv6…');extra={}
                write_status('server',*status,tunnel=False)
                master=MasterConnection(cfg,runtime_dir());attempt_started=now
                try:master.start()
                except Exception as error:
                    status=('red',str(describe('ssh',error)));master.close();master=None;due=now+delay;delay=min(300,delay*2)
            if master:
                if master.alive():
                    meta=runtime_dir()/'master.json'
                    if not meta.exists():
                        fd,name=tempfile.mkstemp(dir=runtime_dir())
                        with os.fdopen(fd,'w') as f:json.dump(master.info(),f)
                        os.replace(name,meta)
                    status=('green','Authenticated server SSH connection established.');extra={};delay=15
                elif master.process.poll() is not None or (runtime_dir()/'master.json').exists() or now-attempt_started>16:
                    failure=master.failure();status=('red',str(failure)+' Retrying automatically.')
                    extra={'stage':failure.stage,'code':failure.code,'retry_at':time.time()+delay}
                    master.close();master=None;(runtime_dir()/'master.json').unlink(missing_ok=True)
                    due=now+delay+random.uniform(0,3);delay=min(300,delay*2)
                else:status=('amber','Authenticating SSH over IPv6…')
            write_status('server',*status,tunnel=status[0]=='green',**extra)
            notify_approvals();stop.wait(1)
    finally:
        if master:master.close()
        (runtime_dir()/'master.json').unlink(missing_ok=True)
        write_status('server','red','Server SSH connection stopped.',tunnel=False)

def notify_approvals():
    # Build 10 uses unresolved sidebar dots. Requests never launch windows or
    # navigate away from the current page; the protected UI reads live status.
    return
