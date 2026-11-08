from pathlib import Path
import copy,time,threading,unittest,json,io,base64
from unittest.mock import patch
from test_build66 import Pairing,RelayCore
from direct_peers import Direct
from direct_protocol import validate,make,address
from direct_ssh import Restricted,key,public
import paramiko

class DirectPeers(Pairing):
 def network(self,mobile=False,actual_server=False):
  if mobile:
   self.b=self.peer('phone','mobile');invite=self.a.create_invitation('mobile',self.route);self.b.import_invitation(invite);self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a);self.a.approve(self.b.identity['endpoint_id']);self.move(self.a,self.b)
  else:self.pair()
  self.failures=[];self.relay=[];self.done=threading.Event()
  for p in (self.a,self.b):Direct(p,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(p.close)
  if actual_server:
   import subprocess,sys,os
   source=Path(os.environ['WALLABY_SERVER_SOURCE'])
   proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server66_fixture.py')),str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.addCleanup(proc.kill)
   def dispatch(peer,body):
    proc.stdin.write(json.dumps({'identity':peer.identity,'body':body})+'\n');proc.stdin.flush();reply=json.loads(proc.stdout.readline())
    if 'error' in reply:raise ValueError(reply['error'])
    if body['action']=='send':self.relay.append(copy.deepcopy(body['frame']))
    return reply['result']
   for peer in (self.a,self.b):
    peer.rpc=lambda body,peer=peer:dispatch(peer,body)
    peer.control('register',{'noise_public_key':peer.identity['noise_public_key'],'cipher_suite':__import__('peer_protocol').CIPHER});peer.registered=True
  def pump():
   while not self.done.wait(.25 if actual_server else .002):
    try:
     if actual_server:
      self.a.tick();self.b.tick();continue
     for a,b in ((self.a,self.b),(self.b,self.a)):
      with a.lock:rows=[v for v in a.outgoing.values() if v['id'] not in a.bulk_frames and not a.direct.holds(v)]
      for v in rows:
       b.accept(v,[a.identity]);self.relay.append(copy.deepcopy(v))
       with a.lock:a.outgoing.pop(v['id'],None)
    except Exception as e:self.failures.append(repr(e));break
  threading.Thread(target=pump,daemon=True).start();self.addCleanup(self.done.set)
  self.until(lambda:all(p.direct.ready(q.identity['endpoint_id']) for p,q in ((self.a,self.b),(self.b,self.a))))
 def until(self,condition,seconds=35):
  deadline=time.monotonic()+seconds
  while not condition() and time.monotonic()<deadline:
   if self.failures:self.fail(str(self.failures))
   time.sleep(.02)
  self.assertTrue(condition(),str([(p.direct.messages,{i:(e.id,e.remote_id,list(e.sessions),e.selected,e.closed,e.settled,[(s.dead,getattr(s,'failure',None),s.remote_selected,s.remote_active) for s in e.sessions.values()]) for i,e in p.direct.states.items()}) for p in (self.a,self.b)]))
 def test_simultaneous_real_ssh_cutover_and_bulk_bypasses_relay(self):
  self.network();received=[]
  self.b.listeners.append(lambda c,r:received.append(r) or True)
  c=self.a.channel(self.b.identity['identity_key']);payload={'data':'bulk fixture'*1000}
  fid=c.send('stream_fixture','a'*64,payload);self.until(lambda:bool(received));self.until(lambda:fid not in self.a.outgoing)
  self.assertEqual(received[-1]['body'],payload);self.assertNotIn(fid,[f['id'] for f in self.relay]);self.assertEqual(self.a.direct.active[self.b.identity['endpoint_id']].epoch,self.b.direct.active[self.a.identity['endpoint_id']].epoch)
 def test_actual_server3_negotiation_and_bulk_direct_only(self):
  self.network(actual_server=True);received=[];self.b.listeners.append(lambda c,r:received.append(r) or True)
  c=self.a.channel(self.b.identity['identity_key']);fid=c.send('stream_fixture','b'*64,{'wallet_bytes':'fixture'*2000});self.until(lambda:bool(received));self.until(lambda:fid not in self.a.outgoing)
  self.assertNotIn(fid,[f['id'] for f in self.relay]);self.assertNotIn('wallet_bytes',json.dumps(self.relay));self.assertNotIn('client_public_key',json.dumps(self.relay))
 def test_eight_megabyte_stream_is_bounded_and_never_relayed(self):
  import base64,hashlib
  from types import SimpleNamespace
  from relay_stream import Stream
  self.network();a=self.a.channel(self.b.identity['identity_key']);stream=Stream(SimpleNamespace(peers=self.a),a,'e'*64,'f'*64);count=[0];maximum=[0]
  def receiver(c,r):
   b=r['body'];raw=base64.b64decode(b['data']);self.assertEqual(b['offset'],count[0]);self.assertEqual(b['sha256'],hashlib.sha256(raw).hexdigest());count[0]+=len(raw);maximum[0]=max(maximum[0],len(stream.acks));c.send('stream_ack',r['operation_hash'],{'stream_id':b['stream_id'],'offset':b['offset']});return True
  self.b.listeners.append(receiver)
  self.a.listeners.append(lambda c,r:stream.acks[r['body']['offset']].set() or True)
  timer=threading.Timer(30,stream.close);timer.daemon=True;timer.start();self.addCleanup(timer.cancel)
  started=time.monotonic();data=b'bounded direct stream fixture 67'*(8*1024*1024//31);stream.write(data)
  self.assertEqual(count[0],len(data));self.assertLessEqual(maximum[0],4);self.assertLess(time.monotonic()-started,30);self.assertFalse(self.failures);self.assertNotIn('stream_data',json.dumps(self.relay))
 def test_mobile_always_client_and_no_agent_stream_authority(self):
  self.network(mobile=True);a=self.a.direct.active[self.b.identity['endpoint_id']];b=self.b.direct.active[self.a.identity['endpoint_id']]
  self.assertFalse(a.sessions[a.selected].client);self.assertTrue(b.sessions[b.selected].client)
  with self.assertRaises(ValueError):self.a.channel(self.b.identity['identity_key'])
 def test_delete_releases_credentials_preserves_pairing_and_blocks_bulk(self):
  self.network();ident=self.b.identity['endpoint_id'];state=self.a.direct.active[ident];saved=self.a.persistence.read();self.a.direct.delete(ident)
  self.assertTrue(state.closed);self.assertIsNone(state.client_key);self.assertIsNone(state.listener.host if state.listener else None);after=self.a.persistence.read();self.assertEqual(saved['private_key'],after['private_key']);self.assertEqual(saved['pairs'][ident]['psk'],after['pairs'][ident]['psk']);self.assertIs(after['pairs'][ident]['direct_enabled'],False);self.assertFalse(self.a.direct.ready(ident))
  with self.assertRaisesRegex(ValueError,'direct peer connection'):self.a.channel(self.b.identity['identity_key']).send('stream_data','a'*64,{'secret':'never relay'})
 def test_expiry_cannot_reuse_ssh_and_renewal_retains_trust(self):
  self.network();ident=self.b.identity['endpoint_id'];old=self.a.direct.active[ident];saved=self.a.persistence.read();old.deadline=time.monotonic()-1
  self.assertFalse(self.a.direct.ready(ident));self.a.direct.tick();self.assertTrue(old.closed);self.assertIsNone(old.client_key);self.assertEqual(saved,self.a.persistence.read())
 def test_live_renewal_changes_epoch_keys_and_releases_old_credentials(self):
  self.network();ident=self.b.identity['endpoint_id'];old=self.a.direct.active[ident];old_id=old.epoch;before=self.a.persistence.read()
  self.a.direct.reconnect(ident)
  self.until(lambda:self.a.direct.ready(ident) and self.a.direct.active[ident].epoch!=old_id and self.b.direct.ready(self.a.identity['endpoint_id']) and self.b.direct.active[self.a.identity['endpoint_id']].epoch!=old_id and old.closed)
  self.assertTrue(old.closed);self.assertIsNone(old.client_key);self.assertEqual(before['private_key'],self.a.persistence.read()['private_key']);self.assertEqual(before['pairs'][ident]['psk'],self.a.persistence.read()['pairs'][ident]['psk'])
 def test_one_reachable_orientation_is_used(self):
  self.pair();self.failures=[];self.relay=[];self.done=threading.Event()
  Direct(self.a,addresses=lambda:['127.0.0.1'],loopback=True).start();Direct(self.b,addresses=lambda:[],loopback=True).start()
  for p in (self.a,self.b):self.addCleanup(p.close)
  def pump():
   while not self.done.wait(.002):
    try:
     for a,b in ((self.a,self.b),(self.b,self.a)):
      with a.lock:rows=[v for v in a.outgoing.values() if not a.direct.holds(v)]
      for v in rows:
       b.accept(v,[a.identity])
       with a.lock:a.outgoing.pop(v['id'],None)
    except Exception as e:self.failures.append(repr(e));break
  threading.Thread(target=pump,daemon=True).start();self.addCleanup(self.done.set)
  self.until(lambda:self.a.direct.ready(self.b.identity['endpoint_id']) and self.b.direct.ready(self.a.identity['endpoint_id']))
  state=self.a.direct.active[self.b.identity['endpoint_id']];self.assertFalse(state.sessions[state.selected].client)
 def test_bulk_received_via_relay_is_refused_even_from_paired_agent(self):
  from types import SimpleNamespace
  self.pair();self.a.direct=SimpleNamespace(require=lambda c:None)
  self.a.channel(self.b.identity['identity_key']).send('stream_data','a'*64,{'data':'must not relay'})
  with self.assertRaisesRegex(ValueError,'forbidden on the Server relay'):self.move(self.a,self.b)
  del self.a.direct
 def test_changed_offer_key_role_address_and_expiry_refused(self):
  self.pair();self.a.direct=Direct(self.a,addresses=lambda:['127.0.0.1'],loopback=True);self.b.direct=Direct(self.b,addresses=lambda:['127.0.0.1'],loopback=True);self.addCleanup(self.a.close);self.addCleanup(self.b.close)
  c=self.a.channel(self.b.identity['identity_key']);s=self.a.direct.begin(c);self.move(self.a,self.b);self.move(self.b,self.a);offer=copy.deepcopy(s.remote_offer)
  for field,value in [('expires_utc',1),('epoch_id','X'*64),('endpoints',[])]:
   bad=copy.deepcopy(offer);bad[field]=value
   with self.assertRaises(ValueError):validate(bad,self.a.identity,self.b.identity,True)
  bad=copy.deepcopy(offer);bad['body']['candidates']=[{'ip':'127.0.0.1','port':22}]
  with self.assertRaises(ValueError):validate(bad,self.a.identity,self.b.identity)
  bad=copy.deepcopy(offer);bad['body']['client_public_key']=public(key())
  with self.assertRaises(ValueError):self.a.direct.handle(c,{'payload_type':'peer.direct','operation_hash':__import__('peer_protocol').digest(c.prologue),'body':bad})

class Restrictions(unittest.TestCase):
 def test_key_only_subsystem_denies_shell_exec_forwarding_and_other_users(self):
  k=key();s=Restricted('w'*20,public(k),time.monotonic()+60)
  self.assertEqual(s.get_allowed_auths('x'),'publickey');self.assertEqual(s.check_auth_publickey('w'*20,k),paramiko.AUTH_SUCCESSFUL)
  self.assertEqual(s.check_auth_publickey('other',k),paramiko.AUTH_FAILED);self.assertEqual(s.check_auth_publickey('w'*20,key()),paramiko.AUTH_FAILED)
  for call in [lambda:s.check_auth_password('w'*20,'password'),lambda:s.check_auth_none('w'*20)]:self.assertEqual(call(),paramiko.AUTH_FAILED)
  self.assertFalse(s.check_channel_shell_request(None));self.assertFalse(s.check_channel_exec_request(None,b'id'));self.assertFalse(s.check_channel_pty_request(None,'x',1,1,1,1,b''));self.assertFalse(s.check_channel_forward_agent_request(None));self.assertFalse(s.check_channel_subsystem_request(None,'sftp'));self.assertFalse(s.check_port_forward_request('127.0.0.1',22))
  self.assertEqual(s.check_channel_direct_tcpip_request(0,('127.0.0.1',1),('127.0.0.1',22)),paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)
 def test_candidates_reject_network_scanner_inputs(self):
  for ip in ['localhost','0.0.0.0','::','127.0.0.1','224.0.0.1','255.255.255.255','fe80::1','192.0.2.1;id']:
   with self.assertRaises(ValueError):address(ip)

class QRImages(Pairing):
 def test_actual_pairing_qr_png_is_decoded_locally(self):
  from peer_qr import decode
  from vendor.qrcodegen import QrCode
  from PIL import Image,ImageDraw
  envelope=self.a.create_invitation('agent',self.route);q=QrCode.encode_text(json.dumps(envelope,separators=(',',':')),QrCode.Ecc.LOW);n=q.get_size();image=Image.new('L',((n+8)*5,)*2,255);d=ImageDraw.Draw(image)
  for y in range(n):
   for x in range(n):
    if q.get_module(x,y):d.rectangle(((x+4)*5,(y+4)*5,(x+5)*5-1,(y+5)*5-1),fill=0)
  output=io.BytesIO();image.save(output,format='PNG');self.assertEqual(decode(base64.b64encode(output.getvalue()).decode())['envelope'],envelope)
  with self.assertRaises(ValueError):decode('A'*2200000)
  with self.assertRaises(ValueError):decode(base64.b64encode(b'not an image').decode())

class DirectCore(RelayCore):
 def setup_peers(self):
  super().setup_peers();self.stopped.set();self.pump.join(timeout=3)
  self.stopped=threading.Event();self.addCleanup(self.stopped.set);self.pump_error=[]
  for p in (self.a,self.b):Direct(p,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(p.close)
  def pump():
   while not self.stopped.wait(.002):
    try:
     for a,b in ((self.a,self.b),(self.b,self.a)):
      with a.lock:rows=[v for v in a.outgoing.values() if v['id'] not in a.bulk_frames and not a.direct.holds(v)]
      for v in rows:
       b.accept(v,[a.identity])
       with a.lock:a.outgoing.pop(v['id'],None)
    except Exception as error:self.pump_error.append(repr(error));break
  self.pump=threading.Thread(target=pump,daemon=True);self.pump.start();deadline=time.monotonic()+35
  while not all(p.direct.ready(q.identity['endpoint_id']) for p,q in ((self.a,self.b),(self.b,self.a))):
   if self.pump_error or time.monotonic()>deadline:self.fail(str(self.pump_error)+' Direct connection timeout')
   time.sleep(.02)
 def test_single_sig_wallet_over_real_direct_ssh(self):self.relay('single')
 def test_original_multisig_role_restored_over_real_direct_ssh(self):self.relay('vault',restoration=True)
 def test_public_vault_history_over_real_direct_ssh(self):self.relay('vault',watch=True,restoration=True)
