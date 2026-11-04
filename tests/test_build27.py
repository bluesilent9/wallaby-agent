"""Native close/status contention, late exchange cancellation and guarded cleanup."""
import copy,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from secure_bridge import WorkspaceFailure,call
from agent_exchange import Exchange
from approval_store import Store

class CloseAdmission(unittest.TestCase):
 def wire(self):
  from test_build21 import NativeWire
  fixture=NativeWire();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.worker.node_stop=threading.Event();return fixture.worker
 def test_native_close_waits_for_short_status_refresh_and_stops_node(self):
  w=self.wire();held=threading.Event()
  def refresh():
   with w.lock:held.set();time.sleep(.15)
  t=threading.Thread(target=refresh);t.start();self.addCleanup(t.join);self.assertTrue(held.wait(2));started=time.monotonic();self.assertEqual(call('ui.request_close'),{'ok':True});self.assertGreater(time.monotonic()-started,.1);self.assertTrue(w.closing);self.assertTrue(w.node_stop.is_set())
 def test_real_private_result_still_prevents_close_or_node_stop(self):
  w=self.wire();w.store.read.return_value={'outbox':{'signed':{'kind':'partial_sign_result','payload':{'status':'signed'}}}}
  with self.assertRaisesRegex(WorkspaceFailure,'completed operation results'):call('ui.request_close')
  self.assertFalse(w.closing);self.assertFalse(w.node_stop.is_set())
 def test_busy_status_snapshot_is_marked_transient(self):
  w=self.wire();w.viewers=[];w.window_required=True;w.node_status={'color':'green'};held=threading.Event();release=threading.Event()
  def refresh():
   with w.lock:held.set();release.wait(2)
  t=threading.Thread(target=refresh);t.start();self.assertTrue(held.wait(2))
  try:
   status=call('service_status');self.assertTrue(status['status_pending']);self.assertTrue(status['busy'])
  finally:release.set();t.join()

class CleanupRetry(unittest.TestCase):
 def fixture(self):
  from test_build17 import LifecycleTests
  f=LifecycleTests();f.setUp();self.addCleanup(f.doCleanups);return f
 def test_transient_status_does_not_claim_private_work_or_disconnect_early(self):
  from configuration import Config
  f=self.fixture();f.state.update(status_pending=True,busy=True);f.life.poll();self.assertTrue(Config().values['enabled']['node']);self.assertIsNone(f.life.thread)
  f.state.update(status_pending=False,busy=False);f.life.poll();self.assertIsNotNone(f.life.thread)
 def test_cleanup_status_race_retries_automatically_through_existing_guard(self):
  from runtime import read_status
  f=self.fixture();f.life.poll()
  with patch('secure_bridge.stop',side_effect=WorkspaceFailure('workspace_status_pending','Still refreshing')):f.life.clean()
  self.assertGreater(f.life.retry_after,time.monotonic());status=read_status('node');self.assertEqual(status['color'],'amber');self.assertNotIn('cleanup_failed',status);self.assertIn('retry automatically',status['message']);f.life.thread.active=False;f.life.retry_after=0;f.life.poll()
  with patch('secure_bridge.stop') as stop:f.life.clean()
  stop.assert_called_once();self.assertEqual(f.life.cleanup_wait_until,0);self.assertIn('cleared',read_status('node')['message'])
 def test_permanent_private_busy_never_force_stops_and_retry_budget_is_bounded(self):
  from runtime import read_status
  f=self.fixture();f.life.poll();f.life.cleanup_wait_until=time.monotonic()-1
  with patch('secure_bridge.stop',side_effect=WorkspaceFailure('workspace_busy','Private operation active')) as stop:f.life.clean()
  stop.assert_called_once();self.assertTrue(read_status('node')['cleanup_failed'])
 def test_bridge_never_stops_service_from_a_transient_busy_snapshot(self):
  from secure_bridge import stop
  with tempfile.TemporaryDirectory() as d,patch('configuration.Config',return_value=SimpleNamespace(values={'enabled':{'node':False}})),patch('runtime.runtime_dir',return_value=Path(d)),patch('secure_bridge.call',return_value={'busy':True,'status_pending':True}),patch('secure_bridge._stop_service') as kill:
   with self.assertRaises(WorkspaceFailure) as error:stop()
   self.assertEqual(error.exception.code,'workspace_status_pending');kill.assert_not_called()

class ExchangeShutdown(unittest.TestCase):
 def test_late_http_reply_does_not_apply_requests_or_acknowledge_unprocessed_outbox(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);key=store.queue('node_identity',{'ipv6':'2001:db8::1'});ex=Exchange(1,'fixture',store);cancelled=threading.Event();ex.cancelled=cancelled.is_set
   def reply(*a,**kw):cancelled.set();return {'version':1,'accepted':[key],'proposals':[{'kind':'wallet_sync_queue','revision':1,'requests':[]}]}
   with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',side_effect=reply):ex.once()
   state=store.read();self.assertIn(key,state['outbox']);self.assertNotIn('sync_revision',state)
 def test_intentional_shutdown_does_not_log_connection_failure_or_requeue_work(self):
  ex=Exchange(1,'fixture');cancelled=threading.Event();ex.cancelled=cancelled.is_set;stop=threading.Event()
  def interrupted(*args,**kwargs):cancelled.set();raise ConnectionRefusedError('Closed deliberately')
  with patch.object(ex,'once',side_effect=interrupted),patch('activity_log.event') as log:ex.run(stop)
  log.assert_not_called()

class QueueDiagnostics(unittest.TestCase):
 def test_empty_dashboard_snapshot_and_reenable_are_distinguishable(self):
  from sync_queue import apply_snapshot
  from sync_preferences import enable
  with tempfile.TemporaryDirectory() as d:
   store=Store(d)
   with patch('activity_log.event') as log:apply_snapshot(store,1,[])
   self.assertIn('receiving=0',log.call_args.args[1]);self.assertIn('visible=0',log.call_args.args[1]);result=enable(store,'1'*64);self.assertIn('Waiting for the Dashboard',result['message']);self.assertFalse(store.read()['pending'])
