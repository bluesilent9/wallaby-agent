#!/usr/bin/python3
"""Wallaby Agent V2 entry point and authenticated loopback configuration page."""
import argparse, copy, fcntl, hmac, json, os, secrets, shutil, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from node_client import Core,decode
from wallet_ops import WalletOps
from approval_store import Store
from block_clock import timezones_with_offsets
from configuration import Config,hostname,discover_cookie,SERVICES
from runtime import runtime_dir,read_status,write_status,apply_config,ctl,worker,monitor,retire_jellyfin

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
    v=Config().values
    if not v['cookie']:v['cookie']=discover_cookie()
    existing=getattr(server,'wallet_ops',None)
    if existing is None or any(existing.core.config.get(k)!=v[k] for k in ('cookie','rpc_port')):
        server.wallet_ops=WalletOps(Core(v))
    return server.wallet_ops

def workspace(server):
    (runtime_dir()/'ui-seen.json').write_text(json.dumps({'at':time.time()}))
    saved=wallet_ops(server).store.read()
    try:
        wallet_ops(server).core.ready();connected=True
    except Exception:connected=False
    return {'connected':connected,'pending':[{"id":k,'kind':v['proposal']['kind'],'state':v['state']} for k,v in saved['pending'].items()],
            'denied':[{"id":k,'proposal':{'kind':v['proposal']['kind'],**({'vault':v['proposal']['vault']} if v['proposal']['kind']=='vault_sync' else {})}} for k,v in saved['denied'].items()],'sync':saved['sync'],'outbox_count':len(saved['outbox'])}

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
        if self.path=='/api/health':return self.reply(200,{'ok':True,'version':'2.0.0~dev6'})
        if self.path=='/api/state':
            with self.server.config_lock:
                c=Config();v=copy.deepcopy(c.values)
                if not v['cookie']:
                    cookie=discover_cookie()
                    if cookie:v['cookie']=cookie;c.save(v)
                return self.reply(200,{'config':v,'status':{k:read_status(k) for k in ['server',*SERVICES]},'version':'V2 Development build 6','workspace':workspace(self.server)})
        if self.path.startswith('/api/timezones?'):
            try:return self.reply(200,timezones_with_offsets(int(parse_qs(urlsplit(self.path).query).get('year',['2026'])[0])))
            except ValueError:return self.reply(400,{'error':'Choose a valid calendar year.'})
        if self.path=='/api/wallets':
            try:return self.reply(200,wallet_ops(self.server).list_wallets())
            except Exception:return self.reply(503,{'error':'Connect local Bitcoin Core RPC first. Check the cookie and RPC port on Services.'})
        paths={'/':'index.html','/app.js':'app.js','/workspace.js':'workspace.js','/timezones.json':'timezones.json','/style.css':'style.css','/wallaby-agent.svg':'wallaby-agent.svg'}
        asset_path=urlsplit(self.path).path
        if asset_path not in paths:return self.reply(404,{'error':'Not found.'})
        f=ASSETS/paths[asset_path];mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.json':'application/json; charset=utf-8'}[f.suffix]
        self.reply(200,f.read_bytes(),mime)
    def do_POST(self):
        if not self.allowed(True):return self.reply(403,{'error':'Configuration access denied.'})
        if self.headers.get('Content-Type')!='application/json':return self.reply(415,{'error':'JSON required.'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=(3*1024*1024 if self.path.startswith(('/api/vault/','/api/authorise/')) else 16384):raise ValueError('Invalid request size.')
            body=decode(self.rfile.read(n))
            if not isinstance(body,dict):raise ValueError('Invalid settings.')
            if self.path=='/api/pick-cookie':return self.reply(200,{'path':picker()})
            if self.path.startswith(('/api/vault/','/api/authorise/')):
                ops=wallet_ops(self.server);store=ops.store
                if self.server.preview:raise ValueError('Wallet operations are disabled in preview mode.')
                if self.path=='/api/vault/build' and set(body)=={'source','destination','fee_rate','date','timezone'}:
                    result=ops.build(body['source'],body['destination'],body['fee_rate'],body['date'],body['timezone'])
                elif self.path=='/api/vault/sign' and set(body)=={'id','password','action'}:
                    if not isinstance(body['password'],str) or len(body['password'])>1024:raise ValueError('Invalid wallet passphrase.')
                    result=ops.sign(body['id'],body['password'],body['action'])
                elif self.path=='/api/authorise/review' and set(body)=={'id'}:result=ops.prepare_request(body['id'])
                elif self.path=='/api/authorise/approve' and set(body)=={'id'}:result=ops.approve_sync(body['id'])
                elif self.path=='/api/authorise/deny' and set(body)=={'id'}:store.deny(body['id']);result={'ok':True}
                elif self.path=='/api/authorise/forget' and set(body)=={'id'}:store.forget(body['id']);result={'ok':True}
                else:raise ValueError('Invalid local approval action or fields.')
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
                    v.update(body);self.server.wallet_ops=None
                elif self.path=='/api/connect':
                    if body:raise ValueError('Invalid connect request.')
                    if not v['hostname']:raise ValueError('Enter a server hostname first.')
                    (runtime_dir()/'connect-request.json').write_text(secrets.token_hex(16))
                elif self.path=='/api/settings':
                    if set(body)!={'ssh_user','ssh_port','identity_file','cookie','rpc_port'}:raise ValueError('Invalid fields.')
                    v.update(body);self.server.wallet_ops=None
                elif self.path=='/api/toggle':
                    if set(body)!={'service','enabled'} or body['service'] not in SERVICES or type(body['enabled']) is not bool:raise ValueError('Invalid service toggle.')
                    if body['enabled'] and not v['hostname']:raise ValueError('Accept a server name first.')
                    v['enabled'][body['service']]=body['enabled']
                else:return self.reply(404,{'error':'Not found.'})
                if self.server.preview:c.save(v)
                else:apply_config(c,v)
            self.reply(200,{'ok':True})
        except ValueError as error:self.reply(400,{'error':str(error) if self.path.startswith(('/api/vault/','/api/authorise/')) else 'Check the hostname, settings and file paths. IP addresses are not allowed.'})
        except (TypeError,KeyError):self.reply(400,{'error':'Invalid request or expired review. Refresh this page and review again.'})
        except Exception:self.reply(503,{'error':'The wallet operation failed or its outcome is uncertain. Check Core and review again; it was not automatically replayed.' if self.path.startswith(('/api/vault/','/api/authorise/')) else 'Settings saved, but the user service manager could not apply them. Check systemd --user and try again.'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def get_request(self):
        s,a=super().get_request();s.settimeout(10);return s,a

def serve(preview=False):
    root=runtime_dir();lock=open(root/'ui.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    server=Server(('127.0.0.1',0),Handler);server.token=secrets.token_urlsafe(32);server.config_lock=threading.Lock();server.preview=preview
    info={'port':server.server_port,'token':server.token,'pid':os.getpid(),'version':'2.0.0~dev6'}
    fd=os.open(root/'ui.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(info,f)
    try:server.serve_forever()
    finally:(root/'ui.json').unlink(missing_ok=True)

def bootstrap():
    retire_jellyfin()
    names=[key for key in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SSH_AUTH_SOCK') if key in os.environ]
    if names:ctl('import-environment',*names)
    ctl('daemon-reload')
    try:installed=json.loads((runtime_dir()/'monitor-build.json').read_text()).get('version')
    except (OSError,ValueError):installed=None
    if installed!='2.0.0~dev6':
        ctl('restart','wallaby-agent-monitor.service')
        for kind,on in Config().values['enabled'].items():
            if on:ctl('restart','wallaby-agent-'+kind+'.service')
    ctl('enable','--now','wallaby-agent-monitor.service')

def launch(page='services'):
    bootstrap()
    try:previous=json.loads((runtime_dir()/'ui.json').read_text()).get('version')
    except (OSError,ValueError):previous=None
    ctl('restart' if previous not in (None,'2.0.0~dev6') or (previous is None and (runtime_dir()/'ui.json').exists()) else 'start','wallaby-agent-ui.service')
    for _ in range(50):
        try:
            d=json.loads((runtime_dir()/'ui.json').read_text());os.kill(d['pid'],0)
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',d['port'],timeout=1);conn.request('GET','/api/health',headers={'Authorization':'Bearer '+d['token']});r=conn.getresponse();r.read();conn.close()
            if r.status==200:
                webbrowser.open(f"http://127.0.0.1:{d['port']}/?page="+page);return
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise RuntimeError('Configuration service did not start.')

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['configure','authorise','ui','bootstrap','monitor',*SERVICES,'preview'],nargs='?',default='configure');a=p.parse_args()
    if a.mode=='configure':launch()
    elif a.mode=='authorise':launch('authorise')
    elif a.mode=='bootstrap':bootstrap()
    elif a.mode=='monitor':monitor()
    elif a.mode in SERVICES:worker(a.mode)
    else:serve(a.mode=='preview')
