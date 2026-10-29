"""Locally frozen selections; one wallet at a time, grouped peer credentials in RAM."""
import threading,time
from peer_wallet import Transfer,active,readiness
from sync_queue import rows,selected,freeze,release
from wallet_preview import verify
from wallet_recovery import Recovery

class BatchTransfer(Transfer):
    def __init__(self,core,store=None):
        super().__init__(core,store);self.recovery=Recovery(self.core,self.store);self.recovery.resume_monitor()
        # Receiving sockets and password authority never survive a UI-service restart.
        saved=self.store.read()
        if saved.get('sync_batch') or saved.get('active_transfer'):
            release(self.store);self.error='Agent restarted during synchronisation. Inspect attempted wallets; no transfer was repeated.'
    def state(self):
        result=super().state();result['recovery']=self.recovery.state();result['busy']=bool(self.store.read().get('sync_batch'));return result
    def complete(self,key):
        super().complete(key)
        if self.store.read().get('sync_batch'):self.success_until=0
    def validate_batch(self,keys,direction):
        saved=self.store.read()
        for key in keys:
            row=saved['pending'].get(key)
            if not row or row.get('withdrawn') or row['state']!='pending' or row['proposal']['direction']!=direction:raise ValueError('Selected requests changed. Review them again.')
            p=row['proposal']
            if p.get('transfer_version')!=2:raise ValueError('Multiple and watch-only transfers require the documented Build 8 queue/transfer protocol from Dashboard.')
            payload=saved.get('transfer_previews',{}).get(key)
            if not payload:raise ValueError('Each selected wallet needs its signed initial public preview before authorisation.')
            verify(self.store,payload)
    def authorise_batch(self,fingerprints):
        keys=selected(self.store,'receive');self.validate_batch(keys,'receive')
        saved=self.store.read()
        if not isinstance(fingerprints,dict) or set(fingerprints)!=set(keys):raise ValueError('Independently compare every sending Agent fingerprint.')
        for key in keys:
            proof=verify(self.store,saved['transfer_previews'][key])
            if fingerprints[key]!=proof['fingerprint']:raise ValueError('A sending Agent fingerprint does not match. Compare it directly on that computer.')
        if not readiness(saved['pending'][keys[0]]['proposal'])['listening']:raise ValueError('Start the receiving machine’s IPv6 SSH listener using the displayed instructions.')
        freeze(self.store,keys,'receive')
        try:
            with self.store.edit() as s:s['active_transfer']=keys[0]
            return super().authorise(keys[0],fingerprints[keys[0]])
        except Exception:release(self.store);raise
    def receive(self,key,p):
        try:
            while self.listener and time.monotonic()<self.deadline:
                saved=self.store.read();batch=saved.get('sync_batch')
                if not batch:return super().receive(key,p)
                pending=[k for k in batch['keys'] if k in saved['pending'] and saved['pending'][k]['state']=='pending' and not saved['pending'][k].get('withdrawn')]
                if not pending:
                    if all(k in saved['completed'] for k in batch['keys']):self.success_until=time.time()+5
                    break
                super().receive(pending[0],saved['pending'][pending[0]]['proposal'])
                if self.error:break
        finally:
            self.close();release(self.store)
    def send_batch(self,credentials):
        keys=selected(self.store,'send');self.validate_batch(keys,'send');saved=self.store.read()
        peers={saved['pending'][key]['proposal']['peer']['node_id'] for key in keys}
        if not isinstance(credentials,dict) or set(credentials)!=peers:raise ValueError('Enter receiving credentials and independently verified SSH fingerprint for each receiving computer.')
        for data in credentials.values():
            if not isinstance(data,dict) or set(data)!={'username','password','fingerprint'}:raise ValueError('Invalid receiving credentials.')
        freeze(self.store,keys,'send');self.error=''
        try:
            for key in keys:
                current=self.store.read()['pending'].get(key)
                if not current or current.get('withdrawn'):continue
                with self.store.edit() as s:s['active_transfer']=key
                data=credentials[current['proposal']['peer']['node_id']]
                super().send(key,**data)
            completed=self.store.read()['completed']
            if all(k in completed for k in keys):self.success_until=time.time()+5
        finally:
            release(self.store)
            for data in credentials.values():data['password']=None
    def stop_receiving(self):
        if self.connection:raise ValueError('A wallet transfer is running. Wait for its outcome before ending receiving authorisation.')
        self.close();release(self.store)
        return {'ok':True}
