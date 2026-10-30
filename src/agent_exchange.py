"""Optional Agent v2 exchange; v1 Dashboard remains usable with read-only RPC.

The transport stores proposals and public results. It never imports or signs.
No retry ever repeats a wallet operation; only content-addressed data is retried.
"""
import time
from peer_wallet import local_ipv6,active
from approval_store import Store
from node_client import http_json,HTTPFailure

class Exchange:
    def __init__(self,port,token,store=None):self.port=port;self.token=token;self.store=store;self.unsupported=False
    def once(self):
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
        state=self.store.read();items=[{'id':key,**row} for key,row in list(state['outbox'].items())[:8]]
        body={'version':1,'outbox':items,'known_vaults':sorted(state['vaults'])[:128],'capabilities':['node_identity','partial_signing','broadcast','wallet_transfer','wallet_retirement']}
        address=local_ipv6()
        if address:body['node_info']={'ipv6':address}
        try:r=http_json(self.port,'/agent/v2/exchange',body,self.token,timeout=10)
        except HTTPFailure as error:
            if error.status in (404,405,501):
                self.unsupported=True
                with self.store.edit() as s:s['sync']='Dashboard does not yet support vault/signing exchange. Public data and unsigned PSBT exports remain queued locally.'
                return
            raise
        if not isinstance(r,dict) or set(r)!={'version','accepted','proposals'} or r['version']!=1 or not isinstance(r['accepted'],list) or not isinstance(r['proposals'],list) or len(r['proposals'])>16:raise ValueError('Invalid Dashboard exchange response.')
        sent={i['id'] for i in items}
        if any(not isinstance(k,str) or k not in sent for k in r['accepted']):raise ValueError('Dashboard acknowledged an item that was not sent.')
        # List membership belongs to Dashboard. Signed previews never grant local authority.
        from vault_policy import validate_proposal
        proposals=[validate_proposal(p) for p in r['proposals']]
        for p in proposals:
            if p['kind']=='wallet_sync_queue':self.store.receive(p)
        for p in proposals:
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
                public=' '.join(key.read_text().split()[:2]);self.store.queue('wallet_setup_identity',sign(self.store,{'version':1,'challenge':p['challenge'],'public_key':public,'fingerprint':fingerprint(public),'hostname':socket.gethostname()}))
            elif p['kind']=='node_identity':
                if address:self.store.queue('node_identity',{'ipv6':address})
            elif p['kind']!='wallet_sync_queue':self.store.receive(p)
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
        with self.store.edit() as s:
            for key in r['accepted']:s['outbox'].pop(key,None)
            s['sync']='Dashboard exchange connected. Pending changes require local authorisation.';s['last_exchange']=time.time()
    def run(self,stop):
        while not stop.is_set() and not self.unsupported:
            try:self.once()
            except Exception:
                if self.store is None:
                    stop.wait(30);continue
                with self.store.edit() as s:s['sync']='Dashboard exchange failed validation or is unavailable. Queued data retained; retry in 30 seconds.'
            stop.wait(30)
