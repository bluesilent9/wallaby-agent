import copy,json,tempfile,time,unittest
from pathlib import Path
from approval_store import Store
from peer_storage import FileStore
from peer_channels import Peers
from peer_protocol import *
class Pairing(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.a=self.peer('a');self.b=self.peer('b');self.route={'host':'example.test','user':'fixture','port':22,'host_public_key':self.a.identity['identity_key'],'host_fingerprint':fingerprint(self.a.identity['identity_key']),'agent_port':56443,'mobile_port':56444}
 def peer(self,name,role='agent'):
  folder=self.root/(name+'-trust');folder.mkdir(mode=0o700);return Peers(Store(self.root/name),FileStore(folder),role)
 def move(self,src,dst):
  with src.lock:
   rows=[r for r in src.outgoing.values() if r['to']==dst.identity['endpoint_id']]
   for r in rows:src.outgoing.pop(r['id'],None)
  for frame in rows:dst.accept(frame,[src.identity])
  return rows
 def pair(self):
  invitation=self.a.create_invitation('agent',self.route);self.b.import_invitation(invitation);self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a);self.a.approve(self.b.identity['endpoint_id']);self.move(self.a,self.b);self.assertTrue(self.a.channel(self.b.identity['identity_key']).ready);self.assertTrue(self.b.channel(self.a.identity['identity_key']).ready);return invitation
 def test_pair_and_encrypted_policy_agreement(self):
  self.pair();requirements={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted([self.a.identity['identity_key'],self.b.identity['identity_key']])};operation=digest({'operation':'fixture'})
  with self.assertRaisesRegex(ValueError,'Waiting'):self.a.agreement(requirements,operation,'policy',{'address':'fixture'})
  frames=self.move(self.a,self.b);self.assertNotIn('fixture',json.dumps(frames));self.b.agreement(requirements,operation,'policy',{'address':'fixture'});self.move(self.b,self.a);self.a.agreement(requirements,operation,'policy',{'address':'fixture'})
 def test_wrong_role_expired_and_used_qr_refused(self):
  invitation=self.pair()
  with self.assertRaises(ValueError):self.b.import_invitation(invitation)
  wrong=self.a.create_invitation('mobile',self.route)
  with self.assertRaises(ValueError):self.b.import_invitation(wrong)
  expired=copy.deepcopy(wrong);expired['message']['expires_at']=1
  with self.assertRaises(ValueError):self.b.import_invitation(expired)
 def test_changed_ciphertext_and_sequence_refused(self):
  self.pair();self.a.channel(self.b.identity['identity_key']).send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64});frame=next(iter(self.a.outgoing.values()));bad=copy.deepcopy(frame);bad['sequence']+=1
  with self.assertRaises(ValueError):self.b.accept(bad,[])
  self.assertFalse(self.b.channels)
 def test_revocation_survives_restart(self):
  self.pair();self.b.revoke(self.a.identity['endpoint_id']);self.assertFalse(self.b.persistence.read()['pairs']);self.assertTrue(self.b.persistence.read()['used']);again=Peers(self.b.store,self.b.persistence);self.assertFalse(again.channels)
 def test_mobile_cannot_act_as_agent(self):
  mobile=self.peer('mobile','mobile');invite=self.a.create_invitation('mobile',self.route);mobile.import_invitation(invite);self.move(mobile,self.a);self.move(self.a,mobile);self.move(mobile,self.a);self.a.approve(mobile.identity['endpoint_id']);self.move(self.a,mobile)
  with self.assertRaises(ValueError):self.a.channel(mobile.identity['identity_key'],'agent')
  mobile.channel(self.a.identity['identity_key'],'agent').send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64})
  with self.assertRaisesRegex(ValueError,'Mobile'):self.move(mobile,self.a)
if __name__=='__main__':unittest.main()

