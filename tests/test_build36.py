"""No raw Core output or arbitrary exceptions escape protected diagnostics."""
import io,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from core_startup import StartupOutput
from diagnostics import action_detail,action_code,LocalActionFailure
from wallet_setup import MemoryCore

class StartupDiagnostics(unittest.TestCase):
 def capture(self,data):
  output=StartupOutput(io.BytesIO(data));output.thread.join(2);return output
 def test_output_is_bounded_and_raw_data_never_enters_failure(self):
  output=self.capture(b'x'*100000+b'\nPermission denied SECRET-DO-NOT-EXPORT\n');self.assertLessEqual(sum(map(len,output.parts)),32768)
  error=output.failure(1);self.assertEqual(action_code(error),'core_startup_permissions');self.assertIn('denied access',action_detail(error));self.assertNotIn('SECRET',str(error));self.assertEqual(output.text(),'')
 def test_loader_memory_port_and_unknown_failures_are_actionable(self):
  for message,code in [('error while loading shared libraries: libx','core_runtime_libraries'),('std::bad_alloc','core_startup_memory'),('Unable to bind','core_startup_rpc_bind'),('unrecognized option','core_startup_options'),('arbitrary PRIVATE-OUTPUT','core_startup_exit')]:
   error=self.capture(message.encode()).failure(127);self.assertEqual(error.code,code);self.assertNotIn('PRIVATE-OUTPUT',str(error))
 def test_success_discards_output_while_continuing_to_drain(self):
  output=self.capture(b'startup data');output.clear();self.assertEqual(output.text(),'');self.assertFalse(output.recording)
 def test_fixed_setup_errors_and_safe_rpc_refusals_are_logged_but_arbitrary_text_is_not(self):
  for message in ['Verify each distinct producing Agent in this exact wallet setup.','Passphrases did not match.','Local secret entry cancelled. No operation was authorised.']:
   self.assertEqual(action_detail(ValueError(message)),message)
  text='Bitcoin Core rejected createwallet (code -4). Check wallet readiness, encryption and node synchronisation.'
  self.assertEqual(action_code(ValueError(text)),'core_rpc_refused');self.assertEqual(action_detail(ValueError(text)),text)
  for message in ['secret=xprvFAKE','Unexpected SECRET-MUST-NOT-EXPORT',text+' SECRET-MUST-NOT-EXPORT']:
   self.assertNotIn('SECRET',action_detail(ValueError(message)));self.assertNotIn('xprv',action_detail(ValueError(message)))
 def test_unusable_executable_has_a_specific_public_reason(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(LocalActionFailure) as e:MemoryCore(Path(d)/'empty','main','/nonexistent-wallaby-bitcoind')
   self.assertEqual(e.exception.code,'core_executable_missing')
 def test_process_launch_refusal_never_claims_keys_exist(self):
  with tempfile.TemporaryDirectory() as d,patch('wallet_setup.subprocess.Popen',side_effect=PermissionError(13,'PRIVATE-FILE-NAME')):
   with self.assertRaises(LocalActionFailure) as e:MemoryCore(Path(d)/'empty','main','/usr/bin/python3')
   self.assertEqual(e.exception.code,'core_execute_failed');self.assertNotIn('PRIVATE',str(e.exception));self.assertIn('errno=13',str(e.exception))

class ThreeAgentVault(unittest.TestCase):
 def test_three_of_five_start_with_disc_producer_and_complete_all_public_policy_reviews(self):
  import os,time
  from approval_store import Store,digest
  from wallet_setup import WalletSetup
  from setup_policy import policy
  from regtest_support import Regtest
  from wallet_ops import rpc
  with tempfile.TemporaryDirectory() as d:
   nodes=[];agents=[]
   try:
    for i in range(3):
     node=Regtest();nodes.append(node);agents.append(WalletSetup(node.core,Store(Path(d)/str(i)),binary=os.environ['WALLABY_TEST_BITCOIND']))
    identities=[a.own_identity() for a in agents]
    roles=[{'id':'role-'+str(i),'name':['Archive alpha','Archive beta','Node gamma','Node delta','Node epsilon'][i],'agent_key':identities[producer]['public_key'],'storage':'disc' if producer==0 else 'node'} for i,producer in enumerate([0,0,1,1,2])]
    p={'kind':'wallet_setup','version':1,'session_id':'b'*64,'chain':'regtest','name':'Three Agent vault fixture','threshold':3,'height':100,'expires_at':int(time.time())+3600,'cosigners':roles};key=digest(p)
    for agent in agents:
     agent.store.receive(p);agent.review(key)
     with patch('wallet_setup.secret_dialog',return_value='fixture-encryption-passphrase') as prompt:
      agent.approve_proposal(key,{v['fingerprint']:v['fingerprint'] for v in identities})
     local_roles=[role for role in roles if role['agent_key']==agent.own_identity()['public_key']]
     self.assertEqual(len(prompt.call_args_list),len(local_roles))
     for call,role in zip(prompt.call_args_list,local_roles):
      self.assertIn('signing role: '+role['name'],call.args[0]);self.assertIn('Wallet: '+p['name'],call.args[0]);self.assertIn('Signer ID: '+role['id'],call.args[0]);self.assertNotIn('key_',call.args[0]);self.assertTrue(call.kwargs['confirm'])
    contributions=[e for a in agents for e in a.sessions[key]['contributions']];self.assertEqual(len(contributions),5)
    descriptors=policy(p,[e['message'] for e in contributions]);final={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descriptors[0],'change_descriptor':descriptors[1]}
    for agent in agents:
     agent.store.receive(final);review=agent.review(digest(final));self.assertEqual((review['setup']['threshold'],review['setup']['total'],review['setup']['height']),(3,5,100));
     with patch('wallet_setup.secret_dialog',return_value='fixture-encryption-passphrase'):agent.approve_policy(digest(final))
    self.assertEqual(len(agents[0].disc_sessions),2)
    self.assertEqual(agents[0].sessions[key]['phase'],'awaiting_disc')
    self.assertEqual([a.sessions[key]['phase'] for a in agents[1:]],['complete','complete'])
    self.assertEqual([len(rpc(n.core,'listwallets')) for n in nodes],[1,2,1])
    # Add an unrelated Wallet Server archive while this producer waits for discs.
    from archive_operations import Operations
    from types import SimpleNamespace
    rpc(nodes[0].core,'createwallet',{'wallet_name':'Independent backup','passphrase':'fixture-backup-passphrase'})
    raw=rpc(nodes[0].core,'listdescriptors',[False],'Independent backup')
    request={'kind':'archive_wallet','version':1,'nonce':'d'*64,'wallet':'Independent backup','public_wallet':raw,'related_policies':[],'require_local_authorisation':True};request['request_id']=digest(request);archive_id=digest(request)
    archives=Operations(nodes[0].core,agents[0].store,agents[0],SimpleNamespace(loaded={},catalogs={}),lambda:None)
    agents[0].store.receive(request);archives.review(archive_id);archives.approve(archive_id)
    burner=agents[0].burner;roles=list(agents[0].disc_sessions)
    self.assertEqual([row.get('signer_name') for row in burner.state()['queue'][:2]],['Archive alpha','Archive beta'])
    self.assertEqual(len(burner.pending),2) # Second role plus unrelated wallet.
    burner.select(roles)
    with self.assertRaisesRegex(ValueError,'one signing role'):burner.combine()
    burner.select([roles[0],archive_id]);burner.combine()
    self.assertEqual(len(burner.job['_members']),2);self.assertEqual([row[0] for row in burner.pending],[roles[1]])
    self.assertEqual(rpc(nodes[0].core,'getwalletinfo',[],'Independent backup')['unlocked_until'],0)

   finally:
    for agent in agents:
     for session in agent.sessions.values():
      if session.get('core'):session['core'].close()
    for node in reversed(nodes):node.close()

class SetupFailureEvents(unittest.TestCase):
 def test_pre_passphrase_startup_failure_records_phase_and_safe_reason(self):
  import time
  from approval_store import Store,digest
  from wallet_setup import WalletSetup
  with tempfile.TemporaryDirectory() as d:
   core=Mock();core.call.side_effect=lambda ident,method,*a,**k:{'result':{'wallets':[]} if method=='listwalletdir' else {'chain':'regtest'}};setup=WalletSetup(core,Store(Path(d)/'state'),binary='/missing-wallaby-bitcoind');own=setup.own_identity()
   p={'kind':'wallet_setup','version':1,'session_id':'c'*64,'chain':'regtest','name':'Failure fixture','threshold':1,'height':100,'expires_at':int(time.time())+3600,'cosigners':[{'id':'one','name':'Disc signer','agent_key':own['public_key'],'storage':'disc'}]};setup.store.receive(p)
   with patch('wallet_setup.secret_dialog') as secret,patch('activity_log.event') as event:
    with self.assertRaises(LocalActionFailure):setup.approve_proposal(digest(p),{own['fingerprint']:own['fingerprint']})
   secret.assert_not_called();source,message=event.call_args.args;self.assertEqual(source,'setup.failure');self.assertIn('stage=offline_core_start',message);self.assertIn('core_executable_missing',message);self.assertIn('executable',message);self.assertNotIn(p['name'],message)
 def test_actual_worker_handler_records_known_error_explanation(self):
  import json,os,socket
  from secure_worker import Handler
  left,right=socket.socketpair()
  try:
   payload=json.dumps({'method':'setup.participate','args':[],'environment':{}}).encode();left.sendall(len(payload).to_bytes(4,'big')+payload)
   server=Mock();server.workspace.dispatch.side_effect=ValueError('Verify each distinct producing Agent in this exact wallet setup.')
   with patch('activity_log.event') as event:Handler(right,None,server)
   source,message=event.call_args.args;self.assertEqual(source,'setup.participate');self.assertIn('Verify each distinct producing Agent',message)
   left.recv(4096)
  finally:left.close();right.close()

class DisplayEnvironment(unittest.TestCase):
 def worker(self):
  from secure_worker import Workspace
  from types import SimpleNamespace
  w=Workspace.__new__(Workspace);w.environment={};w.ops=SimpleNamespace(core=SimpleNamespace(config={'cookie':'fixture-cookie-path','rpc_port':8332}));w.setup=SimpleNamespace(environment={});w.cancellations=SimpleNamespace(environment={});return w
 def configure(self,w,env):
  with patch('secure_worker.Config') as config:
   config.return_value.values={'cookie':'fixture-cookie-path','rpc_port':8332};w.configure(env)
 def test_background_poll_does_not_remove_display_before_native_passphrase_prompt(self):
  from wallet_setup import secret_dialog
  from types import SimpleNamespace
  w=self.worker();gui={'DISPLAY':':77','WAYLAND_DISPLAY':'wayland-fixture','XAUTHORITY':'/run/user/1000/fixture-authority','XDG_RUNTIME_DIR':'/run/user/1000','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'}
  self.configure(w,gui)
  # These are the service's own inherited variables, carried by protected HTTP status/action calls.
  self.configure(w,{'XDG_RUNTIME_DIR':'/run/user/1000','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus','LANG':'C.UTF-8'})
  def prompt(*args,**kwargs):
   available=kwargs['env'].get('DISPLAY')==':77' and kwargs['env'].get('XAUTHORITY')==gui['XAUTHORITY']
   return SimpleNamespace(returncode=0 if available else 1,stdout=b'"fixture-passphrase"')
  with patch('wallet_setup.shutil.which',return_value='/usr/bin/kdialog'),patch('wallet_setup.subprocess.run',side_effect=prompt) as run:
   self.assertEqual(secret_dialog('Fixture confirmation',w.setup.environment,confirm=True),'fixture-passphrase');self.assertEqual(run.call_count,1)
  self.assertEqual(w.cancellations.environment['DISPLAY'],':77')
 def test_empty_background_values_do_not_clear_display_and_valid_replacement_is_used(self):
  w=self.worker();self.configure(w,{'DISPLAY':':77'});self.configure(w,{'DISPLAY':''});self.assertEqual(w.environment['DISPLAY'],':77');self.configure(w,{'DISPLAY':':88'});self.assertEqual(w.environment['DISPLAY'],':88')
 def test_invalid_or_nonallowlisted_environment_never_changes_saved_display(self):
  w=self.worker();self.configure(w,{'DISPLAY':':77'})
  for env in [{'DISPLAY':':88','LD_PRELOAD':'untrusted'},{'DISPLAY':'bad\nvalue'}]:
   with self.assertRaisesRegex(ValueError,'Invalid local display'):self.configure(w,env)
   self.assertEqual(w.environment,{'DISPLAY':':77'})
