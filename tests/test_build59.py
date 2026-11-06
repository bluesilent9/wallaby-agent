"""A long read-only policy scan keeps status/inventory responsive and never approves."""
import copy,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from background_review import Reviews
from secure_worker import Workspace

class BackgroundReview(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from test_build58 import Receipt
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.p=f.p;self.key=digest(self.p);self.store.receive(self.p)
  self.owner=SimpleNamespace(lock=threading.RLock(),store=self.store);self.jobs=Reviews(self.owner);self.entered=threading.Event();self.release=threading.Event();self.addCleanup(self.release.set);self.calls=0
 def review(self,key):
  self.calls+=1;self.entered.set()
  if not self.release.wait(5):raise AssertionError('Fixture release timed out')
  return {'kind':'wallet_policy_refresh','id':key,'refresh':{'verified':True}}
 def wait(self):
  until=time.monotonic()+3
  while self.jobs.active and time.monotonic()<until:time.sleep(.005)
  self.assertIsNone(self.jobs.active)
 def test_one_scan_per_review_with_quick_pending_polls_and_no_approval(self):
  with self.owner.lock:first=self.jobs.start(self.key,'wallet_policy_refresh',self.review)
  self.assertTrue(self.entered.wait(1));self.assertEqual(first['kind'],'public_review_pending')
  for _ in range(20):
   with self.owner.lock:self.assertEqual(self.jobs.start(self.key,'wallet_policy_refresh',self.review)['kind'],'public_review_pending')
  self.assertEqual(self.calls,1);self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending');self.assertFalse(self.store.read()['outbox'])
  self.release.set();self.wait()
  with self.owner.lock:result=self.jobs.start(self.key,'wallet_policy_refresh',self.review)
  self.assertTrue(result['refresh']['verified']);self.assertEqual(self.calls,1)
 def test_withdrawn_request_cannot_leave_a_successful_review_or_approval(self):
  with self.owner.lock:self.jobs.start(self.key,'wallet_policy_refresh',self.review)
  self.assertTrue(self.entered.wait(1))
  with self.store.edit() as s:s['pending'][self.key]['cancel_requested']='cancel'
  self.release.set();self.wait();self.assertEqual(self.jobs.jobs[self.key]['state'],'error');self.assertFalse(self.store.read()['outbox'])
 def test_arbitrary_error_is_not_exposed_and_retry_is_explicit(self):
  def fail(key):raise RuntimeError('PRIVATE FIXTURE ERROR must never be exposed')
  with self.owner.lock:self.jobs.start(self.key,'wallet_policy_refresh',fail)
  self.wait()
  with self.owner.lock,self.assertRaises(ValueError) as error:self.jobs.start(self.key,'wallet_policy_refresh',fail)
  self.assertNotIn('PRIVATE FIXTURE',str(error.exception));self.assertNotIn(self.key,self.jobs.jobs)

class WorkspaceLiveness(unittest.TestCase):
 def setUp(self):
  from test_build39 import PublicExecution
  f=PublicExecution();f.setUp();self.addCleanup(f.doCleanups);self.w=f.w;self.w.node_status={'color':'green'};self.w.viewers=[];self.w.recovery_state=lambda:{};self.w.public_reviews=Reviews(self.w)
 def test_status_retains_protected_view_during_an_exclusive_operation(self):
  held=threading.Event();release=threading.Event();self.addCleanup(release.set)
  self.w._state_snapshot={'pending':[{'id':'known','kind':'wallet_policy_refresh'}],'protected':{'running':True,'viewer':True},'archives':{'loaded':[]}}
  def hold():
   with self.w.lock:held.set();release.wait(3)
  thread=threading.Thread(target=hold);thread.start();self.assertTrue(held.wait(1))
  with patch('secure_worker.enforce',return_value={}):result=self.w.dispatch('status',[],{})
  self.assertTrue(result['protected']['viewer']);self.assertTrue(result['connected']);self.assertTrue(result['status_pending']);self.assertEqual(result['pending'][0]['id'],'known');release.set();thread.join(1)
 def test_review_does_not_hold_inventory_lock_and_blocks_wallet_mutation(self):
  entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
  from test_build58 import Receipt
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.w.store.receive(f.p);key=digest(f.p)
  def review(key):entered.set();release.wait(3);return {'kind':'wallet_policy_refresh','id':key,'refresh':{}}
  self.w.refresh_ops=SimpleNamespace(review=review);self.w.setup.sessions={}
  with patch('secure_worker.enforce',return_value={}):
   result=self.w.dispatch('authorise.review',[key],{});self.assertEqual(result['kind'],'public_review_pending');self.assertTrue(entered.wait(1));self.assertFalse(self.w.busy(public_reads=True));self.assertTrue(self.w.busy())
   self.assertIn('result',self.w.public_rpc('health','getblockchaininfo',[],None,1))
   with self.assertRaisesRegex(ValueError,'read-only policy review'):self.w.dispatch('wallet.sign',['unused'],{})
  release.set()
 def test_idle_cancellation_allows_inventory_but_still_blocks_workspace_close(self):
  self.w.setup.sessions={}
  for kind in ('builder_cancel','archive_cancel','destroy_disc'):
   with self.w.store.edit() as s:s['pending']={'cleanup':{'proposal':{'kind':kind},'state':'pending'}}
   self.assertFalse(self.w.busy(public_reads=True));self.assertTrue(self.w.busy())
   with patch('secure_worker.enforce',return_value={}):self.assertIn('result',self.w.public_rpc('health','getblockchaininfo',[],None,1))