from test_build65 import OriginalRoles
class RelayCore(OriginalRoles):
 def setup_peers(self):
  self.sender=Store(self.root/'sender');folder=self.root/'sender-trust';folder.mkdir(mode=0o700);self.a=Peers(self.sender,FileStore(folder));folder=self.root/'receiver-trust';folder.mkdir(mode=0o700);self.b=Peers(self.store,FileStore(folder));route={'host':'example.test','user':'fixture','port':22,'host_public_key':self.a.identity['identity_key'],'host_fingerprint':fingerprint(self.a.identity['identity_key']),'agent_port':56443,'mobile_port':56444};invite=self.a.create_invitation('agent',route);self.b.import_invitation(invite)
  def move(a,b):
   rows=list(a.outgoing.values())
   for row in rows:
    b.accept(row,[a.identity]);a.outgoing.pop(row['id'],None)
  move(self.b,self.a);move(self.a,self.b);move(self.b,self.a);self.a.approve(self.b.identity['endpoint_id']);move(self.a,self.b)
  from relay_stream import Bridge
  self.a.wallet_bridge=Bridge(self.a,self.sender);self.b.wallet_bridge=Bridge(self.b,self.store)
  import threading
  self.stopped=threading.Event();self.pump_error=[]
  if getattr(self,'use_actual_server',False):
   import subprocess,sys,os
   source=Path(os.environ.get('WALLABY_SERVER_SOURCE',str(Path(__file__).resolve().parents[3]/'wallaby-wallet-server')))
   proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server66_fixture.py')),str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.addCleanup(proc.kill)
   def dispatch(peer,body):
    proc.stdin.write(json.dumps({'identity':peer.identity,'body':body})+'\n');proc.stdin.flush();reply=json.loads(proc.stdout.readline())
    if 'error' in reply:
     from node_client import HTTPFailure
     if reply['error'] in ('Relay queue is full. Retry later.','Relay rate limit reached. Retry shortly.'):raise HTTPFailure(400,'relay_busy')
     raise ValueError(reply['error'])
    return reply['result']
   for peer in (self.a,self.b):peer.rpc=lambda body,peer=peer:dispatch(peer,body)
   def move(a,b):a.tick();b.tick()
  def pump():
   while not self.stopped.is_set():
    try:move(self.a,self.b);move(self.b,self.a)
    except Exception as e:self.pump_error.append(e);self.a.close();self.b.close();break
    self.stopped.wait(.001)
  self.pump=threading.Thread(target=pump,daemon=True);self.pump.start();self.addCleanup(self.stopped.set)
  def deadline():
   self.pump_error.append('Encrypted fixture deadline');self.a.close();self.b.close()
  timer=threading.Timer(90,deadline);timer.daemon=True;timer.start();self.addCleanup(timer.cancel)
 def relay(self,kind='single',watch=False,restoration=False):
  from peer_wallet import wallet_details
  from wallet_preview import prepare,receive
  from sync_queue import apply_snapshot,choose
  from batch_transfer import BatchTransfer
  from test_build8 import paired
  from wallet_ops import rpc
  from approval_store import digest
  import shutil
  if restoration:
   p,ident=self.fixture(kind);rpc(self.receiver.core,'unloadwallet',['Original']);shutil.rmtree(Path(self.receiver.core.config['cookie']).parent/'wallets'/'Original')
  else:p=paired('Original');p['public_wallet']=self.wallet(self.core,'Original',kind)
  self.setup_peers();p.update(transfer_version=3,node_ipv6=None);p['peer']['ipv6']=None;p['transport']={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'sender_endpoint':self.a.identity['endpoint_id'],'receiver_endpoint':self.b.identity['endpoint_id'],'sender_identity':self.a.identity['identity_key'],'receiver_identity':self.b.identity['identity_key'],'sender_noise_key':self.a.identity['noise_public_key'],'receiver_noise_key':self.b.identity['noise_public_key']}
  sending={**copy.deepcopy(p),'direction':'send'};apply_snapshot(self.sender,1,[sending]);apply_snapshot(self.store,1,[p]);sk=digest(sending);rk=digest(p);choose(self.sender,sk,True,watch);choose(self.store,rk,True,watch);payload=prepare(self.core,self.sender,sk,sending);receive(self.store,payload)
  from sync_offers import apply as offers
  offers(self.sender,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[{'id':'f'*64,'transfer_id':sending['transfer_id'],'direction':'send','peer':{k:sending['peer'][k] for k in ('node_id','hostname')},'public_wallet':sending['public_wallet'],'status':'ready'}]},'fixture-session')
  send=BatchTransfer(self.core,self.sender);receiver=BatchTransfer(self.receiver.core,self.store);self.addCleanup(send.close);self.addCleanup(receiver.close);
  from wallet_pull import Pull
  self.a.wallet_pull=Pull(self.a,send);self.b.wallet_pull=Pull(self.b,receiver)
  receiver.authorise_batch({});receiver.thread.join(20)
  for thread in self.a.wallet_pull.threads:thread.join(10)
  self.assertFalse(self.pump_error,self.pump_error);self.assertIn(sk,self.sender.read()['completed']);self.assertIn(rk,self.store.read()['completed']);name='Wallaby Sync '+p['transfer_id'][:24];self.assertEqual(rpc(self.receiver.core,'getwalletinfo',[],name)['private_keys_enabled'],not watch)
  if restoration:self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'restored')
 def test_single_signature_sync_without_peer_ip_password_or_listener(self):self.relay()
 def test_core_wallet_bytes_cross_actual_companion_server_as_ciphertext(self):self.use_actual_server=True;self.relay()
 def test_multisig_original_role_restoration_through_encrypted_relay(self):self.relay('vault',restoration=True)
 def test_public_vault_snapshot_over_relay_has_no_private_keys(self):self.relay('vault',watch=True,restoration=True)

