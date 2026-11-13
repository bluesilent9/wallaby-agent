#!/usr/bin/python3
"""Protected local worker. The browser and Wallet Server can only submit public messages."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json,os,socket,socketserver,struct,threading,time
from decimal import Decimal
from protected_memory import enforce,root
from secure_bridge import receive,ENV
from worker_upgrade import VERSION,PROTOCOL
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
        if item['kind'] in ('wallet_sync_preferences','wallet_setup_identity','node_identity','wallet_transfer_preview','wallet_mobile_verification_record'):continue
        payload=item['payload']
        # Retirement cancellation is an explicit outcome the Wallet Server must flag;
        # retain it until acknowledged, unlike optional sync denial notices.
        if item['kind']=='wallet_retirement_result':return True
        signed=payload.get('message',{})
        if payload.get('status')=='denied' or isinstance(signed,dict) and signed.get('status')=='denied':continue
        return True
    return False

class Workspace:
    def __init__(self):
        from node_recovery import Recovery
        self.recovery=Recovery();self.node_epoch=0;self.node_control_lock=threading.RLock();self.node_controller=None;self.peer_start_lock=threading.Lock()
        self.store=Store(root()/ 'state');self.store.identity_root=Config().root
        # Never replay the legacy non-volatile approvals.json into a new workspace.
        # Only the schema-limited denial store survives workspace shutdown.
        self.node=None;self.node_port=None;self.node_generation=None;self.node_stop=None;self.node_status={'color':'red','message':'Node interface is off.'};self.view_server=None;self.view_token=None;self.viewers=[];self.window_required=False;self.closing=False;self.lock=threading.RLock();self.ops=None;self.transfer=None;self.setup=None;self.retirement=None;self.cancellations=None;self.archives=None;self.messages=None;self.environment={};self.archive_ops=None;self.refresh_ops=None;self.renames=None
    def configure(self,environment):
        for key,value in environment.items():
            if key not in ENV or not isinstance(value,str) or len(value)>4096 or any(ord(c)<32 for c in value):raise ValueError('Invalid local display environment.')
        # Protected HTTP/background callers inherit the system service environment,
        # which lacks the desktop display supplied when the viewer was opened.
        # Keep that authenticated local context; only validated nonempty updates
        # replace it. Never admit arbitrary process/environment variables.
        self.environment.update({key:value for key,value in environment.items() if value})
        c=Config().values;c['cookie']=c['cookie'] or discover_cookie()
        if not c['cookie'] and self.ops and self.planned_core_restart():c['cookie']=self.ops.core.config['cookie']
        if self.ops is None or any(self.ops.core.config.get(k)!=c[k] for k in ('cookie','rpc_port')):
            if self.ops and (self.store.read().get('chain_sync',{}).get('mode')=='ssh_only' or self.busy() or self.archives and (self.archives.loaded or self.archives.staged)):raise ValueError('Finish protected wallet work before changing the Core connection.')
            if self.node_stop:self.node_stop.set()
            if self.transfer:self.transfer.close()
            self.ops=WalletOps(Core(c),self.store);self.ops.core.managed_store=self.store
            from automatic_broadcast import Broadcasts
            self.broadcasts=Broadcasts(self.ops.core,self.store,lambda:not getattr(self,'closing',False) and not self.recovery_state().get('active'))
            self.transfer=BatchTransfer(self.ops.core,self.store);self.retirement=Retirement(self.ops.core,self.store);self.setup=WalletSetup(self.ops.core,self.store,self.environment,enforce,self.binary())
            from disc_restore import Archives
            from message_signing import Messages
            self.archives=Archives(self.ops.core,self.store,self.binary(),enforce)
            import node_client
            node_client.LOCAL_ROUTER=self.archives
            node_client.LOCAL_PUBLIC_RPC=self.public_rpc
            from archive_operations import Operations
            from policy_refresh import Refresh
            self.archive_ops=Operations(self.ops.core,self.store,self.setup,self.archives,enforce);self.refresh_ops=Refresh(self.ops.core,self.store,self.archives)
            self.refresh_ops.archive_ops=self.archive_ops
            from background_review import Reviews
            self.public_reviews=Reviews(self)
            from rename_requests import Renames
            self.renames=Renames(self.ops.core,self.store,self.archives,self.archive_ops,self.rename_guard,self.rename_reconcile_guard)
            from local_wallets import LocalWallets
            self.local_wallets=LocalWallets(self.ops.core,self.rename_guard)
            self.messages=Messages(self.ops.core,self.store,lambda prompt:secret_dialog(prompt,self.environment))
            from cancellation import Cancellations
            self.cancellations=Cancellations(self.ops.core,self.store,self.setup,self.ops,self.environment)
            self.cancellations.archives=self.archives;self.cancellations.archive_ops=self.archive_ops
            import agent_exchange
            agent_exchange.LOCAL_CANCELLATIONS=self.cancellations
            agent_exchange.LOCAL_RETIREMENT=self.retirement
            agent_exchange.LOCAL_ARCHIVES=self.archive_ops
            agent_exchange.LOCAL_BROADCASTS=self.broadcasts
        if getattr(getattr(self,'peers',None),'blocks',None):
            if getattr(self.peers,'wallet_pull',None):self.peers.wallet_pull.transfer=self.transfer
            self.peers.blocks.core=self.ops.core;self.peers.blocks.clones.core=self.ops.core;self.peers.blocks.clones.recovery=self.transfer.recovery
        self.start_peer_support()
        self.setup.environment=self.environment
        if getattr(self,'archives',None):self.archives.environment=self.environment
        if getattr(self,'refresh_ops',None):self.refresh_ops.environment=self.environment
        if self.cancellations:self.cancellations.environment=self.environment
    def start_peer_support(self):
        # Optional peer services must never hold node startup/status hostage.
        with self.peer_start_lock:
            if getattr(self,'peers',None) or getattr(self,'peer_starting',False) or time.monotonic()<getattr(self,'peer_retry_at',0) or self.closing:return
            self.peer_starting=True;self.peer_retry_at=time.monotonic()+30
        def initialise():
            candidate=None
            try:
                from peer_channels import Peers
                from relay_stream import Bridge
                from direct_peers import Direct
                candidate=Peers(self.store)
                candidate.wallet_bridge=Bridge(candidate,self.store);direct=Direct(candidate)
                from block_download import Blocks
                candidate.blocks=Blocks(candidate,self.store,self.ops.core)
                from wallet_pull import Pull
                candidate.wallet_pull=Pull(candidate,self.transfer,self.lock,lambda:bool(self.closing or self.busy() or self.archives.reading or self.ops.prepared))
                from retirement_remote import Comparisons
                candidate.retirement_compare=Comparisons(candidate,self.ops.core,self.lock,lambda:bool(self.closing or self.busy() or self.archives.reading or self.ops.prepared))
                candidate.blocks.clones.operation_lock=self.lock
                candidate.blocks.clones.recovery=self.transfer.recovery
                candidate.blocks.clones.handoff_guard=lambda:bool(self.busy(ignore_history=True) or self.archives.loaded or self.archives.staged or self.ops.prepared)
                candidate.blocks.clones.guard=lambda:bool(self.busy() or self.archives.loaded or self.archives.staged or self.ops.prepared)
                with self.lock:
                    if self.closing:
                        candidate.close();self.store.peers=None;return
                    self.peers=candidate;self.peer_error='';direct.start()
            except Exception:
                if candidate:
                    try:candidate.close()
                    except (ValueError,OSError):pass
                if getattr(self.store,'peers',None) is candidate:self.store.peers=None
                self.peer_error='Peer connections are unavailable. Check the local peer-trust service. Node access and local wallet work remain available; no peer trust was reset.'
            finally:self.peer_starting=False
        threading.Thread(target=initialise,daemon=True,name='optional-peer-support').start()
    def peer_action(self,name,data):
        self.start_peer_support()
        if not getattr(self,'peers',None):
            if name=='status' and not data:
                identity=self.setup.own_identity()
                return {'available':False,'identity':{'identity_key':identity['public_key']},'pairs':[],'pending':[],'registered':False,'error':getattr(self,'peer_error','Checking the local peer-trust service…')}
            raise ValueError(getattr(self,'peer_error','Peer connections are starting. Wait for their local status before pairing or transferring.'))
        from peer_actions import action
        return action(self,name,data)
    def binary(self):
        for path in ('/usr/bin/bitcoind','/usr/local/bin/bitcoind','/opt/bitcoin/bin/bitcoind','/snap/bitcoin-core/current/bin/bitcoind','/snap/bitcoin-core/current/usr/bin/bitcoind'):
            if Path(path).is_file():
                with open(path,'rb') as f:
                    if f.read(4)==b'\x7fELF':return path
        return '/usr/bin/bitcoind'
    def rename_guard(self):
        enforce()
        if self.busy() or self.archives.reading or self.ops.prepared:raise ValueError('Finish active wallet work, prepared signing reviews and archive staging before renaming a wallet.')
    def rename_reconcile_guard(self,key):
        enforce()
        if self.busy(ignore_rename=key) or self.archives.reading or self.ops.prepared:raise ValueError('Finish other active wallet work before reconciling this rename.')
    def busy(self,ignore_rename=None,public_reads=False,ignore_history=False):
        s=self.store.read();archives=getattr(self,'archive_ops',None)
        archive_busy=bool(archives and (any(v['phase'] not in ('queued','complete') for v in archives.jobs.values()) if public_reads else archives.busy()))
        sessions=getattr(self.setup,'sessions',{}) if self.setup else {}
        setup_busy=any(v['phase'] not in (('complete','contributed','awaiting_disc') if public_reads else ('complete',)) for v in sessions.values())
        burner=getattr(self.setup,'burner',None)
        # Optical writing uses an already captured encrypted package. It does
        # not mutate Core wallets or make read-only inventory unavailable.
        writing=False
        active=s.get('setup_active')
        setup_reserved=bool(active and (active not in sessions or sessions[active]['phase'] not in ('contributed','awaiting_disc','complete')))
        return bool((not public_reads and (s.get('block_download',{}).get('running') or getattr(getattr(getattr(getattr(self,'peers',None),'blocks',None),'clones',None),'running',False) or getattr(getattr(getattr(self,'peers',None),'blocks',None),'serving',{}))) or archive_busy or setup_busy or writing or (not public_reads and getattr(self,'public_reviews',None) and self.public_reviews.active) or (not public_reads and getattr(self,'broadcasts',None) and self.broadcasts.active) or public_reads and setup_reserved or
            (not public_reads and any(v['proposal']['kind'] in ('destroy_disc','archive_cancel','builder_cancel') for v in s['pending'].values())) or
            self.archives and self.archives.reading or (s.get('history_jobs') and not ignore_history) or
            any(k!=ignore_rename and row['proposal']['kind']=='wallet_rename' and row['state']!='pending' for k,row in s['pending'].items()) or
            getattr(self.transfer,'sending',False) or s.get('sync_batch') or s.get('active_transfer') or
            (not ignore_history and s.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning')))
    def public_rpc(self,ident,name,params,wallet,timeout):
        """One read-only gate for terminal bridge and Wallet Server execution threads."""
        from agent_rpc import request
        validated,_=request(name,params,wallet)
        busy={'error':{'code':'synchronisation_busy','message':'A locally authorised wallet operation is active. Retry after it finishes.'}}
        # Wallet Server issues parallel read-only inventory calls while the viewer
        # polls status. A non-blocking exclusive lock falsely classified every
        # overlapping public read as wallet work and prevented complete inventory.
        if not self.lock.acquire(timeout=min(3,max(.05,float(timeout)))):
            self.public_busy_notice('workspace_lock_timeout')
            return busy
        try:
            enforce()
            if self.closing or self.busy(public_reads=True):
                self.public_busy_notice('active_wallet_operation');return busy
            result=self.ops.core.call(ident,name,validated,wallet,timeout)
            if name=='getwalletinfo' and isinstance(result.get('result'),dict):
                from managed_accounts import classify
                raw=self.ops.core.call(ident+'-managed' if isinstance(ident,str) else ident,'listdescriptors',[False],wallet,timeout)
                if isinstance(raw.get('result'),dict):
                    metadata=classify(self.store.read(),wallet,raw['result'])
                    if metadata:result['result']['wallaby_managed']=metadata
                retired=[key for key,row in self.store.read().get('retired_policies',{}).items() if wallet in row.get('wallets',[])]
                for record in getattr(self.archives,'loaded',{}).values():
                    if wallet in record['routes']:retired+=record['recovery'].get('retired_policy_hashes',[])
                if retired:result['result']['wallaby_retired_policies']=sorted(set(retired))
            if 'result' in result:
                from sync_table import observe
                observe(self.store,name,wallet,result['result'])
            return result
        finally:self.lock.release()
    def public_busy_notice(self,reason):
        # Fixed diagnostic categories only; never log a descriptor or RPC body.
        now=time.monotonic()
        previous=getattr(self,'_public_busy_log',{})
        if now-previous.get(reason,-60)>=60:
            from activity_log import event
            event('rpc.busy','reason='+reason+' · retryable=true · public inventory deferred')
            previous[reason]=now;self._public_busy_log=previous
    def burn_state(self):
        result=self.setup.burner.state();jobs=getattr(getattr(self,'archive_ops',None),'jobs',{})
        for row in result.get('queue',[]):row['archive_request']=bool(jobs.get(row['id'],{}).get('request') and jobs[row['id']]['phase']=='queued')
        return result
    def state(self):
        if getattr(getattr(self,'archive_ops',None),'cancellations',None):self.archive_ops.cancellations.observe()
        saved=self.store.read()
        connected=self.node_status['color']=='green'
        result={'recovery':self.recovery_state(),'connected':connected,'pending':[{'id':k,'kind':v['proposal']['kind'],'state':('staged' if getattr(self,'archive_ops',None) and self.archive_ops.jobs.get(k,{}).get('phase')=='queued' else v['state']),'wallet_name':__import__('approval_store').title(v['proposal']),'direction':v['proposal'].get('direction'),'rename_stage':v.get('rename_stage'),'rename_error_code':v.get('rename_error_code'),'replaces':sorted(original for original,row in saved['pending'].items() if row.get('cancel_requested')==k) if v['proposal']['kind']=='builder_cancel' else []} for k,v in saved['pending'].items() if (not v.get('withdrawn') or v['proposal']['kind']=='wallet_rename' and v['state']=='attempted') and not v.get('cancel_requested') and v['proposal']['kind']!='broadcast_transaction'],'denied':[{'id':k,'proposal':{'kind':v['proposal']['kind']},'wallet_name':v.get('wallet_name','')} for k,v in saved['denied'].items()],'sync':saved['sync'],'outbox_count':len(saved['outbox']),'transaction_deliveries':[{'id':key,'kind':row['kind'],'wallet':row.get('proposal',{}).get('wallet','Local node'),'state':row.get('delivery','queued'),'status':row.get('status'),'message':row.get('message',''),'txid':row.get('artifact_txid'),'at':row['at']} for key,row in sorted(saved['completed'].items(),key=lambda pair:pair[1].get('at',0),reverse=True) if row.get('kind') in ('sign_psbt_partial','broadcast_transaction') and row.get('outbox_id')][:16],'transfer':self.transfer.state(),'protected':{'running':True,'viewer':True,**enforce()},'burn':self.burn_state(),'archives':self.archives.state(),'exclusions':list(saved.get('sync_exclusions',{}).values()),'request_exclusions':list(saved.get('request_denials',{}).values()),'obsolete_sync_denials':__import__('extinct_sync').obsolete_denials(self.store),'identity':self.setup.own_identity(),'busy':self.busy(),'setups':[{'id':key,'name':v['proposal']['name'],'phase':v['phase'],'cancellation_id':saved.get('cancelled_setups',{}).get(key)} for key,v in self.setup.sessions.items() if v['phase']!='complete']}
        result['pending']=[r for r in result['pending'] if r['kind']!='wallet_transfer']+result['transfer']['receive_approvals']
        self._state_snapshot=__import__('copy').deepcopy(result)
        return result
    def service_status(self):
        if getattr(getattr(self,'archive_ops',None),'cancellations',None):self.archive_ops.cancellations.observe()
        saved=self.store.read();pending=sorted(k for k,row in saved['pending'].items() if row['proposal']['kind']!='broadcast_transaction' and (not row.get('withdrawn') or row['proposal']['kind']=='wallet_rename' and row['state']=='attempted'));result={'recovery':self.recovery_state(),'connected':self.node_status['color']=='green','pending':[],'denied':[],'transfer':{},'burn':{},'sync':'Protected Bitcoin workspace is active. Open its protected pages for wallet data.','outbox_count':0,'worker_version':VERSION,'worker_protocol':PROTOCOL,'peer_support':{'available':bool(getattr(self,'peers',None)),'starting':bool(getattr(self,'peer_starting',False))},'protected':{'running':True,'viewer':False},'has_approvals':bool(pending or any(v['phase']!='complete' for v in self.setup.sessions.values())),'busy':bool(self.busy() or ((self.archives.loaded or self.archives.staged) and not getattr(self,'closing',False)) or delivery_pending(saved)),'has_burn':bool(self.setup.burner.state().get('id')),'notice':digest(pending),'needs_sync':bool(self.transfer.state().get('rows') or self.transfer.state().get('offers') or self.transfer.state().get('recovery',{}).get('status') not in (None,'Synchronised')),'window_required':self.window_required,'viewer_open':any(process.poll() is None for process in self.viewers),'identity':self.setup.own_identity()}
        self._service_snapshot=dict(result);return result
    def recovery_state(self):
        return self.recovery.snapshot() if hasattr(self,'recovery') else {}
    def planned_core_restart(self):
        recovery=getattr(getattr(self,'transfer',None),'recovery',None)
        clones=getattr(getattr(getattr(self,'peers',None),'blocks',None),'clones',None)
        return bool(recovery and recovery.restart_window() or clones and clones.active())
    def connection_lost(self,error):
        from diagnostics import describe
        from activity_log import event
        with self.recovery.lock:
            failure=describe('dashboard',error);before=self.recovery_state()
            if failure.stage=='rpc' and self.planned_core_restart():
                self.recovery.planned_rpc_restart()
                self.node_status={'color':'amber','message':'Planned Bitcoin Core restart. Waiting for local RPC; protected workspace retained.'}
                return
            self.recovery.lost(failure);state=self.recovery_state()
            if state.get('active'):
                event('node.recovery',('Retry failed' if before.get('active') else 'Started')+' · '+failure.stage+' · '+failure.code+' · budget_seconds=15 · remaining='+str(state['remaining']))
                self.node_status={'color':'amber','message':state['message']+'. Reconnecting for up to 15 seconds…','recovery':state}
            else:self.node_status={'color':'red','message':str(failure),'failure':failure.detail(),'failed':True}
    def recovery_watch(self,generation):
        # Never block the deadline behind a Core call, a long poll or a password
        # dialogue. Only tracked UI children close here; private RAM survives until
        # the ordinary lifecycle confirms no operation/archive/delivery is active.
        while self.node_generation==generation:
            state=self.recovery_state()
            if state.get('stage')=='rpc' and self.planned_core_restart():
                self.recovery.planned_rpc_restart()
            if self.recovery.tick():
                state=self.recovery_state()
                from activity_log import event
                self.closing=True
                if self.node_stop:self.node_stop.set()
                event('node.recovery','Expired · '+state['stage']+' · '+state['code']+' · budget_seconds=15')
                for process in list(self.viewers):
                    if process.poll() is None:
                        try:process.terminate()
                        except ProcessLookupError:pass
                return
            if self.node_stop.is_set() and not state.get('active'):return
            time.sleep(.2)
    def start_node(self,port,controller=None):
        from node_client import NodeClient
        from activity_log import event
        if self.recovery_state().get('expired'):raise ValueError('Connection recovery expired. Re-enable the node interface on Services to retry.')
        self.node_controller=controller;self.node_generation=__import__('secrets').token_hex(16);generation=self.node_generation
        self.node_stop=threading.Event();stop=self.node_stop;self.node_port=port
        if not self.recovery_state().get('active'):self.node_status={'color':'amber','message':'Connecting the protected node interface.'}
        def work():
            while not stop.is_set() and self.node_generation==generation and not self.recovery_state().get('expired'):
                self.node_epoch+=1;epoch=self.node_epoch;self.recovery.attempt+=1
                if self.recovery_state().get('active'):event('node.recovery','Attempt · '+str(self.recovery.attempt)+' · remaining='+str(self.recovery_state()['remaining']))
                failed=threading.Event()
                def current(epoch=epoch,failed=failed):return self.node_generation==generation and self.node_epoch==epoch and not stop.is_set() and not failed.is_set()
                def failure(error,current=current,failed=failed):
                    with self.recovery.lock:
                        if current():
                            failed.set();self.connection_lost(error)
                def status(color,message,current=current):
                    with self.recovery.lock:
                        if not current() or color=='red':return
                        if color=='green':
                            recovering=self.recovery_state().get('active')
                            if not self.recovery.connected():return
                            if recovering:event('node.recovery','Recovered · authenticated connection healthy · attempt='+str(self.recovery.attempt))
                        elif self.recovery_state().get('active'):return
                        if self.node_status.get('color')!=color or self.node_status.get('message')!=message:event('node.connection',color+' · '+message)
                        self.node_status={'color':color,'message':message}
                def degraded(error,current=current):
                    if current():self.connection_lost(error)
                client=NodeClient(self.ops.core.config,port,stop,status);client.on_failure=failure;client.on_degraded=degraded;client.planned_core_restart=self.planned_core_restart
                # The exchange must share the live workspace Store object, not
                # merely reopen its file: the optional peer service is attached
                # to this object after asynchronous initialisation completes.
                client.store=self.store;client.diagnostic_workspace=self;client.session_sequence=epoch
                try:client.run()
                except Exception as error:failure(error)
                if not self.recovery_state().get('active'):return
                if stop.wait(2):return
        self.node=threading.Thread(target=work,daemon=True);self.node.start()
        threading.Thread(target=self.recovery_watch,args=(generation,),daemon=True).start()
        return {'session':generation}
    def begin_close(self,deadline=None):
        saved=self.store.read();reasons=[]
        if self.busy():reasons.append('active_wallet_work')
        if delivery_pending(saved):reasons.append('undelivered_operation_result')
        if reasons:
            from activity_log import event
            event('workspace.close','Close refused · blockers='+','.join(reasons)+' · RAM retained')
            raise ValueError('Finish active wallet work and wait for queued Wallet Server deliveries before closing the protected window and disconnecting its node. Blocking: '+', '.join({'active_wallet_work':'wallet operations or history recovery','undelivered_operation_result':'completed operation results awaiting Wallet Server delivery'}[v] for v in reasons)+'.')
        if deadline is not None and time.monotonic()>=deadline:raise ValueError('Close request expired; no workspace state was changed.')
        self.closing=True
        if getattr(self,'peers',None):self.peers.close()
        if getattr(self,'node_stop',None):self.node_stop.set()
        from activity_log import event
        event('workspace.close','Safe close accepted; awaiting node disconnect and RAM cleanup.')
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
        if page not in ('authorise','synchronisation','burn','message','peers','wallets'):raise ValueError('Invalid protected page.')
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
            self.view_token=secrets.token_urlsafe(32);server=Server(('::1',0),ProtectedHandler);server.token=secrets.token_urlsafe(32);server.config_lock=threading.Lock();server.preview=False;self.view_server=server
            threading.Thread(target=server.serve_forever,daemon=True).start()
        config={'origin':'http://[::1]:'+str(self.view_server.server_port),'page':page,'token':self.view_token}
        env={**os.environ,**self.environment};process=__import__('subprocess').Popen(['/usr/bin/python3','-I','-B',str(Path(__file__).with_name('protected_viewer.py'))],stdin=__import__('subprocess').PIPE,stdout=__import__('subprocess').DEVNULL,stderr=__import__('subprocess').DEVNULL,env=env)
        process.stdin.write(json.dumps(config).encode()+b'\n');process.stdin.close();self.viewers=[p for p in self.viewers if p.poll() is None]+[process];self.window_required=True
        return {'message':'Opened the protected Bitcoin workspace.'}
    def dispatch(self,method,args,environment):
        if method=='diagnostics.export':
            if args:raise ValueError('Invalid diagnostic export.')
            enforce()
            from activity_log import DiagnosticLog
            from node_diagnostics import snapshot
            snapshot('protected_export',self)
            return DiagnosticLog().records()
        if method=='ui.request_close':
            if args:raise ValueError('The native close request takes no arguments.')
            admitted=self.lock.acquire(timeout=10)
            if not admitted:
                from activity_log import event
                event('workspace.close','Close deferred · reason=local_action_in_progress · RAM retained')
                raise ValueError('Finish the active protected operation before closing. A local action is still responding; no workspace was discarded.')
            try:
                enforce();self.begin_close();return {'ok':True}
            finally:self.lock.release()
        if method in ('node.connection_lost','node.status','node.stop'):
            enforce()
            from node_control import control
            return control(self,method,args)
        if method=='status' and not self.lock.acquire(blocking=False):
            enforce()
            result=__import__('copy').deepcopy(getattr(self,'_state_snapshot',{'pending':[],'denied':[],'setups':[],'archives':{},'burn':{},'transfer':{},'outbox_count':0}))
            result.update(connected=self.node_status['color']=='green',recovery=self.recovery_state(),protected={'running':True,'viewer':True,**enforce()},busy=True,status_pending=True)
            return result
        elif method=='status':
            try:
                enforce();self.configure(environment);return self.state()
            finally:self.lock.release()
        if method=='service_status':
            # Do not queue ordinary-window liveness behind a native passphrase
            # dialogue/signing operation. This reply contains public flags only.
            if not self.lock.acquire(blocking=False):
                enforce()
                result=dict(getattr(self,'_service_snapshot',{'pending':[],'denied':[],'transfer':{},'burn':{},'outbox_count':0}))
                result.update(recovery=self.recovery_state(),worker_version=VERSION,worker_protocol=PROTOCOL,connected=self.node_status['color']=='green',protected={'running':True,'viewer':False},busy=True,status_pending=True,window_required=getattr(self,'window_required',False),viewer_open=any(p.poll() is None for p in self.viewers),sync='A protected operation is in progress. Continue in the protected window.')
                return result
            try:
                enforce();self.configure(environment);return self.service_status()
            finally:self.lock.release()
        if method=='peers.action':
            if len(args)!=2 or not isinstance(args[0],str) or not isinstance(args[1],dict):raise ValueError('Invalid local peer control.')
            enforce();self.configure(environment)
            clones=getattr(getattr(getattr(self,'peers',None),'blocks',None),'clones',None)
            if clones and (clones.running or clones.preparing) and args[0] not in ('status','block-status'):raise ValueError('Finish trusted cloning before changing direct connections or synchronisation controls.')
            return self.peer_action(*args)
        with self.lock:
            enforce();self.configure(environment)
            if getattr(self,'closing',False) and method not in ('ui.arm','ui.close'):raise ValueError('The protected workspace is closing. Reconnect the node before starting another operation.')
            if self.recovery_state().get('active') and method not in ('status','ui.arm','ui.close','ui.open','node.start'):
                raise ValueError('Node connection recovery is in progress. Protected operations are paused; no operation was started.')
            if getattr(getattr(self,'archive_ops',None),'cancellations',None):self.archive_ops.cancellations.observe()
            saved=self.store.read()
            clones=getattr(getattr(getattr(self,'peers',None),'blocks',None),'clones',None)
            if clones and (clones.running or clones.preparing) and method not in ('status','core.public','core.health','ui.arm','ui.open','ui.close','node.start','exchange','disc.drives'):raise ValueError('Trusted blockchain cloning is active. Wait for Core restart and wallet checks before changing wallets, recovery or Internet peers.')
            if getattr(getattr(self,'public_reviews',None),'active',None) and method not in ('status','authorise.review','authorise.deny','lifecycle.deny','lifecycle.cancel','core.public','core.health','ui.arm','ui.open','node.start','exchange','disc.drives','disc.status','disc.probe'):
                raise ValueError('A read-only policy review is checking local funding. Wait before changing wallets or disc contents; status and public inventory remain available.')
            changing=method in ('refresh.destroyed','rename.approve','rename.reconcile','wallet.sign','archive.cancel_bind','archive.cancel_check','archive.cancel_stage','archive.cancel_confirm','archive.retire_stage','archive.retire_destroyed','retirement.approve','authorise.approve','setup.participate','authorise.history','setup.cancel','cancel.confirm','cancel.reconcile')
            if changing and args:
                from cancellation import blocked
                candidate=saved['pending'].get(args[0],{}).get('proposal') or getattr(self.ops,'prepared',{}).get(args[0])
                if candidate and blocked(saved,candidate):raise ValueError('This build is cancelled. Review its local cancellation on Authorise; no signing or wallet action was started.')
            if changing and (saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning')):raise ValueError('Finish the active transfer or history recovery first.')
            if method in ('wallet.sign','setup.participate','authorise.approve','message.sign','cancel.confirm','cancel.reconcile') and self.archives and self.archives.reading:raise ValueError('Wait for optical restoration to finish before signing or changing wallets.')
            if saved.get('setup_active') and method in ('refresh.destroyed','wallet.sign','archive.cancel_bind','archive.cancel_check','archive.cancel_stage','archive.cancel_confirm','archive.retire_stage','archive.retire_destroyed','retirement.approve','authorise.approve','authorise.history','authorise.review'):
                candidate=saved['pending'].get(args[0],{}).get('proposal',{}) if args else {}
                independent_archive=candidate.get('kind')=='archive_wallet' and method in ('authorise.review','authorise.approve') and not self.busy(public_reads=True)
                if not independent_archive and candidate.get('kind')!='builder_cancel' and (candidate.get('kind')!='wallet_setup_policy' or digest(candidate['proposal'])!=saved['setup_active']):raise ValueError('Finish the current wallet setup and its physical backups first.')
            if method=='service_status':return self.service_status()
            if method=='ui.arm':
                if hasattr(self,'recovery'):self.recovery.reset()
                self.closing=False
                if not any(p.poll() is None for p in self.viewers):self.window_required=False
                return {'ok':True}
            if method=='ui.open':return self.open_view(*args)
            if method=='ui.close':return self.close_views()
            if method=='node.start':
                from node_control import start
                return start(self,args)
            if method=='status':return self.state()
            if method=='core.health':self.ops.core.ready();return {'ok':True}
            if method=='core.public':
                return self.public_rpc(*args)
            if method=='exchange':
                from agent_exchange import Exchange
                if len(args)!=2 or type(args[0]) is not int or not 1<=args[0]<=65535 or not isinstance(args[1],str) or len(args[1])>4096:raise ValueError('Invalid exchange connection.')
                Exchange(args[0],args[1],self.store).once();return {'ok':True}
            if method=='authorise.review':
                kind=self.store.read()['pending'][args[0]]['proposal']['kind']
                if kind=='broadcast_transaction':raise ValueError('Completed transactions are broadcast automatically only when Wallet Server requests it. No second local approval is needed.')
                if kind=='wallet_rename':return self.renames.review(args[0])
                if kind in ('archive_wallet','destroy_disc','archive_cancel'):return self.archive_ops.review(args[0])
                if kind=='wallet_policy_refresh':
                    if self.store.read()['pending'][args[0]]['state']=='awaiting_backups':return self.refresh_ops.review(args[0])
                    return self.public_reviews.start(args[0],kind,self.refresh_ops.review)
                if kind=='wallet_retire':
                    from retirement_phases import require_current
                    require_current(self.store.read()['pending'][args[0]]['proposal'])
                    return self.retirement.review(args[0])
                if kind=='builder_cancel':
                    from policy_refresh_cancel import handles
                    if handles(self.cancellations,self.store.read()['pending'][args[0]]['proposal']):return self.public_reviews.start(args[0],kind,self.cancellations.review)
                    return self.cancellations.review(args[0])
                if kind.startswith('wallet_setup'):return self.setup.review(args[0])
                return self.ops.prepare_request(args[0])
            if method in ('local_wallets.list','local_wallets.review','local_wallets.delete','local_wallets.history'):
                if self.node_status['color']!='green':raise ValueError('Reconnect the node interface before managing local wallets.')
                action=method.split('.')[1]
                return getattr(self.local_wallets,'listing' if action=='list' else action)(*args)
            if method=='rename.reconcile':return self.renames.reconcile(*args)
            if method=='rename.approve':return self.renames.approve(*args)
            if method=='retirement.evidence':
                from retirement_remote import request
                return request(self.retirement,*args)
            if method in ('authorise.history','retirement.approve'):
                from retirement_phases import require_current
                require_current(self.store.read()['pending'][args[0]]['proposal'])
                return self.retirement.prepare_history(*args) if method=='authorise.history' else self.retirement.approve(*args)
            if method=='authorise.deny':
                p=self.store.read()['pending'][args[0]]['proposal']
                if p['kind']=='archive_cancel':raise ValueError('Archive cancellation requires its local disc cleanup checklist; it cannot be denied or silently deleted.')
                if p['kind']=='wallet_rename':return self.renames.deny(args[0])
                if p['kind']=='wallet_policy_refresh':return self.refresh_ops.deny(args[0])
                if p['kind']=='builder_cancel':raise ValueError('Choose Delete and Cancel or Backup and Cancel after reviewing this cancellation.')
                if p['kind'].startswith('wallet_setup'):self.setup.decline(args[0])
                else:self.store.deny(*args)
                return {'ok':True}
            if method=='authorise.forget':self.store.forget(*args);return {'ok':True}
            if method=='authorise.approve':
                kind=self.store.read()['pending'][args[0]]['proposal']['kind']
                if kind=='archive_wallet':return self.archive_ops.approve(args[0])
                if kind=='wallet_policy_refresh':return self.refresh_ops.approve(args[0])
                if kind=='destroy_disc':raise ValueError('Confirm physical destruction on the local destruction checklist.')
                if kind=='wallet_retire':
                    from retirement_phases import require_current
                    require_current(self.store.read()['pending'][args[0]]['proposal'])
                    return self.retirement.approve(args[0])
                if kind=='wallet_setup_policy':return self.setup.approve_policy(args[0])
                return self.ops.approve_sync(args[0])
            if method=='cancel.reconcile':return self.cancellations.reconcile(*args)
            if method=='cancel.confirm':return self.cancellations.confirm(*args)
            if method=='setup.cancel':return self.setup.cancel(*args)
            if method=='setup.participate':return self.setup.approve_proposal(*args)
            if method in ('disc.read','disc.load','disc.unload','message.wallets','message.prepare','message.sign'):
                if self.node_status['color']!='green':raise ValueError('The node connection is recovering. Protected operations are paused; no operation was started.')
                if saved.get('setup_active') or saved.get('active_transfer') or saved.get('sync_batch') or saved.get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'):raise ValueError('Finish the current wallet setup, transfer or history operation first.')
            if method=='archive.cancel_bind':return self.archive_ops.cancellations.bind(*args)
            if method=='archive.cancel_check':return self.archive_ops.cancellations.check(*args)
            if method=='archive.cancel_stage':return self.archive_ops.cancellations.stage(*args)
            if method=='archive.cancel_confirm':return self.archive_ops.cancellations.confirm(*args)
            if method in ('archive.retire_stage','archive.retire_destroyed'):
                from extinct_discs import stage,destroyed
                return (stage if method=='archive.retire_stage' else destroyed)(self.archive_ops,*args)
            if method=='archive.delete':return self.archive_ops.delete(*args)
            if method=='archive.destroyed':return self.archive_ops.destroyed(*args)
            if method=='refresh.destroyed':
                from policy_refresh_backups import confirm
                return confirm(self.refresh_ops,*args)
            if method in ('disc.read','disc.status','disc.probe') and (self.archives.reading or self.setup.burner.thread and self.setup.burner.thread.is_alive()):
                from diagnostics import LocalActionFailure
                raise LocalActionFailure('optical_busy','Another optical read, burn or verification is active. Wait for it to finish before checking or reading the disc.')
            if method in ('disc.burn','disc.verify') and self.archives.reading:raise ValueError('Wait for the current optical read to finish before burning.')
            if method=='disc.verify':return self.setup.burner.verify_written(*args)
            if method=='disc.selection':return self.setup.burner.select(*args)
            if method=='disc.refresh':return self.archive_ops.queue_loaded(*args)
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
                record=self.archives.loaded.get(args[0])
                if record and any(j.get('source_archive')==record.get('archive_id') and j['phase']!='complete' for j in self.archive_ops.jobs.values()):raise ValueError("Finish this archive's queued replacement before unloading its signing account.")
                if self.archives.reading:raise ValueError('Wait for the current optical read to finish.')
                self.ops.prepared.clear();self.messages.prepared.clear();return self.archives.unload(*args)
            if method=='message.wallets':return self.messages.wallets()
            if method=='message.prepare':return self.messages.prepare(*args)
            if method=='message.sign':return self.messages.sign(*args)
            if method=='sync.clear_obsolete':
                if args:raise ValueError('The obsolete-denial cleanup takes no arguments.')
                from extinct_sync import clear_obsolete_denials
                return clear_obsolete_denials(self.store)
            if method in ('lifecycle.deny','lifecycle.cancel','lifecycle.enable'):
                from lifecycle_preferences import deny,cancel,enable
                return {'lifecycle.deny':deny,'lifecycle.cancel':cancel,'lifecycle.enable':enable}[method](self.store,*args)
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
            if method=='disc.status':return __import__('disc_backup').disc_status(*args)
            if method=='disc.drives':return [{'device':'/dev/'+p.name,'name':(p/'device/model').read_text().strip()} for p in Path('/sys/class/block').glob('sr[0-9]*')]
            if method=='wallet.sign':
                key,action,fee_ack=args
                if type(fee_ack) is not bool:raise ValueError('Invalid local fee acknowledgement.')
                if action!='partial':raise ValueError('Broadcast is requested from Wallet Server after signing. No second local approval is needed.')
                from wallet_ops import require_current_review
                prepared=require_current_review(self.ops.prepared.get(key))
                if prepared['review']['fee_review']['requires_ack'] and not fee_ack:raise ValueError('Acknowledge the high fee locally before entering a wallet passphrase.')
                info=__import__('wallet_ops').rpc(self.ops.core,'getwalletinfo',[],prepared['wallet']) if action=='partial' else {}
                encrypted='unlocked_until' in info
                prompt='Bitcoin Core wallet passphrase · sign the reviewed transaction\nCore wallet: '+json.dumps(info.get('walletname',''),ensure_ascii=False)+'\nLocal signing account: '+json.dumps(prepared['wallet'],ensure_ascii=False)
                require_current_review(prepared)
                password=secret_dialog(prompt,self.environment) if encrypted else ''
                try:return self.ops.sign(key,password,action,fee_ack)
                finally:password=None
            if method.startswith('transfer.'):
                name=method.split('.',1)[1]
                if name=='firewall':
                    from peer_wallet import check_firewall
                    return check_firewall(self.transfer)
                if name=='route':
                    from sync_table import choose
                    return choose(self.store,*args)
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
                if name not in ('state','review','review_receive','authorise_receive','cancel_receive','stop_receiving','resume_network'):raise ValueError('Invalid local transfer action.')
                return getattr(self.transfer,name)(*args)
            if method.startswith('recovery.'):
                name=method.split('.',1)[1]
                if name not in ('plan','start'):raise ValueError('Invalid local history action.')
                return getattr(self.transfer.recovery,name)(*args)
            raise ValueError('Unsupported protected action.')

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        started=time.monotonic();method='protected.action'
        try:
            uid=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if uid!=os.getuid():return
            self.request.settimeout(600);n=int.from_bytes(receive(self.request,4),'big')
            if not 0<n<=20*1024*1024:raise ValueError('Invalid protected request size.')
            from node_client import decode
            p=decode(receive(self.request,n))
            if not isinstance(p,dict) or set(p)!={'method','args','environment'} or not isinstance(p['method'],str) or not isinstance(p['args'],list) or len(p['args'])>8 or not isinstance(p['environment'],dict):raise ValueError('Invalid protected action.')
            method=p['method'] if __import__('re').fullmatch('[a-z_.]{1,64}',p['method']) else 'invalid-action'
            result=self.server.workspace.dispatch(p['method'],p['args'],p['environment']);reply={'result':result}
            if p['method'] not in ('status','service_status','node.status','diagnostics.export','ui.arm'):
                from activity_log import event
                method=p['method'] if __import__('re').fullmatch('[a-z_.]{1,64}',p['method']) else 'invalid-action'
                event(method,'Local action completed · elapsed_ms='+str(round((time.monotonic()-started)*1000)))
        except Exception as e:
            from activity_log import event
            from diagnostics import action_code,action_detail
            event(method,'Local action refused or uncertain · '+action_code(e)+' · '+type(e).__name__+' · '+action_detail(e)+' · elapsed_ms='+str(round((time.monotonic()-started)*1000)))
            reply={'error':str(e) if isinstance(e,ValueError) else 'Protected operation stopped or is uncertain. Inspect local state; it was not automatically repeated.'}
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
