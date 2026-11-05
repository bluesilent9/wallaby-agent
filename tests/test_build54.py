"""Review expiry must never solicit an expired secret or emit a signature."""
import copy,tempfile,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from wallet_ops import WalletOps,rpc,require_current_review,review_remaining
from wallet_traits import local_traits,policy_traits
from diagnostics import LocalActionFailure,action_code,action_detail
from secure_worker import Workspace

class Expiry(unittest.TestCase):
 def test_exact_limit_and_monotonic_clock_survive_wall_clock_rollback(self):
  p={'created':1000,'created_monotonic':20}
  with patch('wallet_ops.time.time',return_value=1599),patch('wallet_ops.time.monotonic',return_value=619):self.assertEqual(review_remaining(p),1);require_current_review(p)
  for wall in (1600,900):
   with patch('wallet_ops.time.time',return_value=wall),patch('wallet_ops.time.monotonic',return_value=620),self.assertRaises(LocalActionFailure):require_current_review(p)
 def worker(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.store=Store(tmp.name);w.configure=lambda env:None;w.environment={};w.archives=None
  w.ops=WalletOps(Mock(),w.store);w.ops.prepared['key']={'created':time.time(),'created_monotonic':time.monotonic(),'wallet':'Local wallet','review':{'fee_review':{'requires_ack':False}}}
  return w
 def test_expired_worker_request_refuses_before_core_or_password_dialogue(self):
  w=self.worker();w.ops.prepared['key']['created']-=601
  with patch('secure_worker.enforce'),patch('wallet_ops.rpc') as core,patch('secure_worker.secret_dialog') as prompt,self.assertRaises(LocalActionFailure) as exc:w.dispatch('wallet.sign',['key','partial',False],{})
  prompt.assert_not_called();core.assert_not_called();self.assertEqual(action_code(exc.exception),'transaction_review_expired');self.assertIn('ten-minute',action_detail(exc.exception));self.assertIn('Review this transaction again',str(exc.exception))
 def test_expiry_while_password_dialogue_is_open_does_not_sign(self):
  w=self.worker()
  def password(*args):w.ops.prepared['key']['created']-=601;return 'test-secret'
  with patch('secure_worker.enforce'),patch('wallet_ops.rpc',return_value={'walletname':'Local wallet','unlocked_until':0}) as core,patch('secure_worker.secret_dialog',side_effect=password),self.assertRaises(LocalActionFailure):w.dispatch('wallet.sign',['key','partial',False],{})
  self.assertEqual(core.call_count,1);self.assertEqual(core.call_args.args[1],'getwalletinfo');self.assertEqual(w.store.read()['outbox'],{})
 def test_expiry_during_broadcast_preparation_is_reviewable_without_send(self):
  w=self.worker();review={'inputs':[],'fee_review':{'requires_ack':False}}
  p=w.ops.prepared['key'];p.update(kind='broadcast_transaction',chain='regtest',psbt='fixture',txid='test-tx',review=review)
  with w.store.edit() as state:state['pending']['key']={'state':'pending','proposal':{'kind':'broadcast_transaction'}}
  def core(_core,method,*args,**kwargs):
   if method=='finalizepsbt':return {'complete':True,'hex':'fixture'}
   if method=='decoderawtransaction':return {'txid':'test-tx'}
   if method=='testmempoolaccept':p['created']-=601;return [{'allowed':True}]
   raise AssertionError('Unexpected RPC: '+method)
  with patch.object(w.ops,'review',return_value=review),patch('policy_refresh.verify_output_policies'),patch('transaction_requests.intents'),patch('wallet_ops.rpc',side_effect=core),self.assertRaises(LocalActionFailure):w.ops.sign('key','','broadcast',True)
  self.assertEqual(w.store.read()['pending']['key']['state'],'pending');self.assertEqual(w.store.read()['outbox'],{})
 def test_missing_review_fails_closed_with_clear_explanation(self):
  for p in (None,{}, {'wallet':'Local'}):
   with self.assertRaises(LocalActionFailure):require_current_review(p)

class Traits(unittest.TestCase):
 def test_traits_use_policy_threshold_not_name_or_optional_height_branch(self):
  key='02'+'79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798'
  key2='03'+'f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9'
  plain='wpkh('+key+')';multi='wsh(sortedmulti(2,'+key+','+key2+'))';vault='wsh(and_v(v:after(200),multi(2,'+key+','+key2+')))'
  self.assertEqual(policy_traits(plain),{'vault':False,'multisig':False});self.assertEqual(policy_traits(multi),{'vault':False,'multisig':True});self.assertEqual(policy_traits(vault),{'vault':True,'multisig':True});self.assertEqual(policy_traits('untrusted Dashboard vault label'),{})
  self.assertFalse(policy_traits('wsh(sortedmulti(1,'+key+','+key2+'))')['multisig'])
  self.assertFalse(policy_traits('wsh(or_i(pk('+key+'),multi(2,'+key+','+key2+')))')['multisig'])
 def test_disc_and_watch_are_only_local_core_facts(self):
  def call(core,method,params,name):
   if method=='getwalletinfo':return {'private_keys_enabled':name=='signer','wallaby_storage':'disc' if name=='archive' else 'node'}
   return {'parent_desc':''}
  with patch('wallet_ops.rpc',side_effect=call):
   self.assertEqual(local_traits(None,['archive'],'address'),{'vault':False,'multisig':False,'watch':True,'disc':True})
   self.assertFalse(local_traits(None,['archive','signer'],'address')['watch']);self.assertFalse(local_traits(None,[],'unknown')['disc'])

# Reuse the isolated-node fixture without rerunning inherited test methods.
import test_vault_security as fixtures
@unittest.skipIf(getattr(fixtures.RealCoreVault,'__unittest_skip__',False),'Official isolated Core fixture unavailable')
class RealSigning(unittest.TestCase):
 setUpClass=classmethod(fixtures.RealCoreVault.setUpClass.__func__)
 tearDownClass=classmethod(fixtures.RealCoreVault.tearDownClass.__func__)
 setUp=fixtures.RealCoreVault.setUp
 build=fixtures.RealCoreVault.build
 def test_core_returning_unsigned_psbt_cannot_be_reported_as_signed(self):
  built=self.build();p={'kind':'sign_psbt_partial','request_id':'b'*64,'wallet':self.source,'chain':'regtest','psbt':built['psbt']};self.store.receive(p);key=digest(p);self.ops.prepare_request(key)
  original=rpc
  def no_signature(core,method,params=None,wallet=None,timeout=30):
   if method=='walletprocesspsbt' and isinstance(params,dict) and params.get('sign'):return {'psbt':params['psbt']}
   return original(core,method,params,wallet,timeout)
  with patch('wallet_ops.rpc',side_effect=no_signature),self.assertRaises(LocalActionFailure) as error:self.ops.sign(key,'regtest-password','partial',True)
  self.assertEqual(error.exception.code,'transaction_no_signature');self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertFalse(self.store.read()['outbox']);self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
 def test_expiry_preserves_request_and_explicit_review_again_signs_same_transaction(self):
  built=self.build();p={'kind':'sign_psbt_partial','request_id':'a'*64,'wallet':self.source,'chain':'regtest','psbt':built['psbt']};self.store.receive(p);key=digest(p)
  reviewed=self.ops.prepare_request(key);self.assertGreater(reviewed['review_seconds_remaining'],590);self.assertLessEqual(reviewed['review_seconds_remaining'],600)
  self.assertIn('traits',reviewed['review']['inputs'][0]);self.assertFalse(reviewed['review']['inputs'][0]['traits']['watch'])
  self.ops.prepared[key]['created']-=601
  with self.assertRaises(LocalActionFailure):self.ops.sign(key,'regtest-password','partial',True)
  self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertFalse(any(row['kind']=='partial_sign_result' for row in self.store.read()['outbox'].values()));self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
  fresh=self.ops.prepare_request(key);self.assertEqual(fresh['review'],reviewed['review']);result=self.ops.sign(key,'regtest-password','partial',True);self.assertTrue(result['queued']);self.assertNotIn(key,self.store.read()['pending'])
