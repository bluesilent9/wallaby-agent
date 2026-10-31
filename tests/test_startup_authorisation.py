"""One deliberate setup prompt; never re-authorise failed protection checks."""
import os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from configuration import Config
from secure_bridge import start,ensure_running,wait_ready,WorkspaceFailure
class AuthorisationFlow(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.config=Config(self.temp.name);key=self.config.root/'preview_identity';key.write_text('TEST-IDENTITY-NOT-A-REAL-KEY')
  self.patches=[patch('capabilities.require_node'),patch('configuration.Config',return_value=self.config)]
  for p in self.patches:p.start();self.addCleanup(p.stop)
 def test_ready_workspace_needs_no_system_start_or_setup_prompt(self):
  with patch('secure_bridge.call',return_value={'protected':{'running':True},'worker_version':'2.0.0~dev18','worker_protocol':1}),patch('secure_bridge.subprocess.run') as execute:
   self.assertTrue(start()['protected']['running']);execute.assert_not_called()
 def test_explicit_refusal_never_invokes_privileged_helper(self):
  for code in ['worker_rejected','worker_protocol']:
   original=WorkspaceFailure(code,'Protection check refused.')
   with self.subTest(code=code),patch('secure_bridge.call',side_effect=original),patch('secure_bridge.subprocess.run') as execute,self.assertRaises(WorkspaceFailure) as caught:start()
   self.assertIs(caught.exception,original);execute.assert_not_called()
 def test_prepared_ram_and_failed_worker_do_not_trigger_another_password(self):
  original=WorkspaceFailure('start_failed','Local worker failed.')
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent.')),patch('secure_bridge.ram_prepared',return_value=True),patch('secure_bridge.ensure_running',side_effect=original),patch('secure_bridge.subprocess.run') as execute,self.assertRaises(WorkspaceFailure) as caught:start()
  self.assertIs(caught.exception,original);execute.assert_not_called()
 def test_first_setup_invokes_exactly_one_fixed_helper(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent.')),patch('secure_bridge.ram_prepared',return_value=False),patch('secure_bridge.subprocess.run',return_value=Mock(returncode=0)) as execute,patch('secure_bridge.wait_ready',return_value={'ready':True,'worker_version':'2.0.0~dev18','worker_protocol':1}):
   self.assertEqual(start(),{'ready':True,'worker_version':'2.0.0~dev18','worker_protocol':1})
  execute.assert_called_once_with(['/usr/bin/pkexec','/usr/lib/wallaby-agent/secure-start',str(os.getuid())],capture_output=True,timeout=180)
 def test_cancelled_setup_does_not_retry_prompt_or_worker(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent.')),patch('secure_bridge.ram_prepared',return_value=False),patch('secure_bridge.subprocess.run',return_value=Mock(returncode=126)) as execute,patch('secure_bridge.wait_ready') as ready,self.assertRaises(WorkspaceFailure) as caught:start()
  self.assertEqual(caught.exception.code,'setup_failed');self.assertEqual(execute.call_count,1);ready.assert_not_called()
 def test_routine_start_explicitly_forbids_interactive_authentication(self):
  with patch('secure_bridge.subprocess.run',return_value=Mock(returncode=0)) as execute,patch('secure_bridge.wait_ready',return_value={'ready':True,'worker_version':'2.0.0~dev18','worker_protocol':1}):ensure_running()
  self.assertEqual(execute.call_args.args[0][:3],['/usr/bin/systemctl','--no-ask-password','start'])
 def test_readiness_has_a_single_deadline_and_bounded_socket_timeout(self):
  original=WorkspaceFailure('worker_unreachable','Absent.')
  with patch('secure_bridge.time.monotonic',side_effect=[100,100,116]),patch('secure_bridge.call',side_effect=original) as rpc,patch('secure_bridge.time.sleep') as sleep,self.assertRaises(WorkspaceFailure) as caught:wait_ready()
  self.assertIs(caught.exception,original);rpc.assert_called_once_with('service_status',timeout=8);sleep.assert_not_called()