class CompanionServer(Pairing):
 def test_actual_server_control_relay_mesh_and_restart(self):
  import os,subprocess,sys
  source=Path(os.environ.get('WALLABY_SERVER_SOURCE',str(Path(__file__).resolve().parents[3]/'wallaby-wallet-server')))
  if not source.is_dir():self.skipTest('Set WALLABY_SERVER_SOURCE to companion Wallet Server Build 2 source.')
  process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server66_fixture.py')),str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.addCleanup(process.kill)
  def dispatch(request):
   process.stdin.write(json.dumps(request)+'\n');process.stdin.flush();line=process.stdout.readline()
   if not line:raise AssertionError(process.stderr.read())
   reply=json.loads(line)
   if 'error' in reply:raise ValueError(reply['error'])
   return reply['result']
  for peer in (self.a,self.b):peer.rpc=lambda body,peer=peer:dispatch({'identity':peer.identity,'body':body})
  self.a.tick();self.b.tick();invitation=self.a.create_invitation('agent',self.route);self.b.import_invitation(invitation)
  for _ in range(3):self.b.tick();self.a.tick()
  self.a.approve(self.b.identity['endpoint_id'])
  for _ in range(3):self.a.tick();self.b.tick()
  # Both exact signed reports are required for Server mesh readiness.
  self.assertTrue(dispatch({'audit':True})['mesh']['ready']);self.assertTrue(self.a.channel(self.b.identity['identity_key']).ready)
  dispatch({'reset':True});self.a.registered=False;self.b.registered=False
  for peer in (self.a,self.b):
   for ident in list(peer.channels):peer.drop(ident)
  for _ in range(5):self.a.tick();self.b.tick()
  self.assertTrue(self.a.channel(self.b.identity['identity_key']).ready);self.assertTrue(dispatch({'audit':True})['mesh']['ready'])
  self.assertEqual(len(self.a.persistence.read()['pairs']),1)

