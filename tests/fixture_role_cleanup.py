"""Idle disc waits permit public queries, never closure or private RPC."""
import tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store
from secure_worker import Workspace
from wallet_setup import secret_dialog

class IdleDiscReads(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);w=Workspace.__new__(Workspace);self.w=w;w.store=Store(Path(self.tmp.name)/'state');w.setup=SimpleNamespace(sessions={'setup':{'phase':'awaiting_disc'}},burner=SimpleNamespace(thread=None));w.archive_ops=SimpleNamespace(jobs={},busy=lambda:bool(w.archive_ops.jobs));w.archives=SimpleNamespace(reading=False);w.transfer=SimpleNamespace(sending=False);w.lock=threading.RLock();w.configure=lambda env:None;w.closing=False;w.ops=SimpleNamespace(core=Mock());w.ops.core.call.return_value={'result':{'chain':'regtest'}}
 def query(self,method='getblockchaininfo'):
  with patch('secure_worker.enforce'):return self.w.dispatch('core.public',['fixture',method,[],None,30],{})

class ConfirmationPrompts(unittest.TestCase):
 pass

class CleanupPreflight(unittest.TestCase):
 pass

class InterruptedCleanup(unittest.TestCase):
 def fixture(self):
  from fixture_cancellation import RealCoreCancellation
  f=RealCoreCancellation();f.setUp();self.addCleanup(f.doCleanups);return f

class CancellationReconciliationBoundary(unittest.TestCase):
 pass

class AssetRoutes(unittest.TestCase):
 pass
