"""Optional Agent v2 exchange; v1 Dashboard remains usable with read-only RPC.

The transport stores proposals and public results. It never imports or signs.
No retry ever repeats a wallet operation; only content-addressed data is retried.
"""
import time

LOCAL_CANCELLATIONS=None
LOCAL_RETIREMENT=None
from peer_wallet import local_ipv6,active
from approval_store import Store
from node_client import http_json,HTTPFailure

class Exchange:
    def __init__(self,port,token,store=None):self.port=port;self.token=token;self.store=store;self.unsupported=False;self.phase='local_outbox';self.proposal_kind='none';self.cancelled=lambda:False
    def once(self):
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
        ordered=sorted(state['outbox'].items(),key=lambda pair:0 if pair[1]['kind']=='wallet_setup_identity' else 1)
        items=[{'id':key,**row} for key,row in ordered if not held_item(state,row)][:8]
        body={'version':1,'outbox':items,'known_vaults':sorted(state['vaults'])[:128],'capabilities':['node_identity','partial_signing','broadcast','wallet_transfer','wallet_retirement','wallet_retirement_v2','wallet_retirement_cancel_v1','builder_cancellation_v1','wallet_archive_queue_v1','wallet_policy_refresh_v1','wallet_rename_v1']}
        address=local_ipv6()
        if address:body['node_info']={'ipv6':address}
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
        # List membership belongs to Dashboard. Signed previews never grant local authority.
        from vault_policy import validate_proposal
        proposals=[]
        self.phase='proposal_validation'
        for p in r['proposals']:
            # Record only a fixed known kind, never remote strings or payloads.
            known={'wallet_rename','wallet_rename_queue','builder_cancel','wallet_retire_cancel','wallet_sync_queue','wallet_archive_queue','wallet_transfer_preview','wallet_sync_preferences','wallet_setup_complete','wallet_setup_identity','node_identity','wallet_transfer','vault_sync','wallet_retire','wallet_setup','wallet_setup_policy','wallet_policy_refresh','sign_psbt_partial','broadcast_transaction','archive_wallet','destroy_disc'}
            self.proposal_kind=p.get('kind') if isinstance(p,dict) and p.get('kind') in known else 'unknown'
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
            if p['kind'] in ('wallet_sync_queue','wallet_archive_queue','wallet_rename_queue'):self.store.receive(p)
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
        self.phase='sender_preview';self.proposal_kind='wallet_transfer'
        saved=self.store.read()
        if not saved.get('sync_batch') and not saved.get('active_transfer'):
            from configuration import Config,discover_cookie
            from node_client import Core
            from wallet_preview import prepare
            c=Config().values;c['cookie']=c['cookie'] or discover_cookie()
            for key,row in saved['pending'].items():
                p=row['proposal']
                if p['kind']!='wallet_transfer' or p['direction']!='send' or not p.get('preview_challenge') or key in saved.get('transfer_previews',{}):continue
                try:prepare(Core(c),self.store,key,p)
                except Exception as error:
                    with self.store.edit() as state:state.setdefault('preview_errors',{})[key]=str(error) if isinstance(error,ValueError) else 'Sender node verification failed. Check the local node and wallet.'
        self.phase='acknowledgement';self.proposal_kind='none'
        with self.store.edit() as s:
            for key in r['accepted']:
                item=s['outbox'].pop(key,None)
                if item and item['kind']=='transaction_builder_psbt':s.setdefault('delivered_artifacts',{})[key]=item
            s['sync']='Dashboard exchange connected. Pending changes require local authorisation.';s['last_exchange']=time.time();s.pop('exchange_error',None)
    def failure(self,error):
        from diagnostics import describe,ConnectionFailure
        failure=describe('dashboard',error)
        if isinstance(error,HTTPFailure):
            reason=getattr(error,'safe_reason',None)
            advice={'agent_version':'Dashboard rejected the Agent version. Check both installed Development builds and restart the Agent only after safely finishing active work.','capabilities':'Dashboard rejected the Agent capability list. Update Dashboard to the matching build; do not disable local security validation.','identity_conflict':'Dashboard reports a node identity conflict. Resolve it on the Dashboard Nodes page.','session_expired':'Dashboard exchange session expired. The public node connection may need to register again.'}.get(reason)
            return ConnectionFailure('dashboard','exchange_'+(reason or 'http_'+str(error.status)),advice or str(failure))
        if isinstance(error,ValueError):
            reason={'Invalid public descriptor fields.':'descriptor_fields','Invalid descriptor timestamp or activity.':'descriptor_metadata','Descriptor ranges exceed the safe automatic import limit.':'descriptor_range','Only checksummed public descriptors are accepted.':'descriptor_checksum','Private material is forbidden in Dashboard messages.':'private_material','Invalid synchronisation list.':'sync_list','A revision cannot change contents.':'sync_revision','Stale synchronisation list.':'sync_revision','Authorisation queue is full.':'queue_full','Only an Ed25519 Agent identity is supported.':'identity_format','No unique paired receiving request.':'unpaired_preview'}.get(str(error),'invalid_data')
            if self.phase in ('local_outbox','acknowledgement'):return ConnectionFailure('workspace','exchange_local_state','Protected workspace exchange storage was refused at '+self.phase+'. Queued data retained; inspect local workspace diagnostics.')
            return ConnectionFailure('dashboard','exchange_'+reason,'Agent rejected Dashboard exchange data at '+self.phase+' ('+self.proposal_kind+'); category '+reason+'. Queued data retained. Compare the Dashboard protocol log; no rejected request authorised a wallet operation.')
        return failure
    def run(self,stop):
        while not stop.is_set() and not self.unsupported and not self.cancelled():
            delay=2
            try:self.once()
            except Exception as error:
                if self.cancelled():return
                from activity_log import event
                failure=self.failure(error);delay=30
                event('dashboard.exchange','Exchange failed · endpoint=/agent/v2/exchange · phase='+self.phase+' · kind='+self.proposal_kind+' · '+failure.stage+' · '+failure.code+' · retry_s=30 · '+str(failure))
                if self.store is None:
                    stop.wait(30);continue
                with self.store.edit() as s:s['sync']=str(failure)+' Queued data retained; retry in 30 seconds.';s['exchange_error']={'stage':failure.stage,'code':failure.code,'phase':self.phase,'kind':self.proposal_kind}
            stop.wait(delay)
