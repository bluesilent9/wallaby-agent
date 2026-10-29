import copy,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from agent_rpc import METHODS,request
from agent_exchange import Exchange
from node_client import HTTPFailure
from vault_policy import public_vault
from wallet_ops import WalletOps,rpc
from block_clock import calculate,poisson_cdf_left
from regtest_support import Regtest

class ReadOnly(unittest.TestCase):
 def test_remote_catalogue_excludes_every_write_and_secret_operation(self):
  for method in 'createwallet importdescriptors walletpassphrase walletlock walletprocesspsbt sendall sendrawtransaction setlabel getnewaddress getrawchangeaddress loadwallet unloadwallet backupwallet dumpprivkey dumpwallet encryptwallet rescanblockchain lockunspent getblockfrompeer scantxoutset scanblocks getrpcinfo'.split():
   self.assertNotIn(method,METHODS)
   with self.assertRaises(ValueError):request(method,[],None)
  for p in ([True],{'private':True}):
   with self.assertRaises(ValueError):request('listdescriptors',p,'key wallet')
 def test_exact_quantile_precedes_target_and_next_candidate_fails(self):
  now=datetime(2026,10,28,tzinfo=timezone.utc);r=calculate(970000,'2026-12-01','Australia/Sydney',now)
  self.assertLessEqual(datetime.fromisoformat(r['confidence_utc']),datetime.fromisoformat(r['target_utc']))
  seconds=(datetime.fromisoformat(r['confidence_utc'])-now).total_seconds();k=r['required_new_blocks']
  self.assertAlmostEqual(1-poisson_cdf_left(k-1,seconds/600),.99,places=8)
  mean=r['expected_blocks'];self.assertLess(1-poisson_cdf_left(k,mean),.99)
 def test_legacy_dashboard_keeps_outbox_without_downgrading_rpc_session(self):
  with tempfile.TemporaryDirectory() as root:
   s=Store(root);s.queue('vault_public',{'test':'public-only'});e=Exchange(1,'fake-test-token',s)
   with patch('agent_exchange.http_json',side_effect=HTTPFailure(404)):e.once();e.once()
   self.assertTrue(e.unsupported);self.assertEqual(len(s.read()['outbox']),1)

