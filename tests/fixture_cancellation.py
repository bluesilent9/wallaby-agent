"""Build19 cancellation, diagnostic export and typed public RPC failures."""
import copy,datetime as dt,hashlib,json,multiprocessing,os,secrets,stat,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from cancellation import Cancellations,validate,blocked,held_item
from activity_log import DiagnosticLog,redact,handoff
from cancel_backup import create_export,export_bundle
from secure_bridge import WorkspaceFailure
from wallet_ops import WalletOps,rpc
from wallet_retirement import Retirement
from regtest_support import Regtest

def cancel(builder='transaction',operations=None,hashes=None):
 p={'kind':'builder_cancel','version':1,'builder':builder,'workspace_id':'a'*32,'cancellation_id':'b'*32,'operations':operations or [],'request_hashes':hashes or [],'require_local_authorisation':True,'backup_option':True};p['request_id']=digest(p);return p

def row(message='service connected',origin='unprotected',at=None):return {'id':secrets.token_hex(16),'at':at or time.time(),'origin':origin,'source':'test.event','message':message}

def append_process(path):
 log=DiagnosticLog(path)
 for i in range(12):log.merge([row('concurrent '+str(i))])

class LogTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.log=DiagnosticLog(self.root/'logs')

class CancellationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.core=Mock();self.core.call.return_value={'result':[]};self.ops=SimpleNamespace(prepared={});self.setup=SimpleNamespace(sessions={},disc_sessions={},reviews={},burner=__import__('disc_backup').Burner(self.root/'jobs',lambda *a:None));self.c=Cancellations(self.core,self.store,self.setup,self.ops)

class ExportBoundary(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

class RealCoreCancellation(unittest.TestCase):
 def setUp(self):
  from wallet_setup import WalletSetup
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.setup=WalletSetup(self.core,self.store,binary=os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind'));self.ops=WalletOps(self.core,self.store);self.c=Cancellations(self.core,self.store,self.setup,self.ops)
  def cleanup():
   for session in self.setup.sessions.values():
    if session.get('core'):session['core'].close()
  self.addCleanup(cleanup)
 def setup_wallet(self,installed=False):
  own=self.setup.own_identity();p={'kind':'wallet_setup','version':1,'session_id':'a'*64,'chain':'regtest','name':'Cancel fixture','threshold':2,'height':50,'expires_at':int(time.time())+3600,'cosigners':[{'id':str(i),'name':'Role '+str(i),'agent_key':own['public_key'],'storage':'disc' if i==2 else 'node'} for i in range(3)]};self.store.receive(p)
  with patch('wallet_setup.secret_dialog',return_value='fixture-Core-passphrase'):self.setup.approve_proposal(digest(p),{own['fingerprint']:own['fingerprint']})
  if installed:
   from setup_policy import policy
   contributions=self.setup.sessions[digest(p)]['contributions'];descs=policy(p,[e['message'] for e in contributions]);complete={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};self.store.receive(complete);self.setup.review(digest(complete))
   with patch('wallet_setup.secret_dialog',return_value='fixture-Core-passphrase'):self.setup.approve_policy(digest(complete))
  return p

class ContractAndRPCTests(unittest.TestCase):
 pass

class ExportContractTests(unittest.TestCase):
 pass

class RetirementRaceTests(unittest.TestCase):
 pass

class PublicFailureWireTests(unittest.TestCase):
 pass

class DashboardReceiptFixture(unittest.TestCase):
 pass

class CancellationDispatchGates(unittest.TestCase):
 pass
