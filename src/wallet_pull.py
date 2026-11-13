"""Receiver-approved wallet requests on an existing pinned Agent-only direct link.

The Server cannot initiate these exports. The exact pending request, signed
preview, destination and receiver's watch-only choice are bound before sending.
"""
import secrets,threading,time
from approval_store import digest
from peer_protocol import hexid
from relay_stream import wire_hash

MESSAGES={
    'busy':'The source Agent is busy. Finish its current operation, then approve receiving again.',
    'request_changed':'The source no longer has this exact wallet offer. Refresh synchronisation on the receiver.',
    'preview_changed':'The source wallet or signed preview changed. Refresh and review the receiving request again.',
    'transfer_failed':'The source could not finish sending this wallet. Check its Synchronisation status; no transfer was retried automatically.'}

class Pull:
    def __init__(self,peers,transfer,operation_lock=None,guard=lambda:False):
        self.peers=peers;self.transfer=transfer;self.store=transfer.store;self.operation_lock=operation_lock or threading.RLock();self.guard=guard;self.lock=threading.RLock();self.sent={};self.seen={};self.threads=[]
    def request(self,key,p):
        from wallet_preview import verify_bound
        from sync_preferences import policy_id
        s=self.store.read();row=s['pending'].get(key);batch=s.get('sync_batch',{})
        if not row or row.get('withdrawn') or row['state']!='pending' or row['proposal']!=p or p.get('transfer_version')!=3 or p['direction']!='receive' or policy_id(p) in s.get('sync_exclusions',{}):raise ValueError('This wallet no longer has local receiving approval.')
        if s.get('active_transfer')!=key and not (batch.get('direction')=='receive' and key in batch.get('keys',[])):raise ValueError('Approve receiving this wallet before requesting its data.')
        payload=s.get('transfer_previews',{}).get(key);verify_bound(self.store,payload,p)
        channel=self.peers.binding(p);self.peers.direct.require(channel)
        if channel.peer['role']!='agent':raise ValueError('Wallet sync requires a trusted Agent connection.')
        choice=batch.get('options',{}).get(key,{})
        watch=not p['source_has_private_keys'] or choice.get('watch_only',False)
        token=secrets.token_hex(32);event=threading.Event();entry={'channel':channel,'operation':wire_hash(p),'event':event,'reason':None,'at':time.monotonic(),'key':key}
        with self.lock:
            self.sent={k:v for k,v in self.sent.items() if time.monotonic()-v['at']<2400}
            if len(self.sent)>=128:raise ValueError('Too many recent receiving requests. No automatic retry was started.')
            self.sent[token]=entry
        from activity_log import event as log_event
        log_event('sync.pull','Request sent to pinned source · request='+key[:12])
        channel.send('stream_wallet_pull',entry['operation'],{'token':token,'transfer_id':p['transfer_id'],'preview_hash':digest(payload),'watch_only':watch},ttl=60)
        deadline=time.monotonic()+20
        while not event.wait(.1):
            if not self.transfer.listener or self.peers.stop.is_set() or time.monotonic()>deadline:raise ValueError('The source did not accept the receiving request. Install Build 84 on both Agents and check their direct connection. No sender approval is required.')
        log_event('sync.pull','Source response · status='+(entry['reason'] or 'accepted')+' · request='+key[:12])
        if entry['reason']:raise ValueError(MESSAGES[entry['reason']])
    def __call__(self,channel,record):
        self.peers.direct.require(channel)
        if channel.peer['role']!='agent':raise ValueError('Mobile devices cannot request wallet exports.')
        b=record['body'];kind=record['payload_type'];operation=record['operation_hash']
        if kind=='stream_wallet_pull_result':
            if not isinstance(b,dict) or set(b)!={'token','status'} or not hexid(b['token']) or b['status'] not in ('accepted',*MESSAGES):raise ValueError('Invalid direct wallet response.')
            with self.lock:
                entry=self.sent.get(b['token'])
                if not entry or entry['channel'] is not channel or entry['operation']!=operation:raise ValueError('Wallet response belongs to another approved request.')
                entry['reason']=None if b['status']=='accepted' else b['status'];entry['event'].set()
                s=self.store.read();batch=s.get('sync_batch',{})
                if entry['reason'] and entry['key'] in s['pending'] and (s.get('active_transfer')==entry['key'] or batch.get('direction')=='receive' and entry['key'] in batch.get('keys',[])):self.transfer.error=MESSAGES[entry['reason']]
            return True
        if kind!='stream_wallet_pull' or not isinstance(b,dict) or set(b)!={'token','transfer_id','preview_hash','watch_only'} or not all(hexid(b[k]) for k in ('token','transfer_id','preview_hash')) or type(b['watch_only']) is not bool:raise ValueError('Invalid direct wallet receiving request.')
        with self.lock:
            self.seen={k:v for k,v in self.seen.items() if time.monotonic()-v<2400}
            identity=(channel.peer['endpoint_id'],b['token'])
            if identity in self.seen or len(self.seen)>=128:raise ValueError('Duplicate or excessive wallet receiving request.')
            self.seen[identity]=time.monotonic()
        thread=threading.Thread(target=self.serve,args=(channel,operation,dict(b)),daemon=True,name='receiver-requested-wallet-send');self.threads=[t for t in self.threads if t.is_alive()];self.threads.append(thread);thread.start();return True
    def reply(self,channel,operation,b,status):
        channel.send('stream_wallet_pull_result',operation,{'token':b['token'],'status':status},ttl=60)
    def serve(self,channel,operation,b):
        acquired=False;reserved=False;reason='request_changed'
        try:
            acquired=self.operation_lock.acquire(timeout=5)
            if not acquired or self.guard():reason='busy';raise ValueError()
            self.peers.direct.require(channel)
            s=self.store.read()
            if s.get('sync_batch') or s.get('active_transfer') or self.transfer.listener or getattr(self.transfer,'sending',False):reason='busy';raise ValueError()
            candidates=[(k,r) for k,r in s['pending'].items() if r['proposal'].get('kind')=='wallet_transfer' and r['proposal'].get('transfer_version')==3 and r['proposal']['direction']=='send' and r['state']=='pending' and not r.get('withdrawn') and r['proposal']['transfer_id']==b['transfer_id'] and wire_hash(r['proposal'])==operation]
            if len(candidates)!=1:raise ValueError()
            key,row=candidates[0];p=row['proposal']
            if self.peers.binding(p) is not channel:raise ValueError()
            from sync_table import sender_enabled
            if not sender_enabled(s,p):raise ValueError()
            reason='preview_changed';payload=s.get('transfer_previews',{}).get(key)
            from wallet_preview import verify_bound
            if not payload or digest(payload)!=b['preview_hash']:raise ValueError()
            verify_bound(self.store,payload,p)
            if not p['source_has_private_keys'] and not b['watch_only']:raise ValueError()
            from managed_accounts import guard
            guard(self.transfer.core,p,self.store,public_preview=True)
            with self.store.edit() as state:
                if state.get('sync_batch') or state.get('active_transfer') or state['pending'].get(key)!=row:reason='busy';raise ValueError()
                state['active_transfer']=key;state['sync_batch']={'keys':[key],'direction':'send','options':{key:{'watch_only':b['watch_only']}},'at':time.time(),'receiver_initiated':True}
            reserved=True;self.transfer.sending=True;self.transfer.error='';reason='transfer_failed'
            self.reply(channel,operation,b,'accepted')
            self.transfer.send(key)
        except Exception as error:
            if reserved:self.transfer.error=MESSAGES[reason]
            from activity_log import event
            event('sync.pull','Receiver-requested send stopped · reason='+reason+' · exception='+type(error).__name__)
            try:self.reply(channel,operation,b,reason)
            except Exception:pass
        finally:
            if reserved:
                from sync_queue import release
                release(self.store);self.transfer.sending=False
            if acquired:self.operation_lock.release()
