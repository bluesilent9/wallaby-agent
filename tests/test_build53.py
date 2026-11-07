"""Administrator setup must work without elevating the restricted GUI process."""
import importlib.util,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from secure_bridge import start,WorkspaceFailure

class Preparation(unittest.TestCase):
 def setUp(self):
  from test_startup_authorisation import AuthorisationFlow
  self.f=AuthorisationFlow();self.f.setUp();self.addCleanup(self.f.doCleanups)
 def test_unprepared_restricted_ui_uses_authorised_systemd_ipc_not_setuid(self):
  current={'worker_version':'2.0.0~dev62','worker_protocol':1,'protected':{'running':True}}
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent')),patch('secure_bridge.ram_prepared',return_value=False),patch('secure_bridge.subprocess.run',return_value=Mock(returncode=0)) as run,patch('secure_bridge.wait_ready',return_value=current):self.assertEqual(start(),current)
  cmd=run.call_args.args[0];self.assertEqual(cmd,['/usr/bin/systemctl','start','wallaby-agent-prepare@'+str(os.getuid())+'.service']);self.assertNotIn('--no-ask-password',cmd);self.assertNotIn('pkexec',' '.join(cmd))
 def test_failure_names_preparation_unit_without_logging_raw_responses(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent')),patch('secure_bridge.ram_prepared',return_value=False),patch('secure_bridge.subprocess.run',return_value=Mock(returncode=1,stderr=b'PRIVATE SENTINEL')) as run,patch('secure_bridge.wait_ready') as ready,self.assertRaises(WorkspaceFailure) as caught:start()
  self.assertEqual(caught.exception.code,'setup_failed');self.assertIn('wallaby-agent-prepare@',str(caught.exception));self.assertNotIn('PRIVATE SENTINEL',str(caught.exception));self.assertEqual(run.call_count,1);ready.assert_not_called()
 def test_timeout_does_not_repeat_authorisation_or_claim_worker_started(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Absent')),patch('secure_bridge.ram_prepared',return_value=False),patch('secure_bridge.subprocess.run',side_effect=subprocess.TimeoutExpired(['systemctl'],180)) as run,self.assertRaises(WorkspaceFailure) as caught:start()
  self.assertEqual(caught.exception.code,'setup_timeout');self.assertEqual(run.call_count,1)

class RootEntry(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  path=Path(__file__).resolve().parents[1]/'packaging/secure_start.py';spec=importlib.util.spec_from_file_location('root_setup_53',path);cls.helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.helper)
 def test_only_system_root_preparation_unit_can_replace_pkexec_context(self):
  h=self.helper
  with patch.dict(os.environ,{},clear=True):
   for group,expected in [('/system.slice/system-wallaby\\x2dagent\\x2dprepare.slice/wallaby-agent-prepare@1000.service',True),('/user.slice/user-1000.slice/user@1000.service/app.slice/wallaby-agent-prepare@1000.service',False),('/system.slice/wallaby-agent-prepare@1001.service',False),('/system.slice/wallaby-agent-secure@1000.service',False)]:
    with self.subTest(group=group),patch.object(h.Path,'read_text',return_value='0::'+group+'\n'):self.assertEqual(h.authorised_caller(1000),expected)
 def test_terminal_recovery_retains_matching_pkexec_uid_guard(self):
  with patch.dict(os.environ,{'PKEXEC_UID':'1000'},clear=True):self.assertTrue(self.helper.authorised_caller(1000));self.assertFalse(self.helper.authorised_caller(1001))
 def test_non_root_caller_is_rejected_before_any_setup_command(self):
  with patch.object(self.helper.os,'geteuid',return_value=1000),patch.object(self.helper.sys,'argv',['secure-start','1000']),patch.object(self.helper.subprocess,'run') as run,self.assertRaises(SystemExit):self.helper.main()
  run.assert_not_called()
