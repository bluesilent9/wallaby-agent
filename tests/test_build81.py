"""Carry local preservation consent through real recovery, then prove deletion evidence."""
import copy,time,unittest
from unittest.mock import patch
from approval_store import digest,Store
from wallet_ops import rpc
from wallet_retirement import Retirement
from wallet_recovery import Recovery
from retirement_continuation import finish
from retirement_phases import readback
import test_build62 as fixture62
import test_build77 as fixture77
from test_build30 import proposal

class AutomaticRecovery(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 legacy=fixture77.WholeArchive.legacy
 def test_approval_recovers_legacy_and_current_then_completes_without_second_approval(self):
  address,label,txids=self.legacy();owner=Retirement(self.core,self.store)
  owner.prepare_history(self.key)
  self.assertEqual(self.store.read()['retirement_continuations'][self.key]['state'],'authorised')
  recovery=Recovery(self.core,self.store);plan=recovery.plan();recovery.start(plan['id']);recovery.thread.join(50)
  self.assertFalse(recovery.thread.is_alive());saved=self.store.read();self.assertEqual(saved['recovery']['state'],'complete',saved['recovery'])
  self.assertNotIn(self.key,saved['pending']);result=saved['completed'][self.key]['result'];self.assertTrue(result['history_verified']);self.assertFalse(result['wallet_deleted']);self.assertIn('Old',rpc(self.core,'listwallets'))
  readback(self.core,self.p);self.assertEqual(rpc(self.core,'getaddressinfo',[address],'Wallaby Extinct')['labels'],[label])
  for tx in txids:self.assertGreater(rpc(self.core,'gettransaction',[tx,True],'Wallaby Extinct')['confirmations'],0)
  before=rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'];outbox=copy.deepcopy(saved['outbox']);finish(self.core,self.store)
  self.assertEqual(outbox,self.store.read()['outbox']);self.assertEqual(before,rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'])
 def test_cancelled_or_denied_request_never_continues(self):
  owner=Retirement(self.core,self.store);owner.prepare_history(self.key);owner.cancel_remote(self.key)
  with self.store.edit() as s:s['history_jobs']={}
  with patch('wallet_retirement.Retirement.approve',side_effect=AssertionError('Cancelled consent')):finish(self.core,self.store)
  self.assertNotIn(self.key,self.store.read()['retirement_continuations']);self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_uncertain_completion_is_not_replayed(self):
  owner=Retirement(self.core,self.store);owner.prepare_history(self.key)
  with self.store.edit() as s:s['history_jobs']={}
  with patch('wallet_retirement.Retirement.review',side_effect=ValueError('History differs')):
   with self.assertRaises(ValueError):finish(self.core,self.store)
  self.assertEqual(self.store.read()['retirement_continuations'][self.key]['state'],'uncertain')
  with patch('wallet_retirement.Retirement.review',side_effect=AssertionError('No repeat')):finish(self.core,self.store)
 def test_fresh_session_and_server_proposal_cannot_authorise_preservation(self):
  with patch('wallet_retirement.Retirement.approve',side_effect=AssertionError('No local approval')):finish(self.core,self.store)
  self.assertIn(self.key,self.store.read()['pending'])
  self.assertEqual(Recovery(self.core,self.store).state()['status'],'Extinction review required')

class DeletionEvidence(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 def prepare(self):
  owner=Retirement(self.core,self.store);owner.review(self.key);owner.approve(self.key)
  result=self.store.read()['completed'][self.key]['result']
  proof={'node_id':'1'*32,'request_hash':self.key,'archive_wallet':'Wallaby Extinct','manifest_hash':self.p['manifest_hash'],'verified_utc':'2026-11-13T00:00:00Z','receipt':result['archive_receipt']}
  targets=[{'wallet':'Old','public_wallet':self.raw,'private_keys_enabled':True}]
  p=proposal(self.raw,self.p['manifest'],'delete','Old',targets,proof);key=digest(p);self.store.receive(p)
  return owner,p,key
 def test_every_record_checked_samples_are_local_and_deletion_remains_separate(self):
  owner,p,key=self.prepare();f=owner.review(key)['retirement'];e=f['history_comparison']
  self.assertTrue(e['verified']);self.assertFalse(f['history_elsewhere_confirmation_required']);self.assertEqual(e['transaction_count'],len(p['manifest']['transactions']));self.assertEqual(e['address_count'],len(p['manifest']['addresses']))
  self.assertTrue(e['transaction_samples']);self.assertTrue(all(t['matched'] and t['height']>0 for t in e['transaction_samples']));self.assertIn('Old',rpc(self.core,'listwallets'));self.assertIn(key,self.store.read()['pending'])
 def test_local_archive_missing_record_or_label_blocks_deletion_review(self):
  owner,p,key=self.prepare();r=p['manifest']['addresses'][0]
  rpc(self.core,'setlabel',[r['address'],'Different label'],'Wallaby Extinct')
  with self.assertRaisesRegex(ValueError,'readback'):owner.review(key)
  self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_changed_raw_transaction_never_passes_even_when_txid_summary_matches(self):
  owner,p,key=self.prepare();real=rpc
  def changed(core,method,params=None,wallet=None,**kw):
   value=real(core,method,params,wallet,**kw)
   if method=='gettransaction' and wallet=='Wallaby Extinct':value=dict(value,hex=value['hex']+'00')
   return value
  with patch('retirement_evidence.rpc',side_effect=changed),self.assertRaisesRegex(ValueError,'differ'):owner.review(key)
 def test_unrelated_local_archive_cannot_suppress_preserved_elsewhere_confirmation(self):
  owner,p,key=self.prepare();rpc(self.core,'unloadwallet',['Wallaby Extinct']);rpc(self.core,'createwallet',{'wallet_name':'Unrelated','disable_private_keys':True,'blank':True})
  from retirement_evidence import compare
  e=compare(self.core,p,{'local_wallets':['Old']},['Unrelated']);self.assertFalse(e['verified'])
  with self.assertRaises(ValueError):owner.review(key)
  self.assertIn('Old',rpc(self.core,'listwallets'))

class Revocation(unittest.TestCase):
 def test_dismissed_request_cannot_reuse_approval_when_server_resends_it(self):
  import tempfile
  from lifecycle_preferences import cancel
  from test_build7 import public
  p={'kind':'wallet_retire','version':3,'phase':'preserve','public_wallet':public('Old'),'manifest_hash':'a'*64}
  key=digest(p)
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder)
   with store.edit() as s:s['pending'][key]={'state':'pending','proposal':p};s['retirement_continuations']={key:{'state':'authorised','manifest_hash':p['manifest_hash']}}
   cancel(store,key)
   with store.edit() as s:s['pending'][key]={'state':'pending','proposal':p}
   with patch('wallet_retirement.Retirement.approve',side_effect=AssertionError('Dismissed authorisation reused')):finish(object(),store)
   self.assertNotIn(key,store.read()['retirement_continuations'])

class NamedArchive(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 def test_extinct_watch_name_is_upgraded_and_preserved_without_renaming_it(self):
  from pathlib import Path
  from retirement_phases import imports
  imports(self.core,self.p)
  rpc(self.core,'unloadwallet',['Wallaby Extinct'])
  base=Path(self.core.config['cookie']).parent/'wallets';(base/'Wallaby Extinct').rename(base/'extinct_watch')
  rpc(self.core,'loadwallet',['extinct_watch'])
  p=proposal(self.raw,self.p['manifest'],'preserve','extinct_watch');key=digest(p);self.store.receive(p)
  from extinct_upgrade import upgrade
  upgrade(self.core,self.store,'extinct_watch')
  owner=Retirement(self.core,self.store);owner.review(key);owner.approve(key)
  from extinct_upgrade import status
  self.assertFalse(status(self.core,'extinct_watch')['required']);self.assertTrue(self.store.read()['completed'][key]['result']['history_verified']);self.assertIn('Old',rpc(self.core,'listwallets'));self.assertIn('extinct_watch',rpc(self.core,'listwallets'))
 def test_helper_rejects_private_and_ranged_watch_databases_without_changing_them(self):
  import tempfile,os,hashlib
  from pathlib import Path
  from archive_swap import public_archive
  rpc(self.core,'createwallet',{'wallet_name':'Ranged watch','disable_private_keys':True,'blank':True})
  rpc(self.core,'importdescriptors',[[dict(d,timestamp='now') for d in self.raw['descriptors']]],'Ranged watch')
  with tempfile.TemporaryDirectory() as folder:
   for i,name in enumerate(('Old','Ranged watch')):
    file=Path(folder)/str(i);rpc(self.core,'backupwallet',[str(file)],name);before=hashlib.sha256(file.read_bytes()).digest();fd=os.open(file,os.O_RDONLY)
    try:
     with self.assertRaises(ValueError):public_archive(fd)
    finally:os.close(fd)
    self.assertEqual(hashlib.sha256(file.read_bytes()).digest(),before)

class DataStage(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 legacy=fixture77.WholeArchive.legacy
 def test_existing_original_and_archive_records_advance_without_rescan_or_scan_claim(self):
  from retirement_phases import imports
  from extinct_upgrade import status
  self.legacy();imports(self.core,self.p)
  owner=Retirement(self.core,self.store);real=rpc
  def pruned(core,method,params=None,wallet=None,**kw):
   value=real(core,method,params,wallet,**kw)
   return dict(value,pruned=True,pruneheight=100) if method=='getblockchaininfo' else value
  with patch('extinct_upgrade.rpc',side_effect=pruned),patch('retirement_phases.imports',side_effect=AssertionError('Existing data must not import again')),patch('wallet_recovery.Recovery.register_watch_history',side_effect=AssertionError('Existing data must not rescan')):
   self.assertTrue(status(self.core,'Wallaby Extinct')['required'])
   f=owner.review(self.key)['retirement'];self.assertEqual(f['phase'],'preserved');self.assertTrue(f['history_comparison']['verified'])
   # Reporting this wallet's already-matching records must not invent global
   # provenance for unrelated legacy entries.
   self.assertTrue(status(self.core,'Wallaby Extinct')['required'])
  saved=self.store.read();self.assertTrue(saved['completed'][self.key]['result']['history_verified']);self.assertFalse(saved.get('history_jobs'));self.assertIn('Old',rpc(self.core,'listwallets'))
