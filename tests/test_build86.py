"""Packaged isolated helper launches and protected-session fault containment."""
import json,os,socket,subprocess,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

class PackagedHelper(unittest.TestCase):
 def test_isolated_clone_service_stays_alive_and_refuses_unprotected_caller(self):
  source=Path(os.environ.get('WALLABY_LAUNCH_AGENT_SOURCE',str(ROOT/'src')))
  with tempfile.TemporaryDirectory() as folder:
   folder=Path(folder);endpoint=folder/'clone.sock';marker=folder/'untrusted-import'
   (folder/'chain_clone_files.py').write_text('raise RuntimeError("UNTRUSTED_IMPORT")')
   # Same -I/-B interpreter isolation as ExecStart. Redirect only the test
   # socket; retain the real handler, peer checks and full module import graph.
   program='''import runpy,sys
from pathlib import Path
module=runpy.run_path(sys.argv[1],run_name='isolated_entrypoint_check')
module['main'].__globals__['socket_path']=lambda:Path(sys.argv[2])
module['main']()
'''
   process=subprocess.Popen(['/usr/bin/python3','-I','-B','-c',program,str(source/'chain_clone_service.py'),str(endpoint)],cwd=folder,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   try:
    deadline=time.monotonic()+10
    while not endpoint.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
    if not endpoint.exists():
     out,err=process.communicate(timeout=2);self.fail('Packaged helper failed before opening its socket: '+err.decode()[-1500:])
    with socket.socket(socket.AF_UNIX) as client:
     client.settimeout(3)
     while True:
      try:client.connect(str(endpoint));break
      except ConnectionRefusedError:
       if process.poll() is not None or time.monotonic()>deadline:raise
       time.sleep(.02)
     self.assertEqual(client.recv(1),b'', 'Unprotected caller must be refused before any request or Core access.')
    time.sleep(8);self.assertIsNone(process.poll(),'Clone helper must stay alive beyond the old service restart cycle.')
   finally:
    if process.poll() is None:process.terminate()
    process.communicate(timeout=5)
 def test_all_packaged_python_services_import_under_isolated_interpreter(self):
  names=['secure_supervisor.py','secure_worker.py','chain_clone_service.py','wallet_deletion.py','wallet_rename.py','denial_storage.py','peer_storage.py']
  for name in names:
   with self.subTest(service=name):
    result=subprocess.run(['/usr/bin/python3','-I','-B','-c','import runpy,sys;runpy.run_path(sys.argv[1],run_name="isolated_entrypoint_check")',str(ROOT/'src'/name)],capture_output=True,text=True,timeout=10,cwd='/tmp')
    self.assertEqual(result.returncode,0,result.stderr[-2000:])
 def test_clone_failure_is_optional_to_node_but_still_ordered_before_it(self):
  unit=(ROOT/'build/package/usr/lib/systemd/system/wallaby-agent-secure@.service').read_text()
  fields=dict(line.split('=',1) for line in unit.splitlines() if '=' in line)
  self.assertNotIn('wallaby-agent-chain@%i.service',fields['Requires'].split())
  self.assertIn('wallaby-agent-chain@%i.service',fields['Wants'].split())
  self.assertIn('wallaby-agent-chain@%i.service',fields['After'].split())
  self.assertIn('wallaby-agent-denials-v2@%i.service',fields['Requires'].split())
  helper=(ROOT/'build/package/usr/lib/systemd/system/wallaby-agent-chain@.service').read_text()
  self.assertIn('PartOf=wallaby-agent-secure@%i.service',helper)
  self.assertIn('ProtectHome=read-only',helper)

class HelperDiagnostics(unittest.TestCase):
 def test_journal_reports_safe_failure_categories_without_raw_values(self):
  from node_diagnostics import helper_failures
  unit='wallaby-agent-chain@'+str(os.getuid())+'.service'
  messages=["ModuleNotFoundError: No module named 'chain_clone_files'",'wallaby-agent-chain: Main process exited, code=exited, status=1/FAILURE',"wallaby-agent-chain: Failed with result 'exit-code'.",'ValueError: password=DO_NOT_EXPORT',"ModuleNotFoundError: No module named 'DO_NOT_EXPORT'",'SECRET_PRIVATE_WALLET_DATA']
  rows=[{'_SYSTEMD_UNIT':unit,'MESSAGE':m,'__REALTIME_TIMESTAMP':'1794533400000000'} for m in messages]
  rows+=[{'_SYSTEMD_UNIT':'unrelated.service','MESSAGE':messages[0]}]
  with patch('node_diagnostics.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(r) for r in rows))):value=helper_failures()
  self.assertEqual(len(value),3);self.assertEqual(value[0]['module'],'chain_clone_files');self.assertEqual(value[1]['status'],1);self.assertEqual(value[2]['result'],'exit-code');self.assertNotIn('DO_NOT_EXPORT',json.dumps(value));self.assertNotIn('PRIVATE',json.dumps(value))
 def test_failed_helper_state_included_even_when_protected_worker_is_gone(self):
  from node_diagnostics import snapshot
  def state(user,helper=None):return {'available':True,'ActiveState':'failed' if helper=='chain' else 'inactive','ExecMainStatus':1 if helper=='chain' else 0}
  with patch('node_diagnostics.service',side_effect=state),patch('node_diagnostics.helper_failures',return_value=[{'kind':'chain','exception':'ModuleNotFoundError','module':'chain_clone_files'}]),patch('activity_log.event') as log:
   snapshot('log_export')
  events=[(c.args[0],json.loads(c.args[1])) for c in log.call_args_list]
  self.assertTrue(any(kind=='node.helper' and row.get('kind')=='chain' and row['ExecMainStatus']==1 for kind,row in events))
  self.assertTrue(any(kind=='node.helper_failure' and row.get('module')=='chain_clone_files' for kind,row in events))
 def test_journal_unavailable_and_invalid_helpers_are_bounded(self):
  from node_diagnostics import helper_failures,service
  with patch('node_diagnostics.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',1.5)):
   self.assertEqual(helper_failures(),[{'available':False}])
  with self.assertRaises(ValueError):service(False,'arbitrary/path')
