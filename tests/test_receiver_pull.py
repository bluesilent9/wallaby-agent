"""Build 84: trusted direct receiver approval starts source work automatically."""
from pathlib import Path
import copy,time,threading,unittest
from unittest.mock import patch,Mock
from fixture_direct_peers import DirectCore
from peer_protocol import PROTOCOL,CIPHER
class ReceiverPull(DirectCore):
 def relay(self,kind='single',watch=False,restoration=False,source_watch=False):
  from peer_wallet import wallet_details
  from wallet_preview import prepare,receive
  from sync_queue import apply_snapshot,choose
  from batch_transfer import BatchTransfer
  from fixture_public_policy import paired
  from wallet_ops import rpc
  from approval_store import digest
  import shutil
  if restoration:
   p,ident=self.fixture(kind);rpc(self.receiver.core,'unloadwallet',['Original']);shutil.rmtree(Path(self.receiver.core.config['cookie']).parent/'wallets'/'Original')
  else:p=paired('Original');p['public_wallet']=self.wallet(self.core,'Original',kind)
  if source_watch:
   raw=p['public_wallet'];rpc(self.core,'unloadwallet',['Original']);shutil.rmtree(Path(self.core.config['cookie']).parent/'wallets'/'Original');rpc(self.core,'createwallet',{'wallet_name':'Original','disable_private_keys':True,'blank':True})
   results=rpc(self.core,'importdescriptors',[[{k:v for k,v in r.items() if k in ('desc','timestamp','active','internal','range')} for r in raw['descriptors']]],'Original');self.assertTrue(all(r['success'] for r in results));p['public_wallet']=rpc(self.core,'listdescriptors',[False],'Original');p['source_has_private_keys']=False
  self.setup_peers();p.update(transfer_version=3,node_ipv6=None);p['peer']['ipv6']=None;p['transport']={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'sender_endpoint':self.a.identity['endpoint_id'],'receiver_endpoint':self.b.identity['endpoint_id'],'sender_identity':self.a.identity['identity_key'],'receiver_identity':self.b.identity['identity_key'],'sender_noise_key':self.a.identity['noise_public_key'],'receiver_noise_key':self.b.identity['noise_public_key']}
  incoming=[p]
  if getattr(self,'batch_two',False):
   rpc(self.core,'createwallet',{'wallet_name':'Second wallet','passphrase':__import__('fixture_signer_restoration').PASSWORD});second=copy.deepcopy(p);second['transfer_id']='e'*64;second['preview_challenge']='d'*64;second['public_wallet']=rpc(self.core,'listdescriptors',[False],'Second wallet');incoming.append(second)
  outgoing=[{**copy.deepcopy(q),'direction':'send'} for q in incoming];sending=outgoing[0];sk=digest(sending);rk=digest(p);apply_snapshot(self.sender,1,outgoing);apply_snapshot(self.store,1,incoming)
  for i,(q,r) in enumerate(zip(outgoing,incoming)):
   choose(self.store,digest(r),True,watch if i==0 else False);payload=prepare(self.core,self.sender,digest(q),q);receive(self.store,payload)
  from sync_offers import apply as offers
  offers(self.sender,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[{'id':str(i+1)*64,'transfer_id':q['transfer_id'],'direction':'send','peer':{k:q['peer'][k] for k in ('node_id','hostname')},'public_wallet':q['public_wallet'],'status':'ready'} for i,q in enumerate(outgoing)]},'fixture-session')
  send=BatchTransfer(self.core,self.sender);receiver=BatchTransfer(self.receiver.core,self.store);self.addCleanup(send.close);self.addCleanup(receiver.close);
  from wallet_pull import Pull
  self.a.wallet_pull=Pull(self.a,send,guard=lambda:bool(getattr(self,'source_busy',False)));self.b.wallet_pull=Pull(self.b,receiver)
  if getattr(self,'withdraw',False):
   with self.sender.edit() as s:s['pending'][sk]['withdrawn']=True
  if getattr(self,'stale',False):
   with self.sender.edit() as s:s['transfer_previews'][sk]['preview']['generated_at']+=1
  if getattr(self,'unlock',False):rpc(self.core,'walletpassphrase',[__import__('fixture_signer_restoration').PASSWORD,60],'Original')
  receiver.authorise_batch({});receiver.thread.join(20)
  for t in self.a.wallet_pull.threads:t.join(10)
  if getattr(self,'source_busy',False) or getattr(self,'withdraw',False) or getattr(self,'stale',False) or getattr(self,'unlock',False):
   self.assertTrue(receiver.error,receiver.state());self.assertNotIn(sk,self.sender.read()['completed']);self.assertNotIn(rk,self.store.read()['completed']);self.assertNotIn('Wallaby Sync '+p['transfer_id'][:24],rpc(self.receiver.core,'listwallets'));return
  self.assertFalse(receiver.error,receiver.error);self.assertNotIn(sk,self.sender.read().get('sync_choices',{}));self.assertFalse(self.sender.read().get('sync_batch'))
  self.assertFalse(self.pump_error,self.pump_error);self.assertIn(sk,self.sender.read()['completed']);self.assertIn(rk,self.store.read()['completed']);names=[n for n in rpc(self.receiver.core,'listwallets') if __import__('public_policy').descriptors(rpc(self.receiver.core,'listdescriptors',[False],n))==__import__('public_policy').descriptors(p['public_wallet'])];self.assertEqual(len(names),1);name=names[0];self.assertEqual(rpc(self.receiver.core,'getwalletinfo',[],name)['private_keys_enabled'],not watch and not source_watch)
  if getattr(self,'batch_two',False):
   self.assertIn(digest(outgoing[1]),self.sender.read()['completed']);self.assertIn(digest(incoming[1]),self.store.read()['completed'])
   second_names=[n for n in rpc(self.receiver.core,'listwallets') if __import__('public_policy').descriptors(rpc(self.receiver.core,'listdescriptors',[False],n))==__import__('public_policy').descriptors(incoming[1]['public_wallet'])];self.assertEqual(len(second_names),1);self.assertTrue(rpc(self.receiver.core,'getwalletinfo',[],second_names[0])['private_keys_enabled'])
  if restoration:self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'restored')

 def test_receiver_batch_serialises_two_wallets_with_independent_watch_choices(self):self.batch_two=True;self.relay(watch=True)
 def test_receiver_requests_single_sig_without_sender_selection_or_click(self):self.relay()
 def test_receiver_requests_multisig_without_sender_click(self):self.relay('multi',restoration=True)
 def test_receiver_watch_only_choice_never_copies_private_keys(self):self.relay('single',watch=True)
 def test_original_multisig_role_restored_by_receiver_only(self):self.relay('vault',restoration=True)
 def test_watch_only_original_role_restored_by_receiver_only(self):self.relay('vault',watch=True,restoration=True)
 def test_busy_source_reports_failure_without_export(self):self.source_busy=True;self.relay()
 def test_withdrawn_source_request_reports_failure_without_export(self):self.withdraw=True;self.relay()

 def test_public_vault_watch_source_transfers_automatically(self):self.relay('vault',source_watch=True)
 def test_changed_preview_refuses_without_export(self):self.stale=True;self.relay()
 def test_unlocked_private_source_refuses_without_export(self):self.unlock=True;self.relay()

