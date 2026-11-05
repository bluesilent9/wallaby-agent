"""Optional Agent v2 exchange; v1 Dashboard remains usable with read-only RPC.

The transport stores proposals and public results. It never imports or signs.
No retry ever repeats a wallet operation; only content-addressed data is retried.
"""
import time,threading

LOCAL_CANCELLATIONS=None
LOCAL_RETIREMENT=None
LOCAL_ARCHIVES=None
LOCAL_BROADCASTS=None
from peer_wallet import local_ipv6,active
from approval_store import Store
from node_client import http_json,HTTPFailure

class Exchange:
    def __init__(self,port,token,store=None):self.port=port;self.token=token;self.store=store;self.unsupported=False;self.phase='local_outbox';self.proposal_kind='none';self.cancelled=lambda:False
    def once(self,previews=True):
        if self.cancelled():return
        self.phase='local_outbox';self.proposal_kind='none'
        from protected_memory import required,inside
        if required() and not inside():
            from secure_bridge import call
            return call('exchange',self.port,self.token,timeout=40)
        if self.store is None:self.store=Store()
        if self.unsupported:return
        from transaction_requests import has_signatures
        with self.store.edit() as saved:
            for key,item in list(saved['outbox'].items()):
                old=item['kind']=='sign_result'
                if item['kind']=='transaction_builder_psbt':
                    try:old=has_signatures(item['payload']['psbt'])
                    except (ValueError,KeyError):old=True
                if old:saved.setdefault('legacy_exports',{})[key]=saved['outbox'].pop(key)
        state=self.store.read()
        from cancellation import held_item,blocked
        ordered=sorted(state['outbox'].items(),key=lambda pair:0 if pair[1]['kind']=='wallet_setup_identity' else 1 if pair[1]['kind'] in ('partial_sign_result','broadcast_result') else 2)
        items=[{'id':key,**row} for key,row in ordered if not held_item(state,row)][:8]
        body={'version':1,'outbox':items,'known_vaults':sorted(state['vaults'])[:128],'capabilities':['node_identity','partial_signing','broadcast','automatic_broadcast_v1','wallet_transfer','wallet_retirement_v3','archive_inventory_v1','wallet_retirement_cancel_v1','builder_cancellation_v1','wallet_archive_queue_v1','wallet_archive_cancel_v1','wallet_policy_refresh_v1','wallet_rename_v1']}
        if time.monotonic()-getattr(self,'address_checked',-60)>=30:
            self.address=local_ipv6();self.address_checked=time.monotonic()
        address=getattr(self,'address',None)
        if address:body['node_info']={'ipv6':address}
        from activity_log import event
        for item in items:
            if item['kind'] in ('partial_sign_result','broadcast_result') and item['id'] not in getattr(self,'signing_sent',set()):
                self.signing_sent=(getattr(self,'signing_sent',set()) if len(getattr(self,'signing_sent',set()))<128 else set())|{item['id']}
                event('transaction.delivery','Sending '+('signed result' if item['kind']=='partial_sign_result' else 'broadcast result')+' · request='+item['payload']['request_hash'][:12])
        self.phase='http'
        try:r=http_json(self.port,'/agent/v2/exchange',body,self.token,timeout=10)
        except HTTPFailure as error:
            if error.status in (404,405,501):
                self.unsupported=True
                with self.store.edit() as s:s['sync']='Dashboard does not yet support vault/signing exchange. Public data and unsigned PSBT exports remain queued locally.'
                return
            raise
        if self.cancelled():return
        self.phase='response'
        if not isinstance(r,dict) or set(r)!={'version','accepted','proposals'} or type(r['version']) is not int or r['version']!=1 or not isinstance(r['accepted'],list) or not isinstance(r['proposals'],list) or len(r['proposals'])>16:raise ValueError('Invalid Dashboard exchange response.')
        sent={i['id'] for i in items}
        if any(not isinstance(k,str) or k not in sent for k in r['accepted']):raise ValueError('Dashboard acknowledged an item that was not sent.')
        # A valid acknowledgement is independent of unrelated proposals in this
        # response. Record delivery before processing a new proposal can fail.
        with self.store.edit() as saved:
            for key in r['accepted']:
                item=saved['outbox'].pop(key,None)
                if item and item['kind']=='transaction_builder_psbt':saved.setdefault('delivered_artifacts',{})[key]=item
                if item and item['kind'] in ('partial_sign_result','broadcast_result'):
                    request=item['payload']['request_hash'];record=saved['completed'].get(request)
                    if record and record.get('outbox_id')==key:record.update(delivery='acknowledged',acknowledged_at=time.time())
                    event('transaction.delivery','Dashboard acknowledged '+('signed result' if item['kind']=='partial_sign_result' else 'broadcast result')+' · request='+request[:12])
        # List membership belongs to Dashboard. Signed previews never grant local authority.
        from vault_policy import validate_proposal
        proposals=[]
        self.phase='proposal_validation'
        for p in r['proposals']:
            # Record only a fixed known kind, never remote strings or payloads.
            known={'wallet_rename','wallet_rename_queue','builder_cancel','wallet_retire_cancel','wallet_sync_queue','wallet_archive_queue','wallet_transfer_preview','wallet_sync_preferences','wallet_setup_complete','wallet_setup_identity','node_identity','wallet_transfer','vault_sync','wallet_retire','wallet_setup','wallet_setup_policy','wallet_policy_refresh','sign_psbt_partial','broadcast_transaction','archive_wallet','destroy_disc','archive_cancel'}
            self.proposal_kind=p.get('kind') if isinstance(p,dict) and p.get('kind') in known else 'unknown'
            if self.proposal_kind=='wallet_retire':
                from retirement_phases import require_current
                require_current(p)
            proposals.append(validate_proposal(p))
        self.phase='proposal_application'
        for p in proposals:
            self.proposal_kind=p['kind']
            if p['kind']=='builder_cancel':
                if LOCAL_CANCELLATIONS is None:raise ValueError('Protected cancellation handler is unavailable.')
                LOCAL_CANCELLATIONS.receive(p)
            elif p['kind']=='wallet_retire_cancel':
                if LOCAL_RETIREMENT is None:raise ValueError('Protected retirement handler is unavailable.')
                LOCAL_RETIREMENT.cancel_remote(p['request_hash'])
        for p in proposals:
            self.proposal_kind=p['kind']
            if p['kind']=='wallet_sync_queue':
                from sync_queue import apply_snapshot
                from approval_store import digest
                apply_snapshot(self.store,p['revision'],p['requests'],session=digest({'token':self.token}))
            elif p['kind'] in ('wallet_archive_queue','wallet_rename_queue'):self.store.receive(p)
        if LOCAL_ARCHIVES is not None and LOCAL_ARCHIVES.store.path==self.store.path:LOCAL_ARCHIVES.cancellations.observe(mark_only=True)
        for p in proposals:
            self.proposal_kind=p['kind']
            if p['kind'] in ('builder_cancel','wallet_retire_cancel') or blocked(self.store.read(),p):continue
            if p['kind']=='wallet_transfer_preview':
                from wallet_preview import receive
                receive(self.store,{k:p[k] for k in ('preview','public_key','signature')})
            elif p['kind']=='wallet_sync_preferences':
                from sync_preferences import exchange
                exchange(self.store,p)
            elif p['kind']=='wallet_setup_complete':
                from setup_completion import apply
                from configuration import Config,discover_cookie
                from node_client import Core
                config=Config().values;config['cookie']=config['cookie'] or discover_cookie();apply(Core(config),self.store,p)
            elif p['kind']=='wallet_setup_identity':
                from setup_messages import sign
                from wallet_preview import fingerprint
                from pathlib import Path
                import socket
                key=getattr(self.store,'identity_root',self.store.root)/'preview_identity.pub'
                if not key.exists():sign(self.store,{'purpose':'identity-initialisation','version':1})
                public=' '.join(key.read_text().split()[:2]);self.store.queue('wallet_setup_identity',sign(self.store,{'version':1,'challenge':p['challenge'],'public_key':public,'fingerprint':fingerprint(public),'hostname':socket.gethostname()}))
            elif p['kind']=='node_identity':
                if address:self.store.queue('node_identity',{'ipv6':address})
            elif p['kind'] not in ('wallet_sync_queue','wallet_archive_queue','wallet_rename_queue'):self.store.receive(p)
        if LOCAL_BROADCASTS is not None and LOCAL_BROADCASTS.store.path==self.store.path:LOCAL_BROADCASTS.start()
        if previews:self.prepare_preview()
        self.phase='acknowledgement';self.proposal_kind='none'
        with self.store.edit() as s:
            self.preview_ready=not s.get('sync_batch') and not s.get('active_transfer') and any(row['proposal']['kind']=='wallet_transfer' and row['proposal']['direction']=='send' and row['proposal'].get('preview_challenge') and key not in s.get('transfer_previews',{}) for key,row in s['pending'].items())
            s['sync']='Dashboard exchange connected. Pending changes require local authorisation.';s['last_exchange']=time.time();s.pop('exchange_error',None)
    def prepare_preview(self):
        if self.cancelled():return
        saved=self.store.read()
        self.preview_due={k:v for k,v in getattr(self,'preview_due',{}).items() if k in saved['pending']}
        if not saved.get('sync_batch') and not saved.get('active_transfer'):
            from configuration import Config,discover_cookie
            from node_client import Core
            from wallet_preview import prepare
            for key,row in saved['pending'].items():
                p=row['proposal']
                if p['kind']!='wallet_transfer' or p['direction']!='send' or not p.get('preview_challenge') or key in saved.get('transfer_previews',{}):continue
                if time.monotonic()<getattr(self,'preview_due',{}).get(key,0):continue
                if self.cancelled():return
                if not hasattr(self,'preview_due'):self.preview_due={}
                self.preview_due[key]=time.monotonic()+30
                try:
                    c=Config().values;c['cookie']=c['cookie'] or discover_cookie();prepare(Core(c),self.store,key,p)
                except Exception as error:
                    with self.store.edit() as state:state.setdefault('preview_errors',{})[key]=str(error) if isinstance(error,ValueError) else 'Sender node verification failed. Check the local node and wallet.'
                break
    def start_preview(self):
        if not getattr(self,'preview_ready',False):return
        if getattr(self,'preview_thread',None) and self.preview_thread.is_alive():return
        def work():
            try:self.prepare_preview()
            except Exception:
                from activity_log import event
                event('sync.preview','Background public preview deferred; control exchange remains active.')
        self.preview_thread=threading.Thread(target=work,daemon=True,name='sender-public-preview');self.preview_thread.start()
    def failure(self,error):
        from diagnostics import describe,ConnectionFailure
        failure=describe('dashboard',error)
        if isinstance(error,HTTPFailure):
            reason=getattr(error,'safe_reason',None)
            advice={'agent_version':'Dashboard rejected the Agent version. Check both installed Development builds and restart the Agent only after safely finishing active work.','capabilities':'Dashboard rejected the Agent capability list. Update Dashboard to the matching build; do not disable local security validation.','identity_conflict':'Dashboard reports a node identity conflict. Resolve it on the Dashboard Nodes page.','session_expired':'Dashboard exchange session expired. The public node connection may need to register again.'}.get(reason)
            return ConnectionFailure('dashboard','exchange_'+(reason or 'http_'+str(error.status)),advice or str(failure))
        if isinstance(error,ValueError):
            from sync_queue import RevisionError
            if isinstance(error,RevisionError):
                from activity_log import event
                event('sync.queue.reject','Revision refused · previous='+str(error.previous)+' · incoming='+str(error.incoming)+' · same_authenticated_session=true')
            reason={'Invalid public descriptor fields.':'descriptor_fields','Invalid descriptor timestamp or activity.':'descriptor_metadata','Descriptor ranges exceed the safe automatic import limit.':'descriptor_range','Only checksummed public descriptors are accepted.':'descriptor_checksum','Private material is forbidden in Dashboard messages.':'private_material','Invalid synchronisation list.':'sync_list','A revision cannot change contents.':'sync_revision','Stale synchronisation list.':'sync_revision','Authorisation queue is full.':'queue_full','Only an Ed25519 Agent identity is supported.':'identity_format','No unique paired receiving request.':'unpaired_preview'}.get(str(error),'invalid_data')
            if self.phase in ('local_outbox','acknowledgement'):return ConnectionFailure('workspace','exchange_local_state','Protected workspace exchange storage was refused at '+self.phase+'. Queued data retained; inspect local workspace diagnostics.')
            return ConnectionFailure('dashboard','exchange_'+reason,'Agent rejected Dashboard exchange data at '+self.phase+' ('+self.proposal_kind+'); category '+reason+'. Queued data retained. Compare the Dashboard protocol log; no rejected request authorised a wallet operation.')
        return failure
    def run(self,stop):
        # A temporary local-store/diagnostic failure outside the normal HTTP
        # try block must not silently kill the only result-delivery thread.
        while not stop.is_set() and not self.unsupported and not self.cancelled():
            try:self._run(stop)
            except Exception:
                from activity_log import event
                event('dashboard.exchange','Exchange worker interrupted by a local failure; queued results retained. Retrying data delivery only; no wallet operation is replayed.')
                stop.wait(2)
    def _run(self,stop):
        transport_delay=1
        while not stop.is_set() and not self.unsupported and not self.cancelled():
            delay=2
            try:
                self.once(previews=False);transport_delay=1
                if not self.cancelled() and not self.unsupported:self.start_preview()
            except Exception as error:
                if self.cancelled():return
                from activity_log import event
                failure=self.failure(error);delay=transport_delay if failure.code in ('timeout','transport','io') else 30
                transport_delay=min(30,transport_delay*2)
                event('dashboard.exchange','Exchange failed · endpoint=/agent/v2/exchange · phase='+self.phase+' · kind='+self.proposal_kind+' · '+failure.stage+' · '+failure.code+' · retry_s='+str(delay)+' · '+str(failure))
                if self.store is None:
                    stop.wait(delay);continue
                with self.store.edit() as s:s['sync']=str(failure)+' Queued data retained; retry in '+str(delay)+' seconds.';s['exchange_error']={'stage':failure.stage,'code':failure.code,'phase':self.phase,'kind':self.proposal_kind}
            if self.store is not None and not self.cancelled():
                if delay==2 and any(v['kind']=='wallet_setup_identity' for v in self.store.read()['outbox'].values()):delay=.1
            stop.wait(delay)