class MeshWallets(RelayCore):
 def test_two_real_agents_build_vault_only_after_independent_mesh_agreement(self):
  from wallet_setup import WalletSetup
  from setup_policy import policy
  from approval_store import digest
  from unittest.mock import patch
  import os
  self.setup_peers();agents=[WalletSetup(self.core,self.sender,binary=os.environ['WALLABY_TEST_BITCOIND']),WalletSetup(self.receiver.core,self.store,binary=os.environ['WALLABY_TEST_BITCOIND'])]
  for a in agents:self.addCleanup(lambda a=a:[v['core'].close() for v in a.sessions.values() if v.get('core')])
  keys=[a.own_identity()['public_key'] for a in agents];p={'kind':'wallet_setup','version':2,'session_id':'c'*64,'chain':'regtest','name':'Encrypted Treasury','threshold':2,'height':100,'expires_at':int(time.time())+3600,'cosigners':[{'id':str(i),'name':'Signer '+str(i),'agent_key':k,'storage':'node'} for i,k in enumerate(keys)],'peer_transport':{'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted(keys)}};key=digest(p)
  for a in agents:a.store.receive(p)
  # A server's ready status cannot substitute for a peer's independent review.
  with self.assertRaisesRegex(ValueError,'Waiting'):agents[0].approve_proposal(key,{})
  self.assertFalse(agents[0].sessions)
  for a in agents:a.review(key)
  time.sleep(.1)
  for a in agents:
   with patch('wallet_setup.secret_dialog',return_value='fixture-role-password'):a.approve_proposal(key,{})
  contributions=[e for a in agents for e in a.sessions[key]['contributions']];descs=policy(p,[e['message'] for e in contributions]);final={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};fk=digest(final)
  for a in agents:a.store.receive(final);a.review(fk)
  time.sleep(.1)
  for a in agents:
   with patch('wallet_setup.secret_dialog',return_value='fixture-role-password'):a.approve_policy(fk)
   self.assertIn(fk,a.store.read()['completed'])
  self.assertFalse(self.pump_error,self.pump_error)

class Attacks(Pairing):
 def test_wrong_psk_cannot_create_a_local_grant(self):
  from setup_messages import sign
  invite=self.a.create_invitation('agent',self.route);changed=copy.deepcopy(invite['message']);changed['pairing_secret']=b64(b'wrong-pairing-secret-value-0000000'[:32]);changed=sign(self.a.store,changed,INVITATION);self.b.import_invitation(changed)
  self.move(self.b,self.a)
  with self.assertRaises(Exception):self.move(self.a,self.b)
  self.assertFalse(self.a.persistence.read()['pairs']);self.assertFalse(self.b.persistence.read()['pairs'])
 def test_server_header_substitution_and_replay_under_new_id_fail(self):
  self.pair();self.a.channel(self.b.identity['identity_key']).send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64});value=next(iter(self.a.outgoing.values()));changed=copy.deepcopy(value);changed['id']='f'*64
  with self.assertRaises(ValueError):self.b.accept(changed,[])
 def test_altered_signature_or_directory_key_cannot_grant_trust(self):
  invite=self.a.create_invitation('agent',self.route);bad=copy.deepcopy(invite);bad['message']['allowed_peer_role']='mobile'
  with self.assertRaises(ValueError):self.b.import_invitation(bad)
  self.b.import_invitation(invite);frame=next(iter(self.b.outgoing.values()));false=copy.deepcopy(self.b.identity);false['noise_public_key']=b64(b'x'*32)
  with self.assertRaises(Exception):self.a.accept(frame,[false])
  self.assertFalse(self.a.persistence.read()['pairs'])
 def test_unapproved_device_gets_no_application_access(self):
  invite=self.a.create_invitation('agent',self.route);self.b.import_invitation(invite);self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a)
  with self.assertRaises(ValueError):self.b.channel(self.a.identity['identity_key'])
  self.assertFalse(self.a.persistence.read()['pairs'])
 def test_policy_disagreement_and_offline_peer_block_locally(self):
  self.pair();req={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted([self.a.identity['identity_key'],self.b.identity['identity_key']])};op='a'*64
  with self.assertRaises(ValueError):self.a.agreement(req,op,'refresh',{'height':100})
  self.move(self.a,self.b)
  with self.assertRaisesRegex(ValueError,'disagree'):self.b.agreement(req,op,'refresh',{'height':101})
  self.b.drop(self.a.identity['endpoint_id'])
  with self.assertRaisesRegex(ValueError,'unavailable'):self.b.agreement(req,op,'refresh',{'height':100})
 def test_persistent_peer_service_rejects_unknown_secret_fields_and_symlinks(self):
  saved=self.a.persistence.read();bad=copy.deepcopy(saved);bad['wallet_private_keys']='xprv-fake'
  with self.assertRaises(ValueError):self.a.persistence.commit(saved['revision'],bad)
  file=self.a.persistence.directory/'peer-trust.json';file.unlink();file.symlink_to(self.root/'elsewhere')
  with self.assertRaises(OSError):self.a.persistence.read()
 def test_server_backpressure_retains_exact_ciphertext_and_channel(self):
  from node_client import HTTPFailure
  self.pair();self.a.channel(self.b.identity['identity_key']).send('ping','a'*64,{'fixture':True});value=copy.deepcopy(next(iter(self.a.outgoing.values())));self.a.registered=True
  def rpc(data):
   if data['action']=='directory':return {'endpoints':[self.b.identity]}
   if data['action']=='send':raise HTTPFailure(400,'relay_busy')
   if data['action']=='receive':return {'frames':[]}
   if data['action']=='challenge':return {'endpoint_id':self.a.identity['endpoint_id'],'role':'agent','challenge':'b'*64}
   return {}
  self.a.rpc=rpc;self.a.tick();self.assertEqual(self.a.outgoing[value['id']],value);self.assertTrue(self.a.channel(self.b.identity['identity_key']).ready);self.assertGreater(self.a.backpressured_until,time.monotonic())

