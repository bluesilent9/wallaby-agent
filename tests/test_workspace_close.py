"""Close safety distinguishes advisory cancellation from real operation results."""
import tempfile,threading,unittest
from unittest.mock import Mock,patch
from approval_store import Store
from secure_worker import delivery_pending,Workspace

class Close(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  self.w=object.__new__(Workspace);self.w.store=self.store;self.w.busy=Mock(return_value=False);self.w.peers=Mock();self.w.node_stop=threading.Event();self.w._state_snapshot={}
 def queue(self,kind,status,**kw):self.store.queue(kind,{'request_hash':'a'*64,'status':status,**kw})
 def test_cancelled_retirement_without_mutation_can_close_with_server_offline(self):
  self.queue('wallet_retirement_result','cancelled');self.assertFalse(delivery_pending(self.store.read()))
  with patch('activity_log.event'):self.w.begin_close()
  self.assertTrue(self.w.closing);self.w.peers.close.assert_called_once();self.assertTrue(self.w.node_stop.is_set());self.assertEqual(len(self.store.read()['outbox']),1)
 def test_retirement_denial_can_close_without_changing_durable_preferences(self):
  with self.store.edit() as s:s['request_denials']={'policy':{'purpose':'extinction','wallet_name':'Old'}}
  self.queue('wallet_retirement_result','denied')
  with patch('activity_log.event'):self.w.begin_close()
  self.assertEqual(self.store.read()['request_denials']['policy']['purpose'],'extinction')
 def test_cancelled_label_never_hides_a_wallet_mutation_or_preserved_archive(self):
  for flag in ('wallet_deleted','archive_verified','receipt','signed_artifact'):
   with self.subTest(flag=flag):self.assertTrue(delivery_pending({'outbox':{'x':{'kind':'wallet_retirement_result','payload':{'status':'cancelled',flag:True}}}}))
 def test_signed_results_completed_imports_and_uncertainty_still_block(self):
  for kind,status in [('wallet_retirement_result','complete'),('wallet_retirement_result','error'),('wallet_transfer_result','complete'),('wallet_transfer_result','recovery_required'),('partial_sign_result','complete')]:
   with self.subTest(kind=kind,status=status):self.assertTrue(delivery_pending({'outbox':{'x':{'kind':kind,'payload':{'status':status}}}}))
 def test_active_core_operation_blocks_even_with_only_cancel_notice(self):
  self.queue('wallet_retirement_result','cancelled');self.w.busy.return_value=True
  with patch('activity_log.event'),self.assertRaisesRegex(ValueError,'wallet operations'):self.w.begin_close()
  self.w.peers.close.assert_not_called();self.assertFalse(self.w.node_stop.is_set())
 def test_discovery_denial_and_dismissed_reviews_alone_do_not_block(self):
  with self.store.edit() as s:s['sync_exclusions']={'wallet':{'wallet_name':'Extinct'}};s['viewed_transfer']='obsolete';s['sync_choices']={'obsolete':{'selected':False}}
  with patch('activity_log.event'):self.w.begin_close()
  self.assertTrue(self.w.closing)
 def test_real_busy_check_allows_unstarted_sync_and_disabled_rows(self):
  from types import SimpleNamespace
  self.w.busy=Workspace.busy.__get__(self.w,Workspace);self.w.setup=SimpleNamespace(sessions={});self.w.archive_ops=None;self.w.archives=SimpleNamespace(reading=False,loaded=[],staged=[]);self.w.transfer=SimpleNamespace(sending=False);self.w.peers=None
  with self.store.edit() as s:s['pending']={'sync':{'proposal':{'kind':'wallet_transfer'},'state':'pending'}};s['sync_exclusions']={'archive':{'wallet_name':'Extinct'}}
  self.assertFalse(self.w.busy())
  with patch('activity_log.event'):self.w.begin_close()
  self.assertTrue(self.w.closing)
