"""Busy status must preserve the same local approval as a fresh worker response."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import test_sync_approvals as fixtures
from sync_queue import choose
from sync_approvals import groups
from secure_worker import Workspace

class StatusSnapshots(unittest.TestCase):
 setUp=fixtures.ReceiveApprovals.setUp
 def test_busy_snapshot_never_restores_raw_transfer_or_resets_receive_review(self):
  choose(self.store,self.ka,True,True)
  w=Workspace.__new__(Workspace);w.store=self.store;w.node_status={'color':'green'};w.recovery_state=lambda:{};w.archive_ops=None;w.transfer=SimpleNamespace(state=lambda:{'receive_approvals':groups(self.store)});w.burn_state=lambda:{};w.archives=SimpleNamespace(state=lambda:{});w.setup=SimpleNamespace(own_identity=lambda:{},sessions={});w.busy=lambda:False
  with patch('secure_worker.enforce',return_value={}),patch('extinct_sync.obsolete_denials',return_value=[]):
   normal=w.state();expected=normal['pending'];self.assertEqual(len(expected),1);self.assertEqual(expected[0]['kind'],'wallet_sync_receive')
   w.lock=Mock();w.lock.acquire.return_value=False
   for _ in range(5):
    cached=w.dispatch('status',[],{});self.assertEqual(cached['pending'],expected);self.assertTrue(cached['status_pending']);self.assertEqual(w.state()['pending'],expected)
   self.assertEqual(self.store.read()['pending'][self.ka]['proposal']['kind'],'wallet_transfer')
