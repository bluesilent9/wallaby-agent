"""Node auto-open, window-close disconnect, guarded cleanup and public polling."""
import contextlib,copy,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from configuration import Config
from node_lifecycle import Lifecycle,control_lock
from secure_bridge import WorkspaceFailure

class DeferredThread:
 def __init__(self,**kwargs):self.target=kwargs['target'];self.active=False
 def start(self):self.active=True
 def is_alive(self):return self.active

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.temp.name,'XDG_RUNTIME_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
  c=Config();v=copy.deepcopy(c.values);v['hostname']='example.test';v['enabled']={k:True for k in v['enabled']};c.save(v)
  self.state={'protected':{'running':True},'window_required':True,'viewer_open':False,'busy':False};self.life=Lifecycle()
  self.patches=[patch('protected_memory.required',return_value=True),patch('secure_bridge.call',side_effect=lambda *a,**kw:{'ok':True} if a[0]=='ui.prepare_close' else copy.deepcopy(self.state)),patch('runtime.apply_config',side_effect=lambda c,v:c.save(v)),patch('node_lifecycle.threading.Thread',DeferredThread)]
  self.mocks=[p.start() for p in self.patches]
  for p in self.patches:self.addCleanup(p.stop)
 def test_closing_window_disables_only_node_and_schedules_cleanup_without_browser_polling(self):
  self.life.poll();cfg=Config().values
  self.assertFalse(cfg['enabled']['node']);self.assertTrue(cfg['enabled']['ddns']);self.assertTrue(cfg['enabled']['dashboard']);self.assertTrue(self.life.thread.active)
  from node_lifecycle import closing
  self.assertTrue(closing());self.mocks[1].reset_mock();self.life.poll();self.mocks[1].assert_not_called()
  with patch('secure_bridge.stop',return_value={}) as stop:self.life.clean()
  stop.assert_called_once();self.assertFalse(closing())
 def test_connected_window_or_not_yet_opened_window_does_not_disable_node(self):
  for field in [('viewer_open',True),('window_required',False)]:
   original=copy.deepcopy(self.state);self.state[field[0]]=field[1];self.life.poll();self.assertTrue(Config().values['enabled']['node']);self.assertIsNone(self.life.thread);self.state=original
 def test_unknown_status_does_not_mean_window_closed(self):
  self.mocks[1].side_effect=WorkspaceFailure('worker_unreachable','Unavailable')
  self.life.poll();self.assertTrue(Config().values['enabled']['node']);self.assertIsNone(self.life.thread)
 def test_busy_forced_window_loss_disconnects_but_never_discards_ram(self):
  self.state['busy']=True;self.life.poll();self.assertFalse(Config().values['enabled']['node']);self.assertIsNone(self.life.thread)
  from runtime import read_status
  self.assertIn('retained',read_status('node')['message'])
 def test_explicit_node_off_also_cleans_workspace_and_window(self):
  c=Config();v=copy.deepcopy(c.values);v['enabled']['node']=False;c.save(v);self.state['window_required']=False;self.state['viewer_open']=True
  self.life.poll();self.assertTrue(self.life.thread.active)
 def test_failed_cleanup_retains_protection_and_backs_off(self):
  self.life.poll()
  with patch('secure_bridge.stop',side_effect=ValueError('PRIVATE-FIXTURE-NOT-FOR-LOGS')):self.life.clean()
  self.assertGreater(self.life.retry_after,time.monotonic());from runtime import read_status
  self.assertNotIn('PRIVATE',read_status('node')['message']);self.assertIn('did not confirm',read_status('node')['message'])
 def test_stale_cleanup_marker_is_cleared_only_after_systemd_proves_service_stopped(self):
  from runtime import runtime_dir
  flag=runtime_dir()/'workspace-closing';self.mocks[1].side_effect=WorkspaceFailure('worker_unreachable','Unavailable')
  for active in ['active','deactivating','inactive','failed']:
   flag.write_text('closing')
   with patch('subprocess.run',return_value=Mock(returncode=0,stdout=active)) as command:self.life.poll()
   self.assertEqual(flag.exists(),active not in ('inactive','failed'));self.assertIn('--no-ask-password',command.call_args.args[0])
 def test_control_lock_skips_poll_while_enable_is_preparing_workspace(self):
  with control_lock():self.life.poll()
  self.mocks[1].assert_not_called();self.assertTrue(Config().values['enabled']['node'])

