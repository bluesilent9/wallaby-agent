"""Reserved receiving index is request-bound, locally derived, and Core checked."""
import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch
from approval_store import digest
from policy_refresh import Refresh,validate,verify_receiving_address,transition
from vendor.embit.descriptor import Descriptor
from vendor.embit.networks import NETWORKS
from wallet_ops import rpc

class AddressComparison(unittest.TestCase):
 def setUp(self):
  from test_build58 import Receipt
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.p=copy.deepcopy(f.p);self.store=f.store
 def address(self,index=15,branch=0):
  return Descriptor.from_string(self.p['receive_descriptor' if branch==0 else 'change_descriptor']).derive(index).address(NETWORKS['regtest'])
 def bound(self,index=15):
  p=copy.deepcopy(self.p);p['receiving_address']={'index':index,'address':self.address(index)};return p
 def test_reserved_address_is_bound_to_request_but_not_a_new_policy(self):
  p=self.bound();self.assertEqual(validate(p),p);self.assertNotEqual(digest(p),digest(self.p));self.assertEqual(transition(p),transition(self.p))
 def test_wrong_address_or_branch_or_index_is_rejected(self):
  for value in (self.address(0),self.address(15,1),'not-an-address'):
   p=self.bound();p['receiving_address']['address']=value
   with self.assertRaises(ValueError):validate(p)
 def test_invalid_index_and_unknown_fields_rejected(self):
  for value in (True,-1,1000,'15',15.0):
   p=self.bound();p['receiving_address']['index']=value
   with self.assertRaises(ValueError):validate(p)
  for value in ({'index':15},{'index':15,'address':self.address(),'change_index':15},None):
   p=self.bound();p['receiving_address']=value
   with self.assertRaises(ValueError):validate(p)
 def test_core_disagreement_refuses_review(self):
  with patch('policy_refresh.rpc',return_value=[self.address(0)]):
   with self.assertRaisesRegex(ValueError,'differs from Core'):verify_receiving_address(self.bound(),object())
 def review(self,p,core=None):
  def call(_,method,params=None,wallet=None,**kw):
   if method=='getblockchaininfo':return {'chain':'regtest'}
   if method=='listdescriptors':return {'wallet_name':p['wallet'],'descriptors':[{'desc':d} for d in p['previous_descriptors']]}
   if method=='getaddressinfo':return {'labels':[]}
   if method=='getdescriptorinfo':return {'hasprivatekeys':False}
   if method=='deriveaddresses':return [Descriptor.from_string(params[0]).derive(params[1][0]).address(NETWORKS['regtest'])]
   if method=='scantxoutset':return {'success':True,'unspents':[]}
   raise AssertionError(method)
  manager=Refresh(core or object(),self.store,SimpleNamespace(loaded={}))
  with patch('vault_time.estimates',return_value=[]):
   if core:return manager.review_single(digest(p),p)
   with patch('policy_refresh.rpc',side_effect=call):return manager.review_single(digest(p),p)
 def test_receive_and_change_start_at_reserved_index(self):
  f=self.review(self.bound())['refresh'];self.assertEqual(f['sample_start_index'],15)
  self.assertEqual([(r['branch'],r['index']) for r in f['samples']],[(b,i) for b in ('Receive','Change') for i in (15,16,17)])
  self.assertEqual(f['receiving_address']['address'],self.address());self.assertEqual(f['samples'][3]['address'],self.address(15,1))
 def test_boundaries_do_not_wrap(self):
  for index in (0,998,999):
   f=self.review(self.bound(index))['refresh'];self.assertEqual([r['index'] for r in f['samples'] if r['branch']=='Receive'],list(range(index,min(index+3,1000))))
 def test_legacy_samples_still_valid_and_not_claimed_as_reserved(self):
  self.assertEqual(validate(self.p),self.p);f=self.review(self.p)['refresh'];self.assertNotIn('receiving_address',f);self.assertEqual(f['sample_start_index'],0)
 def test_live_core_review_uses_nonzero_index_on_both_branches(self):
  from regtest_support import Regtest
  node=Regtest();self.addCleanup(node.close)
  from vendor.embit.descriptor.checksum import checksum
  rpc(node.core,'createwallet',{'wallet_name':'fixture-source'})
  raw=rpc(node.core,'listdescriptors',[False],'fixture-source')['descriptors'];pairs=[]
  for height in (100,200):
   pair=[]
   for branch in (0,1):
    source=next(r['desc'].split('#')[0][5:-1] for r in raw if r.get('active') and bool(r.get('internal'))==bool(branch) and r['desc'].startswith('wpkh('))
    body='wsh(and_v(v:after('+str(height)+'),pk('+source+')))';pair.append(body+'#'+checksum(body))
   pairs.append(pair)
  self.p.update(previous_descriptors=pairs[0],receive_descriptor=pairs[1][0],change_descriptor=pairs[1][1]);p=self.bound()
  rpc(node.core,'createwallet',{'wallet_name':p['wallet'],'disable_private_keys':True,'blank':True,'descriptors':True})
  rpc(node.core,'importdescriptors',[[{'desc':d,'timestamp':'now','range':[0,999],'active':True,'internal':bool(i)} for i,d in enumerate(p['previous_descriptors'])]],p['wallet'])
  f=self.review(p,node.core)['refresh'];self.assertEqual(len(f['samples']),6)
  for row in f['samples']:
   desc=p['receive_descriptor' if row['branch']=='Receive' else 'change_descriptor']
   self.assertEqual(rpc(node.core,'deriveaddresses',[desc,[row['index'],row['index']]]),[row['address']])
  # An unapproved generation has no Core or disc mutation to perform: keep
  # the required fresh funding proof, but run no redundant follow-up scans.
  from policy_refresh_cancel import review,confirm
  original=digest(p);self.store.receive(p)
  cancel={'kind':'builder_cancel','version':1,'builder':'wallet','workspace_id':'d'*32,'cancellation_id':'e'*32,'operations':[],'request_hashes':[original],'require_local_authorisation':True,'backup_option':True,'request_id':'f'*64};key=digest(cancel)
  with self.store.edit() as state:state['pending'][key]={'proposal':cancel,'state':'pending'}
  c=SimpleNamespace(store=self.store,core=node.core,reviews={},ops=SimpleNamespace(prepared={}),setup=SimpleNamespace(burner=SimpleNamespace(thread=None)),archives=None)
  rpc(node.core,'generatetoaddress',[101,rpc(node.core,'getnewaddress',[],'fixture-source')])
  review(c,key)
  with patch('policy_refresh_cancel.rpc',wraps=rpc) as calls:confirm(c,key,'delete')
  self.assertEqual(sum(call.args[1]=='scantxoutset' for call in calls.call_args_list),1)
  self.assertNotIn(key,self.store.read()['pending'])

