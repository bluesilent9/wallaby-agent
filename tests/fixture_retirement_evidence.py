"""Carry local preservation consent through real recovery, then prove deletion evidence."""
import copy,time,unittest
from unittest.mock import patch
from approval_store import digest,Store
from wallet_ops import rpc
from wallet_retirement import Retirement
from wallet_recovery import Recovery
from retirement_continuation import finish
from retirement_phases import readback
import fixture_history_recovery as fixture62
import fixture_archive_upgrade as fixture77
from fixture_retirement import proposal

class AutomaticRecovery(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 legacy=fixture77.WholeArchive.legacy

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
  facts=owner.review(key)['retirement'];self.assertFalse(facts['history_comparison']['verified']);self.assertTrue(facts['history_elsewhere_confirmation_required'])
  self.assertIn('Old',rpc(self.core,'listwallets'))

class Revocation(unittest.TestCase):
 pass

class NamedArchive(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp

class DataStage(unittest.TestCase):
 setUp=fixture62.ExtinctionRecovery.setUp
 legacy=fixture77.WholeArchive.legacy
