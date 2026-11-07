"""Real-Core preservation barrier, deletion-only cold nodes and mixed-disc guards."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement,inventory
from retirement_phases import validate,require_current
from regtest_support import Regtest
from setup_messages import sign
from wallet_preview import fingerprint
from wallet_deletion import remove
from test_build7 import public

def proposal(raw,history,phase,wallet,targets=None,proof=None,operation='a'*64):
 p={'kind':'wallet_retire','version':3,'operation_id':operation,'phase':phase,'wallet':wallet,'public_wallet':raw,'archive_label':'Historical source','require_zero_balance':True,'delete_wallet':phase=='delete','nonce':'b'*64,'manifest':history,'manifest_hash':digest(history),'delete_wallets':targets or [],'preservation':proof};p['request_id']=digest(p);return p

def legacy(raw,targets,wallet='Old'):
 p={'kind':'wallet_retire','version':2,'wallet':wallet,'public_wallet':raw,'archive_label':'Historical source','require_zero_balance':True,'delete_wallet':True,'nonce':'c'*64,'delete_wallets':targets};p['request_id']=digest(p);return p

class RealPhasedRetirement(unittest.TestCase):
 def test_real_preserve_then_delete_cold_watch_and_private_with_no_archive_creation(self):
  source=Regtest();self.addCleanup(source.close);cold=Regtest();self.addCleanup(cold.close);core=source.core;remote=cold.core
  with tempfile.TemporaryDirectory() as folder:
   store=Store(Path(folder)/'source');other=Store(Path(folder)/'cold');rpc(core,'createwallet',{'wallet_name':'Old'});rpc(core,'createwallet',{'wallet_name':'Destination'});address=rpc(core,'getnewaddress',[],'Old');dest=rpc(core,'getnewaddress',[],'Destination');rpc(core,'generatetoaddress',[1,address]);rpc(core,'generatetoaddress',[101,dest]);rpc(core,'sendall',{'recipients':[dest]},'Old');rpc(core,'generatetoaddress',[1,dest]);raw=rpc(core,'listdescriptors',[False],'Old')
   def blocks():
    for h in range(rpc(remote,'getblockcount')+1,rpc(core,'getblockcount')+1):rpc(remote,'submitblock',[rpc(core,'getblock',[rpc(core,'getblockhash',[h]),0])])
   blocks();rpc(remote,'createwallet',{'wallet_name':'Watch','disable_private_keys':True,'blank':True});rpc(remote,'importdescriptors',[[dict(d,timestamp=0) for d in raw['descriptors']]],'Watch')
   targets=[{'wallet':'Old','public_wallet':raw,'private_keys_enabled':True}]
   def history():
    facts=inventory(core,store,legacy(raw,targets),collect_only=True);return {'addresses':[{k:r[k] for k in ('address','label')} for r in facts['addresses']],'transactions':facts['transaction_records']}
   p=proposal(raw,history(),'preserve','Wallaby Extinct');key=digest(p);store.receive(p);ret=Retirement(core,store)
   with self.assertRaisesRegex(ValueError,'existing Extinct'):ret.review(key)
   self.assertNotIn('Wallaby Extinct',rpc(core,'listwallets'))
   rpc(core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True})
   self.assertTrue(rpc(core,'getwalletinfo',[],'Wallaby Extinct')['wallaby_extinct']);self.assertNotIn('wallaby_extinct',rpc(core,'getwalletinfo',[],'Destination'))
   ret.review(key)
   with patch('wallet_deletion.delete',side_effect=AssertionError('Preserve must never delete')):ret.approve(key)
   first=store.read()['completed'][key]['result'];self.assertFalse(first['wallet_deleted']);self.assertEqual(first['deleted_wallets'],[]);self.assertIn('Old',rpc(core,'listwallets'))
   def proof(p,key,result):return {'node_id':'1'*32,'request_hash':key,'archive_wallet':'Wallaby Extinct','manifest_hash':p['manifest_hash'],'verified_utc':'2026-11-03T00:00:00Z','receipt':result['archive_receipt']}
   coldtargets=[{'wallet':'Watch','public_wallet':rpc(remote,'listdescriptors',[False],'Watch'),'private_keys_enabled':False}]
   deletion=proposal(raw,p['manifest'],'delete','Watch',coldtargets,proof(p,key,first));other.receive(deletion);r=Retirement(remote,other);k=digest(deletion);facts=r.review(k)['retirement'];pin=facts['preservation_fingerprint']
   self.assertTrue(facts['history_elsewhere_confirmation_required']);self.assertEqual(facts['local_extinct_wallets'],[])
   with self.assertRaisesRegex(ValueError,'No Extinct wallet'):r.approve(k,pin)
   self.assertEqual(other.read()['pending'][k]['state'],'pending')
   with self.assertRaisesRegex(ValueError,'fingerprint'):r.approve(k)
   # A new unconfirmed deposit is sufficient to stop a reviewed deletion.
   txid=rpc(core,'sendtoaddress',[address,'0.01'],'Destination');tx=rpc(core,'gettransaction',[txid], 'Destination');rpc(remote,'sendrawtransaction',[tx['hex']])
   with self.assertRaisesRegex(ValueError,'contains funds'):r.approve(k,pin)
   self.assertIn('Watch',rpc(remote,'listwallets'));self.assertNotIn('Wallaby Extinct',rpc(remote,'listwallets'))
   rpc(core,'generatetoaddress',[1,dest]);rpc(core,'sendall',{'recipients':[dest]},'Old');rpc(core,'generatetoaddress',[1,dest]);blocks()
   with self.assertRaisesRegex(ValueError,'manifest'):r.review(k)
   r.cancel_remote(k);self.assertEqual(other.read()['completed'][k]['result']['status'],'cancelled')
   # A deliberate fresh operation preserves the new complete history first.
   p=proposal(raw,history(),'preserve','Wallaby Extinct',operation='d'*64);key=digest(p);store.receive(p);ret.review(key);ret.approve(key);outcome=store.read()['completed'][key]['result'];saved=proof(p,key,outcome)
   for record in p['manifest']['transactions']:self.assertGreater(rpc(core,'gettransaction',[record['txid'],True],'Wallaby Extinct')['confirmations'],0)
   for record in p['manifest']['addresses']:self.assertEqual(rpc(core,'getaddressinfo',[record['address']],'Wallaby Extinct')['labels'],[record['label']])
   import os,subprocess,sys
   dashboard=os.environ.get('WALLABY_TEST_DASHBOARD_SRC')
   if dashboard:
    run=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('dashboard34_retirement_probe.py')),dashboard],input=json.dumps({'proposal':p,'result':outcome,'core':core.config}),text=True,capture_output=True,timeout=90)
    self.assertEqual(run.returncode,0,run.stderr);evidence=json.loads(run.stdout);self.assertTrue(all(evidence.values()));print('Dashboard/Agent live-Core preservation interoperability:',json.dumps(evidence),flush=True)
   deletion=proposal(raw,p['manifest'],'delete','Watch',coldtargets,saved,operation='d'*64);k=digest(deletion);other.receive(deletion);facts=r.review(k)['retirement']
   def local_remove(request):return remove(request,[Path(request['path']).parent])
   with patch('wallet_deletion.delete',side_effect=local_remove):r.approve(k,facts['preservation_fingerprint'],history_elsewhere_confirmed=True)
   self.assertNotIn('Watch',rpc(remote,'listwallets'));self.assertNotIn('Watch',[w['name'] for w in rpc(remote,'listwalletdir')['wallets']]);self.assertNotIn('Wallaby Extinct',[w['name'] for w in rpc(remote,'listwalletdir')['wallets']])
   deletion=proposal(raw,p['manifest'],'delete','Old',targets,saved,operation='d'*64);k=digest(deletion);store.receive(deletion);facts=ret.review(k)['retirement']
   with patch('wallet_deletion.delete',side_effect=local_remove):ret.approve(k,facts['preservation_fingerprint'])
   self.assertNotIn('Old',[w['name'] for w in rpc(core,'listwalletdir')['wallets']]);self.assertIn('Wallaby Extinct',rpc(core,'listwallets'));self.assertIn('Destination',rpc(core,'listwallets'))
   result=store.read()['completed'][k]['result'];self.assertNotIn('archive_wallet',result);self.assertTrue(result['zero_balance_verified']);self.assertEqual(result['deleted_wallets'],['Old'])
   # An archive-only holder verifies the public policy and real chain records,
   # without loading or recreating the retired private/watch wallet.
   rpc(remote,'createwallet',{'wallet_name':'Existing Archive','disable_private_keys':True,'blank':True})
   public_request=proposal(raw,p['manifest'],'preserve','Existing Archive',operation='e'*64);pk=digest(public_request);other.receive(public_request);r.review(pk);r.approve(pk);self.assertEqual(rpc(remote,'listwallets'),['Existing Archive']);self.assertFalse(other.read()['completed'][pk]['result']['wallet_deleted'])
   # An old watch copy reappearing later gets a new nonce-bound request;
   # completion of the earlier deletion cannot hide or authorise this one.
   before_archive=rpc(remote,'listdescriptors',[False],'Existing Archive');rpc(remote,'createwallet',{'wallet_name':'Old_watch','disable_private_keys':True,'blank':True});rpc(remote,'importdescriptors',[[dict(d,timestamp=0) for d in raw['descriptors']]],'Old_watch')
   later_targets=[{'wallet':'Old_watch','public_wallet':rpc(remote,'listdescriptors',[False],'Old_watch'),'private_keys_enabled':False}];later=proposal(raw,p['manifest'],'delete','Old_watch',later_targets,saved,operation='d'*64);later['nonce']='f'*64;later['request_id']=digest({k:v for k,v in later.items() if k!='request_id'});lk=digest(later);self.assertTrue(other.receive(later));r.review(lk)
   with patch('wallet_deletion.delete',side_effect=local_remove):r.approve(lk,pin,history_elsewhere_confirmed=True)
   self.assertNotIn('Old_watch',[w['name'] for w in rpc(remote,'listwalletdir')['wallets']]);self.assertEqual(rpc(remote,'listdescriptors',[False],'Existing Archive'),before_archive);self.assertFalse(other.receive(later))

class PhaseSchema(unittest.TestCase):
 def test_extra_dashboard_history_requires_independent_policy_and_chain_verification(self):
  from retirement_phases import review
  p={'phase':'preserve','wallet':'Archive','public_wallet':{'wallet_name':'Old'},'manifest':{'addresses':[{'address':'unproven','label':'Old'}],'transactions':[]},'manifest_hash':'fixture'}
  with patch('retirement_phases.validate'),patch('retirement_phases.check_chain',return_value={'blocks':1}),patch('retirement_phases.existing_archive'),patch('retirement_phases.readback',side_effect=ValueError('Archive not complete')),patch('retirement_phases.local_facts',return_value={'addresses':[],'transaction_records':[]}),patch('retirement_phases.verify_public',side_effect=ValueError('unproven policy')) as verify:
   with self.assertRaisesRegex(ValueError,'unproven policy'):review(Mock(),Mock(),p)
   verify.assert_called_once()
 def test_attempted_extinction_cannot_be_relabelled_as_an_unstarted_denial(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);key='f'*64
   with store.edit() as s:s['pending'][key]={'proposal':{'kind':'wallet_retire','version':3},'state':'attempted'}
   with self.assertRaisesRegex(ValueError,'uncertain'):store.deny(key)
   self.assertEqual(store.read()['pending'][key]['state'],'attempted');self.assertFalse(store.read()['outbox'])
 def test_obsolete_combined_requests_are_not_current_protocol(self):
  with self.assertRaisesRegex(ValueError,'obsolete'):require_current({'version':2})
 def test_missing_or_forged_manifest_phase_and_target_are_rejected(self):
  history={'addresses':[{'address':'bcrt1q6smzg0e2cu4cyzz8pqk6tqsv2r3gv0hdqmhnyq','label':'Old'}],'transactions':[{'txid':'1'*64,'blockhash':'2'*64}]}
  # Use a valid address obtained from a descriptor, not a hard-coded checksum.
  from vendor.embit import ec,script
  history['addresses'][0]['address']=script.p2wpkh(ec.PrivateKey(b'\x01'*32).get_public_key()).address(__import__('vendor.embit.networks',fromlist=['NETWORKS']).NETWORKS['regtest'])
  p=proposal(public('Old'),history,'preserve','Wallaby Extinct');validate(p)
  for field,value in (('delete_wallet',True),('manifest_hash','0'*64),('preservation',{}),('delete_wallets',[{}])):
   bad=copy.deepcopy(p);bad[field]=value;bad['request_id']=digest({k:v for k,v in bad.items() if k!='request_id'})
   with self.assertRaises(ValueError):validate(bad)
 def test_cancel_and_deny_outcomes_carry_phase_and_exact_manifest(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);key='e'*64;p={'kind':'wallet_retire','version':3,'phase':'preserve','manifest_hash':'a'*64,'wallet':'Wallaby Extinct','public_wallet':public('Old')}
   with store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
   Retirement(Mock(),store).cancel_remote(key);result=next(iter(store.read()['outbox'].values()))['payload'];self.assertEqual(result['phase'],'preserve');self.assertEqual(result['manifest_hash'],'a'*64)
   with store.edit() as s:s['pending']['f'*64]={'proposal':p,'state':'pending'}
   store.deny('f'*64);self.assertTrue(any(i['payload'].get('status')=='denied' and i['payload'].get('phase')=='preserve' for i in store.read()['outbox'].values()))

if __name__=='__main__':unittest.main()

class MixedDiscRetirement(unittest.TestCase):
 def setUp(self):
  from archive_inventory import member
  from archive_format import identity
  from archive_operations import Operations
  from vendor.embit import ec
  from vendor.embit.descriptor.checksum import checksum
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name);self.store=Store(root/'agent');self.peer=Store(root/'preserver');records=[]
  for i,n in enumerate(('Retired','Current'),1):
   body='wpkh('+ec.PrivateKey(bytes([i])*32).get_public_key().sec().hex()+')';raw={'wallet_name':n,'descriptors':[{'desc':body+'#'+checksum(body),'timestamp':0}]};r={'version':1,'kind':'node_wallet','chain':'regtest','name':n,'policy_hash':digest(raw),'public_wallet':raw,'labels':[]};records.append(r)
  self.old,self.current=records;catalog={identity(r):r for r in records};self.archive='c'*64;inventory=sign(self.store,{'version':1,'event':'archive_observed','archive_id':self.archive,'payload_sha256':self.archive,'payload_verified':True,'readback_verified':False,'replacements':[],'members':[member(r) for r in records]});saved=sign(self.peer,{'version':1,'kind':'wallet_retirement_preservation','request_hash':'a'*64,'operation_id':'b'*64,'manifest_hash':'d'*64,'archive_wallet':'Wallaby Extinct','address_count':1,'wallet_deleted':False});preservation={'node_id':'1'*32,'request_hash':'a'*64,'archive_wallet':'Wallaby Extinct','manifest_hash':'d'*64,'verified_utc':'2026-11-03T00:00:00Z','receipt':saved}
  self.pin=fingerprint(saved['public_key']);self.p={'kind':'destroy_disc','version':2,'reason':'wallet_extinction','nonce':'e'*64,'operation_id':'b'*64,'archive_id':self.archive,'label':'Old retired disc','archive_inventory':inventory,'retired_wallet':self.old['public_wallet'],'retired_member_ids':[identity(self.old)],'manifest_hash':'d'*64,'preservation':preservation,'require_local_authorisation':True,'require_replacement_if_live_members':True,'require_verified_readback_before_destruction':True};self.p['request_id']=digest(self.p);self.key=digest(self.p);self.store.receive(self.p)
  staged={}
  for r in records:
   p=root/(r['name']+'.dat');p.write_bytes(b'fixture-encrypted-placeholder-not-a-wallet');staged[identity(r)]={'archive_id':self.archive,'recovery':r,'wallet':p}
  self.ops=SimpleNamespace(store=self.store,enforce=lambda:None,archives=SimpleNamespace(catalogs={self.archive:catalog},staged=staged,loaded={}),setup=SimpleNamespace(own_identity=lambda:{'public_key':inventory['public_key']},burner=SimpleNamespace(queue=Mock())),jobs={})
  self.ops.covers=lambda new,old:Operations.covers(self.ops,new,old)
 def test_mixed_disc_queues_only_current_member_and_blocks_destruction_until_readback(self):
  from extinct_discs import review,stage,completed,destroyed
  from archive_format import identity
  r=review(self.ops,self.key)['destruction'];self.assertTrue(r['replacement_required']);self.assertEqual(r['retired_members'],['Retired']);self.assertEqual(r['current_members'],['Current'])
  with self.assertRaisesRegex(ValueError,'verified replacement'):destroyed(self.ops,self.key,True,self.pin)
  with self.assertRaisesRegex(ValueError,'fingerprint'):stage(self.ops,self.key,True,'wrong')
  stage(self.ops,self.key,True,self.pin);self.assertEqual(self.ops.setup.burner.queue.call_count,1);self.assertEqual(next(iter(self.ops.jobs.values()))['recovery']['name'],'Current')
  completed(self.ops,{identity(self.old):self.old},'f'*64)
  with self.assertRaises(ValueError):destroyed(self.ops,self.key,True,self.pin)
  completed(self.ops,{identity(self.current):self.current},'f'*64);destroyed(self.ops,self.key,True,self.pin);self.assertIn(self.key,self.store.read()['completed']);out=[i['payload'] for i in self.store.read()['outbox'].values() if i['kind']=='archive_queue_result' and i['payload']['status']=='complete'][0];self.assertTrue(out['replacement_readback_verified']);self.assertEqual(out['replacement_image_sha256'],'f'*64)
 def test_dashboard_cannot_omit_current_member_or_swap_preservation_proof(self):
  from extinct_discs import proof
  p=copy.deepcopy(self.p);p['archive_inventory']['message']['members'].pop();p['request_id']=digest({k:v for k,v in p.items() if k!='request_id'})
  with self.assertRaises(ValueError):proof(self.ops,p)
  p=copy.deepcopy(self.p);p['preservation']['receipt']['message']['manifest_hash']='f'*64;p['request_id']=digest({k:v for k,v in p.items() if k!='request_id'})
  with self.assertRaises(ValueError):proof(self.ops,p)
 def test_shared_signer_with_another_policy_is_retained(self):
  from extinct_discs import proof
  from archive_format import identity
  from archive_inventory import member
  old=copy.deepcopy(self.old);old['public_policies']=self.current['public_wallet'];catalog=self.ops.archives.catalogs[self.archive];catalog[identity(old)]=old
  p=copy.deepcopy(self.p);p['archive_inventory']=sign(self.store,{'version':1,'event':'archive_observed','archive_id':self.archive,'payload_verified':True,'payload_sha256':self.archive,'readback_verified':False,'members':[member(r) for r in catalog.values()]});p['request_id']=digest({k:v for k,v in p.items() if k!='request_id'});facts=proof(self.ops,p);self.assertIn(identity(old),facts['current'])
 def test_only_retired_members_need_no_new_disc_but_still_require_local_confirmation(self):
  from extinct_discs import destroyed,proof
  from archive_format import identity
  from archive_inventory import member
  catalog={identity(self.old):self.old};self.ops.archives.catalogs[self.archive]=catalog;p=copy.deepcopy(self.p);p['archive_inventory']=sign(self.store,{'version':1,'event':'archive_observed','archive_id':self.archive,'payload_verified':True,'payload_sha256':self.archive,'readback_verified':False,'members':[member(self.old)]});p['request_id']=digest({k:v for k,v in p.items() if k!='request_id'});key=digest(p);self.store.receive(p);self.assertFalse(proof(self.ops,p)['current'])
  with self.assertRaises(ValueError):destroyed(self.ops,key,False,self.pin)
  destroyed(self.ops,key,True,self.pin);self.assertEqual(self.ops.setup.burner.queue.call_count,0)