class VerificationAndUpgrade(Pairing):
 def test_pairing_and_operation_qr_fit_and_bind_exact_current_request(self):
  from mobile_verification import qr,review,NAMESPACE
  from setup_messages import verify
  invitation=self.a.create_invitation('mobile',self.route);graphic=qr(invitation);self.assertIn('<svg',graphic);self.assertNotIn('script',graphic);self.assertNotIn('pairing_secret',graphic)
  p={'kind':'sign_psbt_partial','wallet':'Fixture','public_transaction':'fixture'};key=digest(p)
  with self.a.store.edit() as saved:saved['pending'][key]={'proposal':p,'state':'pending'}
  envelope=review(self.a.store,key);message=verify(self.a.store,envelope,self.a.identity['identity_key'],NAMESPACE);self.assertEqual(message['request_digest'],key);self.assertFalse(message['approval_authority']);self.assertIn('<svg',qr(envelope))
  with self.a.store.edit() as saved:saved['pending'].pop(key)
  with self.assertRaises(ValueError):review(self.a.store,key)
 def test_courier_cannot_downgrade_new_transfer_but_frozen_work_is_retained(self):
  from peer_compatibility import require_current
  from test_build8 import paired
  p=paired('Fixture')
  with self.assertRaisesRegex(ValueError,'cannot silently'):require_current(self.a.store,p)
  with self.a.store.edit() as saved:saved['pending'][digest(p)]={'proposal':p,'state':'pending'}
  require_current(self.a.store,p)
 def test_mobile_verification_cannot_request_signing_or_wallet_bytes(self):
  from mobile_verification import respond
  from types import SimpleNamespace
  class Forbidden:
   def send(self,*args):raise AssertionError('No wallet authority or bytes may be sent.')
  for kind in ('sign','stream_open','wallet_transfer','approve'):
   with self.assertRaisesRegex(ValueError,'verification reads only'):respond(self.a,Forbidden(),{'payload_type':kind,'operation_hash':'a'*64,'body':{}})
 def test_required_mesh_matches_distinct_actual_producers(self):
  required={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted([self.a.identity['identity_key'],self.b.identity['identity_key']])}
  requirements(required,[self.a.identity['identity_key'],self.a.identity['identity_key'],self.b.identity['identity_key']])
  with self.assertRaises(ValueError):requirements(required,[self.a.identity['identity_key']])

class DeliveryFaults(Pairing):
 def test_ambiguous_send_retains_the_exact_frame_for_retry(self):
  self.pair();self.a.channel(self.b.identity['identity_key']).send('ping','a'*64,{'fixture':True});value=copy.deepcopy(next(iter(self.a.outgoing.values())));self.a.registered=True
  def rpc(data):
   if data['action']=='directory':return {'endpoints':[self.b.identity]}
   if data['action']=='send':raise TimeoutError('invented lost HTTP response')
   return {'frames':[]}
  self.a.rpc=rpc
  with self.assertRaises(TimeoutError):self.a.tick()
  self.assertEqual(self.a.outgoing[value['id']],value);self.assertTrue(self.a.channel(self.b.identity['identity_key']).ready)
 def test_duplicate_identical_frame_is_idempotent_but_new_id_replay_is_refused(self):
  self.pair();self.a.channel(self.b.identity['identity_key']).send('ping','a'*64,{'fixture':True});values=self.move(self.a,self.b);self.b.accept(values[0],[])
  replay=copy.deepcopy(values[0]);replay['id']='f'*64
  with self.assertRaises(ValueError):self.b.accept(replay,[])
 def test_rejected_or_expired_pending_grant_cannot_later_be_approved(self):
  invite=self.a.create_invitation('agent',self.route);self.b.import_invitation(invite);self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a);ident=self.b.identity['endpoint_id'];self.a.drop(ident)
  with self.assertRaises(ValueError):self.a.approve(ident)
  self.assertFalse(self.a.persistence.read()['pairs'])

