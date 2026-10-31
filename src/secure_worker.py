#!/usr/bin/python3
"""Protected local worker. The browser and Dashboard can only submit public messages."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json,os,socket,socketserver,struct,threading,time
from protected_memory import enforce,root
from secure_bridge import receive,ENV
from configuration import Config,discover_cookie
from node_client import Core
from approval_store import Store,digest
from wallet_ops import WalletOps
from wallet_setup import WalletSetup,secret_dialog
from wallet_retirement import Retirement
from batch_transfer import BatchTransfer

def delivery_pending(state):
    """Keep completed operation results until delivered, not background notices.

    Disabled synchronisation and one-off denial are intentional completed user
    choices; their optional status messages must not prevent window closure.
    """
    for item in state['outbox'].values():
        if item['kind'] in ('wallet_sync_preferences','wallet_setup_identity','node_identity','wallet_transfer_preview'):continue
        payload=item['payload']
        signed=payload.get('message',{})
        if payload.get('status')=='denied' or isinstance(signed,dict) and signed.get('status')=='denied':continue
        return True
    return False

class Workspace:
    def __init__(self):
        self.store=Store(root()/ 'state');self.store.identity_root=Config().root
        # Never replay the legacy non-volatile approvals.json into a new workspace.
        # Only the schema-limited denial store survives workspace shutdown.
        self.node=None;self.node_port=None;self.node_generation=None;self.node_stop=None;self.node_status={'color':'red','message':'Node interface is off.'};self.view_server=None;self.view_token=None;self.viewers=[];self.window_required=False;self.closing=False;self.lock=threading.RLock();self.ops=None;self.transfer=None;self.setup=None;self.retirement=None;self.archives=None;self.messages=None;self.environment={}
    def configure(self,environment):
        for key,value in environment.items():
            if key not in ENV or not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value):raise ValueError('Invalid local display environment.')
        self.environment=dict(environment)
        c=Config().values;c['cookie']=c['cookie'] or discover_cookie()
        if self.ops is None or any(self.ops.core.config.get(k)!=c[k] for k in ('cookie','rpc_port')):
            if self.ops and (self.busy() or self.archives and (self.archives.loaded or self.archives.staged)):raise ValueError('Finish protected wallet work before changing the Core connection.')
            if self.node_stop:self.node_stop.set()
            if self.transfer:self.transfer.close()
            self.ops=WalletOps(Core(c),self.store);self.transfer=BatchTransfer(self.ops.core,self.store);self.retirement=Retirement(self.ops.core,self.store);self.setup=WalletSetup(self.ops.core,self.store,self.environment,enforce,self.binary())
            from disc_restore import Archives
            from message_signing import Messages
            self.archives=Archives(self.ops.core,self.store,self.binary(),enforce)
            import node_client
            node_client.LOCAL_ROUTER=self.archives
            self.messages=Messages(self.ops.core,self.store,lambda prompt:secret_dialog(prompt,self.environment))
        self.setup.environment=self.environment
    def binary(self):
        for path in ('/usr/bin/bitcoind','/usr/local/bin/bitcoind','/opt/bitcoin/bin/bitcoind','/snap/bitcoin-core/current/bin/bitcoind','/snap/bitcoin-core/current/usr/bin/bitcoind'):
            if Path(path).is_file():
                with open(path,'rb') as f:
                    if f.read(4)==b'\x7fELF':return path
        return '/usr/bin/bitcoind'
    def busy(self):
        s=self.store.read();return bool(self.archives and (self.archives.reading) or s.get('history_jobs') or getattr(self.transfer,'sending',False) or s.get('sync_batch') or s.get('active_transfer') or s.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning') or self.setup and any(v['phase']!='complete' for v in self.setup.sessions.values()))
    def state(self):
        saved=self.store.read()
        try:self.ops.core.ready();connected=self.node_status['color']=='green'
        except Exception:connected=False
        return {'connected':connected,'pending':[{'id':k,'kind':v['proposal']['kind'],'state':v['state'],'wallet_name':v['proposal'].get('wallet',v['proposal'].get('public_wallet',{}).get('wallet_name',v['proposal'].get('name',v['proposal'].get('proposal',{}).get('name','')))),'direction':v['proposal'].get('direction')} for k,v in saved['pending'].items() if not v.get('withdrawn')],'denied':[{'id':k,'proposal':{'kind':v['proposal']['kind']},'wallet_name':v.get('wallet_name','')} for k,v in saved['denied'].items()],'sync':saved['sync'],'outbox_count':len(saved['outbox']),'transfer':self.transfer.state(),'protected':{'running':True,'viewer':True,**enforce()},'burn':self.setup.burner.state(),'archives':self.archives.state(),'exclusions':list(saved.get('sync_exclusions',{}).values()),'identity':self.setup.own_identity(),'busy':self.busy(),'setups':[{'id':key,'name':v['proposal']['name'],'phase':v['phase']} for key,v in self.setup.sessions.items() if v['phase']!='complete']}
    def service_status(self):
        saved=self.store.read();pending=sorted(k for k,row in saved['pending'].items() if not row.get('withdrawn'));result={'connected':self.node_status['color']=='green','pending':[],'denied':[],'transfer':{},'burn':{},'sync':'Protected Bitcoin workspace is active. Open its protected pages for wallet data.','outbox_count':0,'protected':{'running':True,'viewer':False},'has_approvals':bool(pending or any(v['phase']!='complete' for v in self.setup.sessions.values())),'busy':bool(self.busy() or self.archives.loaded or self.archives.staged or delivery_pending(saved)),'has_burn':bool(self.setup.burner.state().get('id')),'notice':digest(pending),'needs_sync':bool(self.transfer.state().get('rows') or self.transfer.state().get('recovery',{}).get('status') not in (None,'Synchronised')),'window_required':self.window_required,'viewer_open':any(process.poll() is None for process in self.viewers),'identity':self.setup.own_identity()}
        self._service_snapshot=dict(result);return result
    def begin_close(self,deadline=None):
        if self.busy() or self.archives and (self.archives.loaded or self.archives.staged) or delivery_pending(self.store.read()):raise ValueError('Finish active wallet work, wait for queued Dashboard deliveries and unload archival wallets before closing the protected window and disconnecting its node.')
        if deadline is not None and time.monotonic()>=deadline:raise ValueError('Close request expired; no workspace state was changed.')
        self.closing=True
    def close_views(self):
        # Only tracked viewers; the monitor disconnects and stops the worker.
        self.begin_close()
        viewers=[p for p in self.viewers if p.poll() is None]
        for process in viewers:process.terminate()
        for process in viewers:
            try:process.wait(timeout=5)
            except __import__('subprocess').TimeoutExpired:
                process.kill();process.wait(timeout=5)
        self.viewers=[]
        return {'message':'Protected window closed. The node interface will disconnect and its protected workspace will close automatically.'}
    def open_view(self,page):
        if page not in ('authorise','synchronisation','burn','message'):raise ValueError('Invalid protected page.')
        if any(p.poll() is None for p in self.viewers):
            self.window_required=True
            return {'message':'The protected window is already open.'}
        import secrets,importlib.util
        try:available=importlib.util.find_spec('PyQt6.QtWebEngineWidgets')
        except ModuleNotFoundError:available=None
        if available is None:raise ValueError('The protected HTML5 viewer is unavailable. Install optional python3-pyqt6 and python3-pyqt6.qtwebengine packages; wallet data will not be opened in an ordinary browser.')
        if self.view_server is None:
            from app import Server,Handler
            owner=self
            class ProtectedHandler(Handler):
                def allowed(self,auth=False):
                    import hmac
                    return hmac.compare_digest(self.headers.get('X-Wallaby-Protected-View',''),owner.view_token) and super().allowed(auth)
            self.view_token=secrets.token_urlsafe(32);server=Server(('127.0.0.1',0),ProtectedHandler);server.token=secrets.token_urlsafe(32);server.config_lock=threading.Lock();server.preview=False;self.view_server=server
            threading.Thread(target=server.serve_forever,daemon=True).start()
        config={'origin':'http://127.0.0.1:'+str(self.view_server.server_port),'page':page,'token':self.view_token}
        env={**os.environ,**self.environment};process=__import__('subprocess').Popen(['/usr/bin/python3','-I','-B',str(Path(__file__).with_name('protected_viewer.py'))],stdin=__import__('subprocess').PIPE,stdout=__import__('subprocess').DEVNULL,stderr=__import__('subprocess').DEVNULL,env=env)
        process.stdin.write(json.dumps(config).encode()+b'\n');process.stdin.close();self.viewers=[p for p in self.viewers if p.poll() is None]+[process];self.window_required=True
        return {'message':'Opened the protected Bitcoin workspace.'}
    def dispatch(self,method,args,environment):
        if method=='ui.prepare_close':
            if len(args)!=1 or type(args[0]) not in (int,float) or not time.monotonic()<args[0]<time.monotonic()+8:raise ValueError('Close request expired; no workspace state was changed.')
            if not self.lock.acquire(blocking=False):raise ValueError('Finish the active protected operation before closing.')
            try:
                enforce();self.begin_close(args[0]);return {'ok':True}
            finally:self.lock.release()
        if method in ('node.status','node.stop'):
            enforce()
            if len(args)!=1 or args[0]!=self.node_generation:return {'color':'red','message':'Node session changed. Reconnecting.','failed':True}
            if method=='node.stop':
                if self.node_stop:self.node_stop.set()
                return {'ok':True}
            return dict(self.node_status)
        if method=='service_status':
            # Do not queue ordinary-window liveness behind a native passphrase
            # dialogue/signing operation. This reply contains public flags only.
            if not self.lock.acquire(blocking=False):
                enforce()
                result=dict(getattr(self,'_service_snapshot',{'pending':[],'denied':[],'transfer':{},'burn':{},'outbox_count':0}))
                result.update(connected=self.node_status['color']=='green',protected={'running':True,'viewer':False},busy=True,window_required=getattr(self,'window_required',False),viewer_open=any(p.poll() is None for p in self.viewers),sync='A protected operation is in progress. Continue in the protected window.')
                return result
            try:
                enforce();self.configure(environment);return self.service_status()
            finally:self.lock.release()
        with self.lock:
            enforce();self.configure(environment)
            if getattr(self,'closing',False) and method not in ('ui.arm','ui.close'):raise ValueError('The protected workspace is closing. Reconnect the node before starting another operation.')
            saved=self.store.read()
            changing=method in ('wallet.sign','authorise.approve','setup.participate','authorise.history','setup.cancel')
            if changing and (saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning')):raise ValueError('Finish the active transfer or history recovery first.')
            if method in ('wallet.sign','setup.participate','authorise.approve','message.sign') and self.archives and self.archives.reading:raise ValueError('Wait for optical restoration to finish before signing or changing wallets.')
            if saved.get('setup_active') and method in ('wallet.sign','authorise.approve','authorise.history','authorise.review'):
                candidate=saved['pending'].get(args[0],{}).get('proposal',{}) if args else {}
                if candidate.get('kind')!='wallet_setup_policy' or digest(candidate['proposal'])!=saved['setup_active']:raise ValueError('Finish the current wallet setup and its physical backups first.')
            if method=='service_status':return self.service_status()
            if method=='ui.arm':
                self.closing=False
                if not any(p.poll() is None for p in self.viewers):self.window_required=False
                return {'ok':True}
            if method=='ui.open':return self.open_view(*args)
            if method=='ui.close':return self.close_views()
            if method=='node.start':
                port=args[0]
                if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid node tunnel port.')
                if self.node and self.node.is_alive():
                    if port!=self.node_port or self.node_stop.is_set():raise ValueError('Previous node session is still closing.')
                    return {'session':self.node_generation}
                self.node_generation=__import__('secrets').token_hex(16);self.node_stop=threading.Event();self.node_port=port;self.node_status={'color':'amber','message':'Connecting the protected node interface.'}
                from node_client import NodeClient
                from diagnostics import describe
                def status(color,message):self.node_status={'color':color,'message':message}
                def work():
                    try:NodeClient(self.ops.core.config,port,self.node_stop,status).run()
                    except Exception as error:
                        failure=describe('rpc',error);self.node_status={'color':'red','message':str(failure),'failure':failure.detail(),'failed':True}
                self.node=threading.Thread(target=work,daemon=True);self.node.start();return {'session':self.node_generation}
            if method=='status':return self.state()
            if method=='core.health':self.ops.core.ready();return {'ok':True}
            if method=='core.public':
                from agent_rpc import request
                ident,name,params,wallet,timeout=args;validated,_=request(name,params,wallet)
                if self.busy():return {'error':{'code':'synchronisation_busy','message':'A locally authorised wallet operation is active.'}}
                return self.ops.core.call(ident,name,validated,wallet,timeout)
            if method=='exchange':
                from agent_exchange import Exchange
                if len(args)!=2 or type(args[0]) is not int or not 1<=args[0]<=65535 or not isinstance(args[1],str) or len(args[1])>4096:raise ValueError('Invalid exchange connection.')
                Exchange(args[0],args[1],self.store).once();return {'ok':True}
            if method=='authorise.review':
                kind=self.store.read()['pending'][args[0]]['proposal']['kind']
                if kind=='wallet_retire':return self.retirement.review(args[0])
                if kind.startswith('wallet_setup'):return self.setup.review(args[0])
                return self.ops.prepare_request(args[0])
            if method=='authorise.history':return self.retirement.prepare_history(*args)
            if method=='authorise.deny':
                p=self.store.read()['pending'][args[0]]['proposal']
                if p['kind'].startswith('wallet_setup'):self.setup.decline(args[0])
                else:self.store.deny(*args)
                return {'ok':True}
            if method=='authorise.forget':self.store.forget(*args);return {'ok':True}
            if method=='authorise.approve':
                kind=self.store.read()['pending'][args[0]]['proposal']['kind']
                if kind=='wallet_retire':return self.retirement.approve(args[0])
                if kind=='wallet_setup_policy':return self.setup.approve_policy(args[0])
                return self.ops.approve_sync(args[0])
            if method=='setup.cancel':return self.setup.cancel(*args)
            if method=='setup.participate':return self.setup.approve_proposal(*args)
            if method in ('disc.read','disc.load','disc.unload','message.wallets','message.prepare','message.sign'):
                if self.node_status['color']!='green':raise ValueError('Connect the Bitcoin Core Node Dashboard Interface before using Disc Operations or Sign Message.')
                if saved.get('setup_active') or saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'):raise ValueError('Finish the current wallet setup, transfer or history operation first.')
            if method=='disc.read':
                if self.archives.reading:raise ValueError('An optical read is already active.')
                password=secret_dialog('Disc-backup passphrase · decrypt the selected recovery package (not your Core wallet passphrase)',self.environment)
                self.archives.reading=True;self.archives.error='';self.archives.message='Reading encrypted optical recovery copies.'
                def read_disc():
                    nonlocal password
                    try:self.archives.inspect(args[0],password);self.archives.message='Read complete. Review the policy below before loading its signing key.'
                    except Exception as error:self.archives.error=str(error) if isinstance(error,ValueError) else 'Optical restoration stopped. No archive was loaded; try another disc or drive.'
                    finally:password=None;self.archives.reading=False
                threading.Thread(target=read_disc,daemon=True).start();return {'message':'Disc reading started. Damaged copies will be skipped automatically.'}
            if method=='disc.load':return self.archives.load(*args)
            if method=='disc.unload':
                if self.archives.reading:raise ValueError('Wait for the current optical read to finish.')
                self.ops.prepared.clear();self.messages.prepared.clear();return self.archives.unload(*args)
            if method=='message.wallets':return self.messages.wallets()
            if method=='message.prepare':return self.messages.prepare(*args)
            if method=='message.sign':return self.messages.sign(*args)
            if method=='sync.disable':
                from sync_preferences import change
                return change(self.store,args[0],True)
            if method=='sync.enable':
                from sync_preferences import enable
                return enable(self.store,*args)
            if method=='sync.cancel':
                from sync_preferences import cancel
                return cancel(self.store,*args)
            if method=='disc.burn':return self.setup.burn(*args)
            if method=='disc.probe':
                from disc_backup import media
                return media(*args)
            if method=='disc.drives':return [{'device':'/dev/'+p.name,'name':(p/'device/model').read_text().strip()} for p in Path('/sys/class/block').glob('sr[0-9]*')]
            if method=='wallet.sign':
                key,action,fee_ack=args
                if type(fee_ack) is not bool:raise ValueError('Invalid local fee acknowledgement.')
                if action not in ('partial','broadcast'):raise ValueError('Vault Builder has moved to Dashboard. Only reviewed transaction signing or broadcast is available.')
                prepared=self.ops.prepared.get(key,{})
                if not prepared:raise ValueError('Review this transaction again before authorising it.')
                if prepared['review']['fee_review']['requires_ack'] and not fee_ack:raise ValueError('Acknowledge the high fee locally before entering a wallet passphrase.')
                info=__import__('wallet_ops').rpc(self.ops.core,'getwalletinfo',[],prepared['wallet']) if action=='partial' else {}
                encrypted='unlocked_until' in info
                prompt='Bitcoin Core wallet passphrase · sign the reviewed transaction\nCore wallet: '+json.dumps(info.get('walletname',''),ensure_ascii=False)+'\nLocal signing account: '+json.dumps(prepared['wallet'],ensure_ascii=False)
                password=secret_dialog(prompt,self.environment) if encrypted else ''
                try:return self.ops.sign(key,password,action,fee_ack)
                finally:password=None
            if method.startswith('transfer.'):
                name=method.split('.',1)[1]
                if name=='firewall':
                    from peer_wallet import check_firewall
                    return check_firewall(self.transfer)
                if name=='selection':
                    from sync_queue import choose
                    choose(self.store,*args);return {'ok':True}
                if name=='send_batch':
                    if self.transfer.sending:raise ValueError('A sending batch is already active.')
                    def send():
                        try:self.transfer.send_batch(*args)
                        except Exception as e:self.transfer.error=str(e) if isinstance(e,ValueError) else 'Transfer stopped with an uncertain result. Inspect both Agents.'
                        finally:self.transfer.sending=False
                    self.transfer.sending=True;threading.Thread(target=send,daemon=True).start();return {'ok':True}
                if name not in ('state','review','authorise_batch','stop_receiving'):raise ValueError('Invalid local transfer action.')
                return getattr(self.transfer,name)(*args)
            if method.startswith('recovery.'):
                name=method.split('.',1)[1]
                if name not in ('plan','start'):raise ValueError('Invalid local history action.')
                return getattr(self.transfer.recovery,name)(*args)
            raise ValueError('Unsupported protected action.')

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            uid=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if uid!=os.getuid():return
            self.request.settimeout(600);n=int.from_bytes(receive(self.request,4),'big')
            if not 0<n<=20*1024*1024:raise ValueError('Invalid protected request size.')
            from node_client import decode
            p=decode(receive(self.request,n))
            if not isinstance(p,dict) or set(p)!={'method','args','environment'} or not isinstance(p['method'],str) or not isinstance(p['args'],list) or len(p['args'])>8 or not isinstance(p['environment'],dict):raise ValueError('Invalid protected action.')
            result=self.server.workspace.dispatch(p['method'],p['args'],p['environment']);reply={'result':result}
        except Exception as e:reply={'error':str(e) if isinstance(e,ValueError) else 'Protected operation stopped or is uncertain. Inspect local state; it was not automatically repeated.'}
        raw=json.dumps(reply,allow_nan=False).encode();self.request.sendall(struct.pack('!I',len(raw))+raw)

class Server(socketserver.ThreadingUnixStreamServer):daemon_threads=True

def main():
    os.umask(0o077);enforce();os.environ['TMPDIR']=str(root());os.environ['PYTHONDONTWRITEBYTECODE']='1'
    import tempfile
    tempfile.tempdir=str(root());path=root()/'worker.sock';path.unlink(missing_ok=True)
    from protected_peer import start
    peer_server=start()
    server=Server(str(path),Handler);path.chmod(0o600);server.workspace=Workspace();server.serve_forever()

if __name__=='__main__':main()
