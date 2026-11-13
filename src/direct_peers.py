"""Volatile, role-bound direct SSH lifecycle. Relay never carries stream bytes."""
import secrets,subprocess,json,threading,time
from direct_protocol import make,validate,address
from peer_protocol import digest,hexid
MAX_AGE=86400

def candidates():
    result=[]
    try:
        output=subprocess.run(['/usr/sbin/ip','-j','address','show'],capture_output=True,text=True,timeout=3,check=True)
        for device in json.loads(output.stdout):
            for row in device.get('addr_info',[]):
                try:ip=address(row['local'])
                except (ValueError,KeyError):continue
                if ip not in result:result.append(ip)
    except (OSError,ValueError,subprocess.SubprocessError):pass
    return sorted(result,key=lambda ip:':' not in ip)[:8]

class Epoch:
    def __init__(self,channel):
        from direct_ssh import key
        self.channel=channel;self.id=secrets.token_hex(32);self.remote_id=None;self.epoch=self.id;self.client_key=key();self.remote_key=None;self.created=time.monotonic();self.deadline=self.created+MAX_AGE;self.offer=None;self.remote_offer=None;self.listener=None;self.sessions={};self.remote_ready={};self.selected=None;self.selection_sent=False;self.closed=False;self.seen={};self.attempted=False;self.settled=False
    @property
    def negotiation(self):return min(self.id,self.remote_id) if self.remote_id else self.id
    def close(self):
        if self.closed:return
        self.closed=True
        for session in list(self.sessions.values()):session.close()
        if self.listener:self.listener.close()
        self.client_key=None;self.remote_key=None;self.offer=None;self.remote_offer=None;self.seen.clear()

