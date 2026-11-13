"""Locally granted Noise peers; the relay sees ciphertext and public routing only."""
import copy,json,secrets,threading,time
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from noise.connection import NoiseConnection,Keypair
from peer_protocol import *
from setup_messages import sign,verify

class Channel:
    def __init__(self,owner,peer,psk,invitation,initiator,channel_id=None,known=False):
        self.owner=owner;self.peer=participant(peer);self.psk=psk;self.invitation=invitation;self.initiator=initiator;self.id=channel_id or secrets.token_hex(32);self.known=known;self.local_grant=known or initiator;self.remote_grant=False;self.ready=False;self.created=time.monotonic();self.seen=self.created;self.tx=0;self.rx=0;self.outgoing={};self.lock=owner.lock
        self.prologue={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'channel_id':self.id,'invitation_id':invitation,'initiator':owner.identity if initiator else peer,'responder':peer if initiator else owner.identity}
        self.proof={'protocol':PROTOCOL,'version':1,'kind':'handshake','prologue_hash':digest(self.prologue),'initiator':self.prologue['initiator'],'responder':self.prologue['responder']}
        self.noise=NoiseConnection.from_name(CIPHER.encode());self.noise.set_as_initiator() if initiator else self.noise.set_as_responder();self.noise.set_keypair_from_private_bytes(Keypair.STATIC,binary(owner.private));self.noise.set_psks(psk=binary(psk));self.noise.set_prologue(canonical(self.prologue))
        if initiator:self.noise.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC,binary(peer['noise_public_key']))
        self.noise.start_handshake()
    def emit(self,kind,data,sequence):
        value={'version':1,'id':secrets.token_hex(32),'from':self.owner.identity['endpoint_id'],'to':self.peer['endpoint_id'],'channel_id':self.id,'sequence':sequence,'kind':kind,'ciphertext':b64(bytes(data))};frame(value);self.owner.queue(value);return value
    def first(self):
        self.emit('handshake',self.noise.write_message(canonical(sign(self.owner.store,self.proof,HANDSHAKE))),0)
    def handshake(self,value):
        if value['sequence']!=0 or self.noise.handshake_finished:raise ValueError('Replayed peer handshake.')
        payload=self.noise.read_message(__import__('base64').b64decode(value['ciphertext']));envelope=self.owner.decode(payload)
        if verify(self.owner.store,envelope,self.peer['identity_key'],HANDSHAKE)!=self.proof:raise ValueError('Peer handshake proof differs from pinned roles or transcript.')
        if not self.initiator:
            actual=self.noise.noise_protocol.handshake_state.rs.public_bytes
            if actual!=binary(self.peer['noise_public_key']):raise ValueError('Noise initiator static key differs from its signed identity.')
            self.emit('handshake',self.noise.write_message(canonical(sign(self.owner.store,self.proof,HANDSHAKE))),0)
        if not self.noise.handshake_finished:raise ValueError('Incomplete peer handshake.')
        self.handshake_hash=self.noise.get_handshake_hash().hex();self.seen=time.monotonic()
        if self.local_grant:self.send('grant',digest(self.prologue),{'accepted':True})
    def send(self,kind,operation,body,ttl=None):
        if kind.startswith('stream_') or kind=='policy_agreement':
            direct=getattr(self.owner,'direct',None)
            if not direct:raise ValueError('Connect the paired Agent in Peer Connections before continuing. Policy confirmation and transfers require the direct connection.')
            direct.require(self)
        ttl=ttl if ttl is not None else (3600 if kind.startswith('stream_') or kind in ('ping','pong') else 120)
        with self.lock:
            if not self.noise.handshake_finished or not self.local_grant or kind!='grant' and not self.ready:raise ValueError('Finish authenticated local peer pairing first.')
            header={'version':1,'id':secrets.token_hex(32),'from':self.owner.identity['endpoint_id'],'to':self.peer['endpoint_id'],'channel_id':self.id,'sequence':self.tx,'kind':'transport'}
            record={'protocol':PROTOCOL,'version':1,'header':header,'role':self.owner.identity['role'],'operation_hash':operation,'payload_type':kind,'expires_at':int(time.time())+ttl,'body':body}
            raw=canonical(record)
            if len(raw)>48000 or not hexid(operation):raise ValueError('Invalid encrypted application record.')
            if len(self.owner.outgoing)>=120:raise ValueError('Encrypted relay queue is full; wait for delivery before retrying.')
            ciphertext=self.noise.encrypt(raw);value={**header,'ciphertext':b64(bytes(ciphertext))};frame(value);self.tx+=1
            if kind.startswith('stream_'):self.owner.bulk_frames.add(value['id'])
            self.owner.queue(value);return header['id']
    def read(self,value,direct=False):
        if value['sequence']!=self.rx or not self.noise.handshake_finished:raise ValueError('Encrypted peer frames were reordered or replayed. Reconnect securely.')
        record=self.owner.decode(self.noise.decrypt(__import__('base64').b64decode(value['ciphertext'])))
        expected={k:v for k,v in value.items() if k!='ciphertext'}
        if not isinstance(record,dict) or set(record)!={'protocol','version','header','role','operation_hash','payload_type','expires_at','body'} or record['protocol']!=PROTOCOL or type(record['version']) is not int or record['version']!=1 or record['header']!=expected or record['role']!=self.peer['role'] or not hexid(record['operation_hash']) or type(record['expires_at']) is not int or not time.time()<=record['expires_at']<=time.time()+3600:raise ValueError('Encrypted application header, role or expiry mismatch.')
        if not isinstance(record['payload_type'],str) or len(record['payload_type'])>48:raise ValueError('Invalid encrypted payload type.')
        kind=record['payload_type']
        if (kind.startswith('stream_') or kind=='policy_agreement') and not direct:raise ValueError('Wallet data and policy confirmations require the direct Agent connection.')
        self.rx+=1;self.seen=time.monotonic()
        if kind=='grant':
            if record['operation_hash']!=digest(self.prologue) or record['body']!={'accepted':True}:raise ValueError('Invalid local peer grant.')
            self.remote_grant=True
            if self.local_grant:
                if not self.ready:
                    self.owner.persist(self);self.ready=True
                    self.send('ping',digest(self.prologue),{'nonce':secrets.token_hex(16),'device_name':self.owner.device_name})
            return
        if not self.ready or not self.local_grant:raise ValueError('Peer has not been granted application authority locally.')
        if kind=='ping':self.owner.peer_name(self,record['body']);self.send('pong',record['operation_hash'],record['body']);return
        if kind=='pong':return
        self.owner.application(self,record)

