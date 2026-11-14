"""Cancellation must stop transport without abandoning an in-flight Core write."""
import tempfile,unittest
from unittest.mock import Mock,patch
from approval_store import Store
from batch_transfer import BatchTransfer

class Cancellation(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
  self.store=Store(self.folder.name)
  with self.store.edit() as s:
   s.update(sync_batch={'direction':'receive','keys':['wallet']},active_transfer='wallet',sync_choices={'wallet':{'selected':True,'watch_only':True}})
  self.transfer=object.__new__(BatchTransfer);self.transfer.store=self.store;self.transfer.sending=False;self.transfer.thread=Mock();self.transfer.close=Mock();self.transfer.receive_reviews={'old':object()};self.transfer.details={}
 def test_running_core_operation_keeps_reservation_until_safe_checkpoint(self):
  self.transfer.thread.is_alive.return_value=True
  with patch('activity_log.event'):
   result=self.transfer.stop_receiving()
  self.assertTrue(result['cancelling']);self.assertEqual(self.store.read()['active_transfer'],'wallet');self.assertIn('sync_batch',self.store.read())
  self.assertFalse(self.store.read()['sync_choices']['wallet']['selected']);self.transfer.close.assert_called_once();self.transfer.thread.join.assert_called_once_with(timeout=2)
  self.assertFalse(self.transfer.receive_reviews);self.assertIsNone(self.transfer.details)
 def test_finished_operation_releases_reservation_and_stale_review_can_cancel(self):
  self.transfer.thread.is_alive.return_value=False
  with patch('activity_log.event'):
   result=self.transfer.cancel_receive('obsolete-review-id')
  self.assertFalse(result['cancelling']);self.assertNotIn('active_transfer',self.store.read());self.assertNotIn('sync_batch',self.store.read())
 def test_receive_control_does_not_cancel_sender(self):
  self.transfer.sending=True
  with self.assertRaisesRegex(ValueError,'outgoing'):self.transfer.stop_receiving()
  self.transfer.close.assert_not_called();self.assertIn('sync_batch',self.store.read())
