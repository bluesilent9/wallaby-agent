"""Local protected startup/IPC failures must never masquerade as Dashboard data errors."""
import json,os,socket,struct,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from diagnostics import ConnectionFailure,describe
from protected_node import ProtectedNode
from secure_bridge import WorkspaceFailure,call,ensure_running,receive

class LocalWorkspace(unittest.TestCase):
 def node(self):return ProtectedNode({},1234,threading.Event(),lambda *_:None)
 def test_failed_local_service_start_stays_workspace_failure(self):
  with patch('secure_bridge.subprocess.run',return_value=Mock(returncode=1,stderr=b'PRIVATE-SYSTEM-OUTPUT')),self.assertRaises(ConnectionFailure) as caught:self.node().run()
  failure=describe('dashboard',caught.exception)
  self.assertEqual((failure.stage,failure.code),('workspace','start_failed'));self.assertIn('Services',str(failure));self.assertNotIn('PRIVATE',str(failure))
 def test_local_start_timeout_has_its_own_stage(self):
  with patch('secure_bridge.subprocess.run',side_effect=subprocess.TimeoutExpired('systemctl',20)),self.assertRaises(ConnectionFailure) as caught:self.node().run()
  self.assertEqual((caught.exception.stage,caught.exception.code),('workspace','start_timeout'))
 def test_unreachable_worker_during_node_start_is_not_dashboard_protocol(self):
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=WorkspaceFailure('worker_unreachable','Use Start protected workspace on Services.')),self.assertRaises(ConnectionFailure) as caught:self.node().run()
  self.assertEqual((caught.exception.stage,caught.exception.code),('workspace','worker_unreachable'))
 def test_status_disconnect_stops_only_the_started_generation(self):
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=[{'session':'fixture'},WorkspaceFailure('worker_closed','Protected worker stopped.'),{'ok':True}]) as rpc,self.assertRaises(ConnectionFailure) as caught:self.node().run()
  self.assertEqual(caught.exception.stage,'workspace');self.assertEqual(rpc.call_args.args,('node.stop','fixture'))
 def test_explicit_protection_refusal_is_not_hidden_by_readiness_retry(self):
  original=WorkspaceFailure('worker_rejected','Persistent filesystem write restrictions could not be verified.')
  with patch('secure_bridge.subprocess.run',return_value=Mock(returncode=0)),patch('secure_bridge.call',side_effect=original) as rpc,patch('secure_bridge.time.sleep') as sleep,self.assertRaises(WorkspaceFailure) as caught:ensure_running()
  self.assertIs(caught.exception,original);rpc.assert_called_once_with('service_status');sleep.assert_not_called()
 def test_bad_node_session_and_status_are_local_protocol_errors(self):
  for replies in [[None],[{'session':'fixture'},None,{'ok':True}]]:
   with self.subTest(replies=replies),patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=replies),self.assertRaises(ConnectionFailure) as caught:self.node().run()
   self.assertEqual((caught.exception.stage,caught.exception.code),('workspace','worker_protocol'))
 def test_unclassified_local_value_error_does_not_echo_unbounded_data(self):
  with patch('secure_bridge.ensure_running',side_effect=ValueError('PRIVATE-RESPONSE')),self.assertRaises(ConnectionFailure) as caught:self.node().run()
  self.assertEqual(caught.exception.stage,'workspace');self.assertNotIn('PRIVATE',str(caught.exception))
 def test_real_local_socket_error_is_preserved_without_contacting_dashboard(self):
  with tempfile.TemporaryDirectory() as tmp:
   listener=socket.socket(socket.AF_UNIX);listener.bind(str(Path(tmp)/'worker.sock'));listener.listen(1);errors=[]
   def serve():
    try:
     peer,_=listener.accept()
     with peer:
      length=int.from_bytes(receive(peer,4),'big');request=json.loads(receive(peer,length));self.assertEqual(request['method'],'service_status')
      raw=json.dumps({'error':'An active sleep/hibernation inhibitor for this protected process could not be verified.'}).encode();peer.sendall(struct.pack('!I',len(raw))+raw)
    except Exception as e:errors.append(e)
   thread=threading.Thread(target=serve);thread.start()
   try:
    with patch('secure_bridge.root',return_value=Path(tmp)),self.assertRaises(WorkspaceFailure) as caught:call('service_status')
    self.assertEqual(caught.exception.code,'worker_rejected');self.assertIn('inhibitor',str(caught.exception))
   finally:listener.close();thread.join(2)
   self.assertFalse(thread.is_alive());self.assertFalse(errors)
 def test_actual_missing_socket_remains_compatible_with_existing_valueerror_callers(self):
  with tempfile.TemporaryDirectory() as tmp,patch('secure_bridge.root',return_value=Path(tmp)),self.assertRaises(ValueError) as caught:call('service_status')
  self.assertIsInstance(caught.exception,WorkspaceFailure);self.assertEqual(caught.exception.code,'worker_unreachable');self.assertIn('Services',str(caught.exception))

class NodeEnablePreparation(unittest.TestCase):
 def setUp(self):
  from test_build13 import TunnelOnlyAPI
  self.fixture=TunnelOnlyAPI();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
  from configuration import Config
  config=Config();v=config.values;v['hostname']='server.example.com';config.save(v)
  self.fixture.server.preview=False
 def test_node_enable_prepares_workspace_before_persisting_enabled_flag(self):
  from configuration import Config
  observations=[]
  def start():observations.append(Config().values['enabled']['node']);return {'protected':{'running':True}}
  with patch('app.require_node'),patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=False),patch('secure_bridge.start',side_effect=start),patch('runtime.ctl'):
   status,body=self.fixture.call('/api/toggle',{'service':'node','enabled':True})
  self.assertEqual(status,200,body);self.assertEqual(observations,[False]);self.assertTrue(Config().values['enabled']['node'])
 def test_preparation_failure_is_visible_and_does_not_enable_or_start_node(self):
  from configuration import Config
  for error in [WorkspaceFailure('start_failed','Protected workspace needs initial setup.'),subprocess.TimeoutExpired('pkexec',180)]:
   with self.subTest(error=type(error).__name__),patch('app.require_node'),patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=False),patch('secure_bridge.start',side_effect=error),patch('runtime.ctl') as service:
    status,body=self.fixture.call('/api/toggle',{'service':'node','enabled':True})
   self.assertEqual(status,400);self.assertIn('workspace',body['error']);self.assertFalse(Config().values['enabled']['node']);service.assert_not_called()
 def test_tunnel_enable_and_node_disable_do_not_prepare_bitcoin_workspace(self):
  with patch('protected_memory.required',return_value=True),patch('secure_bridge.start') as prepare,patch('runtime.ctl'):
   for service in ['ddns','dashboard']:
    self.assertEqual(self.fixture.call('/api/toggle',{'service':service,'enabled':True})[0],200)
   self.assertEqual(self.fixture.call('/api/toggle',{'service':'node','enabled':False})[0],200);prepare.assert_not_called()