class NodeAndWindow(unittest.TestCase):
 def test_first_green_opens_one_protected_window_not_one_per_status_poll(self):
  from protected_node import ProtectedNode
  class Stop:
   count=0
   def is_set(self):return self.count>=3
   def wait(self,_):self.count+=1
  stop=Stop();calls=[]
  def worker(method,*args):
   calls.append((method,*args))
   if method=='node.start':return {'session':'fixture'}
   if method=='node.status':return {'color':'amber' if stop.count==0 else 'green','message':'Ready'}
   return {'ok':True}
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=worker):ProtectedNode({},1,stop,lambda *_:None).run()
  self.assertEqual(calls.count(('ui.open','authorise')),1);self.assertEqual(calls[-1],('node.stop','fixture'))
 def test_node_status_and_stop_do_not_wait_for_a_signing_dialogue(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);worker.node_generation='fixture';worker.node_status={'color':'green','message':'Ready'};worker.node_stop=threading.Event();worker.lock=Mock();worker.configure=Mock(side_effect=AssertionError('No wallet operation is permitted'))
  with patch('secure_worker.enforce'):
   self.assertEqual(worker.dispatch('node.status',['fixture'],{})['color'],'green');worker.dispatch('node.stop',['fixture'],{})
  self.assertTrue(worker.node_stop.is_set());worker.configure.assert_not_called();worker.lock.assert_not_called()
 def test_busy_window_refuses_close_without_terminating_viewer(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);worker.busy=Mock(return_value=True);worker.archives=None;viewer=Mock();worker.viewers=[viewer]
  with self.assertRaisesRegex(ValueError,'Finish active'):worker.close_views()
  viewer.terminate.assert_not_called()
 def test_queued_dashboard_delivery_prevents_discarding_workspace(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);worker.busy=Mock(return_value=False);worker.archives=None;worker.store=Mock();worker.store.read.return_value={'outbox':{'delivery':{'kind':'partial_sign_result','payload':{'status':'signed','psbt':'public fixture'}}}};viewer=Mock();worker.viewers=[viewer]
  with self.assertRaisesRegex(ValueError,'queued Dashboard deliveries'):worker.close_views()
  viewer.terminate.assert_not_called()
 def test_disabled_sync_and_denied_notices_are_not_unfinished_work(self):
  from secure_worker import delivery_pending
  notices=[{'kind':'wallet_sync_preferences','payload':{}},{'kind':'partial_sign_result','payload':{'status':'denied'}},{'kind':'wallet_setup_ack','payload':{'message':{'status':'denied'}}}]
  self.assertFalse(delivery_pending({'outbox':{str(i):v for i,v in enumerate(notices)}}))
  self.assertTrue(delivery_pending({'outbox':{'x':{'kind':'partial_sign_result','payload':{'status':'signed'}}}}))
 def test_close_gate_prevents_later_secret_operations_and_expired_requests_do_not_arm_it(self):
  from secure_worker import Workspace
  worker=Workspace.__new__(Workspace);worker.lock=threading.RLock();worker.closing=False;worker.busy=Mock(return_value=False);worker.archives=None;worker.store=Mock();worker.store.read.return_value={'outbox':{}};worker.configure=Mock()
  with patch('secure_worker.enforce'):
   with self.assertRaisesRegex(ValueError,'expired'):worker.dispatch('ui.prepare_close',[time.monotonic()-1],{})
   self.assertFalse(worker.closing)
   self.assertTrue(worker.dispatch('ui.prepare_close',[time.monotonic()+4],{})['ok']);self.assertTrue(worker.closing)
   with self.assertRaisesRegex(ValueError,'closing'):worker.dispatch('wallet.sign',[],{})
 def test_native_close_guard_requires_explicit_not_busy_status(self):
  from protected_viewer import close_allowed
  for value in [True,False,None]:
   with patch('secure_bridge.call',return_value={'ok':value}):self.assertEqual(close_allowed(),value is True)
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('unreachable','Unavailable')):self.assertFalse(close_allowed())

class CleanupVerification(unittest.TestCase):
 def test_successful_service_stop_requires_empty_verified_ram(self):
  from secure_bridge import stop
  with tempfile.TemporaryDirectory() as tmp,patch('configuration.Config',return_value=SimpleNamespace(values={'enabled':{'node':False}})),patch('secure_bridge.call',return_value={'busy':False}),patch('secure_bridge.subprocess.run',return_value=Mock(returncode=0)),patch('secure_bridge.root',return_value=Path(tmp)),patch('protected_memory.noswap_path',return_value=True):
   self.assertIn('cleared',stop()['message'])
   (Path(tmp)/'remaining-fixture').write_text('fixture')
   with self.assertRaisesRegex(ValueError,'empty protected RAM'):stop()

class NodeAPI(unittest.TestCase):
 def test_enabling_is_blocked_during_cleanup_without_prompting(self):
  from test_build13 import TunnelOnlyAPI
  fixture=TunnelOnlyAPI();fixture.setUp()
  try:
   c=Config();v=copy.deepcopy(c.values);v['hostname']='example.test';c.save(v)
   from runtime import runtime_dir
   (runtime_dir()/'workspace-closing').write_text('closing')
   with patch('secure_bridge.start') as start,patch('app.require_node'):
    code,result=fixture.call('/api/toggle',{'service':'node','enabled':True})
   self.assertEqual(code,400);self.assertIn('still closing',result['error']);start.assert_not_called();self.assertFalse(Config().values['enabled']['node'])
  finally:fixture.tearDown()
