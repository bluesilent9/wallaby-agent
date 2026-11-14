"""Late Server retirement indications are reconciled from actual Core records."""
import copy,shutil,unittest
from pathlib import Path
from unittest.mock import patch
from fixture_history_recovery import ExtinctionRecovery
from fixture_retirement import proposal
from wallet_retirement import Retirement
from wallet_ops import rpc
from approval_store import digest
from direct_wallet_catalogue import reconcile_preservation

class ExistingArchive(unittest.TestCase):
 setUp=ExtinctionRecovery.setUp
 def prepare(self,remove_original=True):
  owner=Retirement(self.core,self.store);owner.review(self.key);owner.approve(self.key)
  if remove_original:
   rpc(self.core,'unloadwallet',{'wallet_name':'Old'});shutil.rmtree(Path(self.core.config['cookie']).parent/'wallets'/'Old')
  p=proposal(self.raw,self.p['manifest'],'preserve','Wallaby Extinct',operation='d'*64);key=digest(p);self.store.receive(p)
  return p,key
 def check(self,key):
  with patch('retirement_phases.imports',side_effect=AssertionError('No imports permitted')),patch('core_history.install',side_effect=AssertionError('No database replacement permitted')),patch('retirement_phases.approve',side_effect=AssertionError('No wallet operation approval permitted')):reconcile_preservation(self.core,self.store)
  saved=self.store.read();self.assertNotIn(key,saved['pending']);self.assertEqual(saved['completed'][key]['result']['status'],'complete');self.assertFalse(saved['completed'][key]['result']['wallet_deleted']);self.assertFalse(saved.get('history_jobs'));return saved
 def test_archived_records_satisfy_late_request_after_original_was_deleted(self):
  p,key=self.prepare();before=rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'];saved=self.check(key)
  self.assertEqual(saved['completed'][key]['verification_basis'],'verified_archive');self.assertEqual(before,rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount']);self.assertNotIn('Old',{w['name'] for w in rpc(self.core,'listwalletdir')['wallets']});before=len(saved['outbox']);self.assertFalse(self.store.receive(p));reconcile_preservation(self.core,self.store);self.assertEqual(before,len(self.store.read()['outbox']))
 def test_existing_original_is_compared_and_retained_even_when_initially_unloaded(self):
  p,key=self.prepare(False);rpc(self.core,'unloadwallet',{'wallet_name':'Old'});saved=self.check(key)
  self.assertEqual(saved['completed'][key]['verification_basis'],'local_original_comparison');self.assertNotIn('Old',rpc(self.core,'listwallets'));self.assertIn('Old',{w['name'] for w in rpc(self.core,'listwalletdir')['wallets']})
 def test_conflicting_request_label_cannot_be_automatically_reported_complete(self):
  p,key=self.prepare();p['manifest']['addresses'][0]['label']='Untrusted different label';p['manifest_hash']=digest(p['manifest']);p['request_id']=digest({k:v for k,v in p.items() if k!='request_id'});bad=digest(p);self.store.receive(p)
  with self.store.edit() as s:s['pending'].pop(key)
  reconcile_preservation(self.core,self.store);self.assertIn(bad,self.store.read()['pending']);self.assertNotIn(bad,self.store.read()['completed']);self.assertFalse(self.store.read().get('history_jobs'))
 def test_unverified_archive_does_not_gain_a_completion_from_matching_record_counts(self):
  p,key=self.prepare()
  with patch('retirement_phases.rpc',wraps=rpc) as observed,patch('extinct_upgrade.status',return_value={'required':True,'mode':'download','addresses':2}):reconcile_preservation(self.core,self.store)
  self.assertIn(key,self.store.read()['pending']);self.assertNotIn(key,self.store.read()['completed']);self.assertFalse(self.store.read().get('history_jobs'))

 def test_missing_confirmed_record_cannot_be_automatically_reported_complete(self):
  p,key=self.prepare();real=rpc
  def missing(core,method,params=None,wallet=None,**kw):
   if method=='gettransaction' and wallet=='Wallaby Extinct':raise ValueError('Record unavailable')
   return real(core,method,params,wallet,**kw)
  with patch('retirement_phases.rpc',side_effect=missing):reconcile_preservation(self.core,self.store)
  self.assertIn(key,self.store.read()['pending']);self.assertNotIn(key,self.store.read()['completed']);self.assertFalse(self.store.read().get('history_jobs'))

 def test_authorised_continuation_does_not_approve_again_after_existing_data_reconciliation(self):
  p,key=self.prepare()
  from retirement_continuation import authorise,finish
  authorise(self.store,key,p)
  with patch('retirement_phases.approve',side_effect=AssertionError('No replay permitted')):finish(self.core,self.store)
  self.assertNotIn(key,self.store.read()['pending']);self.assertNotIn(key,self.store.read().get('retirement_continuations',{}));self.assertEqual(self.store.read()['completed'][key]['verification_basis'],'verified_archive')