class RefreshMesh(Pairing):
 def test_refresh_needs_exact_policy_agreement_before_import_or_unlock(self):
  from test_build58 import BatchIsolation
  from policy_refresh import transition
  from peer_mesh import observe
  from unittest.mock import patch
  f=BatchIsolation();f.setUp();self.addCleanup(f.doCleanups);self.pair();p=copy.deepcopy(f.p);p.update(version=2,peer_transport={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'required_agent_keys':sorted([self.a.identity['identity_key'],self.b.identity['identity_key']])});key=digest(p);self.a.store.receive(p);f.ops.store=self.a.store;f.ops.reviews[key]=(p,f.facts,time.monotonic(),f.targets)
  with patch('policy_refresh_group.targets',return_value=f.targets),patch('policy_refresh_group.rpc',side_effect=f.call):
   with self.assertRaisesRegex(ValueError,'Waiting'):f.ops.approve(key)
  self.assertFalse(f.imports);self.assertEqual(self.a.store.read()['pending'][key]['state'],'pending');self.move(self.a,self.b)
  other=copy.deepcopy(p);other['wallet']='Another original local name';other['request_id']='7'*64
  self.assertTrue(observe(self.b.store,other,'refresh',strict=True)['ready']);self.move(self.b,self.a);self.assertTrue(observe(self.a.store,p,'refresh',strict=True)['ready'])

class Concurrency(Pairing):
 def test_simultaneous_application_sends_and_receives_share_one_lock_order(self):
  import threading
  self.pair();errors=[];stop=threading.Event()
  def produce(peer,other):
   try:
    for i in range(24):peer.channel(other.identity['identity_key']).send('policy_agreement',digest({'i':i}),{'scope':'policy','digest':'b'*64});time.sleep(.001)
   except Exception as error:errors.append(error)
  threads=[threading.Thread(target=produce,args=pair,daemon=True) for pair in ((self.a,self.b),(self.b,self.a))]
  for thread in threads:thread.start()
  deadline=time.monotonic()+5
  while any(thread.is_alive() for thread in threads) and time.monotonic()<deadline:
   self.move(self.a,self.b);self.move(self.b,self.a)
  for thread in threads:thread.join(.5)
  self.assertTrue(all(not t.is_alive() for t in threads));self.assertFalse(errors);self.move(self.a,self.b);self.move(self.b,self.a);self.assertEqual(len(self.a.agreements),24);self.assertEqual(len(self.b.agreements),24)

class ReceiptRetry(Pairing):
 def test_lost_relay_receipt_ack_deduplicates_ids_without_redecrypting(self):
  self.pair();self.a.channel(self.b.identity['identity_key']).send('ping','a'*64,{'fixture':True});value=next(iter(self.a.outgoing.values()));self.b.registered=True;attempts=[]
  def rpc(data):
   if data['action']=='directory':return {'endpoints':[self.a.identity]}
   if data['action']=='receive':return {'frames':[value]}
   if data['action']=='ack':
    attempts.append(data['ids'][:]);self.assertEqual(len(data['ids']),len(set(data['ids'])))
    if len(attempts)==1:raise TimeoutError('invented lost receipt ACK')
   if data['action']=='challenge':return {'endpoint_id':self.b.identity['endpoint_id'],'role':'agent','challenge':'c'*64}
   return {}
  self.b.rpc=rpc
  with self.assertRaises(TimeoutError):self.b.tick()
  counter=self.b.channel(self.a.identity['identity_key']).rx;self.b.tick();self.assertEqual(self.b.channel(self.a.identity['identity_key']).rx,counter);self.assertEqual(attempts,[[value['id']],[value['id']]])
