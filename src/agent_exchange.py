"""Optional Agent v2 exchange; v1 Dashboard remains usable with read-only RPC.

The transport stores proposals and public results. It never imports or signs.
No retry ever repeats a wallet operation; only content-addressed data is retried.
"""
import time
from peer_wallet import local_ipv6,active
from approval_store import Store
from node_client import http_json,HTTPFailure

class Exchange:
    def __init__(self,port,token,store=None):self.port=port;self.token=token;self.store=store or Store();self.unsupported=False
    def once(self):
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
        body={'version':1,'outbox':items,'known_vaults':sorted(state['vaults'])[:128],'capabilities':['node_identity','partial_signing','broadcast','wallet_transfer']}
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
        # Validate the entire bounded batch before storing any work. The initial wallet
        # batch is sorted once; while active, all subsequent Dashboard work is refused.
        from vault_policy import validate_proposal
        proposals=[validate_proposal(p) for p in r['proposals']]
        for proposal in proposals:
            if proposal['kind']=='wallet_transfer_preview':
                from wallet_preview import receive
                receive(self.store,{k:proposal[k] for k in ('preview','public_key','signature')})
        if not state.get('active_transfer'):
            transfers=sorted((p for p in proposals if p['kind']=='wallet_transfer'),key=lambda p:(p['public_wallet']['wallet_name'].casefold(),p['transfer_id']))
            for p in transfers or proposals:
                if p['kind']=='node_identity':
                    if address:self.store.queue('node_identity',{'ipv6':address})
                elif p['kind']!='wallet_transfer_preview':self.store.receive(p)
            active(self.store)
        key,row=active(self.store)
        if row and row['proposal']['direction']=='send' and row['proposal'].get('preview_challenge') and key not in self.store.read().get('transfer_previews',{}):
            from configuration import Config,discover_cookie
            from node_client import Core
            from wallet_preview import prepare
            c=Config().values;c['cookie']=c['cookie'] or discover_cookie()
            try:prepare(Core(c),self.store,key,row['proposal'])
            except Exception as error:
                with self.store.edit() as saved:saved['preview_error']=str(error) if isinstance(error,ValueError) else 'Sender node verification failed. Check the local node and wallet.'
        with self.store.edit() as s:
            for key in r['accepted']:s['outbox'].pop(key,None)
            s['sync']='Dashboard exchange connected. Pending changes require local authorisation.';s['last_exchange']=time.time()
    def run(self,stop):
        while not stop.is_set() and not self.unsupported:
            try:self.once()
            except Exception:
                with self.store.edit() as s:s['sync']='Dashboard exchange failed validation or is unavailable. Queued data retained; retry in 30 seconds.'
            stop.wait(30)
