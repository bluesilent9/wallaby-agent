"""Optional Agent v2 exchange; v1 Dashboard remains usable with read-only RPC.

The transport stores proposals and public results. It never imports or signs.
No retry ever repeats a wallet operation; only content-addressed data is retried.
"""
import time
from approval_store import Store
from node_client import http_json,HTTPFailure

class Exchange:
    def __init__(self,port,token,store=None):self.port=port;self.token=token;self.store=store or Store();self.unsupported=False
    def once(self):
        if self.unsupported:return
        state=self.store.read();items=[{'id':key,**row} for key,row in list(state['outbox'].items())[:8]]
        try:r=http_json(self.port,'/agent/v2/exchange',{'version':1,'outbox':items,'known_vaults':sorted(state['vaults'])},self.token,timeout=10)
        except HTTPFailure as error:
            if error.status in (404,405,501):
                self.unsupported=True
                with self.store.edit() as s:s['sync']='Dashboard does not yet support vault/signing exchange. Public data and signed PSBT exports remain queued locally.'
                return
            raise
        if not isinstance(r,dict) or set(r)!={'version','accepted','proposals'} or r['version']!=1 or not isinstance(r['accepted'],list) or not isinstance(r['proposals'],list) or len(r['proposals'])>16:raise ValueError('Invalid Dashboard exchange response.')
        sent={i['id'] for i in items}
        if any(not isinstance(k,str) or k not in sent for k in r['accepted']):raise ValueError('Dashboard acknowledged an item that was not sent.')
        for proposal in r['proposals']:self.store.receive(proposal)
        with self.store.edit() as s:
            for key in r['accepted']:s['outbox'].pop(key,None)
            s['sync']='Dashboard exchange connected. Pending changes require local authorisation.';s['last_exchange']=time.time()
    def run(self,stop):
        while not stop.is_set() and not self.unsupported:
            try:self.once()
            except Exception:
                with self.store.edit() as s:s['sync']='Dashboard exchange failed validation or is unavailable. Queued data retained; retry in 30 seconds.'
            stop.wait(30)