class Peers:
    def __init__(self,store,persistence=None,role='agent'):
        from peer_storage import Client
        self.device_name=__import__('socket').gethostname()[:128]
        self.store=store;self.persistence=persistence or Client();self.lock=threading.RLock();self.channels={};self.invitations={};self.pending={};self.outgoing={};self.bulk_frames=set();self.acks=[];self.seen_ids={};self.agreements={};self.listeners=[];self.error='';self.registered=False;self.last_directory=[];self.closed_reports=[];self.backpressured_until=0;self.importing=None;self.stop=threading.Event();self.rpc=None;self.thread=None
        saved=self.persistence.read()
        if saved['private_key'] is None:
            saved['private_key']=b64(X25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()));saved['revision']+=1;self.persistence.commit(saved['revision']-1,saved)
        self.private=saved['private_key'];key=sign(store,{'purpose':'peer-identity','version':1})['public_key'];public=X25519PrivateKey.from_private_bytes(binary(self.private)).public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.identity={'endpoint_id':endpoint(role,key),'role':role,'identity_key':key,'noise_public_key':b64(public)};store.peers=self
    @staticmethod
    def decode(raw):
        from denial_storage import strict_json
        if len(raw)>65536:raise ValueError('Oversized peer message.')
        return strict_json(raw)
    def queue(self,value):
        with self.lock:
            if len(self.outgoing)>=128:raise ValueError('Local encrypted relay queue is full; no application operation was repeated.')
            self.outgoing[value['id']]=value
            if getattr(self,'direct',None) and hasattr(self.direct,'wake'):self.direct.wake.set()
    def prune_local(self):
        for ident,c in list(self.channels.items()):
            if not c.ready and time.monotonic()-c.created>120:
                self.drop(ident)
                self.connection_error('pairing_expired','Pairing did not complete within two minutes. Keep both devices connected to Wallaby Wallet, generate a fresh QR and scan again.')
        self.invitations={k:v for k,v in self.invitations.items() if v['expires_at']>time.time()}
    def create_invitation(self,role,relay):
        self.prune_local()
        if self.pending:raise ValueError('Approve or reject the pending local pairing before creating another invitation.')
        auto=role in ('auto','connect')
        if role not in ('agent','mobile','auto','connect') or self.identity['role']=='mobile' and not auto:raise ValueError('Invalid pairing role.')
        self.validate_route(relay);now=int(time.time());ident=secrets.token_hex(32)
        message={'protocol':'wallaby-wallet-peer-pair','version':1,'kind':'agent_invitation','invitation_id':ident,'issuer_role':'agent','allowed_peer_role':role,'issuer_identity_key':self.identity['identity_key'],'issuer_noise_public_key':self.identity['noise_public_key'],'issuer_endpoint_id':self.identity['endpoint_id'],'cipher_suite':CIPHER,'pairing_secret':b64(secrets.token_bytes(32)),'expires_at':now+120,'relay':relay}
        if auto:message.update(version=2,issuer_role=self.identity['role'],allowed_peer_role='auto' if self.identity['role']=='agent' else 'agent',issuer_name=self.valid_name(self.device_name))
        if role=='connect':message.update(version=3,pairing_mode='scan-connect')
        with self.lock:self.invitations={ident:message}
        return sign(self.store,message,INVITATION)
    @staticmethod
    def validate_route(route):
        from configuration import hostname
        from wallet_preview import fingerprint
        if not isinstance(route,dict) or set(route)!={'host','port','user','host_public_key','host_fingerprint','agent_port','mobile_port'} or hostname(route['host'])!=route['host'] or type(route['port']) is not int or not 1<=route['port']<=65535 or not isinstance(route['user'],str) or not re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}',route['user']) or fingerprint(route['host_public_key'])!=route['host_fingerprint'] or route['agent_port']!=56443 or route['mobile_port']!=56444:raise ValueError('Invalid independently pinned Server SSH route.')
    def import_invitation(self,envelope):
        m=envelope.get('message',{}) if isinstance(envelope,dict) else {};fields={'protocol','version','kind','invitation_id','issuer_role','allowed_peer_role','issuer_identity_key','issuer_noise_public_key','issuer_endpoint_id','cipher_suite','pairing_secret','expires_at','relay'}
        version=m.get('version')
        if version in (2,3):fields.add('issuer_name')
        if version==3:fields.add('pairing_mode')
        if set(m)!=fields or m['protocol']!='wallaby-wallet-peer-pair' or type(version) is not int or version not in (1,2,3) or m['kind']!='agent_invitation' or m['issuer_role'] not in ('agent','mobile') or version==1 and m['issuer_role']!='agent' or m['allowed_peer_role'] not in ((self.identity['role'],'auto') if version in (2,3) else (self.identity['role'],)) or m['issuer_role']==self.identity['role']=='mobile' or m['cipher_suite']!=CIPHER or not hexid(m['invitation_id']) or type(m['expires_at']) is not int or not time.time()<m['expires_at']<=time.time()+120 or m['issuer_endpoint_id']!=endpoint(m['issuer_role'],m['issuer_identity_key']):raise ValueError('Expired, wrong-role or invalid pairing invitation. Automatic pairing requires a matching updated Agent or Mobile.')
        if version==3 and m['pairing_mode']!='scan-connect':raise ValueError('Invalid QR connection mode.')
        if version in (2,3):
            self.valid_name(m['issuer_name'])
            if m['issuer_role']=='mobile' and m['allowed_peer_role']!='agent':raise ValueError('A Mobile can pair only with an Agent.')
        binary(m['pairing_secret']);binary(m['issuer_noise_public_key']);self.validate_route(m['relay']);verify(self.store,envelope,m['issuer_identity_key'],INVITATION)
        saved=self.persistence.read()
        if self.importing and self.importing['invitation_id']==m['invitation_id'] and m['issuer_endpoint_id'] in self.channels:raise ValueError('This pairing invitation is already in progress.')
        if m['invitation_id'] in saved['used'] or m['issuer_endpoint_id'] in saved['pairs'] or m['issuer_endpoint_id']==self.identity['endpoint_id']:raise ValueError('Invitation was already used or peer already paired. Revoke the old local pairing before replacing it.')
        peer={'endpoint_id':m['issuer_endpoint_id'],'role':m['issuer_role'],'identity_key':m['issuer_identity_key'],'noise_public_key':m['issuer_noise_public_key']}
        # The user imports the QR directly from the trusted Agent screen, not Server.
        c=Channel(self,peer,m['pairing_secret'],m['invitation_id'],True);self.channels[peer['endpoint_id']]=c;self.importing=m;c.first()
        self.diagnostic('pairing_started','QR accepted; authenticated pairing started')
        return {'message':'Connecting securely. Direct connection setup starts automatically.' if version==3 else 'Older pairing format: confirm this device on the QR-generating device.','peer':peer,'automatic':version==3}
    @staticmethod
    def valid_name(name):
        if not isinstance(name,str) or not name.strip() or len(name)>128 or any(ord(ch)<32 for ch in name):raise ValueError('Invalid peer device name.')
        return name
    def peer_name(self,c,body):
        # Authenticated display metadata only; roles and pinned keys cannot change.
        if not isinstance(body,dict) or 'device_name' not in body:return
        name=self.valid_name(body['device_name']);saved=self.persistence.read();row=saved['pairs'].get(c.peer['endpoint_id'])
        if row and row['peer']==c.peer and row['name']!=name:
            row['name']=name;saved['revision']+=1;self.persistence.commit(saved['revision']-1,saved)
    def persist(self,c):
        saved=self.persistence.read();existing=saved['pairs'].get(c.peer['endpoint_id'])
        label=existing['name'] if existing else c.peer['role'].title()+' '+fingerprint(c.peer['identity_key'])
        if not existing and self.importing and self.importing['invitation_id']==c.invitation:label=self.importing.get('issuer_name',label)
        value={'peer':c.peer,'psk':c.psk,'invitation_id':c.invitation,'initiator':c.initiator,'name':label}
        if existing and existing.get('direct_enabled') is not None:value['direct_enabled']=existing['direct_enabled']
        if existing and existing!=value:raise ValueError('Pinned peer keys or roles changed; revoke and pair locally again.')
        if not existing:
            saved['pairs'][c.peer['endpoint_id']]=value
            if c.invitation not in saved['used']:saved['used'].append(c.invitation)
            saved['revision']+=1;self.persistence.commit(saved['revision']-1,saved)
            self.diagnostic('pairing_saved','Authenticated pairing saved; direct SSH setup follows')
        self.invitations.pop(c.invitation,None);self.pending.pop(c.peer['endpoint_id'],None)
        if self.importing and self.importing['invitation_id']==c.invitation:self.importing=None
    def approve(self,ident):
        with self.lock:
            c=self.pending.get(ident)
            if not c or self.channels.get(ident) is not c or time.monotonic()-c.created>120 or not c.noise.handshake_finished:raise ValueError('This pairing confirmation expired. Create a fresh QR invitation.')
            saved=self.persistence.read()
            if c.invitation in saved['used']:raise ValueError('This invitation has already been accepted.')
            c.local_grant=True
            if c.remote_grant:self.persist(c)
            c.send('grant',digest(c.prologue),{'accepted':True});c.ready=c.remote_grant
            if c.ready:c.send('ping',digest(c.prologue),{'nonce':secrets.token_hex(16),'device_name':self.device_name})
            return {'message':'Local peer permission granted. Compare the same channel code on both devices.'}
    def revoke(self,ident):
        with self.lock:
            saved=self.persistence.read();saved['pairs'].pop(ident,None);saved['revision']+=1;self.persistence.commit(saved['revision']-1,saved);self.drop(ident);self.pending.pop(ident,None)
            return {'message':'Peer revoked locally. Its encrypted session is closed; a fresh QR pairing is required.'}
    def drop(self,ident):
        with self.lock:return self._drop(ident)
    def _drop(self,ident):
        c=self.channels.pop(ident,None);self.pending.pop(ident,None)
        if c:
            if c.ready:self.closed_reports.append(c)
            c.ready=False
            self.outgoing={k:v for k,v in self.outgoing.items() if v['channel_id']!=c.id}
            self.bulk_frames.intersection_update(self.outgoing)
            if getattr(self,'direct',None):self.direct.closed(ident)
            for listener in list(self.listeners):
                if hasattr(listener,'closed'):listener.closed(ident)
    def accept(self,value,directory,direct=False):
        frame(value);ident=value['from']
        if value['to']!=self.identity['endpoint_id']:raise ValueError('Peer frame is addressed to another endpoint.')
        with self.lock:
            if value['id'] in self.seen_ids:
                if self.seen_ids[value['id']]!=digest(value):raise ValueError('Conflicting peer frame ID.')
                return
            c=self.channels.get(ident)
            if value['kind']=='handshake' and (not c or c.id!=value['channel_id']):
                if c and c.ready:raise ValueError('A new channel cannot silently replace a live trusted session.')
                saved=self.persistence.read();binding=saved['pairs'].get(ident)
                if binding:
                    if binding['initiator']:raise ValueError('Unexpected reverse peer handshake.')
                    peer=binding['peer'];psk=binding['psk'];invitation=binding['invitation_id'];known=True
                else:
                    invitations=[m for m in self.invitations.values() if m['expires_at']>time.time() and m['invitation_id'] not in saved['used']]
                    if len(invitations)!=1 or self.pending:raise ValueError('No unused local QR invitation is awaiting a peer.')
                    m=invitations[0];matches=[r for r in directory if r.get('endpoint_id')==ident]
                    if any(other.invitation==m['invitation_id'] and not other.known for other in self.channels.values()):raise ValueError('This QR invitation is already connecting another channel.')
                    if len(matches)!=1:raise ValueError('Peer discovery is missing; no trust granted.')
                    row=matches[0];peer=participant({k:row[k] for k in ('endpoint_id','role','identity_key','noise_public_key')})
                    if m['allowed_peer_role'] not in ('auto',peer['role']) or peer['role']==self.identity['role']=='mobile':raise ValueError('Mobile cannot claim Agent authority.')
                    psk=m['pairing_secret'];invitation=m['invitation_id'];known=False
                c=Channel(self,peer,psk,invitation,False,value['channel_id'],known);self.channels[ident]=c
            if not c or c.id!=value['channel_id']:raise ValueError('Unknown or stale peer channel.')
            try:
                if value['kind']=='handshake':
                    c.handshake(value)
                    invitation=self.invitations.get(c.invitation)
                    if not c.local_grant and invitation and invitation.get('version')==3 and invitation.get('pairing_mode')=='scan-connect':
                        # Generating this one-use QR and scanning it are the local
                        # pairing actions. Grant only after PSK, typed identity,
                        # static key and signed transcript verification succeed.
                        c.local_grant=True
                        c.send('grant',digest(c.prologue),{'accepted':True})
                        self.diagnostic('pairing_authenticated','QR peer authenticated; completing automatic pairing')
                    if not c.local_grant:self.pending[ident]=c
                else:c.read(value,direct)
            except Exception:self.drop(ident);raise
            if len(self.seen_ids)>=1024:self.seen_ids.pop(next(iter(self.seen_ids)))
            self.seen_ids[value['id']]=digest(value)
    def channel(self,identity,role='agent'):
        ident=endpoint(role,identity);c=self.channels.get(ident);saved=self.persistence.read()['pairs'].get(ident)
        if not c or not c.ready or not c.local_grant or not saved or saved['peer']!=c.peer or time.monotonic()-c.seen>75:raise ValueError('The independently paired '+role+' channel is unavailable. Open Peer Connections and reconnect both devices.')
        return c
    def binding(self,p):
        value=transport(p);own='sender' if p['direction']=='send' else 'receiver';other='receiver' if own=='sender' else 'sender'
        if value[own+'_endpoint']!=self.identity['endpoint_id'] or value[own+'_identity']!=self.identity['identity_key'] or value[own+'_noise_key']!=self.identity['noise_public_key']:raise ValueError('Wallet transport does not identify this Agent.')
        c=self.channel(value[other+'_identity'])
        if c.peer['endpoint_id']!=value[other+'_endpoint'] or c.peer['noise_public_key']!=value[other+'_noise_key']:raise ValueError('Server substituted a pinned wallet peer.')
        return c
    def application(self,c,record):
        if record['payload_type']=='peer.direct':
            direct=getattr(self,'direct',None)
            if not direct:raise ValueError('Direct peer negotiation is unavailable.')
            return direct.handle(c,record)
        if record['payload_type']=='policy_agreement':
            if c.peer['role']!='agent':raise ValueError('A Mobile cannot approve an Agent policy.')
            body=record['body']
            if not isinstance(body,dict) or set(body)!={'scope','digest'} or body['scope'] not in ('proposal','policy','refresh') or not hexid(body['digest']):raise ValueError('Invalid encrypted policy agreement.')
            if len(self.agreements)>=256:self.agreements.pop(next(iter(self.agreements)))
            self.agreements[(c.peer['endpoint_id'],record['operation_hash'],body['scope'])]=(body['digest'],time.monotonic(),c.id);return
        if c.peer['role']=='mobile':
            from mobile_verification import respond
            return respond(self,c,record)
        for listener in list(self.listeners):
            if listener(c,record):return
        raise ValueError('Unsupported encrypted Agent operation; no authority granted.')
    def agreement(self,required,operation,scope,value):
        requirements(required);own=self.identity['identity_key']
        if own not in required['required_agent_keys']:raise ValueError('This Agent is absent from the producing mesh.')
        others=[self.channel(k) for k in required['required_agent_keys'] if k!=own]
        expected=digest(value)
        for c in others:c.send('policy_agreement',operation,{'scope':scope,'digest':expected})
        for c in others:
            record=self.agreements.get((c.peer['endpoint_id'],operation,scope))
            if not record:raise ValueError('Waiting for independently paired Agents to review this exact '+scope+'. No keys or policy were changed. Retry after their reviews are open.')
            if record[0]!=expected or record[2]!=c.id or time.monotonic()-record[1]>300:raise ValueError('Agents disagree on the exact '+scope+' or its channel changed. No operation was authorised.')
        return True
    def status(self):
        with self.lock:return self._status()
    def diagnostic(self,code,message):
        # Fixed messages only: never log QR secrets, frames, keys or raw errors.
        from activity_log import event
        if code!=getattr(self,'last_diagnostic',None):event('peers.connection',message+' · code='+code)
        self.last_diagnostic=code
    def connection_error(self,code,message):
        self.error=message;self.error_until=time.monotonic()+30
        self.diagnostic(code,message)
    def _status(self):
        self.prune_local()
        saved=self.persistence.read();rows=[]
        for ident,value in saved['pairs'].items():
            c=self.channels.get(ident);ready=bool(c and c.ready and time.monotonic()-c.seen<=75)
            rows.append({'id':ident,'role':value['peer']['role'],'name':value['name'],'fingerprint':fingerprint(value['peer']['identity_key']),'ready':ready,'channel_code':c.handshake_hash if c and c.noise.handshake_finished else None,'direct':self.direct.status(ident) if getattr(self,'direct',None) else None})
        pending=[{'id':i,'role':c.peer['role'],'fingerprint':fingerprint(c.peer['identity_key']),'identity_key':c.peer['identity_key'],'channel_code':c.handshake_hash,'expires_at':int(time.time()+max(0,120-(time.monotonic()-c.created)))} for i,c in self.pending.items()]
        connecting=[{'role':c.peer['role'],'message':'Authenticating scanned QR and waiting for the other device.'} for ident,c in self.channels.items() if ident not in saved['pairs'] and ident not in self.pending]
        return {'identity':self.identity,'pairs':rows,'pending':pending,'connecting':connecting,'error':self.error,'registered':self.registered}
    def connect(self,rpc):
        self.rpc=rpc
        if not self.thread or not self.thread.is_alive():
            self.diagnostic('relay_attached','Peer service attached to the authenticated node connection')
            self.stop.clear();self.thread=threading.Thread(target=self.run,daemon=True,name='encrypted-peer-relay');self.thread.start()
    def control(self,kind,fields):
        challenge=self.rpc({'action':'challenge'})
        if challenge.get('endpoint_id')!=self.identity['endpoint_id'] or challenge.get('role')!=self.identity['role'] or not hexid(challenge.get('challenge')):raise ValueError('Server returned a different relay identity.')
        message={'protocol':PROTOCOL,'version':1,'kind':kind,'endpoint_id':self.identity['endpoint_id'],'role':self.identity['role'],'challenge':challenge['challenge'],**fields}
        return self.rpc({'action':kind,'proof':sign(self.store,message,CONTROL)})
    def tick(self):
        self.prune_local()
        if not self.registered:
            self.control('register',{'noise_public_key':self.identity['noise_public_key'],'cipher_suite':CIPHER});self.registered=True
        directory=self.rpc({'action':'directory'})['endpoints']
        if not isinstance(directory,list) or len(directory)>256:raise ValueError('Oversized untrusted peer directory.')
        self.last_directory=directory
        saved=self.persistence.read()
        for ident,pair in saved['pairs'].items():
            c=self.channels.get(ident)
            active_stream=any(s.channel is c and not s.dead for s in getattr(getattr(self,'wallet_bridge',None),'streams',{}).values())
            if c and (time.monotonic()-c.seen>75 and not active_stream or not c.ready and time.monotonic()-c.created>120):self.drop(ident);c=None
            if not c and pair['initiator'] and any(r.get('endpoint_id')==ident and r.get('noise_public_key')==pair['peer']['noise_public_key'] for r in directory):
                c=Channel(self,pair['peer'],pair['psk'],pair['invitation_id'],True,known=True);self.channels[ident]=c;c.first()
        if time.monotonic()>=self.backpressured_until:
            from node_client import HTTPFailure
            for value in list(self.outgoing.values())[:16]:
                if value['id'] in self.bulk_frames or getattr(self,'direct',None) and self.direct.holds(value):continue
                try:self.rpc({'action':'send','frame':value})
                except HTTPFailure as error:
                    if error.safe_reason!='relay_busy':raise
                    self.backpressured_until=time.monotonic()+5;self.error='Wallet Server relay is full. The encrypted transfer is paused safely; no wallet operation is repeated.';break
                else:self.outgoing.pop(value['id'],None)
        for c in self.closed_reports[:8]:
            current=self.channels.get(c.peer['endpoint_id'])
            if not any(r.get('endpoint_id')==c.peer['endpoint_id'] for r in directory) or current and current.id!=c.id:
                self.closed_reports.remove(c);continue
            self.control('channel',{'peer_id':c.peer['endpoint_id'],'peer_role':c.peer['role'],'peer_noise_public_key':c.peer['noise_public_key'],'channel_id':c.id,'handshake_hash':c.handshake_hash,'state':'closed','paired_by_qr':True});self.closed_reports.remove(c)
        frames=self.rpc({'action':'receive'})['frames']
        if not isinstance(frames,list) or len(frames)>16:raise ValueError('Oversized untrusted relay delivery.')
        for value in frames:
            try:self.accept(value,directory)
            except Exception:self.connection_error('peer_message_refused','An unauthenticated, expired or inconsistent peer message was refused. Generate a new QR and scan again.')
            else:
                if value['id'] not in self.acks:self.acks.append(value['id'])
        if self.acks:self.rpc({'action':'ack','ids':self.acks[:16]});self.acks=self.acks[16:]
        for c in list(self.channels.values()):
            if c.ready and time.monotonic()>=self.backpressured_until and time.monotonic()-getattr(c,'pinged',0)>20:c.send('ping',digest(c.prologue),{'nonce':secrets.token_hex(16),'device_name':self.device_name});c.pinged=time.monotonic()
            if c.ready and any(r.get('endpoint_id')==c.peer['endpoint_id'] and r.get('noise_public_key')==c.peer['noise_public_key'] for r in directory) and time.monotonic()-getattr(c,'reported',0)>30:
                self.control('channel',{'peer_id':c.peer['endpoint_id'],'peer_role':c.peer['role'],'peer_noise_public_key':c.peer['noise_public_key'],'channel_id':c.id,'handshake_hash':c.handshake_hash,'state':'ready' if time.monotonic()-c.seen<=75 else 'closed','paired_by_qr':True});c.reported=time.monotonic()
                if getattr(self,'direct',None):
                    active=self.direct.active.get(c.peer['endpoint_id']);ready=self.direct.ready(c.peer['endpoint_id'])
                    self.control('path',{'peer_id':c.peer['endpoint_id'],'channel_id':c.id,'epoch_id':active.epoch if ready else '0'*64,'transport':'direct-ssh' if ready else 'relay','state':'ready'})
    def run(self):
        import http.client
        from node_client import HTTPFailure
        while not self.stop.is_set():
            try:
                self.tick()
                if time.monotonic()>=max(self.backpressured_until,getattr(self,'error_until',0)):self.error=''
                delay=.3
            except (OSError,TimeoutError,http.client.HTTPException):
                self.connection_error('relay_transport','Pairing connection interrupted. Check that both devices are connected to Wallaby Wallet. Pending connection messages are retained.');delay=3
            except HTTPFailure as error:
                # Rate limiting applies to discovery/receive/control as well as
                # send. Retain the same handshake and ciphertext while paused.
                if error.safe_reason=='relay_busy':
                    self.backpressured_until=time.monotonic()+5
                    self.connection_error('relay_busy','Pairing service is busy. Connection setup is paused briefly and will resume automatically.');delay=5
                else:
                    self.registered=False
                    for ident in list(self.channels):self.drop(ident)
                    self.connection_error('relay_http','Pairing service rejected the connection. Check Wallaby Wallet access and matching device versions. Saved peer trust is retained.');delay=3
            except Exception:
                self.registered=False
                for ident in list(self.channels):self.drop(ident)
                self.connection_error('relay_protocol','Pairing service unavailable or incompatible. Check both device connections and the Wallet Server version. Saved peer trust is retained.');delay=3
            self.stop.wait(delay)
    def close(self):
        self.stop.set()
        if getattr(self,'direct',None):self.direct.close()
        for ident in list(self.channels):self.drop(ident)
