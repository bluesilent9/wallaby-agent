"""Only a later Dashboard broadcast request publishes a complete transaction."""
import socket,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store,digest
from automatic_broadcast import Broadcasts
from wallet_ops import rpc

class Automatic(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(tmp.name);self.core=Mock();self.broadcasts=Broadcasts(self.core,self.store)
  self.p={'kind':'broadcast_transaction','request_id':'a'*64,'chain':'regtest','psbt':'fixture','txid':'b'*64};self.key=digest(self.p)
  with self.store.edit() as s:s['pending'][self.key]={'proposal':self.p,'state':'pending'}
  self.calls=[];self.known=False;self.complete=True;self.matches=True;self.allowed=True;self.uncertain=False
 def call(self,core,method,params=None,wallet=None,timeout=30):
  self.calls.append(method);self.assertIsNone(wallet)
  if method=='getblockchaininfo':return {'chain':'regtest'}
  if method=='finalizepsbt':return {'complete':self.complete,'hex':'signed-transaction'}
  if method=='decoderawtransaction':return {'txid':self.p['txid'] if self.matches else 'c'*64}
  if method=='getmempoolentry':
   if self.known:return {'vsize':100}
   raise ValueError('Not in mempool')
  if method=='getrawtransaction':raise ValueError('Not confirmed')
  if method=='testmempoolaccept':return [{'allowed':self.allowed}]
  if method=='sendrawtransaction':
   if self.uncertain:raise OSError('Lost response')
   return self.p['txid']
  raise AssertionError('Unexpected or private-wallet RPC: '+method)
 def run_broadcast(self):
  with patch('automatic_broadcast.rpc',side_effect=self.call),patch('activity_log.event'):return self.broadcasts.process(self.key)
 def test_exact_signed_tx_broadcasts_without_a_password_or_review_and_completes_once(self):
  with patch('wallet_setup.secret_dialog',side_effect=AssertionError('No prompt')):
   result=self.run_broadcast();self.assertEqual(result['status'],'broadcast');self.assertEqual(result['txid'],self.p['txid'])
   self.run_broadcast()
  self.assertEqual(self.calls.count('sendrawtransaction'),1);self.assertNotIn(self.key,self.store.read()['pending']);self.assertEqual(len(self.store.read()['outbox']),1)
 def test_unsigned_wrong_txid_or_core_refusal_never_sends(self):
  for flag in ('complete','matches','allowed'):
   setattr(self,flag,False);result=self.run_broadcast();self.assertEqual(result['status'],'error');self.assertNotIn('sendrawtransaction',self.calls)
   setattr(self,flag,True)
   with self.store.edit() as s:s['pending'][self.key]={'proposal':self.p,'state':'pending'}
 def test_uncertain_send_is_reported_and_never_repeated(self):
  self.uncertain=True;self.assertEqual(self.run_broadcast()['status'],'error');self.run_broadcast();self.assertEqual(self.calls.count('sendrawtransaction'),1);self.assertIn('uncertain',self.store.read()['completed'][self.key]['message'])
 def test_already_in_mempool_is_confirmed_without_another_send(self):
  self.known=True;self.assertEqual(self.run_broadcast()['status'],'broadcast');self.assertNotIn('sendrawtransaction',self.calls)
 def test_signing_request_alone_never_triggers_a_broadcast(self):
  with self.store.edit() as s:s['pending']={self.key:{'proposal':{'kind':'sign_psbt_partial'},'state':'pending'}}
  with patch('automatic_broadcast.rpc',side_effect=AssertionError('Signing must not broadcast')):self.broadcasts.start()
  self.assertIsNone(self.broadcasts.thread)
 def test_closed_workspace_or_cancelled_request_does_not_send(self):
  self.broadcasts.can_run=lambda:False;self.assertIsNone(self.run_broadcast());self.assertFalse(self.calls)
  self.broadcasts.can_run=lambda:True
  with self.store.edit() as s:s['cancelled_requests']={self.key:'cancelled'}
  self.assertIsNone(self.run_broadcast());self.assertFalse(self.calls)
 def test_exchange_starts_publication_and_delivers_receipt_without_an_approval(self):
  from agent_exchange import Exchange
  exchange=Exchange(1,'fixture-token',self.store);caps=[]
  def response(port,path,body,*a,**k):
   caps.append(body['capabilities']);return {'version':1,'accepted':[item['id'] for item in body['outbox']],'proposals':[]}
  with patch('agent_exchange.LOCAL_BROADCASTS',self.broadcasts),patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',side_effect=response),patch('automatic_broadcast.rpc',side_effect=self.call),patch('activity_log.event'):
   exchange.once(False);self.broadcasts.thread.join(5);self.assertFalse(self.broadcasts.active);self.assertNotIn(self.key,self.store.read()['pending']);exchange.once(False)
  self.assertIn('automatic_broadcast_v1',caps[0]);self.assertEqual(self.store.read()['completed'][self.key]['delivery'],'acknowledged');self.assertFalse(self.store.read()['outbox']);self.assertEqual(self.calls.count('sendrawtransaction'),1)

from regtest_support import Regtest
class RealCore(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.node=Regtest();cls.c=cls.node.core;rpc(cls.c,'createwallet',{'wallet_name':'miner56'});cls.miner=rpc(cls.c,'getnewaddress',[],'miner56');rpc(cls.c,'generatetoaddress',[105,cls.miner])
 @classmethod
 def tearDownClass(cls):cls.node.close()
 def check(self,multi=False,recipients=1):
  suffix=('multi' if multi else 'single')+str(recipients);name='source-'+suffix
  if multi:
   from vendor.embit import ec
   from vendor.embit.networks import NETWORKS
   from vendor.embit.descriptor.checksum import checksum
   keys=[ec.PrivateKey(bytes([n])*32) for n in (1,2,3)]
   for index in range(2):
    wallet=name+str(index);rpc(self.c,'createwallet',{'wallet_name':wallet,'blank':True,'passphrase':'test-password'});rpc(self.c,'walletpassphrase',['test-password',60],wallet)
    body='wsh(sortedmulti(2,'+','.join(k.wif(NETWORKS['regtest']) if n==index else k.get_public_key().sec().hex() for n,k in enumerate(keys))+'))'
    result=rpc(self.c,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now'}]],wallet);self.assertTrue(result[0]['success'])
   public='wsh(sortedmulti(2,'+','.join(k.get_public_key().sec().hex() for k in keys)+'))';address=rpc(self.c,'deriveaddresses',[rpc(self.c,'getdescriptorinfo',[public])['descriptor']])[0];name+='0'
  else:
   rpc(self.c,'createwallet',{'wallet_name':name,'passphrase':'test-password'});address=rpc(self.c,'getnewaddress',[],name);rpc(self.c,'walletpassphrase',['test-password',60],name)
  txid=rpc(self.c,'sendtoaddress',[address,'0.1'],'miner56');rpc(self.c,'generatetoaddress',[1,self.miner]);utxo=next(r for r in rpc(self.c,'listunspent',[0],name) if r['txid']==txid)
  outputs=[{rpc(self.c,'getnewaddress',[],'miner56'):format(.1/recipients,'.8f')} for _ in range(recipients)]
  built=rpc(self.c,'walletcreatefundedpsbt',{'inputs':[{'txid':txid,'vout':utxo['vout']}],'outputs':outputs,'options':{'add_inputs':False,'subtractFeeFromOutputs':[0],'fee_rate':1}},name)
  signed=rpc(self.c,'walletprocesspsbt',{'psbt':built['psbt'],'sign':True,'finalize':False},name)['psbt']
  if multi:signed=rpc(self.c,'walletprocesspsbt',{'psbt':signed,'sign':True,'finalize':False},'source-'+suffix+'1')['psbt']
  final=rpc(self.c,'finalizepsbt',[signed]);self.assertTrue(final['complete']);expected=rpc(self.c,'decoderawtransaction',[final['hex']])['txid']
  # Signing alone never sends anything to the test network.
  self.assertNotIn(expected,rpc(self.c,'getrawmempool'))
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder);p={'kind':'broadcast_transaction','request_id':'a'*64,'chain':'regtest','psbt':signed,'txid':expected};store.receive(p);key=digest(p)
   with patch('wallet_setup.secret_dialog',side_effect=AssertionError('No broadcast prompt')):result=Broadcasts(self.c,store).process(key)
   self.assertEqual(result['status'],'broadcast');self.assertIn(expected,rpc(self.c,'getrawmempool'));self.assertNotIn(key,store.read()['pending']);self.assertEqual(next(iter(store.read()['outbox'].values()))['payload']['txid'],expected)
 def test_single_signature(self):self.check()
 def test_multiple_recipients(self):self.check(recipients=3)
 def test_multisig(self):self.check(multi=True)
