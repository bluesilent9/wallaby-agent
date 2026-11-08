"""Application-owned SSH service: key-only, one subsystem, fresh inner Noise.

All epoch credentials are objects in the non-swapping worker; no OS account,
authorized_keys, known_hosts file, temporary password or persistent key file.
"""
import base64,io,json,queue,secrets,socket,struct,threading,time
import paramiko
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from noise.connection import NoiseConnection,Keypair
from peer_protocol import CIPHER,canonical,digest,binary
from setup_messages import sign,verify
SUBSYSTEM='wallaby-peer-v1'
NAMESPACE='wallaby-wallet-direct-handshake-v1'

def key():
    raw=Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.OpenSSH,serialization.NoEncryption())
    return paramiko.Ed25519Key.from_private_key(io.StringIO(raw.decode()))
def public(k):return k.get_name()+' '+k.get_base64()
def read_exact(channel,n):
    result=bytearray()
    while len(result)<n:
        part=channel.recv(n-len(result))
        if not part:raise EOFError('Direct peer disconnected.')
        result.extend(part)
    return bytes(result)
def receive(channel):
    n=struct.unpack('>I',read_exact(channel,4))[0]
    if not 0<n<=65536:raise ValueError('Direct frame exceeded its bound.')
    return read_exact(channel,n)
def send(channel,raw):
    if not 0<len(raw)<=65536:raise ValueError('Direct frame exceeded its bound.')
    channel.sendall(struct.pack('>I',len(raw))+raw)

class Restricted(paramiko.ServerInterface):
    def __init__(self,login,client,deadline):self.login=login;self.client=client;self.deadline=deadline;self.channel=False;self.subsystem=threading.Event()
    def get_allowed_auths(self,username):return 'publickey'
    def check_auth_publickey(self,username,k):return paramiko.AUTH_SUCCESSFUL if time.monotonic()<self.deadline and username==self.login and public(k)==self.client else paramiko.AUTH_FAILED
    def check_channel_request(self,kind,chanid):
        if kind!='session' or self.channel or time.monotonic()>=self.deadline:return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        self.channel=True;return paramiko.OPEN_SUCCEEDED
    def check_channel_subsystem_request(self,channel,name):
        if name!=SUBSYSTEM or self.subsystem.is_set():return False
        self.subsystem.set();return True
    # Paramiko's other defaults reject password/none, shell, exec, PTY,
    # forwarding, agent forwarding, X11 and arbitrary subsystem requests.

def retire_transport(t):
    t.close()
    t.server_key_dict.clear()
    if t.auth_handler and hasattr(t.auth_handler,'private_key'):t.auth_handler.private_key=None

def transport(sock):
    sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    t=paramiko.Transport(sock,default_window_size=262144,default_max_packet_size=32768)
    options=t.get_security_options();options.key_types=('ssh-ed25519',);options.kex=('curve25519-sha256@libssh.org',);options.ciphers=('aes256-gcm@openssh.com','aes128-gcm@openssh.com');t.banner_timeout=6;t.auth_timeout=6;t.channel_timeout=6
    return t

