"""Existing-wallet archives remain usable while unrelated setup awaits approval."""
import threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_build38
from secure_worker import Workspace
from node_client import NodeClient

class PublicExecution(test_build38.IdleDiscReads):
 def test_idle_contribution_reservation_allows_read_only_health_and_inventory(self):
  self.w.setup.sessions['setup']['phase']='contributed'
  with self.w.store.edit() as s:s['setup_active']='setup'
  self.assertTrue(self.w.busy());self.assertFalse(self.w.busy(public_reads=True))
  from test_build8 import paired
  self.w.ops.core.call.side_effect=lambda ident,method,params,wallet=None,timeout=30: {'result':paired()['public_wallet'] if method=='listdescriptors' else {'walletname':wallet} if method=='getwalletinfo' else {'chain':'regtest'}}
  client=NodeClient({},1,threading.Event(),lambda *args:None);self.addCleanup(lambda:client.pool.shutdown(wait=True));sent=[]
  client.post=lambda path,body: {'execute':True} if path=='ack' else sent.append(body)
  for method,wallet in [('getblockchaininfo',None),('listwallets',None),('getwalletinfo','Existing wallet'),('listdescriptors','Existing wallet')]:
   client.pending.acquire()
   with patch('node_client.LOCAL_PUBLIC_RPC',self.w.public_rpc),patch('secure_worker.enforce'):
    client.execute({'id':'fixture','expires_in_seconds':30,'kind':'rpc','method':method,'params':[],'wallet':wallet},time.monotonic())
   self.assertIn('result',sent[-1])
  self.assertTrue(self.w.busy(),'closure remains guarded despite public availability')
 def test_active_mutation_or_unavailable_lock_returns_busy_without_core_call(self):
  for phase in ('generating','installing','error'):
   self.w.setup.sessions['setup']['phase']=phase
   with patch('secure_worker.enforce'):self.assertIn('error',self.w.public_rpc('test','getblockchaininfo',[],None,30))
  self.w.setup.sessions['setup']['phase']='contributed';self.w.lock=Mock();self.w.lock.acquire.return_value=False
  with patch('secure_worker.enforce'):self.assertIn('error',self.w.public_rpc('test','getblockchaininfo',[],None,30))
  self.w.ops.core.call.assert_not_called()

class ExistingArchive(unittest.TestCase):
 def test_real_core_archive_during_contributed_setup_preserves_original_setup(self):
  from test_build19 import RealCoreCancellation
  from wallet_ops import rpc
  from approval_store import digest
  from archive_operations import Operations
  f=RealCoreCancellation();f.setUp();self.addCleanup(f.doCleanups);p=f.setup_wallet();binding=digest(p)
  self.assertEqual(f.setup.sessions[binding]['phase'],'contributed');before=f.setup.sessions[binding]['core'];contributions=list(f.setup.sessions[binding]['contributions'])
  rpc(f.core,'createwallet',{'wallet_name':'Existing wallet','passphrase':'fixture-independent-passphrase'})
  raw=rpc(f.core,'listdescriptors',[False],'Existing wallet');task={'kind':'archive_wallet','version':1,'nonce':'e'*64,'wallet':'Existing wallet','public_wallet':raw,'related_policies':[],'require_local_authorisation':True};task['request_id']=digest(task);key=digest(task);f.store.receive(task)
  w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.store=f.store;w.setup=f.setup;w.ops=f.ops;w.closing=False;w.configure=lambda env:None;w.recovery_state=lambda:{};w.archives=SimpleNamespace(reading=False,loaded={},staged={},catalogs={});w.transfer=SimpleNamespace(sending=False);w.archive_ops=Operations(f.core,f.store,f.setup,w.archives,lambda:None)
  with patch('secure_worker.enforce'):
   self.assertIn('result',w.dispatch('core.public',['health','getblockchaininfo',[],None,30],{}))
   self.assertEqual(w.dispatch('authorise.review',[key],{})['kind'],'archive_wallet')
   w.dispatch('authorise.approve',[key],{})
  self.assertEqual(w.archive_ops.jobs[key]['phase'],'queued');self.assertEqual(f.store.read()['setup_active'],binding)
  self.assertIs(f.setup.sessions[binding]['core'],before);self.assertIsNone(before.process.poll());self.assertEqual(f.setup.sessions[binding]['contributions'],contributions)
  self.assertEqual(f.setup.sessions[binding]['phase'],'contributed');self.assertIn('Existing wallet',rpc(f.core,'listwallets'))

  # The original ceremony can still install its policy and add its disc signer.
  from setup_policy import policy
  descs=policy(p,[e['message'] for e in contributions]);complete={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};f.store.receive(complete)
  with patch('secure_worker.enforce'):
   w.dispatch('authorise.review',[digest(complete)],{});w.dispatch('authorise.approve',[digest(complete)],{})
  self.assertEqual(f.setup.sessions[binding]['phase'],'awaiting_disc');self.assertEqual(f.setup.burner.job['id'],key);self.assertEqual(len(f.setup.burner.pending),1)
