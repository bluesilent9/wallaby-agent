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
from regtest_support import Regtest

class ReadOnly(unittest.TestCase):
 def test_remote_catalogue_excludes_every_write_and_secret_operation(self):
  for method in 'createwallet importdescriptors walletpassphrase walletlock walletprocesspsbt sendall sendrawtransaction setlabel getnewaddress getrawchangeaddress loadwallet unloadwallet backupwallet dumpprivkey dumpwallet encryptwallet rescanblockchain lockunspent getblockfrompeer scantxoutset scanblocks getrpcinfo'.split():
   self.assertNotIn(method,METHODS)
   with self.assertRaises(ValueError):request(method,[],None)
  for p in ([True],{'private':True}):
   with self.assertRaises(ValueError):request('listdescriptors',p,'key wallet')
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
 def build(self,height=None):
  from vault_fixture import proposal
  return proposal(self.ops,self.source,self.dest,height)

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
 def test_remote_psbt_review_and_sign_for_matured_vault(self):
  height=rpc(self.c,'getblockcount')+2
  from vault_fixture import fund
  r=self.build(height);fund(self.ops,self.source,'regtest-password',r['psbt']);rpc(self.c,'generatetoaddress',[1,self.miner])
  rpc(self.c,'generatetoaddress',[2,self.miner]);monitor=next(iter(self.store.read()['vaults'].values()))['monitor_wallet'];utxo=rpc(self.c,'listunspent',[0],monitor)[0]
  recipient=rpc(self.c,'getnewaddress',[],self.source)
  response=self.c.call('test-withdraw','walletcreatefundedpsbt',{'inputs':[{'txid':utxo['txid'],'vout':utxo['vout'],'sequence':4294967294}],'outputs':[{recipient:utxo['amount']}],'locktime':height,'options':{'add_inputs':False,'includeWatching':True,'replaceable':False,'subtractFeeFromOutputs':[0],'fee_rate':'2'}},monitor)
  self.assertNotIn('error',response,response);built=response['result']
  proposal={'kind':'sign_psbt_partial','request_id':'a'*64,'wallet':self.dest,'chain':'regtest','psbt':built['psbt']};self.store.receive(proposal);key=digest(proposal);review=self.ops.prepare_request(key);self.assertEqual(review['review']['fee_sats'],str(round(float(built['fee'])*100000000)))
  rpc(self.c,'generatetoaddress',[2,self.miner]);out=self.ops.sign(key,'regtest-password','partial',fee_ack=True);self.assertTrue(out['queued']);self.assertTrue(any(i['kind']=='partial_sign_result' for i in self.store.read()['outbox'].values()));self.assertNotIn(key,self.store.read()['pending'])
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
 def test_wrong_passphrase_can_be_reviewed_again_without_replaying_signing(self):
  r=self.build();proposal={'kind':'sign_psbt_partial','request_id':'a'*64,'wallet':self.source,'chain':'regtest','psbt':r['psbt']};self.store.receive(proposal);key=digest(proposal);self.ops.prepare_request(key)
  with self.assertRaises(ValueError):self.ops.sign(key,'incorrect-password','partial',fee_ack=True)
  self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertEqual(rpc(self.c,'getwalletinfo',[],self.source)['unlocked_until'],0)
  self.ops.prepare_request(key);out=self.ops.sign(key,'regtest-password','partial',fee_ack=True);self.assertTrue(out['queued']);self.assertTrue(any(i['kind']=='partial_sign_result' for i in self.store.read()['outbox'].values()))
