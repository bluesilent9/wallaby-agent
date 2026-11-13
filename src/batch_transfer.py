"""Locally frozen selections; one wallet at a time, grouped peer credentials in RAM."""
import threading,time
from peer_wallet import Transfer,active,readiness
from sync_queue import rows,selected,freeze,release
from wallet_preview import verify_bound
from wallet_recovery import Recovery

class BatchTransfer(Transfer):
    def __init__(self,core,store=None):
        super().__init__(core,store);self.recovery=Recovery(self.core,self.store);self.recovery.resume_monitor()
        # Receiving sockets and password authority never survive a UI-service restart.
        saved=self.store.read()
        if saved.get('sync_batch') or saved.get('active_transfer'):
            release(self.store);self.error='Agent restarted during synchronisation. Inspect attempted wallets; no transfer was repeated.'
    def state(self):
        result=super().state();from sync_offers import rows as offers
        result['offers']=offers(self.store);result['offers_received']=bool(self.store.read().get('sync_offers_received'));result['offer_server_support']=self.store.read().get('sync_offer_server_support');result['sync_denials']=list(self.store.read().get('sync_exclusions',{}).values());result.update(__import__('sync_table').state(self.store,result['rows']));result['recovery']=self.recovery.state();clones=getattr(getattr(getattr(self.store,'peers',None),'blocks',None),'clones',None);result['clone_running']=bool(clones and (clones.running or clones.preparing));result['busy']=bool(self.store.read().get('sync_batch') or result['clone_running']);return result
    def complete(self,key):
        super().complete(key)
        if self.store.read().get('sync_batch'):self.success_until=0
    def validate_batch(self,keys,direction):
        saved=self.store.read()
        from sync_preferences import policy_id
        identities=[policy_id(saved['pending'][key]['proposal']) for key in keys if key in saved['pending']]
        if len(identities)!=len(keys) or len(set(identities))!=len(identities):raise ValueError('Select one peer for each wallet in the table again. Older overlapping selections cannot be transferred together.')
        for key in keys:
            row=saved['pending'].get(key)
            if not row or row.get('withdrawn') or row['state']!='pending' or row['proposal']['direction']!=direction:raise ValueError('Selected requests changed. Review them again.')
            p=row['proposal']
            if not __import__('sync_table').sender_enabled(saved,p):raise ValueError('The receiver has not enabled this wallet. No transfer was started.')
            if p.get('transfer_version')==3 and not __import__('sync_table').direct_ready(self.store,p):raise ValueError('No Agent Detected. Reconnect the directly paired Agent and review the selected wallets again.')
            from managed_accounts import guard
            guard(self.core,p,self.store,public_preview=True)
            if p.get('transfer_version')!=3:raise ValueError('This older sync request cannot authenticate a direct peer. Reconnect the paired Agents and request a current direct wallet sync. Manual fingerprints and login transfers are no longer accepted.')
            payload=saved.get('transfer_previews',{}).get(key)
            if not payload:raise ValueError('Each selected wallet needs its signed initial public preview before authorisation.')
            verify_bound(self.store,payload,p)
            if direction=='receive' and __import__('signer_restoration').requested(p):
                option=saved.get('sync_choices',{}).get(key,{})
                __import__('signer_restoration').offer(self.store,p,not p['source_has_private_keys'] or option.get('watch_only',False))
    def authorise_batch(self,fingerprints=None):
        if fingerprints is None:fingerprints={}
        keys=selected(self.store,'receive');self.validate_batch(keys,'receive')
        saved=self.store.read()
        if isinstance(fingerprints,dict):
            fingerprints=dict(fingerprints)
            for key in keys:
                p=saved['pending'][key]['proposal']
                if p.get('transfer_version')==3:
                    from peer_mesh import manager
                    fingerprints[key]=__import__('wallet_preview').fingerprint(manager(self.store).binding(p).peer['identity_key'])
        if not isinstance(fingerprints,dict) or set(fingerprints)!=set(keys):raise ValueError('The selected wallets must have authenticated direct Agent connections.')
        for key in keys:
            if saved['pending'][key]['proposal'].get('transfer_version')==3:
                from peer_mesh import manager
                channel=manager(self.store).binding(saved['pending'][key]['proposal']);fingerprints[key]=__import__('wallet_preview').fingerprint(channel.peer['identity_key'])
            proof=verify_bound(self.store,saved['transfer_previews'][key],saved['pending'][key]['proposal'])
            if fingerprints[key]!=proof['fingerprint']:raise ValueError('The signed preview differs from the authenticated direct Agent identity.')
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
        saved=self.store.read();keys=[k for k in selected(self.store,'send') if saved['pending'][k]['proposal'].get('transfer_version')!=3]
        if not keys:raise ValueError('Trusted direct transfers start when the receiving Agent approves Receive. No sender approval is required.')
        self.validate_batch(keys,'send');saved=self.store.read()
        peers={saved['pending'][key]['proposal']['peer']['node_id'] for key in keys if saved['pending'][key]['proposal'].get('transfer_version')!=3}
        if not isinstance(credentials,dict) or set(credentials)!=peers:raise ValueError('Enter receiving credentials and independently verified SSH fingerprint for each receiving computer.')
        for data in credentials.values():
            if not isinstance(data,dict) or set(data)!={'username','password','fingerprint'}:raise ValueError('Invalid receiving credentials.')
        freeze(self.store,keys,'send');self.error='';skipped=0
        try:
            for key in keys:
                current=self.store.read()['pending'].get(key)
                if not current or current.get('withdrawn'):skipped+=1;continue
                with self.store.edit() as s:s['active_transfer']=key
                data=credentials.get(current['proposal']['peer']['node_id'],{})
                super().send(key,**data)
            completed=self.store.read()['completed']
            if all(k in completed for k in keys):self.success_until=time.time()+5
            elif skipped:
                self.error='Synchronisation batch interrupted: '+str(sum(k in completed for k in keys))+' of '+str(len(keys))+' selected transfers completed. Wallet Server withdrew '+str(skipped)+' selected requests, which were skipped. Review the current list; no operation was automatically repeated.'
                from activity_log import event
                event('sync.batch',self.error)
                raise ValueError(self.error)
        finally:
            release(self.store)
            for data in credentials.values():data['password']=None
    def stop_receiving(self):
        if self.connection:raise ValueError('A wallet transfer is running. Wait for its outcome before ending receiving authorisation.')
        self.close();release(self.store)
        return {'ok':True}
