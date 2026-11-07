"""Preparation must not rescan before queuing recovery or duplicate archive history."""
import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement,inventory,MissingHistory
from retirement_phases import prepare_history,imports,readback,review
from regtest_support import Regtest
from test_build30 import proposal,legacy

class ExtinctionRecovery(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(Path(tmp.name))
  for name in ('Old','Miner'):rpc(self.core,'createwallet',{'wallet_name':name})
  a=rpc(self.core,'getnewaddress',[],'Old');miner=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[1,a]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'sendall',{'recipients':[miner]},'Old');rpc(self.core,'generatetoaddress',[1,miner])
  self.raw=rpc(self.core,'listdescriptors',[False],'Old');targets=[{'wallet':'Old','public_wallet':self.raw,'private_keys_enabled':True}];facts=inventory(self.core,self.store,legacy(self.raw,targets))
  manifest={'addresses':[{k:r[k] for k in ('address','label')} for r in facts['addresses']],'transactions':facts['transaction_records']};self.p=proposal(self.raw,manifest,'preserve','Wallaby Extinct');self.key=digest(self.p);self.store.receive(self.p)
  rpc(self.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True})
 def test_missing_history_stages_without_rescan_reuses_job_and_preserves_labels(self):
  calls=[]
  def checked(core,method,params=None,wallet=None,**kwargs):
   if method=='importdescriptors':
    calls.append(copy.deepcopy(params));self.assertTrue(all(type(r['timestamp']) is int and r['timestamp']>time.time()+7200 for r in params['requests']),'Preparation must not trigger historical rescan')
   return rpc(core,method,params,wallet,**kwargs)
  with patch('retirement_phases.rpc',side_effect=checked):result=prepare_history(self.core,self.store,self.key,self.p)
  self.assertTrue(result['history_prepared']);self.assertEqual(len(calls),1)
  jobs=copy.deepcopy(self.store.read()['history_jobs']);self.assertEqual({r['wallet'] for r in jobs.values()},{'Old','Wallaby Extinct'})
  job=jobs[digest({'local_retirement_history':self.key})];self.assertTrue(job['local_only']);self.assertFalse(job['expected_private_keys']);self.assertTrue(all(row['timestamp']==0 for row in job['details']['public_wallet']['descriptors']));self.assertTrue(job['details']['address_labels'])
  with patch('retirement_phases.imports',side_effect=AssertionError('Repeated preparation must not import')):self.assertTrue(prepare_history(self.core,self.store,self.key,self.p)['history_prepared'])
  self.assertEqual(jobs,self.store.read()['history_jobs'])
  manager=Retirement(self.core,self.store)
  with patch('retirement_phases.readback',side_effect=ValueError('Not complete')),patch('retirement_phases.local_facts',side_effect=MissingHistory('Required old blocks pruned')):
   shown=manager.review(self.key)['retirement'];self.assertTrue(shown['history_prepared']);self.assertTrue(shown['history_required'])
  self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_repeated_imports_do_not_duplicate_transactions_or_descriptors_and_readback_finishes(self):
  imports(self.core,self.p);readback(self.core,self.p)
  first_info=rpc(self.core,'getwalletinfo',[],'Wallaby Extinct');first=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct')
  imports(self.core,self.p);readback(self.core,self.p)
  self.assertEqual(first_info['txcount'],rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount']);self.assertEqual(first,rpc(self.core,'listdescriptors',[False],'Wallaby Extinct'))
  manager=Retirement(self.core,self.store)
  with patch('retirement_phases.local_facts',side_effect=AssertionError('Complete archive must not loop back to pruned source coverage')):
   shown=manager.review(self.key);self.assertEqual(shown['retirement']['phase'],'preserve')
   with patch('retirement_phases.imports',side_effect=AssertionError('Already verified history must not rescan')):manager.approve(self.key)
  self.assertNotIn(self.key,self.store.read()['pending']);self.assertTrue(self.store.read()['completed'][self.key]['result']['history_verified']);self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_already_imported_addresses_are_not_reimported_during_preparation(self):
  imports(self.core,self.p)
  # A previous attempt may have installed every descriptor before failing its rescan.
  with patch('retirement_phases.readback',side_effect=ValueError('Previous rescan incomplete')),patch('retirement_phases.rpc',wraps=rpc) as calls:
   prepare_history(self.core,self.store,self.key,self.p)
  self.assertFalse(any(c.args[1]=='importdescriptors' for c in calls.call_args_list))

class PrunedPreservationBarrier(unittest.TestCase):
 def setUp(self):
  self.p={'phase':'preserve','wallet':'Extinct','public_wallet':{'wallet_name':'Old'},'manifest':{'addresses':[],'transactions':[]},'manifest_hash':'hash'}
 def test_missing_archive_history_requires_explicit_recovery_even_if_source_has_coverage(self):
  with patch('retirement_phases.validate'),patch('retirement_phases.check_chain',return_value={'blocks':100,'pruned':True,'pruneheight':50}),patch('retirement_phases.existing_archive'),patch('retirement_phases.readback',side_effect=ValueError('Incomplete archive')),patch('retirement_phases.local_facts',side_effect=AssertionError('Do not offer a doomed genesis import')):
   with self.assertRaisesRegex(MissingHistory,'Prepare local history recovery'):review(object(),object(),self.p)
 def test_complete_archive_does_not_need_deleted_blocks_or_repeat_import(self):
  with patch('retirement_phases.validate'),patch('retirement_phases.check_chain',return_value={'blocks':100,'pruned':True,'pruneheight':50}),patch('retirement_phases.existing_archive'),patch('retirement_phases.readback'),patch('retirement_phases.verify_public') as verify,patch('retirement_phases.local_facts',side_effect=AssertionError('Complete archive is sufficient for preservation')):
   self.assertEqual(review(object(),object(),self.p)['phase'],'preserve');self.assertEqual(verify.call_args.kwargs,{'transaction_wallet':'Extinct'})