class Direct:
    def __init__(self,peers,addresses=candidates,loopback=False):
        self.peers=peers;self.addresses=addresses;self.loopback=loopback;self.states={};self.active={};self.disabled={i for i,p in peers.persistence.read()['pairs'].items() if p.get('direct_enabled') is False};self.retry={};self.slots=threading.BoundedSemaphore(4);self.stop=threading.Event();self.wake=threading.Event();self.last_addresses=None;self.last_address_check=0;self.thread=None;self.retirements={};self.messages={};peers.direct=self
    def start(self):
        if not self.thread or not self.thread.is_alive():self.thread=threading.Thread(target=self.run,daemon=True,name='direct-peer-lifecycle');self.thread.start()
    def emit(self,state,kind,body):
        value=make(kind,state.negotiation,state.epoch,self.peers.identity,state.channel.peer,body)
        state.channel.send('peer.direct',digest(state.channel.prologue),value)
        return value
    def begin(self,c):
        ident=c.peer['endpoint_id'];old=self.states.pop(ident,None)
        if old and old is not self.active.get(ident):old.close()
        if len(self.states)>=8:raise ValueError('Direct connection limit reached. Delete an unused connection first.')
        state=Epoch(c);self.states[ident]=state
        from direct_ssh import public
        self.emit(state,'client-key',{'client_public_key':public(state.client_key)})
        self.messages[ident]='Negotiating a direct connection.';return state
    def handle(self,c,record):
        if record['payload_type']!='peer.direct':return False
        if record['operation_hash']!=digest(c.prologue):raise ValueError('Direct negotiation belongs to another logical channel.')
        value=record['body'];kind=validate(value,self.peers.identity,c.peer,self.loopback);ident=c.peer['endpoint_id']
        with self.peers.lock:
            if ident in self.disabled:return True
            state=self.states.get(ident)
            if kind=='disconnect':self.delete(ident,notify=False);return True
            if kind=='client-key':
                if not state or state.closed or state.channel is not c or state.settled:
                    state=self.begin(c)
                if state.remote_id and state.remote_id!=value['negotiation_id']:
                    # A new peer renewal cannot replace an unfinished exchange.
                    if time.monotonic()-state.created<120:return True
                    state=self.begin(c)
                if state.remote_id and state.remote_key!=value['body']['client_public_key']:raise ValueError('Direct client key changed within the same negotiation.')
                state.remote_id=value['negotiation_id'];state.remote_key=value['body']['client_public_key'];state.epoch=state.negotiation
                # Sender clock may be ahead: local receipt always starts a <=24h limit.
                self.offer(state);return True
            if not state or state.closed or value['negotiation_id']!=state.negotiation or value['epoch_id']!=state.epoch:return True
            marker=(kind,value['body'].get('offer_hash',value['body'].get('old_epoch_id','')))
            previous=state.seen.get(marker);content=digest({k:v for k,v in value.items() if k not in ('created_utc','expires_utc')})
            if previous and previous!=content:raise ValueError('Contradictory direct negotiation record.')
            if marker not in state.seen and len(state.seen)>=16:raise ValueError('Direct negotiation record limit exceeded.')
            state.seen[marker]=content
            b=value['body']
            if kind=='offer':
                from direct_ssh import public,connect
                if b['server_endpoint']!=ident or b['client_endpoint']!=self.peers.identity['endpoint_id'] or b['client_public_key']!=public(state.client_key):raise ValueError('Direct offer keys or direction changed.')
                if state.remote_offer and digest(state.remote_offer)!=digest(value):raise ValueError('Direct offer changed within an epoch.')
                if not state.remote_offer:
                    state.remote_offer=value
                    threading.Thread(target=connect,args=(self,state,value),daemon=True,name='direct-peer-client').start()
            elif kind=='accept':
                if not state.offer or b['offer_hash']!=digest(state.offer):raise ValueError('Unrecognised direct acceptance.')
            elif kind=='ready':
                if b['offer_hash'] not in {digest(o) for o in (state.offer,state.remote_offer) if o}:raise ValueError('Unknown direct ready offer.')
                state.remote_ready[b['offer_hash']]=b['ssh_session_binding']
            elif kind in ('select','selected'):
                if kind=='select' and state.negotiation!=state.remote_id or kind=='selected' and state.negotiation!=state.id:raise ValueError('Only the elected peer selects a direct orientation.')
                session=state.sessions.get(b['offer_hash'])
                if not session or session.dead or state.remote_ready.get(session.hash)!=session.binding:raise ValueError('Unconfirmed direct orientation.')
                if state.selected and state.selected!=session.hash:raise ValueError('Direct selection changed.')
                state.selected=session.hash;session.selected=True
                if kind=='select':self.emit(state,'selected',{'offer_hash':session.hash})
                session.write({'type':'selected','offer_hash':session.hash})
            elif kind=='retire':
                active=self.active.get(ident)
                if active is not state or not self.ready(ident) or b['new_epoch_id']!=state.epoch:raise ValueError('No authenticated cutover permits old credential destruction.')
                old=self.retirements.pop((ident,b['old_epoch_id']),None)
                if old:old.close()
                self.emit(state,'retired',b)
            elif kind=='retired':self.messages[ident]='Direct connection ready. Previous session credentials retired on both devices.'
        return True
    def offer(self,state):
        if state.offer or self.peers.identity['role']=='mobile' and state.channel.peer['role']=='agent':return
        from direct_ssh import key,public,Listener
        ips=[address(ip,self.loopback) for ip in self.addresses()][:8]
        if not ips:return
        host=key();login='w'+secrets.token_hex(15);listener=Listener(self,state,host,state.remote_key,login)
        state.listener=listener
        state.offer=make('offer',state.negotiation,state.epoch,self.peers.identity,state.channel.peer,{'server_endpoint':self.peers.identity['endpoint_id'],'client_endpoint':state.channel.peer['endpoint_id'],'candidates':[{'ip':ip,'port':listener.port} for ip in ips],'host_public_key':public(host),'login_id':login,'client_public_key':state.remote_key,'credential_max_age_seconds':86400})
        # Public key authorisation is already installed in this listener object.
        threading.Thread(target=listener.run,daemon=True,name='direct-peer-listener').start();state.channel.send('peer.direct',digest(state.channel.prologue),state.offer)
    def established(self,session):
        with self.peers.lock:
            state=session.state
            if state.closed or self.states.get(state.channel.peer['endpoint_id']) is not state or time.monotonic()>=state.deadline:raise ValueError('Superseded direct session.')
            if session.hash in state.sessions:raise ValueError('Duplicate direct SSH connection.')
            state.sessions[session.hash]=session
            if session.client:self.emit(state,'accept',{'offer_hash':session.hash})
            self.emit(state,'ready',{'offer_hash':session.hash,'ssh_session_binding':session.binding})
    def tick(self):
        now=time.monotonic()
        with self.peers.lock:
            if now-self.last_address_check>15:
                ips=tuple(self.addresses());self.last_address_check=now
                if self.last_addresses is not None and ips!=self.last_addresses:
                    for ident,state in list(self.states.items()):
                        if state.settled:self.begin(state.channel)
                self.last_addresses=ips
            for ident,c in list(self.peers.channels.items()):
                if not c.ready or ident in self.disabled:continue
                state=self.states.get(ident);active=self.active.get(ident)
                if active and (active.closed or now>=active.deadline or active.selected and active.sessions[active.selected].dead):
                    active.close();self.peers.drop(ident);self.messages[ident]='Direct connection interrupted. Inspect the transfer before retrying; no bulk data was sent through the relay.';continue
                if not state or state.closed or state.channel is not c or state.settled and now>=state.deadline-300:
                    if now>=self.retry.get(ident,0):state=self.begin(c);self.retry[ident]=now+30
                if not state:continue
                if not state.settled and now-state.created>120:
                    state.close();self.messages[ident]='No reachable direct connection. Check the peer network; no firewall was changed.';continue
                for pending_session in list(state.sessions.values()):
                    if not pending_session.dead and now-getattr(pending_session,'barrier_sent',0)>1:
                        pending_session.write({'type':'barrier','tx':c.tx,'rx':c.rx});pending_session.barrier_sent=now
                eligible=[s for s in state.sessions.values() if not s.dead and state.remote_ready.get(s.hash)==s.binding]
                # Give both orientations a bounded opportunity to prove reachable.
                expected=1 if self.peers.identity['role']!=c.peer['role'] else 2
                if not state.selected and state.negotiation==state.id and eligible and (len(eligible)>=expected or now-state.created>12):
                    session=secrets.choice(eligible);state.selected=session.hash;session.selected=True;self.emit(state,'select',{'offer_hash':session.hash});session.write({'type':'selected','offer_hash':session.hash})
                if state.selected:
                    session=state.sessions[state.selected]
                    if session.dead:continue
                    if now-getattr(session,'barrier_sent',0)>1:
                        session.write({'type':'barrier','tx':c.tx,'rx':c.rx});session.barrier_sent=now
                    # No queued logical relay frames may be overtaken at cutover.
                    if session.remote_selected and session.remote_barrier==(c.rx,c.tx):
                        if self.active.get(ident) is not state:
                            old=self.active.get(ident);self.active[ident]=state;state.settled=True;session.write({'type':'active','offer_hash':session.hash});self.messages[ident]='Direct SSH ready. Bulk data bypasses Wallet Server.'
                            for other in list(state.sessions.values()):
                                if other is not session:other.close()
                            if state.listener and session.client:state.listener.close();state.listener=None
                            if old and old is not state:
                                self.retirements[(ident,old.epoch)]=old
                # Keep a still-valid active connection moving during renewal.
                active=self.active.get(ident)
                if active and self.ready(ident):
                    for (peer,oldid),old in list(self.retirements.items()):
                        if peer==ident:
                            old.close();self.retirements.pop((peer,oldid),None);self.emit(active,'retire',{'old_epoch_id':oldid,'new_epoch_id':active.epoch,'reason':'rotation'})
                    session=active.sessions[active.selected]
                    if now-getattr(session,'barrier_sent',0)>1:
                        session.write({'type':'barrier','tx':c.tx,'rx':c.rx});session.barrier_sent=now
                    pending=[f for f in self.peers.outgoing.values() if f['to']==ident and f['channel_id']==c.id]
                    for frame in pending[:8]:
                        if frame['id'] in session.tx_pending:continue
                        if len(session.tx_pending)>=8:break
                        session.tx_pending[frame['id']]=now;session.write({'type':'frame','frame':frame})
                    if any(now-at>20 for at in session.tx_pending.values()):session.close()
    def ready(self,ident):
        state=self.active.get(ident)
        return bool(state and not state.closed and time.monotonic()<state.deadline and state.selected and not state.sessions[state.selected].dead and state.sessions[state.selected].remote_active)
    def holds(self,frame):
        # Once direct is active, all logical frames use the same ordered path.
        # Stream records are blocked from relay independently in Channel.send.
        return self.ready(frame['to'])
    def require(self,c):
        if not self.ready(c.peer['endpoint_id']):raise ValueError('A direct Agent connection is required. Open Peer Connections and reconnect the relevant Agent before continuing.')
    def status(self,ident):
        state=self.active.get(ident);pending=self.states.get(ident)
        return {'state':'disabled' if ident in self.disabled else 'ready' if self.ready(ident) else 'negotiating' if pending and not pending.closed else 'waiting','message':self.messages.get(ident,'Waiting for a direct connection.'),'expires_in':max(0,int(state.deadline-time.monotonic())) if state and self.ready(ident) else None,'server':bool(state and state.selected and not state.sessions[state.selected].client)}
    def delete(self,ident,notify=True):
        with self.peers.lock:
            state=self.states.get(ident)
            if notify and state and state.channel.ready:self.emit(state,'disconnect',{})
            self.disabled.add(ident)
            if notify:self.preference(ident,False)
            for epoch in (self.states.pop(ident,None),self.active.pop(ident,None)):
                if epoch:epoch.close()
            for (peer,epoch),old in list(self.retirements.items()):
                if peer==ident:old.close();self.retirements.pop((peer,epoch),None)
            if hasattr(self.peers,'wallet_bridge'):self.peers.wallet_bridge.closed(ident)
            self.messages[ident]='Direct connection deleted; its volatile credentials were released. QR pairing is retained. Reconnect locally when wanted.'
        return {'message':self.messages[ident]}
    def reconnect(self,ident):
        with self.peers.lock:
            c=self.peers.channels.get(ident)
            if not c or not c.ready:raise ValueError('Wait for the paired encrypted control channel first.')
            self.preference(ident,True);self.disabled.discard(ident);self.retry.pop(ident,None);self.begin(c)
        return {'message':'Fresh direct credentials are being negotiated.'}
    def preference(self,ident,enabled):
        saved=self.peers.persistence.read()
        if ident in saved['pairs']:
            saved['pairs'][ident]['direct_enabled']=enabled;saved['revision']+=1;self.peers.persistence.commit(saved['revision']-1,saved)
    def closed(self,ident):
        self.delete(ident,False)
        if self.peers.persistence.read()['pairs'].get(ident,{}).get('direct_enabled') is not False:self.disabled.discard(ident)
    def run(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception:
                # One failed epoch never grants authority or replays a wallet job.
                for ident,state in list(self.states.items()):
                    if not state.settled and time.monotonic()-state.created>120:state.close()
            self.wake.wait(.1);self.wake.clear()
    def close(self):
        self.stop.set();self.wake.set()
        for ident in set(self.states)|set(self.active):self.closed(ident)
