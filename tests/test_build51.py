"""Measured stage ETA and exact-job burn selection admission."""
import tempfile,unittest
from unittest.mock import patch,Mock
from disc_backup import Burner,WriterProgress,StageProgress

class Estimates(unittest.TestCase):
 def test_countdown_uses_actual_progress_stales_and_restarts_for_verification(self):
  with tempfile.TemporaryDirectory() as folder:
   b=Burner(folder,Mock());b.authorise('job',{}, {'policy_hash':'public'});j=b.job;j.update(phase='burning',total_bytes=1000)
   clock=[0]
   with patch('disc_backup.time.monotonic',side_effect=lambda:clock[0]),patch('disc_backup.time.time',side_effect=lambda:100+clock[0]):
    writer=WriterProgress(j);writer.writer_report(writer_input_bytes=1000)
    self.assertIsNone(b.state()['estimated_remaining_seconds'])
    clock[0]=6;writer(100);self.assertEqual(b.state()['estimated_remaining_seconds'],54)
    clock[0]=8;self.assertEqual(b.state()['estimated_remaining_seconds'],52)
    clock[0]=40;self.assertTrue(b.state()['eta_waiting_for_progress']);self.assertIsNone(b.state()['estimated_remaining_seconds'])
    j['phase']='verifying';verify=StageProgress(j,'verified_bytes','verifying');self.assertEqual(j['verified_bytes'],0);self.assertIsNone(b.state()['estimated_remaining_seconds'])
    clock[0]=46;verify(500);self.assertEqual(b.state()['estimated_remaining_seconds'],6)
    self.assertEqual(j['written_bytes'],100);self.assertEqual(j['verified_bytes'],500)
 def test_zero_progress_never_creates_an_eta(self):
  j={'total_bytes':1000,'phase':'burning'}
  with patch('disc_backup.time.monotonic',side_effect=[0,10]):
   p=WriterProgress(j);p(0)
  self.assertIsNone(j['eta_seconds'])

class SelectionAdmission(unittest.TestCase):
 def test_stale_selection_does_not_change_new_disc_job(self):
  with tempfile.TemporaryDirectory() as folder:
   b=Burner(folder,Mock());b.authorise('current',{}, {'policy_hash':'public'})
   with self.assertRaisesRegex(ValueError,'job changed'):b.select(['current'],'previous')
   self.assertIsNone(b.selected)
 def test_atomic_burn_selection_is_applied_before_drive_checks_or_passphrase(self):
  from wallet_setup import WalletSetup
  # The production burn entry point must bind visible ids to the same job before
  # opening a dialog or calling the writer, even if the earlier save was delayed.
  setup=WalletSetup.__new__(WalletSetup)
  with tempfile.TemporaryDirectory() as folder:
   b=setup.burner=Burner(folder,Mock());b.authorise('a',{}, {'policy_hash':'public'});b.pending=[('b',{}, {'policy_hash':'other'})]
   setup.enforce=Mock();setup.environment={}
   with patch.object(b,'validate_options',side_effect=ValueError('drive check reached')):
    with self.assertRaisesRegex(ValueError,'drive check reached'):setup.burn('/dev/sr0',True,1,'slowest','a',['b'])
   self.assertEqual(b.selected,['b'])
   with self.assertRaisesRegex(ValueError,'job changed'):setup.burn('/dev/sr0',True,1,'slowest','old',['a'])
   self.assertEqual(b.selected,['b'])
