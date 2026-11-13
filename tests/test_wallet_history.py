"""Real local Core ledgers and optional public comparisons over paired SSH."""
import time,threading,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wallet_ops import rpc,sats
from approval_store import digest
from regtest_support import Regtest
import fixture_retirement_evidence as preservation_fixture
import fixture_direct_peers as direct_fixture

class History(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core
  for name in ('Funding','Alpha','Beta'):rpc(self.core,'createwallet',{'wallet_name':name})
  self.mine=rpc(self.core,'getnewaddress',[],'Funding');self.a=rpc(self.core,'getnewaddress',[],'Alpha');self.b=rpc(self.core,'getnewaddress',[],'Beta')
  rpc(self.core,'generatetoaddress',[101,self.mine]);self.first=rpc(self.core,'sendmany',['',{self.a:'0.25',self.b:'0.5'}],'Funding');rpc(self.core,'generatetoaddress',[1,self.mine])
 def balance(self,name):return sum(sats(v.get(k,0)) for v in rpc(self.core,'getbalances',[],name).values() for k in ('trusted','untrusted_pending','immature'))
 def test_multiple_recipients_fees_self_transfer_and_newest_first(self):
  from wallet_history import transactions
  data=transactions(self.core,'Funding');row=next(r for r in data['groups'][0]['rows'] if r['txid']==self.first)
  self.assertEqual(row['addresses'],sorted([self.a,self.b]));tx=rpc(self.core,'gettransaction',[self.first,True],'Funding');self.assertEqual(int(row['amount_sats']),__import__('wallet_history').signed_sats(tx['amount'])+__import__('wallet_history').signed_sats(tx['fee']));self.assertEqual(int(data['groups'][0]['rows'][0]['balance_sats']),self.balance('Funding'))
  own=rpc(self.core,'getnewaddress',[],'Alpha');selftx=rpc(self.core,'sendtoaddress',[own,'0.02'],'Alpha');rpc(self.core,'generatetoaddress',[1,self.mine]);data=transactions(self.core,'Alpha');rows=data['groups'][0]['rows'];self.assertEqual(rows,sorted(rows,key=lambda r:(r['timestamp'],r['txid']),reverse=True));self.assertEqual(int(rows[0]['balance_sats']),self.balance('Alpha'));row=next(r for r in rows if r['txid']==selftx);self.assertEqual(int(row['amount_sats']),__import__('wallet_history').signed_sats(rpc(self.core,'gettransaction',[selftx,True],'Alpha')['fee']))
 def test_extinct_groups_keep_names_and_lost_labels_and_separate_balances(self):
  from wallet_history import transactions
  raw_addresses={}
  for name in ('Alpha','Beta'):
   for record in rpc(self.core,'listtransactions',['*',1000,0,True],name):
    decoded=rpc(self.core,'gettransaction',[record['txid'],True,True],name)['decoded']
    for output in decoded['vout']:
     address=output['scriptPubKey'].get('address')
     if address and rpc(self.core,'getaddressinfo',[address],name).get('ismine'):raw_addresses[address]=name
  rpc(self.core,'createwallet',{'wallet_name':'extinct_watch','disable_private_keys':True,'blank':True})
  imports=[{'desc':rpc(self.core,'getdescriptorinfo',['addr('+a+')'])['descriptor'],'timestamp':0,'label':'Old '+name+' | LOST:01/01/2020 00:00:00 UTC'} for a,name in raw_addresses.items()];rpc(self.core,'importdescriptors',[imports],'extinct_watch')
  data=transactions(self.core,'extinct_watch');self.assertTrue(data['extinct']);self.assertEqual({g['name'] for g in data['groups']},{'Old Alpha','Old Beta'});groups={g['name']:g for g in data['groups']};self.assertEqual(int(groups['Old Alpha']['rows'][0]['balance_sats']),25000000);self.assertEqual(int(groups['Old Beta']['rows'][0]['balance_sats']),50000000);self.assertTrue(all('LOST:' in row['label'] for row in __import__('wallet_labels').read_labels(self.core,'extinct_watch',rpc(self.core,'listdescriptors',[False],'extinct_watch'),[])))
 def test_history_never_requests_private_descriptors_or_block_replay(self):
  from wallet_history import transactions
  original=rpc;calls=[]
  def check(core,method,args=None,wallet=None,**kwargs):
   calls.append(method)
   if method=='listdescriptors':self.assertEqual(args,[False])
   self.assertNotIn(method,('rescanblockchain','importdescriptors','getrawtransaction','walletpassphrase','dumpprivkey','stop'))
   return original(core,method,args,wallet,**kwargs)
  with patch('wallet_history.rpc',side_effect=check):transactions(self.core,'Alpha')
  self.assertIn('gettransaction',calls)

class WarningDeletion(preservation_fixture.DeletionEvidence):
 def test_absent_extinct_wallet_and_no_peers_warn_but_do_not_block_deletion(self):
  from wallet_deletion import remove
  owner,p,key=self.prepare();rpc(self.core,'unloadwallet',['Wallaby Extinct']);self.assertIsNone(getattr(owner.store,'peers',None));facts=owner.review(key)['retirement'];self.assertFalse(facts['history_comparison']['verified']);self.assertTrue(facts['history_elsewhere_confirmation_required'])
  with patch('wallet_deletion.delete',side_effect=lambda record:remove(record,[Path(record['path']).parent])):owner.approve(key)
  self.assertNotIn('Old',[r['name'] for r in rpc(self.core,'listwalletdir')['wallets']]);self.assertIn('Wallaby Extinct',[r['name'] for r in rpc(self.core,'listwalletdir')['wallets']])

class RemoteEvidence(unittest.TestCase):
 setUp=direct_fixture.DirectPeers.setUp
 peer=direct_fixture.DirectPeers.peer
 pair=direct_fixture.DirectPeers.pair
 move=direct_fixture.DirectPeers.move
 network=direct_fixture.DirectPeers.network
 until=direct_fixture.DirectPeers.until
 def test_actual_direct_comparison_is_optional_and_checks_all_raw_history(self):
  from relay_stream import Bridge
  from retirement_remote import Comparisons,request,FEATURE
  local=Regtest();remote=Regtest();self.addCleanup(local.close);self.addCleanup(remote.close);core=local.core;other=remote.core
  rpc(core,'createwallet',{'wallet_name':'Old'});rpc(core,'createwallet',{'wallet_name':'Funding'});old=rpc(core,'getnewaddress',[],'Old');mine=rpc(core,'getnewaddress',[],'Funding');rpc(core,'generatetoaddress',[101,mine]);txid=rpc(core,'sendtoaddress',[old,'0.125'],'Funding');rpc(core,'generatetoaddress',[1,mine]);tx=rpc(core,'gettransaction',[txid,True],'Old')
  for h in range(1,rpc(core,'getblockcount')+1):rpc(other,'submitblock',[rpc(core,'getblock',[rpc(core,'getblockhash',[h]),0])])
  rpc(other,'createwallet',{'wallet_name':'extinct_watch','disable_private_keys':True,'blank':True});desc=rpc(core,'getdescriptorinfo',['addr('+old+')'])['descriptor'];rpc(other,'importdescriptors',[[{'desc':desc,'timestamp':0,'label':'Old'}]],'extinct_watch')
  self.network();self.a.wallet_bridge=Bridge(self.a,self.a.store);self.b.wallet_bridge=Bridge(self.b,self.b.store);self.b.retirement_compare=Comparisons(self.b,other,threading.RLock(),lambda:False)
  self.until(lambda:FEATURE in self.a.channel(self.b.identity['identity_key']).features)
  p={'phase':'delete','manifest':{'addresses':[{'address':old,'label':'Old'}],'transactions':[{'txid':txid,'blockhash':tx['blockhash']}]}};key=digest(p)
  with self.a.store.edit() as state:state['pending'][key]={'proposal':p,'state':'pending'}
  owner=SimpleNamespace(store=self.a.store,core=core,reviews={key:({'local_wallets':['Old'],'history_comparison':{'verified':False}},time.time())})
  saved_peers=owner.store.peers;owner.store.peers=None;self.assertEqual(request(owner,key)['state'],'unavailable');owner.store.peers=saved_peers
  result=request(owner,key);self.assertIn(result['state'],('checking','complete'));self.until(lambda:request(owner,key)['state']!='checking');result=request(owner,key);self.assertEqual(result['state'],'complete',str(result)+' '+__import__('activity_log').DiagnosticLog().text()[-5000:]);self.assertEqual(result['evidence']['transaction_count'],1);self.assertEqual(result['evidence']['address_count'],1);self.assertTrue(result['evidence']['remote'])
  rpc(other,'setlabel',[old,'Wrong original wallet'],'extinct_watch');owner.reviews[key]=(owner.reviews[key][0],time.time());request(owner,key);self.until(lambda:request(owner,key)['state']!='checking');self.assertEqual(request(owner,key)['state'],'unavailable');self.assertIn(key,self.a.store.read()['pending'])
  channel=self.a.channel(self.b.identity['identity_key']);channel.features=set();owner.remote_comparisons={};self.assertEqual(request(owner,key)['state'],'unavailable')
  self.a.direct.delete(self.b.identity['endpoint_id']);owner.remote_comparisons={};self.assertEqual(request(owner,key)['state'],'unavailable');self.assertIn(key,self.a.store.read()['pending'])

class LocalAPI(unittest.TestCase):
 def setUp(self):
  from fixture_protected_api import ProtectedCancellationAPI
  ProtectedCancellationAPI.setUp(self)
 def test_history_and_optional_comparison_are_local_protected_routes(self):
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   for route,body,method in [('wallet-history',{'wallet':'Old'},'local_wallets.history'),('retirement-evidence',{'id':'review'},'retirement.evidence')]:
    code,value=self.fixture.call('/api/authorise/'+route,body);self.assertEqual(code,200,value);self.assertEqual(call.call_args.args,(method,*body.values()))
    before=call.call_count;code,value=self.fixture.call('/api/authorise/'+route,{**body,'remote':True});self.assertEqual(code,400);self.assertEqual(call.call_count,before)
