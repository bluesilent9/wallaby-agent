#!/usr/bin/python3
"""Wallaby Agent V1 entry point and authenticated loopback configuration page."""
import argparse, copy, fcntl, hmac, json, os, secrets, shutil, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from configuration import Config,hostname,discover_cookie,SERVICES
from runtime import runtime_dir,read_status,write_status,apply_config,ctl,worker,monitor

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
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':return False
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://127.0.0.1:{self.server.server_port}':return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return False
        if auth and not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):return False
        return True
    def do_GET(self):
        if not self.allowed(self.path.startswith('/api/')):return self.reply(403,{'error':'Open configuration using the Utilities menu shortcut.'})
        if self.path=='/api/state':
            with self.server.config_lock:
                c=Config();v=copy.deepcopy(c.values)
                if not v['cookie']:
                    cookie=discover_cookie()
                    if cookie:v['cookie']=cookie;c.save(v)
                return self.reply(200,{'config':v,'status':{k:read_status(k) for k in ['server',*SERVICES]},'version':'V1 Development'})
        paths={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/wallaby-agent.svg':'wallaby-agent.svg'}
        if self.path not in paths:return self.reply(404,{'error':'Not found.'})
        f=ASSETS/paths[self.path];mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'}[f.suffix]
        self.reply(200,f.read_bytes(),mime)
    def do_POST(self):
        if not self.allowed(True):return self.reply(403,{'error':'Configuration access denied.'})
        if self.headers.get('Content-Type')!='application/json':return self.reply(415,{'error':'JSON required.'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=16384:raise ValueError('Invalid request size.')
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict):raise ValueError('Invalid settings.')
            if self.path=='/api/pick-cookie':return self.reply(200,{'path':picker()})
            with self.server.config_lock:
                c=Config();v=copy.deepcopy(c.values)
                if self.path=='/api/hostname':
                    if set(body)!={'hostname'}:raise ValueError('Invalid fields.')
                    v['hostname']=hostname(body['hostname'])
                elif self.path=='/api/settings':
                    if set(body)!={'ssh_user','ssh_port','identity_file','cookie','rpc_port'}:raise ValueError('Invalid fields.')
                    v.update(body)
                elif self.path=='/api/toggle':
                    if set(body)!={'service','enabled'} or body['service'] not in SERVICES or type(body['enabled']) is not bool:raise ValueError('Invalid service toggle.')
                    if body['enabled'] and not v['hostname']:raise ValueError('Accept a server name first.')
                    v['enabled'][body['service']]=body['enabled']
                else:return self.reply(404,{'error':'Not found.'})
                if self.server.preview:c.save(v)
                else:apply_config(c,v)
            self.reply(200,{'ok':True})
        except (ValueError,TypeError,KeyError):self.reply(400,{'error':'Check the hostname, settings and file paths. IP addresses are not allowed.'})
        except Exception:self.reply(503,{'error':'Settings saved, but the user service manager could not apply them. Check systemd --user and try again.'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def get_request(self):
        s,a=super().get_request();s.settimeout(10);return s,a

def serve(preview=False):
    root=runtime_dir();lock=open(root/'ui.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    server=Server(('127.0.0.1',0),Handler);server.token=secrets.token_urlsafe(32);server.config_lock=threading.Lock();server.preview=preview
    info={'port':server.server_port,'token':server.token,'pid':os.getpid()}
    fd=os.open(root/'ui.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(info,f)
    try:server.serve_forever()
    finally:(root/'ui.json').unlink(missing_ok=True)

def bootstrap():
    names=[key for key in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SSH_AUTH_SOCK') if key in os.environ]
    if names:ctl('import-environment',*names)
    ctl('daemon-reload');ctl('enable','--now','wallaby-agent-monitor.service')

def launch():
    bootstrap();ctl('start','wallaby-agent-ui.service')
    for _ in range(50):
        try:
            d=json.loads((runtime_dir()/'ui.json').read_text());os.kill(d['pid'],0)
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',d['port'],timeout=1);conn.request('GET','/api/state',headers={'Authorization':'Bearer '+d['token']});r=conn.getresponse();r.read();conn.close()
            if r.status==200:
                webbrowser.open(f"http://127.0.0.1:{d['port']}/#"+d['token']);return
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise RuntimeError('Configuration service did not start.')

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['configure','ui','bootstrap','monitor','jellyfin','ddns','node','preview'],nargs='?',default='configure');a=p.parse_args()
    if a.mode=='configure':launch()
    elif a.mode=='bootstrap':bootstrap()
    elif a.mode=='monitor':monitor()
    elif a.mode in SERVICES:worker(a.mode)
    else:serve(a.mode=='preview')
