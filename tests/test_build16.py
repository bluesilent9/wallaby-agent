"""Regression checks for restrictive umasks, shipped assets and viewer lifecycle."""
import importlib.util,os,stat,sys,tempfile,unittest,http.client,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('secure_start_helper',ROOT/'packaging/secure_start.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

class RuntimeParents(unittest.TestCase):
 def root_identity(self,fd):
  result=self.actual_fstat(fd)
  return SimpleNamespace(st_uid=0,st_mode=result.st_mode)
 def setUp(self):self.actual_fstat=os.fstat
 def test_restrictive_umask_and_existing_parents_are_repaired_without_opening_private_ram(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp)/'base';home=base/'1000';old=os.umask(0o077)
   try:
    with patch.object(helper.os,'fstat',side_effect=self.root_identity):helper.runtime_parent(base);helper.runtime_parent(home)
   finally:os.umask(old)
   ram=home/'ram';ram.mkdir(mode=0o700)
   self.assertEqual(stat.S_IMODE(base.stat().st_mode),0o755);self.assertEqual(stat.S_IMODE(home.stat().st_mode),0o755);self.assertEqual(stat.S_IMODE(ram.stat().st_mode),0o700)
   base.chmod(0o700);home.chmod(0o700)
   with patch.object(helper.os,'fstat',side_effect=self.root_identity):helper.runtime_parent(base);helper.runtime_parent(home)
   self.assertEqual(stat.S_IMODE(home.stat().st_mode),0o755);self.assertEqual(stat.S_IMODE(ram.stat().st_mode),0o700)
 def test_symlinks_nonroot_owners_and_writable_parents_are_never_chmodded(self):
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'target';target.mkdir(mode=0o700);link=Path(tmp)/'link';link.symlink_to(target)
   with self.assertRaises(OSError):helper.runtime_parent(link)
   self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
   for info in [SimpleNamespace(st_uid=1000,st_mode=0o40700),SimpleNamespace(st_uid=0,st_mode=0o40777)]:
    with patch.object(helper.os,'fstat',return_value=info),patch.object(helper.os,'fchmod') as chmod,self.assertRaises(SystemExit):helper.runtime_parent(target)
    chmod.assert_not_called()

class AssetsAndViewer(unittest.TestCase):
 def test_all_referenced_javascript_is_actually_served(self):
  import re
  from test_build13 import TunnelOnlyAPI
  fixture=TunnelOnlyAPI();fixture.setUp()
  try:
   for name in re.findall(r'<script src="/([^"]+)"', (ROOT/'web/index.html').read_text()):
    with self.subTest(asset=name):
     conn=http.client.HTTPConnection('127.0.0.1',fixture.server.server_port)
     conn.request('GET','/'+name,headers={'Host':'127.0.0.1:'+str(fixture.server.server_port)})
     response=conn.getresponse();data=response.read();conn.close()
     self.assertEqual(response.status,200);self.assertEqual(data,(ROOT/'web'/name).read_bytes())
  finally:fixture.tearDown()
 def test_closing_view_terminates_only_tracked_live_viewers(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);live=Mock();live.poll.return_value=None;dead=Mock();dead.poll.return_value=0
  worker.viewers=[live,dead];worker.node=Mock();worker.ops=Mock()
  result=worker.close_views();live.terminate.assert_called_once();live.wait.assert_called_once_with(timeout=5);dead.terminate.assert_not_called();worker.node.assert_not_called();worker.ops.assert_not_called();self.assertEqual(worker.viewers,[]);self.assertIn('remain active',result['message'])
 def test_public_liveness_does_not_wait_for_a_wallet_operation(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);worker.lock=threading.RLock();worker.node_status={'color':'green'};viewer=Mock();viewer.poll.return_value=None;worker.viewers=[viewer];worker.configure=Mock(side_effect=AssertionError('Must not touch Core/config'))
  held=threading.Event();release=threading.Event()
  def operation():
   with worker.lock:held.set();release.wait(3)
  thread=threading.Thread(target=operation);thread.start();held.wait(2)
  try:
   with patch('secure_worker.enforce') as enforce:result=worker.dispatch('service_status',[],{})
   enforce.assert_called_once();worker.configure.assert_not_called();self.assertTrue(result['busy']);self.assertTrue(result['viewer_open']);self.assertTrue(result['connected']);self.assertNotIn('wallets',result)
  finally:release.set();thread.join(2)
 def test_slow_viewer_is_killed_and_reaped_before_unlocking(self):
  import subprocess
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);live=Mock();live.poll.return_value=None;live.wait.side_effect=[subprocess.TimeoutExpired('viewer',5),0];worker.viewers=[live]
  worker.close_views();live.kill.assert_called_once();self.assertEqual(live.wait.call_count,2);self.assertEqual(worker.viewers,[])
