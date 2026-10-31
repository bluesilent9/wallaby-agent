#!/usr/bin/python3
"""Wallaby Agent V2 entry point and authenticated loopback configuration page."""
import argparse, copy, fcntl, hmac, json, os, secrets, shutil, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from capabilities import node_support,require_node,NodeUnavailable
from node_client import Core,decode
from wallet_ops import WalletOps
from peer_wallet import peer_receive,askpass,check_firewall
from batch_transfer import BatchTransfer as Transfer
from approval_store import Store
from configuration import Config,hostname,discover_cookie,SERVICES
from runtime import runtime_dir,read_status,write_status,apply_config,ctl,worker,monitor,retire_jellyfin

LOCAL_ACTION_LOCK=threading.RLock()
TRANSFER_LOCK=threading.RLock()

def local_busy(server):
    from protected_memory import required
    if required():
        from secure_bridge import call
        try:return call('service_status')['busy']
        except ValueError:return False
    saved=Store().read()
    return bool(getattr(getattr(server,'transfer',None),'sending',False) or saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'))

ASSETS=Path(__file__).resolve().parent.parent/'web'

def picker():
    # Native dialog returns the selected path; cookie contents never enter the browser.
    if shutil.which('kdialog'):cmd=['kdialog','--getopenfilename',str(Path.home()),'*','--title','Select Bitcoin Core RPC cookie']
    elif shutil.which('zenity'):cmd=['zenity','--file-selection','--show-hidden','--title=Select Bitcoin Core RPC cookie']
    else:raise ValueError('Install kdialog or zenity, or enter the full cookie path.')
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
    if p.returncode:return ''
    path=Path(p.stdout.strip())
    if not path.is_file() or not os.access(path,os.R_OK):raise ValueError('Choose a readable cookie file.')
    return str(path.resolve())

def wallet_ops(server):
    from protected_memory import required
    if required():
        from secure_bridge import Proxy
        return Proxy('wallet')
    v=Config().values
    if not v['cookie']:v['cookie']=discover_cookie()
    existing=getattr(server,'wallet_ops',None)
    if existing is None or any(existing.core.config.get(k)!=v[k] for k in ('cookie','rpc_port')):
        server.wallet_ops=WalletOps(Core(v))
    return server.wallet_ops

def transfer(server):
    with TRANSFER_LOCK:return _transfer(server)

def _transfer(server):
    from protected_memory import required
    if required():
        from secure_bridge import Proxy
        return Proxy('transfer')
    ops=wallet_ops(server)
    if not getattr(server,'transfer',None):server.transfer=Transfer(ops.core,ops.store)
    if any(server.transfer.core.config.get(k)!=ops.core.config.get(k) for k in ('cookie','rpc_port')):
        server.transfer.close();server.transfer=Transfer(ops.core,ops.store)
    return server.transfer

def workspace(server):
    from protected_memory import inside,root as protected_root
    seen_root=protected_root() if inside() else runtime_dir()
    (seen_root/'ui-seen.json').write_text(json.dumps({'at':time.time()}))
    from protected_memory import required
    if required():
        from secure_bridge import call
        try:return call('status' if inside() else 'service_status')
        except ValueError as error:return {'connected':False,'pending':[],'denied':[],'sync':str(error),'outbox_count':0,'transfer':{},'burn':{},'protected':{'running':False,'message':str(error)},'busy':False}
    saved=wallet_ops(server).store.read()
    try:
        wallet_ops(server).core.ready();connected=True
    except Exception:connected=False
    return {'connected':connected,'pending':[{"id":k,'kind':v['proposal']['kind'],'state':v['state']} for k,v in saved['pending'].items() if v['proposal']['kind']!='wallet_transfer'],
            'denied':[{"id":k,'proposal':{'kind':v['proposal']['kind']},'wallet_name':v.get('wallet_name','')} for k,v in saved['denied'].items()],'sync':saved['sync'],'outbox_count':len(saved['outbox']),'transfer':transfer(server).state()}

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*_):pass
    def reply(self,status,data,kind='application/json'):
        raw=json.dumps(data,allow_nan=False).encode() if kind=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers();self.wfile.write(raw)
    def allowed(self,auth=False):
        authority=self.headers.get('Host','')
        if authority not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):return False
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+authority:return False
        if self.headers.get('Sec-Fetch-Site') in ('cross-site','same-site'):return False
        if auth and not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):return False
        return True
    def do_GET(self):
        if self.path=='/api/session':
            if not self.allowed() or self.headers.get('Sec-Fetch-Site')!='same-origin' or self.headers.get('X-Wallaby-UI')!='1':return self.reply(403,{'error':'Local page session access denied.'})
            return self.reply(200,{'token':self.server.token})
        if not self.allowed(self.path.startswith('/api/')):return self.reply(403,{'error':'The local Agent session needs to reconnect.'})
        if self.path=='/api/health':return self.reply(200,{'ok':True,'version':'2.0.0~dev17'})
        if self.path=='/api/state':
            with self.server.config_lock:
                c=Config();v=copy.deepcopy(c.values)
                if not v['cookie']:
                    cookie=discover_cookie()
                    if cookie:v['cookie']=cookie;c.save(v)
                return self.reply(200,{'config':v,'status':{k:read_status(k) for k in ['server',*SERVICES]},'version':'V2 Development Build 17','node_support':node_support(v),'workspace':workspace(self.server)})
        paths={'/':'index.html','/app.js':'app.js','/workspace.js':'workspace.js','/message.js':'message.js','/disc_operations.js':'disc_operations.js','/synchronisation.js':'synchronisation.js','/wallet_setup.js':'wallet_setup.js','/style.css':'style.css','/wallaby-agent.svg':'wallaby-agent.svg'}
        asset_path=urlsplit(self.path).path
        if asset_path not in paths:return self.reply(404,{'error':'Not found.'})
        f=ASSETS/paths[asset_path];mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.json':'application/json; charset=utf-8'}[f.suffix]
        self.reply(200,f.read_bytes(),mime)
    def do_POST(self):
        from node_lifecycle import control_lock
        from protected_memory import inside
        import contextlib
        with LOCAL_ACTION_LOCK, (contextlib.nullcontext() if inside() else control_lock()):self.post()
    def post(self):
        if not self.allowed(True):return self.reply(403,{'error':'Configuration access denied.'})
        if self.headers.get('Content-Type')!='application/json':return self.reply(415,{'error':'JSON required.'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=(3*1024*1024 if self.path.startswith(('/api/vault/','/api/authorise/','/api/synchronisation/','/api/disc/','/api/message/','/api/protected/')) else 16384):raise ValueError('Invalid request size.')
            body=decode(self.rfile.read(n))
            if not isinstance(body,dict):raise ValueError('Invalid settings.')
            if self.path=='/api/protected/open' and set(body)=={'page'}:
                from secure_bridge import call
                return self.reply(200,call('ui.open',body['page']))
            from protected_memory import required,inside
            if required() and not inside() and self.path.startswith(('/api/authorise/','/api/synchronisation/','/api/disc/','/api/message/','/api/vault/')):raise ValueError('Open the protected Bitcoin workspace from Services. Wallet information never passes through the ordinary browser service.')
            if self.path=='/api/protected/close-view' and not body:
                from secure_bridge import call
                return self.reply(200,call('ui.close'))
            if self.path=='/api/protected/stop' and not body:
                from secure_bridge import stop
                return self.reply(200,stop())
            if self.path=='/api/protected/start' and not body:
                if self.server.preview:raise ValueError('Protected operations are disabled in preview mode.')
                from secure_bridge import start
                return self.reply(200,start())
            if self.path.startswith('/api/message/'):
                if self.server.preview:raise ValueError('Message signing is disabled in preview mode.')
                from secure_bridge import call
                actions={'wallets':('message.wallets',()),'prepare':('message.prepare',('wallets','address','message','partial')),'sign':('message.sign',('id',))}
                key=self.path.rsplit('/',1)[-1]
                if key not in actions or set(body)!=set(actions[key][1]):raise ValueError('Invalid message action.')
                name,fields=actions[key];return self.reply(200,call(name,*[body[k] for k in fields],timeout=600))
            if self.path.startswith('/api/disc/'):
                if self.server.preview:raise ValueError('Disc operations are disabled in preview mode.')
                from secure_bridge import call
                if self.path=='/api/disc/read' and set(body)=={'device'}:return self.reply(200,call('disc.read',body['device'],timeout=600))
                if self.path=='/api/disc/load' and set(body)=={'id','confirmed'}:return self.reply(200,call('disc.load',body['id'],body['confirmed'],timeout=120))
                if self.path=='/api/disc/unload' and set(body)=={'id'}:return self.reply(200,call('disc.unload',body['id'],timeout=120))
                if self.path=='/api/disc/drives' and not body:return self.reply(200,call('disc.drives'))
                if self.path=='/api/disc/probe' and set(body)=={'device'}:return self.reply(200,call('disc.probe',body['device']))
                if self.path=='/api/disc/burn' and set(body)=={'device','confirmed','disc_count','speed'}:return self.reply(200,call('disc.burn',body['device'],body['confirmed'],body['disc_count'],body['speed'],timeout=600))
                raise ValueError('Invalid disc action.')
            if self.path=='/api/pick-cookie':return self.reply(200,{'path':picker()})
            if self.path.startswith('/api/synchronisation/'):
                if self.server.preview:raise ValueError('Transfers are disabled in preview mode.')
                from protected_memory import required
                if required():
                    from secure_bridge import call
                    endpoints={'review':('transfer.review',('id',)),'selection':('transfer.selection',('id','selected','watch_only')),'authorise-batch':('transfer.authorise_batch',('fingerprints',)),'end-receiving':('transfer.stop_receiving',()),'recovery-plan':('recovery.plan',()),'recovery-start':('recovery.start',('id',)),'send-batch':('transfer.send_batch',('credentials',)),'firewall':('transfer.firewall',('id',))}
                    action=self.path.rsplit('/',1)[1]
                    if action not in endpoints:raise ValueError('Invalid synchronisation action.')
                    method,fields=endpoints[action]
                    if set(body)!=set(fields):raise ValueError('Invalid synchronisation fields.')
                    return self.reply(200,call(method,*[body[f] for f in fields],timeout=600))
                t=transfer(self.server)
                if self.path=='/api/synchronisation/firewall' and set(body)=={'id'}:
                    if transfer(self.server).state()['id']!=body['id']:raise ValueError('Active request changed.')
                    result=check_firewall(t)
                elif self.path=='/api/synchronisation/review' and set(body)=={'id'}:result=t.review(body['id'])
                elif self.path=='/api/synchronisation/selection' and set(body)=={'id','selected','watch_only'}:
                    from sync_queue import choose
                    choose(t.store,body['id'],body['selected'],body['watch_only']);result={'ok':True}
                elif self.path=='/api/synchronisation/authorise-batch' and set(body)=={'fingerprints'}:result=t.authorise_batch(body['fingerprints'])
                elif self.path=='/api/synchronisation/end-receiving' and not body:result=t.stop_receiving()
                elif self.path=='/api/synchronisation/recovery-plan' and not body:result=t.recovery.plan()
                elif self.path=='/api/synchronisation/recovery-start' and set(body)=={'id'}:
                    if getattr(t,'sending',False):raise ValueError('Finish the sending batch before recovering history.')
                    result=t.recovery.start(body['id'])
                elif self.path=='/api/synchronisation/send-batch' and set(body)=={'credentials'}:
                    if not isinstance(body['credentials'],dict) or len(body['credentials'])>128:raise ValueError('Invalid receiving credentials.')
                    if getattr(t,'sending',False):raise ValueError('A transfer is already in progress.')
                    def send_batch():
                        try:t.send_batch(body['credentials'])
                        except Exception as error:t.error=str(error) if isinstance(error,ValueError) else 'Transfer stopped with an uncertain result. Inspect both Agents before retrying.'
                        finally:
                            for data in body.get('credentials',{}).values():
                                if isinstance(data,dict):data['password']=None
                            t.sending=False
                    t.sending=True;t.error='';threading.Thread(target=send_batch,daemon=True).start();result={'ok':True}
                else:raise ValueError('Invalid synchronisation action.')
                return self.reply(200,result)
            if self.path.startswith('/api/authorise/'):
                if self.server.preview:raise ValueError('Wallet operations are disabled in preview mode.')
                from protected_memory import required
                if required():
                    from secure_bridge import call
                    actions={'disable-sync':('sync.disable',('id',)),'enable-sync':('sync.enable',('id',)),'cancel-sync':('sync.cancel',('id',)),'cancel-setup':('setup.cancel',('id',)),'history':('authorise.history',('id',)),'review':('authorise.review',('id',)),'approve':('authorise.approve',('id',)),'deny':('authorise.deny',('id',)),'forget':('authorise.forget',('id',)),'participate':('setup.participate',('id','pins')),'sign':('wallet.sign',('id','action','fee_ack'))}
                    action=self.path.rsplit('/',1)[1]
                    if action not in actions:raise ValueError('Invalid local authorisation action.')
                    method,fields=actions[action]
                    if set(body)!=set(fields):raise ValueError('Only public authorisation fields are accepted; passphrases are entered in the protected native dialogue.')
                    return self.reply(200,call(method,*[body[f] for f in fields],timeout=600))
                ops=wallet_ops(self.server);store=ops.store
                if self.path=='/api/authorise/review' and set(body)=={'id'}:result=ops.prepare_request(body['id'])
                elif self.path=='/api/authorise/approve' and set(body)=={'id'}:result=ops.approve_sync(body['id'])
                elif self.path=='/api/authorise/deny' and set(body)=={'id'}:store.deny(body['id']);result={'ok':True}
                elif self.path=='/api/authorise/forget' and set(body)=={'id'}:store.forget(body['id']);result={'ok':True}
                else:raise ValueError('Invalid local authorisation action.')
                return self.reply(200,result)

            with self.server.config_lock:
                c=Config();v=copy.deepcopy(c.values)
                if self.path=='/api/hostname':
                    if set(body)!={'hostname'}:raise ValueError('Invalid fields.')
                    v['hostname']=hostname(body['hostname']) if body['hostname'].strip() else ''
                elif self.path=='/api/patch':
                    allowed={'hostname','ssh_user','ssh_port','identity_file','cookie','rpc_port'}
                    if not body or set(body)-allowed:raise ValueError('Invalid settings fields.')
                    if 'hostname' in body:body['hostname']=hostname(body['hostname']) if body['hostname'].strip() else ''
                    if set(body)&{'cookie','rpc_port'} and local_busy(self.server):raise ValueError('Finish synchronisation before changing Core connection settings.')
                    v.update(body);self.server.wallet_ops=None
                elif self.path=='/api/connect':
                    if body:raise ValueError('Invalid connect request.')
                    if not v['hostname']:raise ValueError('Enter a server hostname first.')
                    (runtime_dir()/'connect-request.json').write_text(secrets.token_hex(16))
                elif self.path=='/api/settings':
                    if set(body)!={'ssh_user','ssh_port','identity_file','cookie','rpc_port'}:raise ValueError('Invalid fields.')
                    if set(body)&{'cookie','rpc_port'} and local_busy(self.server):raise ValueError('Finish synchronisation before changing Core connection settings.')
                    v.update(body);self.server.wallet_ops=None
                elif self.path=='/api/toggle':
                    if set(body)!={'service','enabled'} or body['service'] not in SERVICES or type(body['enabled']) is not bool:raise ValueError('Invalid service toggle.')
                    if body['enabled'] and not v['hostname']:raise ValueError('Accept a server name first.')
                    if body['service']=='node' and body['enabled']:
                        from node_lifecycle import closing
                        if closing():raise NodeUnavailable('The previous protected workspace is still closing. Wait for cleanup before reconnecting the node.')
                        require_node(v)
                        if not self.server.preview and required() and not inside():
                            from secure_bridge import start
                            try:
                                start()
                                from secure_bridge import call
                                call('ui.arm')
                            except ValueError as error:
                                write_status('node','red',str(error),stage='workspace',preparation_failed=True)
                                raise NodeUnavailable(str(error)) from None
                            except subprocess.TimeoutExpired:raise NodeUnavailable('Preparing the local protected Bitcoin workspace timed out. Check its status on Services before trying again; the node service was not enabled.') from None
                            except OSError:raise NodeUnavailable('The local protected Bitcoin workspace could not be prepared. Check its system-service status; the node service was not enabled.') from None
                    if body['service']=='node' and not body['enabled'] and not self.server.preview and required() and not inside():
                        from secure_bridge import call
                        try:protected=call('service_status',timeout=3)
                        except ValueError:protected={}
                        if protected.get('busy'):raise NodeUnavailable('Finish active wallet work, wait for queued Dashboard deliveries and unload archival wallets before disconnecting the node. Its protected window remains open.')
                    if body['service']=='node' and not body['enabled']:write_status('node','red','Off',tunnel=False)
                    v['enabled'][body['service']]=body['enabled']
                else:return self.reply(404,{'error':'Not found.'})
                if self.server.preview:c.save(v)
                else:apply_config(c,v)
            self.reply(200,{'ok':True})
        except NodeUnavailable as error:self.reply(400,{'error':str(error)})
        except ValueError as error:self.reply(400,{'error':str(error) if self.path.startswith(('/api/vault/','/api/authorise/','/api/synchronisation/','/api/disc/','/api/message/','/api/protected/')) else 'Check the hostname, settings and file paths. IP addresses are not allowed.'})
        except (TypeError,KeyError):self.reply(400,{'error':'Invalid request or expired review. Refresh this page and review again.'})
        except Exception:self.reply(503,{'error':'The wallet operation failed or its outcome is uncertain. Check Core and review again; it was not automatically replayed.' if self.path.startswith(('/api/vault/','/api/authorise/','/api/synchronisation/','/api/disc/','/api/message/','/api/protected/')) else 'Settings saved, but the user service manager could not apply them. Check systemd --user and try again.'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def get_request(self):
        s,a=super().get_request();s.settimeout(10);return s,a

def serve(preview=False):
    root=runtime_dir();lock=open(root/'ui.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    server=Server(('127.0.0.1',0),Handler);server.token=secrets.token_urlsafe(32);server.config_lock=threading.Lock();server.preview=preview
    info={'port':server.server_port,'token':server.token,'pid':os.getpid(),'version':'2.0.0~dev17'}
    fd=os.open(root/'ui.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(info,f)
    try:server.serve_forever()
    finally:(root/'ui.json').unlink(missing_ok=True)

def bootstrap():
    retire_jellyfin()
    from protected_memory import required
    if required() and Config().values['enabled']['node']:
        from secure_bridge import ensure_running
        try:require_node();ensure_running()
        except (ValueError,subprocess.TimeoutExpired) as error:write_status('node','red',str(error) if isinstance(error,NodeUnavailable) else 'Protected Bitcoin workspace could not start. Open Services to review its setup.',tunnel=False)
    names=[key for key in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SSH_AUTH_SOCK') if key in os.environ]
    if names:ctl('import-environment',*names)
    ctl('daemon-reload')
    try:installed=json.loads((runtime_dir()/'monitor-build.json').read_text()).get('version')
    except (OSError,ValueError):installed=None
    if installed!='2.0.0~dev17':
        ctl('restart','wallaby-agent-monitor.service')
        for kind,on in Config().values['enabled'].items():
            if on:ctl('restart','wallaby-agent-'+kind+'.service')
    ctl('enable','--now','wallaby-agent-monitor.service')

def launch(page='services'):
    bootstrap()
    try:previous=json.loads((runtime_dir()/'ui.json').read_text()).get('version')
    except (OSError,ValueError):previous=None
    ctl('restart' if previous not in (None,'2.0.0~dev17') or (previous is None and (runtime_dir()/'ui.json').exists()) else 'start','wallaby-agent-ui.service')
    for _ in range(50):
        try:
            d=json.loads((runtime_dir()/'ui.json').read_text());os.kill(d['pid'],0)
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',d['port'],timeout=1);conn.request('GET','/api/health',headers={'Authorization':'Bearer '+d['token']});r=conn.getresponse();r.read();conn.close()
            if r.status==200:
                from protected_memory import required
                if required() and page!='services':
                    from secure_bridge import call
                    call('ui.open',page);return
                webbrowser.open(f"http://127.0.0.1:{d['port']}/?page="+page);return
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise RuntimeError('Configuration service did not start.')

if __name__=='__main__':
    os.umask(0o077)
    if os.environ.get('WALLABY_ASKPASS_SOCKET'):askpass();sys.exit(0)
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['configure','authorise','synchronisation','peer-receive','ui','bootstrap','monitor',*SERVICES,'preview'],nargs='?',default='configure');a=p.parse_args()
    if a.mode=='configure':launch()
    elif a.mode=='authorise':launch('authorise')
    elif a.mode=='synchronisation':launch('synchronisation')
    elif a.mode=='peer-receive':peer_receive()
    elif a.mode=='bootstrap':bootstrap()
    elif a.mode=='monitor':monitor()
    elif a.mode in SERVICES:worker(a.mode)
    else:serve(a.mode=='preview')