class UnstartedCancellation(unittest.TestCase):
 def setUp(self):
  from test_build58 import Receipt
  from policy_refresh_cancel import review
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.store=f.store;self.p=f.p;self.original=digest(self.p);self.store.receive(self.p)
  p={'kind':'builder_cancel','version':1,'builder':'wallet','workspace_id':'a'*32,'cancellation_id':'b'*32,'operations':[],'request_hashes':[self.original],'require_local_authorisation':True,'backup_option':True,'request_id':'c'*64};self.key=digest(p)
  with self.store.edit() as state:state['pending'][self.key]={'proposal':p,'state':'pending'}
  self.c=SimpleNamespace(store=self.store,core=object(),ops=SimpleNamespace(prepared={}),reviews={})
  self.f={'builder':'wallet','policy_refresh':True,'policies':[{'request_hash':self.original,'wallets':[{'wallet':'primary','installed':False}]}],'funded':False,'discs':[],'active_disc_write':False}
  with patch('policy_refresh_cancel.facts',return_value=copy.deepcopy(self.f)):review(self.c,self.key)
 def test_one_fresh_funding_check_and_no_mutation_for_uninstalled_policy(self):
  from policy_refresh_cancel import confirm
  with patch('policy_refresh_cancel.facts',return_value=copy.deepcopy(self.f)) as check,patch('policy_refresh_cancel.wallets',return_value=[{'wallet':'primary','installed':False}]),patch('policy_refresh_cancel.rpc',side_effect=AssertionError('No wallet mutation permitted')):
   confirm(self.c,self.key,'delete');self.assertEqual(check.call_count,1)
  self.assertNotIn(self.key,self.store.read()['pending']);self.assertNotIn(self.original,self.store.read()['pending'])
 def test_new_installation_or_funding_refuses_shortcut(self):
  from policy_refresh_cancel import confirm
  with patch('policy_refresh_cancel.facts',return_value=copy.deepcopy(self.f)),patch('policy_refresh_cancel.wallets',return_value=[{'wallet':'primary','installed':True}]):
   with self.assertRaisesRegex(ValueError,'installation changed'):confirm(self.c,self.key,'delete')
  self.assertIn(self.key,self.store.read()['pending'])
  f=copy.deepcopy(self.f);f['funded']=True
  with patch('policy_refresh_cancel.facts',return_value=f):
   with self.assertRaisesRegex(ValueError,'funded'):confirm(self.c,self.key,'delete')
  self.assertIn(self.key,self.store.read()['pending'])
