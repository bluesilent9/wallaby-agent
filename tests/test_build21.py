"""Native close through the real framed JSON/Decimal boundary, not direct calls."""
import ast,copy,json,os,socket,tempfile,threading,time,types,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock,patch
from secure_worker import Workspace,Server,Handler
from secure_bridge import call,WorkspaceFailure,prepare_stop
import protected_viewer

def workspace():
 w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.busy=Mock(return_value=False);w.archives=None;w.store=Mock();w.store.read.return_value={'outbox':{}};w.closing=False;w.configure=Mock();return w

class NativeWire(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.worker=workspace();self.server=Server(str(self.root/'worker.sock'),Handler);self.server.workspace=self.worker;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.addCleanup(self.shutdown);self.patches=[patch('secure_bridge.root',return_value=self.root),patch('secure_worker.enforce'),patch('activity_log.event')]
  for p in self.patches:p.start();self.addCleanup(p.stop)
 def shutdown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_original_build20_validator_rejects_a_fresh_wire_deadline_as_decimal(self):
  # Frozen admission branch from Build20; actual decoder and socket stay current.
  original=self.worker.dispatch;seen=[]
  def old(method,args,environment):
   if method=='ui.prepare_close':
    seen.append(type(args[0]))
    if len(args)!=1 or type(args[0]) not in (int,float) or not time.monotonic()<args[0]<time.monotonic()+8:raise ValueError('Close request expired; no workspace state was changed.')
   return original(method,args,environment)
  self.worker.dispatch=old;deadline=time.monotonic()+4
  with self.assertRaisesRegex(WorkspaceFailure,'expired'):call('ui.prepare_close',deadline)
  self.assertEqual(seen,[Decimal]);self.assertGreater(deadline,time.monotonic());self.assertFalse(self.worker.closing)
 def test_actual_viewer_call_passes_no_deadline_and_closes_via_real_wire(self):
  original=self.worker.dispatch;seen=[]
  def capture(method,args,env):seen.append((method,args));return original(method,args,env)
  self.worker.dispatch=capture
  self.assertTrue(protected_viewer.close_allowed());self.assertEqual(seen,[('ui.request_close',[])]);self.assertTrue(self.worker.closing)
 def test_native_x_event_source_accepts_after_real_worker_reply(self):
  # Exercise the exact QMainWindow closeEvent body without requiring Qt/display.
  source=ast.parse((Path(__file__).resolve().parents[1]/'src/protected_viewer.py').read_text());cls=next(n for n in ast.walk(source) if isinstance(n,ast.ClassDef) and n.name=='Window');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='closeEvent');module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
  with patch.object(protected_viewer,'QMessageBox',Mock(),create=True):
   exec(compile(module,'native-close-event','exec'),protected_viewer.__dict__);event=Mock();protected_viewer.closeEvent(None,event);event.accept.assert_called_once();event.ignore.assert_not_called();self.assertTrue(self.worker.closing)
 def test_native_x_keeps_window_open_for_active_work_or_queued_delivery(self):
  for busy,outbox in [(True,{}),(False,{'signed':{'kind':'partial_sign_result','payload':{'status':'signed'}}})]:
   self.worker.busy.return_value=busy;self.worker.store.read.return_value={'outbox':outbox};self.worker.closing=False
   self.assertFalse(protected_viewer.close_allowed());self.assertFalse(self.worker.closing);self.assertIn('Finish active',protected_viewer.close_error)
 def test_legacy_fresh_decimal_deadline_still_works_for_an_old_viewer(self):
  self.assertEqual(call('ui.prepare_close',time.monotonic()+4),{'ok':True});self.assertTrue(self.worker.closing)
 def test_invalid_new_arguments_and_stale_legacy_deadlines_refused(self):
  with self.assertRaisesRegex(WorkspaceFailure,'no arguments'):call('ui.request_close',time.monotonic()+4)
  with self.assertRaisesRegex(WorkspaceFailure,'expired'):call('ui.prepare_close',time.monotonic()-1)
  with self.assertRaises(WorkspaceFailure):call('ui.prepare_close',True)
  self.assertFalse(self.worker.closing)
 def test_ordinary_cleanup_uses_identical_no_argument_gate(self):
  original=self.worker.dispatch;seen=[]
  def capture(method,args,env):seen.append((method,args));return original(method,args,env)
  self.worker.dispatch=capture;prepare_stop({});self.assertEqual(seen,[('ui.request_close',[])]);self.assertTrue(self.worker.closing)

class LegacyEscape(unittest.TestCase):
 def setUp(self):
  from test_build13 import TunnelOnlyAPI
  self.api=TunnelOnlyAPI();self.api.setUp();self.api.server.preview=False;self.addCleanup(self.api.tearDown)
 def test_known_broken_open_worker_can_use_guarded_escape_before_node_stop(self):
  order=[]
  def protected(method,*args,**kw):
   order.append(method)
   return {'viewer_open':True,'worker_version':'2.0.0~dev20'} if method=='service_status' else {'message':'Guarded close accepted'}
  with patch('secure_bridge.call',side_effect=protected),patch('app.apply_config',side_effect=lambda *_:order.append('disable-node')),patch('secure_bridge.stop',side_effect=lambda:order.append('safe-stop') or {'message':'Cleared'}),patch('app.write_status'):
   code,result=self.api.call('/api/protected/recover',{})
  self.assertEqual(code,200);self.assertEqual(order,['service_status','ui.close','disable-node','safe-stop'])
 def test_busy_old_worker_refusal_cannot_disable_node_or_force_stop(self):
  with patch('secure_bridge.call',side_effect=[{'viewer_open':True,'worker_version':'2.0.0~dev20'},WorkspaceFailure('worker_rejected','Finish active work.')]),patch('app.apply_config') as apply,patch('secure_bridge.stop') as stop:
   code,_=self.api.call('/api/protected/recover',{})
  self.assertEqual(code,400);apply.assert_not_called();stop.assert_not_called()
 def test_current_unknown_or_future_open_worker_never_treated_as_broken_legacy(self):
  from app import legacy_close_window
  for version in ('2.0.0~dev27','2.0.0~dev27','unknown',None):self.assertFalse(legacy_close_window({'viewer_open':True,'worker_version':version}))
  self.assertTrue(legacy_close_window({'viewer_open':True,'worker_version':'2.0.0~dev20'}));self.assertFalse(legacy_close_window({'viewer_open':False,'worker_version':'2.0.0~dev20'}))
