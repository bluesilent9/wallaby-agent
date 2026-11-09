"""Scan-to-connect covers real Server routing before any pairing exists."""
import copy,json,os,subprocess,sys,time
from pathlib import Path
from test_build66 import Pairing
from peer_protocol import CIPHER
from direct_peers import Direct

class ScanConnect(Pairing):
 def scan(self,a,b):
  invitation=a.create_invitation('connect',self.route);self.assertEqual(invitation['message']['version'],3);r=b.import_invitation(invitation);self.assertTrue(r['automatic'])
  self.assertTrue(b.status()['connecting']);self.assertFalse(a.persistence.read()['pairs']);self.assertFalse(b.persistence.read()['pairs'])
  for _ in range(4):self.move(b,a);self.move(a,b)
  self.assertTrue(a.channel(b.identity['identity_key'],b.identity['role']).ready);self.assertTrue(b.channel(a.identity['identity_key'],a.identity['role']).ready)
  self.assertFalse(a.pending);self.assertFalse(b.pending);self.assertFalse(b.status()['connecting']);return invitation
 def test_scan_automatically_pairs_both_agents_without_approve(self):
  self.a.device_name='Treasury Australia';self.b.device_name='wallet-laptop';self.scan(self.a,self.b)
  self.assertEqual(self.a.status()['pairs'][0]['name'],'wallet-laptop');self.assertEqual(self.b.status()['pairs'][0]['name'],'Treasury Australia')
 def test_mobile_scanning_and_mobile_issuing_keep_mobile_restrictions(self):
  phone=self.peer('phone','mobile');self.scan(self.a,phone)
  with self.assertRaises(ValueError):self.a.channel(phone.identity['identity_key'],'agent')
  phone.channel(self.a.identity['identity_key']).send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64})
  with self.assertRaisesRegex(ValueError,'Mobile'):self.move(phone,self.a)
  other=self.peer('other');phone2=self.peer('phone2','mobile');self.scan(phone2,other)
  with self.assertRaises(ValueError):phone.import_invitation(phone2.create_invitation('connect',self.route))
 def test_mode_version_signature_and_expiry_tampering_never_grant(self):
  envelope=self.a.create_invitation('connect',self.route)
  for field,value in [('pairing_mode','other'),('version',2),('issuer_name','substituted'),('expires_at',1),('allowed_peer_role','agent')]:
   bad=copy.deepcopy(envelope);bad['message'][field]=value
   with self.assertRaises(ValueError):self.b.import_invitation(bad)
   self.assertFalse(self.b.channels);self.assertFalse(self.b.persistence.read()['pairs'])
 def test_invalid_noise_proof_cannot_consume_or_grant(self):
  envelope=self.a.create_invitation('connect',self.route);self.b.import_invitation(envelope);frame=copy.deepcopy(next(iter(self.b.outgoing.values())));frame['ciphertext']='A'+frame['ciphertext'][1:]
  with self.assertRaises(Exception):self.a.accept(frame,[self.b.identity])
  self.assertFalse(self.a.persistence.read()['pairs']);self.assertFalse(self.a.channels);self.assertTrue(self.a.invitations)
 def test_one_qr_can_only_reserve_one_authenticated_channel(self):
  envelope=self.a.create_invitation('connect',self.route);self.b.import_invitation(envelope);self.move(self.b,self.a)
  third=self.peer('third');third.import_invitation(envelope)
  with self.assertRaisesRegex(ValueError,'already connecting'):self.move(third,self.a)
  for _ in range(3):self.move(self.a,self.b);self.move(self.b,self.a)
  self.assertEqual(set(self.a.persistence.read()['pairs']),{self.b.identity['endpoint_id']})
 def test_legacy_v2_still_requires_issuer_confirmation(self):
  self.b.import_invitation(self.a.create_invitation('auto',self.route));self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a)
  self.assertFalse(self.a.persistence.read()['pairs']);self.assertIn(self.b.identity['endpoint_id'],self.a.pending)
 def server_pair(self,mobile=False):
  source=Path(os.environ['WALLABY_SERVER_SOURCE']);proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server66_fixture.py')),str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.addCleanup(proc.kill)
  if mobile:self.b=self.peer('phone','mobile')
  sent=[]
  def dispatch(peer,body):
   proc.stdin.write(json.dumps({'identity':peer.identity,'body':body})+'\n');proc.stdin.flush();reply=json.loads(proc.stdout.readline())
   if 'error' in reply:raise AssertionError(reply['error'])
   if body['action']=='send':sent.append(copy.deepcopy(body['frame']))
   return reply['result']
  for peer in (self.a,self.b):
   peer.rpc=lambda body,peer=peer:dispatch(peer,body);peer.tick();Direct(peer,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(peer.close)
  self.assertFalse(self.a.persistence.read()['pairs']);self.assertFalse(self.b.persistence.read()['pairs'])
  self.b.import_invitation(self.a.create_invitation('connect',self.route))
  original=self.b.rpc
  def interrupted(body):
   if body['action']=='send':raise OSError('fixture temporary transport loss')
   return original(body)
  self.b.rpc=interrupted
  with self.assertRaises(OSError):self.b.tick()
  self.assertTrue(self.b.outgoing);self.assertFalse(self.a.persistence.read()['pairs']);self.b.rpc=original
  deadline=time.monotonic()+35
  while time.monotonic()<deadline:
   self.a.tick();self.b.tick()
   if self.a.direct.ready(self.b.identity['endpoint_id']) and self.b.direct.ready(self.a.identity['endpoint_id']):break
   time.sleep(.3)
  self.assertTrue(self.a.direct.ready(self.b.identity['endpoint_id']),self.a.status());self.assertTrue(self.b.direct.ready(self.a.identity['endpoint_id']),self.b.status())
  self.assertFalse(self.a.pending);self.assertFalse(self.b.pending)
  received=[];self.b.listeners.append(lambda c,r:received.append(r) or True)
  if not mobile:
   fid=self.a.channel(self.b.identity['identity_key']).send('stream_fixture','a'*64,{'fixture':'direct only'})
   deadline=time.monotonic()+10
   while not received and time.monotonic()<deadline:time.sleep(.05)
   self.assertTrue(received);self.assertNotIn(fid,[f['id'] for f in sent])
  else:
   self.assertTrue(self.b.direct.status(self.a.identity['endpoint_id'])['server'] is False)
   with self.assertRaises(ValueError):self.a.channel(self.b.identity['identity_key'],'agent')
 def test_actual_server6_unpaired_scan_to_real_direct_ssh_and_bulk(self):self.server_pair()
 def test_actual_server6_unpaired_mobile_scan_to_direct_client(self):self.server_pair(True)

class Feedback(Pairing):
 def test_backpressure_during_discovery_retains_in_progress_handshake(self):
  from unittest.mock import patch
  from node_client import HTTPFailure
  self.b.import_invitation(self.a.create_invitation('connect',self.route));before=copy.deepcopy(self.b.outgoing);channels=dict(self.b.channels)
  def stop_wait(delay):self.b.stop.set();return True
  with patch.object(self.b,'tick',side_effect=HTTPFailure(400,'relay_busy')),patch.object(self.b.stop,'wait',side_effect=stop_wait):self.b.run()
  self.assertEqual(before,self.b.outgoing);self.assertEqual(channels,self.b.channels);self.assertIn('resume automatically',self.b.error)
 def test_error_is_not_cleared_immediately_by_next_successful_tick(self):
  from unittest.mock import patch
  self.a.connection_error('peer_message_refused','Fixed safe diagnostic')
  def stop_wait(delay):self.a.stop.set();return True
  with patch.object(self.a,'tick'),patch.object(self.a.stop,'wait',side_effect=stop_wait):self.a.run()
  self.assertEqual(self.a.error,'Fixed safe diagnostic')
 def test_expected_empty_camera_frame_is_not_a_failed_action(self):
  from unittest.mock import patch
  from peer_actions import action
  from types import SimpleNamespace
  with patch('peer_qr.decode',side_effect=ValueError('Choose an image containing exactly one clear pairing QR.')):
   self.assertEqual(action(SimpleNamespace(peers=self.a),'decode-qr',{'image':'fixture'}),{'found':False})
 def test_expired_unfinished_pairing_has_explicit_feedback(self):
  self.b.import_invitation(self.a.create_invitation('connect',self.route));next(iter(self.b.channels.values())).created-=121;self.b.prune_local()
  self.assertFalse(self.b.channels);self.assertIn('two minutes',self.b.error);self.assertFalse(self.b.persistence.read()['pairs'])