@unittest.skipUnless(Path(os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind')).exists(),'Set WALLABY_TEST_BITCOIND to official Core 31 binary for isolated regtest.')
class RealCoreVault(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.node=Regtest();cls.c=cls.node.core;cls.temp=tempfile.TemporaryDirectory();cls.counter=0
  rpc(cls.c,'createwallet',{'wallet_name':'miner'});cls.miner=rpc(cls.c,'getnewaddress',[],'miner');rpc(cls.c,'generatetoaddress',[105,cls.miner])
 @classmethod
 def tearDownClass(cls):cls.node.close();cls.temp.cleanup()
 def setUp(self):
  type(self).counter+=1;self.source='source '+str(self.counter);self.dest='destination '+str(self.counter)
  for n in (self.source,self.dest):rpc(self.c,'createwallet',{'wallet_name':n,'passphrase':'regtest-password'})
  for amount in ('0.6','0.4'):rpc(self.c,'sendtoaddress',[rpc(self.c,'getnewaddress',[],self.source),amount],'miner')
  rpc(self.c,'generatetoaddress',[1,self.miner]);self.store=Store(Path(self.temp.name)/str(self.counter));self.ops=WalletOps(self.c,self.store)
 def build(self):
  day=(datetime.now()+timedelta(days=30)).date().isoformat()
  return self.ops.build(self.source,self.dest,'2',day,'Australia/Sydney')
 def test_full_sweep_local_sign_broadcast_and_relock(self):
  before=rpc(self.c,'listunspent',[0],self.source);mempool=rpc(self.c,'getrawmempool');r=self.build()
  self.assertEqual(len(r['review']['inputs']),len(before));self.assertEqual(len(r['review']['outputs']),1)
  self.assertEqual(rpc(self.c,'getrawmempool'),mempool);self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
  out=self.ops.sign(r['id'],'regtest-password','broadcast');self.assertIn(out['txid'],rpc(self.c,'getrawmempool'))
  self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
  with self.assertRaises(ValueError):self.ops.sign(r['id'],'regtest-password','broadcast')
  self.assertTrue(self.store.read()['outbox']);self.assertTrue(next(v for v in self.ops.list_wallets()['wallets'] if v['name']==self.dest)['active_vault'])
 def test_export_is_unsigned_immutable_and_never_broadcast(self):
  r=self.build();before=rpc(self.c,'getrawmempool');out=self.ops.sign(r['id'],'regtest-password','transaction_builder')
  self.assertTrue(out['queued']);self.assertEqual(rpc(self.c,'getrawmempool'),before)
  items=list(self.store.read()['outbox'].values());item=next(x for x in items if x['kind']=='transaction_builder_psbt')['payload']
  self.assertTrue(item['immutable']);self.assertEqual(item['stage'],2);self.assertFalse(rpc(self.c,'finalizepsbt',[item['psbt']])['complete']);self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
 def test_changed_wallet_inputs_require_new_review(self):
  r=self.build();rpc(self.c,'sendtoaddress',[rpc(self.c,'getnewaddress',[],self.source),'0.1'],'miner');rpc(self.c,'generatetoaddress',[1,self.miner])
  with self.assertRaisesRegex(ValueError,'inputs changed'):self.ops.sign(r['id'],'regtest-password','broadcast')
 def test_denial_content_hash_survives_restart_and_deletion_rearms(self):
  r=self.build();self.store=Store(Path(self.temp.name)/(str(self.counter)+'-peer'));self.ops.store=self.store;p={'kind':'vault_sync','vault':r['vault']};self.assertTrue(self.store.receive(p));key=digest(p);self.store.deny(key)
  restored=Store(self.store.root);self.assertFalse(restored.receive(copy.deepcopy(p)));restored.forget(key);self.assertTrue(restored.receive(p))
  review=self.ops.prepare_request(key);self.assertEqual(review['proof']['address'],r['vault']['address']);self.ops.approve_sync(key)
  self.assertNotIn(key,self.store.read()['pending']);self.assertFalse(self.store.receive(p))
 def test_tampered_vault_address_height_private_key_and_bypass_rejected(self):
  r=self.build()
  for field,value in [('address','bcrt1qbad'),('height',r['vault']['height']+1),('descriptor',r['vault']['source']['descriptor'])]:
   v=copy.deepcopy(r['vault']);v[field]=value
   with self.assertRaises(ValueError):public_vault(v)
 def test_locked_or_immature_funds_cannot_be_silently_omitted(self):
  u=rpc(self.c,'listunspent',[],self.source)[0];rpc(self.c,'lockunspent',[False,[{'txid':u['txid'],'vout':u['vout']}]],self.source)
  with self.assertRaisesRegex(ValueError,'whole wallet'):self.build()
 def test_remote_psbt_review_and_sign_for_matured_vault(self):
  height=rpc(self.c,'getblockcount')+2
  from block_clock import calculate as clock
  def near(h,d,z):
   r=clock(h,d,z);r['height']=height;return r
  with patch('wallet_ops.calculate',side_effect=near):r=self.build()
  self.ops.sign(r['id'],'regtest-password','broadcast');rpc(self.c,'generatetoaddress',[1,self.miner])
  rpc(self.c,'generatetoaddress',[2,self.miner]);monitor=next(iter(self.store.read()['vaults'].values()))['monitor_wallet'];utxo=rpc(self.c,'listunspent',[0],monitor)[0]
  recipient=rpc(self.c,'getnewaddress',[],self.source)
  response=self.c.call('test-withdraw','walletcreatefundedpsbt',{'inputs':[{'txid':utxo['txid'],'vout':utxo['vout'],'sequence':4294967294}],'outputs':[{recipient:utxo['amount']}],'locktime':height,'options':{'add_inputs':False,'includeWatching':True,'replaceable':False,'subtractFeeFromOutputs':[0],'fee_rate':'2'}},monitor)
  self.assertNotIn('error',response,response);built=response['result']
  proposal={'kind':'sign_psbt_partial','request_id':'a'*64,'wallet':self.dest,'chain':'regtest','psbt':built['psbt']};self.store.receive(proposal);key=digest(proposal);review=self.ops.prepare_request(key);self.assertEqual(review['review']['fee_sats'],str(round(float(built['fee'])*100000000)))
  rpc(self.c,'generatetoaddress',[2,self.miner]);out=self.ops.sign(key,'regtest-password','partial');self.assertTrue(out['queued']);self.assertTrue(any(i['kind']=='partial_sign_result' for i in self.store.read()['outbox'].values()));self.assertNotIn(key,self.store.read()['pending'])
 def test_forged_psbt_input_amount_and_weak_sighash_are_rejected(self):
  import base64,io,struct
  r=self.build();raw=base64.b64decode(r['psbt']);value=int(r['review']['inputs'][0]['sats']);needle=struct.pack('<Q',value)
  self.assertGreaterEqual(raw.count(needle),1)
  forged=base64.b64encode(raw.replace(needle,struct.pack('<Q',value+10000),1)).decode()
  with self.assertRaises(ValueError):self.ops.review(forged,self.source,'regtest')
  def compact(f):
   first=f.read(1)[0]
   if first<253:return first
   return int.from_bytes(f.read({253:2,254:4,255:8}[first]),'little')
  f=io.BytesIO(raw);f.seek(5)
  for scope in range(2):
   while True:
    start=f.tell();length=compact(f)
    if not length:break
    f.read(length);f.read(compact(f))
  weak=raw[:start]+b'\x01\x03\x04\x02\x00\x00\x00'+raw[start:]
  with self.assertRaises(ValueError):self.ops.review(base64.b64encode(weak).decode(),self.source,'regtest')
 def test_address_only_watch_wallet_not_a_vault_destination(self):
  name='address-only '+str(self.counter);rpc(self.c,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True})
  address=rpc(self.c,'getnewaddress',[],self.dest);desc=rpc(self.c,'getdescriptorinfo',['addr('+address+')'])['descriptor']
  rpc(self.c,'importdescriptors',{'requests':[{'desc':desc,'timestamp':'now'}]},name)
  self.assertFalse(next(w for w in self.ops.list_wallets()['wallets'] if w['name']==name)['destination'])
 def test_inactive_public_descriptor_watch_wallet_is_valid_destination(self):
  name='public-watch '+str(self.counter);rpc(self.c,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True})
  desc=rpc(self.c,'listdescriptors',{'private':False},self.dest)['descriptors'][0]['desc']
  rpc(self.c,'importdescriptors',{'requests':[{'desc':desc,'timestamp':'now','range':[0,10],'active':False}]},name)
  self.assertTrue(next(w for w in self.ops.list_wallets()['wallets'] if w['name']==name)['destination'])

 def test_builder_can_roll_matured_vault_monitors_into_new_vault(self):
  height=rpc(self.c,'getblockcount')+2
  from block_clock import calculate as clock
  def near(h,d,z):
   r=clock(h,d,z);r['height']=height;return r
  with patch('wallet_ops.calculate',side_effect=near):r=self.build()
  self.ops.sign(r['id'],'regtest-password','broadcast');rpc(self.c,'generatetoaddress',[3,self.miner])
  view=next(w for w in self.ops.list_wallets()['wallets'] if w['name']==self.dest);self.assertTrue(view['source']);self.assertGreater(int(view['balance_sats']),0)
  later=self.ops.build(self.dest,self.source,'2',(datetime.now()+timedelta(days=30)).date().isoformat(),'UTC')
  self.assertEqual(later['review']['locktime'],height)
  result=self.ops.sign(later['id'],'regtest-password','broadcast');self.assertIn(result['txid'],rpc(self.c,'getrawmempool'))

 def test_wrong_passphrase_can_be_reviewed_again_without_replaying_signing(self):
  r=self.build();proposal={'kind':'sign_psbt_partial','request_id':'a'*64,'wallet':self.source,'chain':'regtest','psbt':r['psbt']};self.store.receive(proposal);key=digest(proposal);self.ops.prepare_request(key)
  with self.assertRaises(ValueError):self.ops.sign(key,'incorrect-password','partial')
  self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
  self.ops.prepare_request(key);out=self.ops.sign(key,'regtest-password','partial');self.assertTrue(out['queued']);self.assertTrue(any(i['kind']=='partial_sign_result' for i in self.store.read()['outbox'].values()))