class PullGuards(unittest.TestCase):
 def test_mobile_and_malformed_watch_choices_never_start_source(self):
  from types import SimpleNamespace
  from wallet_pull import Pull
  source=Mock();source.store=Mock();peers=Mock();pull=Pull(peers,source)
  record={'payload_type':'stream_wallet_pull','operation_hash':'a'*64,'body':{'token':'b'*64,'transfer_id':'c'*64,'preview_hash':'d'*64,'watch_only':False}}
  with self.assertRaisesRegex(ValueError,'Mobile'):pull(SimpleNamespace(peer={'role':'mobile'}),record)
  for value in ('false',None,0,1):
   record['body']['watch_only']=value
   with self.assertRaises(ValueError):pull(SimpleNamespace(peer={'role':'agent'}),record)
  self.assertFalse(pull.threads);source.send.assert_not_called()
 def test_response_from_another_channel_cannot_approve_a_request(self):
  from types import SimpleNamespace
  from wallet_pull import Pull
  source=Mock();source.store=Mock();pull=Pull(Mock(),source);event=threading.Event();pull.sent['b'*64]={'channel':object(),'operation':'a'*64,'event':event}
  with self.assertRaisesRegex(ValueError,'another approved'):pull(SimpleNamespace(peer={'role':'agent'}),{'payload_type':'stream_wallet_pull_result','operation_hash':'a'*64,'body':{'token':'b'*64,'status':'accepted'}})
  self.assertFalse(event.is_set());source.send.assert_not_called()