class Session:
    def __init__(self,manager,state,offer,t,channel,client):
        self.manager=manager;self.state=state;self.offer=offer;self.hash=digest(offer);self.transport=t;self.channel=channel;self.client=client;self.lock=threading.Lock();self.dead=False;self.selected=False;self.remote_selected=False;self.remote_barrier=None;self.remote_active=False;self.acked=set();self.tx_pending={};self.last_rx=time.monotonic();self.created=time.monotonic();self.binding=None
    def handshake(self):
        owner=self.manager.peers;c=self.state.channel
        proof={'protocol':'wallaby-wallet-direct','version':1,'offer_hash':self.hash,'epoch_id':self.state.epoch,'endpoints':self.offer['endpoints'],'host_public_key':self.offer['body']['host_public_key'],'client_public_key':self.offer['body']['client_public_key'],'ssh_session_id':self.transport.session_id.hex()}
        n=NoiseConnection.from_name(CIPHER.encode());n.set_as_initiator() if self.client else n.set_as_responder();n.set_keypair_from_private_bytes(Keypair.STATIC,binary(owner.private));n.set_psks(psk=binary(c.psk));n.set_prologue(canonical(proof))
        if self.client:n.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC,binary(c.peer['noise_public_key']))
        n.start_handshake();payload=canonical(sign(owner.store,proof,NAMESPACE))
        if self.client:send(self.channel,bytes(n.write_message(payload)));remote=n.read_message(receive(self.channel))
        else:
            remote=n.read_message(receive(self.channel))
            if n.noise_protocol.handshake_state.rs.public_bytes!=binary(c.peer['noise_public_key']):raise ValueError('Direct Noise identity changed.')
        if verify(owner.store,owner.decode(remote),c.peer['identity_key'],NAMESPACE)!=proof:raise ValueError('Direct peer application binding changed.')
        if not self.client:send(self.channel,bytes(n.write_message(payload)))
        self.noise=n;self.binding=digest({**proof,'noise_handshake_hash':n.get_handshake_hash().hex()})
        ready={'type':'peer.direct.ready','offer_hash':self.hash,'ssh_session_binding':self.binding}
        self.write(ready)
        if self.read()!=ready:raise ValueError('Direct peer did not confirm the same SSH and Noise session.')
        self.channel.settimeout(8)
    def write(self,value):
        with self.lock:
            if self.dead or time.monotonic()>=self.state.deadline:raise EOFError('Direct credentials expired.')
            send(self.channel,bytes(self.noise.encrypt(canonical(value))))
    def read(self):return self.manager.peers.decode(self.noise.decrypt(receive(self.channel)))
    def run(self):
        try:
            self.handshake();self.manager.established(self)
            while not self.dead and time.monotonic()<self.state.deadline:
                value=self.read()
                self.last_rx=time.monotonic();self.state.channel.seen=self.last_rx;kind=value.get('type')
                if kind=='frame' and set(value)=={'type','frame'}:
                    frame=value['frame']
                    if self.manager.active.get(self.state.channel.peer['endpoint_id']) is not self.state or self.state.selected!=self.hash or not self.remote_active:raise ValueError('Application data arrived before bilateral direct cutover.')
                    if frame.get('from')!=self.state.channel.peer['endpoint_id'] or frame.get('to')!=self.manager.peers.identity['endpoint_id'] or frame.get('channel_id')!=self.state.channel.id:raise ValueError('Direct frame identity changed.')
                    self.manager.peers.accept(frame,[self.state.channel.peer],direct=True);self.write({'type':'receipt','id':frame['id']})
                elif kind=='receipt' and set(value)=={'type','id'}:
                    with self.manager.peers.lock:
                        if value['id'] not in self.tx_pending:raise ValueError('Unexpected direct receipt.')
                        self.manager.peers.outgoing.pop(value['id'],None);self.manager.peers.bulk_frames.discard(value['id']);self.tx_pending.pop(value['id'],None)
                elif kind=='barrier' and set(value)=={'type','tx','rx'} and all(type(value[k]) is int and 0<=value[k]<=2**53 for k in ('tx','rx')):self.remote_barrier=(value['tx'],value['rx'])
                elif kind=='active' and set(value)=={'type','offer_hash'} and value['offer_hash']==self.hash:self.remote_active=True
                elif kind=='selected' and set(value)=={'type','offer_hash'} and value['offer_hash']==self.hash:self.remote_selected=True
                else:raise ValueError('Invalid direct application packet.')
        except Exception as error:self.failure=type(error).__name__
        finally:self.close()
    def close(self):
        if self.dead:return
        self.dead=True
        try:self.channel.close()
        except (OSError,EOFError):pass
        finally:retire_transport(self.transport);self.noise=None;self.offer=None

class Listener:
    def __init__(self,manager,state,host,client,login):
        self.manager=manager;self.state=state;self.host=host;self.client=client;self.login=login;self.dead=False;self.busy=False;self.sockets=[]
        self.sock=socket.socket(socket.AF_INET6);self.sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0);self.sock.bind(('::',0));self.sock.listen(2);self.sock.settimeout(.5);self.port=self.sock.getsockname()[1]
    def run(self):
        while not self.dead and time.monotonic()<self.state.deadline:
            try:sock,_=self.sock.accept()
            except socket.timeout:continue
            except OSError:break
            if self.busy or not self.manager.slots.acquire(False):sock.close();continue
            self.busy=True;threading.Thread(target=self.accept,args=(sock,),daemon=True,name='restricted-peer-ssh').start()
    def accept(self,sock):
        t=None
        try:
            sock.settimeout(8);t=transport(sock);self.sockets.append(t);t.add_server_key(self.host);server=Restricted(self.login,self.client,self.state.deadline);t.start_server(server=server);channel=t.accept(8)
            if channel is None or not server.subsystem.wait(8):raise ValueError('Only the Wallaby subsystem is allowed.')
            channel.settimeout(8);session=Session(self.manager,self.state,self.state.offer,t,channel,False);session.run()
        except Exception:
            if t:t.close()
            sock.close()
        finally:
            if t in self.sockets:self.sockets.remove(t)
            self.busy=False;self.manager.slots.release()
    def close(self):
        self.dead=True;self.sock.close()
        for t in list(self.sockets):retire_transport(t)
        self.host=None;self.client=None;self.login=None

def connect(manager,state,offer):
    for candidate in offer['body']['candidates']:
        if state.closed or time.monotonic()>=state.deadline:return
        t=None;sock=None
        try:
            ip=candidate['ip'];sock=socket.socket(socket.AF_INET6 if ':' in ip else socket.AF_INET);sock.settimeout(3);sock.connect((ip,candidate['port']));t=transport(sock);t.start_client(timeout=6)
            if public(t.get_remote_server_key())!=offer['body']['host_public_key']:raise ValueError('Direct SSH host pin changed.')
            t.auth_publickey(offer['body']['login_id'],state.client_key)
            if not t.is_authenticated():raise ValueError('Direct public key authentication failed.')
            channel=t.open_session(timeout=6);channel.settimeout(8);channel.invoke_subsystem(SUBSYSTEM);session=Session(manager,state,offer,t,channel,True);session.run();return
        except Exception:
            if t:t.close()
            if sock:sock.close()
