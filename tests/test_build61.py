"""Deletion-only nodes explicitly confirm preservation elsewhere; never bypass proof."""
import copy,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store
from retirement_phases import local_archives,review,approve

class LocalArchiveDetection(unittest.TestCase):
 def test_only_loaded_idle_address_only_watch_wallets_count(self):
  rows={'Source':{'descriptors':[{'desc':'not-address-only'}]},'Extinct':{'descriptors':[]},'Private Blank':{'descriptors':[]},'Scanning Archive':{'descriptors':[]}}
  def call(core,method,args=None,wallet=None):
   if method=='listwallets':return list(rows)
   if method=='listdescriptors':return rows[wallet]
   if method=='getwalletinfo':return {'private_keys_enabled':wallet=='Private Blank','scanning':wallet=='Scanning Archive'}
   raise AssertionError(method)
  with patch('retirement_phases.rpc',side_effect=call),patch('retirement_phases.address_only',side_effect=lambda raw:not raw['descriptors']):self.assertEqual(local_archives(object()),['Extinct'])
 def test_deletion_review_reports_archive_absence_from_local_core(self):
  p={'phase':'delete','manifest_hash':'manifest','preservation':{'archive_wallet':'Remote Extinct','node_id':'remote'}}
  with patch('retirement_phases.validate'),patch('retirement_phases.check_chain'),patch('retirement_phases.local_facts',side_effect=lambda *a:{}),patch('retirement_phases.receipt',return_value='SHA256:verified'),patch('retirement_evidence.compare',side_effect=lambda core,p,facts,names:{'verified':bool(names)}):
   for names,required in (([],True),(['Local Extinct'],False)):
    with patch('retirement_phases.local_archives',return_value=names):
     f=review(object(),object(),p);self.assertEqual(f['history_elsewhere_confirmation_required'],required);self.assertEqual(f['local_extinct_wallets'],names)

class LocalConsent(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.store=Store(Path(temp.name));self.key='a'*64;self.p={'kind':'wallet_retire','phase':'delete','manifest':{'addresses':[],'transactions':[]}};self.f={'blocks':1,'tip':'tip','addresses':[],'transaction_records':[],'deletion':[],'local_wallets':[],'retained_signers':[],'history_elsewhere_confirmation_required':True,'local_extinct_wallets':[],'preservation_fingerprint':'SHA256:verified'}
  with self.store.edit() as s:s['pending'][self.key]={'state':'pending','proposal':self.p};s['retirement_cancel_pending']={self.key:True}
  self.owner=SimpleNamespace(store=self.store,core=object(),reviews={self.key:(copy.deepcopy(self.f),time.time())},_cancel_result=Mock(return_value={'cancelled':True}))
 def attempt(self,confirmed=False,pin='SHA256:verified'):
  with patch('retirement_phases.validate',return_value=self.p),patch('retirement_phases.review',return_value=copy.deepcopy(self.f)):
   return approve(self.owner,self.key,pin,confirmed)
 def test_absent_archive_warning_needs_no_additional_checkbox(self):
  for value in (None,1,'yes'):
   with self.assertRaises(ValueError):self.attempt(value)
   self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending')
  self.assertEqual(self.attempt(False),{'cancelled':True})
 def test_checkbox_does_not_replace_independent_agent_fingerprint(self):
  with self.assertRaisesRegex(ValueError,'fingerprint'):self.attempt(True,'SHA256:untrusted')
  self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending')
 def test_checkbox_does_not_replace_signed_receipt_and_chain_review(self):
  with patch('retirement_phases.validate',return_value=self.p),patch('retirement_phases.review',side_effect=ValueError('Invalid signed preservation proof')):
   with self.assertRaisesRegex(ValueError,'signed preservation'):approve(self.owner,self.key,'SHA256:verified',True)
  self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending')
 def test_existing_local_archive_needs_no_extra_checkbox(self):
  self.f.update(history_elsewhere_confirmation_required=False,local_extinct_wallets=['Extinct']);self.owner.reviews[self.key]=(copy.deepcopy(self.f),time.time())
  self.assertEqual(self.attempt(False),{'cancelled':True})
 def test_changed_archive_presence_requires_a_new_review(self):
  self.f.update(history_elsewhere_confirmation_required=False,local_extinct_wallets=['Newly Loaded Extinct'])
  with self.assertRaisesRegex(ValueError,'changed since review'):self.attempt(True)
  self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending')

class ProtectedAPI(unittest.TestCase):
 def setUp(self):
  from test_build31 import ProtectedCancellationAPI
  ProtectedCancellationAPI.setUp(self)
 def test_confirmation_reaches_protected_worker_and_cannot_be_omitted(self):
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   body={'id':'reviewed','fingerprint':'SHA256:verified','history_elsewhere_confirmed':True}
   status,result=self.fixture.call('/api/authorise/retire',body);self.assertEqual(status,200,result);self.assertEqual(call.call_args.args,('retirement.approve','reviewed','SHA256:verified',True))
   count=call.call_count;body.pop('history_elsewhere_confirmed');status,result=self.fixture.call('/api/authorise/retire',body);self.assertEqual(status,400);self.assertEqual(call.call_count,count)
