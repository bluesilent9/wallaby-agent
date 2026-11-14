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
  if getattr(self,'extinct_source',False):
   from vendor.embit.descriptor.checksum import checksum
   from fixture_signer_restoration import PASSWORD
   desc=p['public_wallet']['descriptors'][0]['desc'];self.old_address=rpc(self.core,'deriveaddresses',[desc,*([[0,0]] if '*' in desc else [])])[0];miner=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[1,self.old_address]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'walletpassphrase',[PASSWORD,60],'Original');rpc(self.core,'sendall',{'recipients':[miner]},'Original');rpc(self.core,'walletlock',[],'Original');rpc(self.core,'generatetoaddress',[1,miner])
   rpc(self.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True});desc='addr('+self.old_address+')';self.lost='Retired Treasury | LOST:06/11/2026 01:02:03 UTC';rpc(self.core,'importdescriptors',[[{'desc':desc+'#'+checksum(desc),'timestamp':0,'label':self.lost}]],'Wallaby Extinct');p['public_wallet']=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct');p['source_has_private_keys']=False;source_watch=True
  if getattr(self,'active_archive_owner',False):self.wallet(self.receiver.core,'Active local copy',kind)
  if getattr(self,'archive_subset',False):
   from vendor.embit.descriptor.checksum import checksum
   extra=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+extra+')'
   rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now','label':'Other retired history'}]],'Wallaby Extinct')
  if getattr(self,'archive_extra_record',False):
   # Legacy native archives can retain CWalletTx rows beyond the currently
   # watched fixed-address set. Preserve that public history, not just rows
   # rediscovered by decoding a direct address match.
   from core_history import collect,install,validate_rows
   from approval_store import Store
   txid=rpc(self.core,'listtransactions',['*',1000,0,True],'Miner')[0]['txid']
   rows=collect(self.core,['Miner'],{txid},self.root)
   manifest={'addresses':[{'address':self.old_address,'label':self.lost}],'transactions':[{'txid':r['txid'],'blockhash':r['blockhash']} for r in rows]}
   with self.assertRaisesRegex(ValueError,'unrelated'):validate_rows(self.core,rows,manifest,allow_unfunded=True)
   install(self.core,Store(self.root/'legacy-fixture'), 'Wallaby Extinct',rows,manifest,allow_unfunded=True,trusted_inventory=True)
   self.extra_txid=txid
  if getattr(self,'pruned_history',False):
   # Download and validate once, then genuinely discard the historical block
   # files on BOTH nodes before transferring any archive history.
   rpc(self.core,'generatetoaddress',[600,miner])
   for height in range(1,rpc(self.core,'getblockcount')+1):rpc(self.receiver.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
   for core in (self.core,self.receiver.core):
    rpc(core,'pruneblockchain',[300]);chain=rpc(core,'getblockchaininfo');self.assertTrue(chain['pruned']);self.assertGreater(chain['pruneheight'],2)
    block=rpc(core,'getblockhash',[2]);self.assertGreater(rpc(core,'getblockheader',[block])['confirmations'],0)
    with self.assertRaises(ValueError):rpc(core,'getblock',[block])
  self.setup_peers()
  if getattr(self,'extinct_source',False) and not getattr(self,'uncertified',False):
   from extinct_upgrade import certify
   certify(self.core,self.sender,'Wallaby Extinct',[self.old_address])
  p.update(transfer_version=3,node_ipv6=None);p['peer']['ipv6']=None;p['transport']={'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,'sender_endpoint':self.a.identity['endpoint_id'],'receiver_endpoint':self.b.identity['endpoint_id'],'sender_identity':self.a.identity['identity_key'],'receiver_identity':self.b.identity['identity_key'],'sender_noise_key':self.a.identity['noise_public_key'],'receiver_noise_key':self.b.identity['noise_public_key']}
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
  from sync_approvals import groups
  self.receiving=receiver
  if getattr(self,'cancel_connected',False):
   def cancel():
    self.pause_started.wait(5);self.cancel_result=receiver.stop_receiving();self.resume_source.set()
   self.canceller=threading.Thread(target=cancel);self.canceller.start()
  group=groups(receiver.store)[0];review=receiver.review_receive(group['id']);self.assertEqual(len(review['wallets']),len(incoming));receiver.authorise_receive(group['id'],review['token']);receiver.thread.join(20)
  for t in self.a.wallet_pull.threads:t.join(10)
  if getattr(self,'cancel_connected',False):self.canceller.join(5)
  if getattr(self,'source_export_failed',False) or getattr(self,'cancel_connected',False):
   self.assertFalse(receiver.thread.is_alive());self.assertFalse(receiver.state()['busy']);self.assertFalse(self.sender.read().get('sync_batch'));self.assertNotIn(rk,self.store.read()['completed']);self.assertEqual(self.sender.read()['pending'][sk]['state'],'pending');self.assertFalse(self.b.stop.is_set());return
  if getattr(self,'source_busy',False) or getattr(self,'withdraw',False) or getattr(self,'stale',False) or getattr(self,'unlock',False) or getattr(self,'active_archive_owner',False):
   self.assertTrue(receiver.error,receiver.state());self.assertNotIn(sk,self.sender.read()['completed']);self.assertNotIn(rk,self.store.read()['completed']);self.assertNotIn('Wallaby Sync '+p['transfer_id'][:24],rpc(self.receiver.core,'listwallets'));return
  self.assertFalse(receiver.error,receiver.error);self.assertNotIn(sk,self.sender.read().get('sync_choices',{}));self.assertFalse(self.sender.read().get('sync_batch'))
  self.assertFalse(self.pump_error,self.pump_error);self.assertIn(sk,self.sender.read()['completed']);self.assertIn(rk,self.store.read()['completed']);names=[n for n in rpc(self.receiver.core,'listwallets') if __import__('public_policy').descriptors(rpc(self.receiver.core,'listdescriptors',[False],n))==__import__('public_policy').descriptors(p['public_wallet'])];self.assertEqual(len(names),1);name=names[0];self.assertEqual(rpc(self.receiver.core,'getwalletinfo',[],name)['private_keys_enabled'],not watch and not source_watch)
  if getattr(self,'batch_two',False):
   self.assertIn(digest(outgoing[1]),self.sender.read()['completed']);self.assertIn(digest(incoming[1]),self.store.read()['completed'])
   second_names=[n for n in rpc(self.receiver.core,'listwallets') if __import__('public_policy').descriptors(rpc(self.receiver.core,'listdescriptors',[False],n))==__import__('public_policy').descriptors(incoming[1]['public_wallet'])];self.assertEqual(len(second_names),1);self.assertTrue(rpc(self.receiver.core,'getwalletinfo',[],second_names[0])['private_keys_enabled'])
  if getattr(self,'extinct_source',False):
   self.assertEqual(rpc(self.receiver.core,'getwalletinfo',[],name)['txcount'],rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount']);self.assertGreater(rpc(self.receiver.core,'getwalletinfo',[],name)['txcount'],0);self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[self.old_address],name)['labels'],[self.lost])
   if getattr(self,'uncertified',False):
    from extinct_upgrade import snapshot,valid
    state=snapshot(self.receiver.core,name);self.assertTrue(valid(self.receiver.core,state));self.assertEqual(state['marker']['basis'],'trusted_direct_snapshot');self.assertFalse(self.store.read().get('history_jobs'))
    from extinct_history_sync import coverage
    self.assertEqual(coverage(self.receiver.core,name,state['addresses'],state['txids'])['basis'],'trusted_direct_snapshot')
   if getattr(self,'archive_extra_record',False):self.assertEqual(rpc(self.receiver.core,'gettransaction',[self.extra_txid,True],name)['hex'],rpc(self.core,'gettransaction',[self.extra_txid,True],'Wallaby Extinct')['hex'])
  if restoration:self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'restored')

 def test_source_export_failure_wakes_receiver_and_releases_authorisation(self):
  self.extinct_source=True;self.source_export_failed=True
  with patch('history_wire.export',side_effect=ValueError('Upgrade and verify the source Extinct archive before sending a complete history update.')):self.relay(watch=True)
 def test_trusted_existing_extinct_records_copy_without_claiming_a_local_scan(self):
  self.extinct_source=True;self.uncertified=True
  with patch('wallet_recovery.Recovery.register_watch_history',side_effect=AssertionError('No historical rescan is needed for a trusted snapshot.')):self.relay(watch=True)
 def test_existing_archive_inventory_preserves_records_without_a_direct_address_match(self):
  self.extinct_source=True;self.uncertified=True;self.archive_extra_record=True;self.relay(watch=True)
 def test_requested_archive_subset_is_not_mistaken_for_a_source_mutation(self):
  self.extinct_source=True;self.uncertified=True;self.archive_subset=True;self.relay(watch=True)
 def test_actual_archive_inventory_change_during_export_still_stops_before_import(self):
  self.extinct_source=True;self.uncertified=True;self.source_export_failed=True
  from history_wire import collect
  from wallet_ops import rpc
  from vendor.embit.descriptor.checksum import checksum
  def changing(*args,**kwargs):
   rows=collect(*args,**kwargs);body='addr('+rpc(self.core,'getnewaddress',[],'Miner')+')';rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now'}]],'Wallaby Extinct');return rows
  with patch('history_wire.collect',side_effect=changing):self.relay(watch=True)
 def test_changed_lost_label_during_export_still_stops_before_import(self):
  self.extinct_source=True;self.uncertified=True;self.source_export_failed=True
  from history_wire import collect
  from wallet_ops import rpc
  def changing(*args,**kwargs):
   rows=collect(*args,**kwargs);rpc(self.core,'setlabel',[self.old_address,self.lost+' changed'],'Wallaby Extinct');return rows
  with patch('history_wire.collect',side_effect=changing):self.relay(watch=True)
 def test_trusted_snapshot_still_refuses_active_local_wallet_ownership(self):
  self.extinct_source=True;self.uncertified=True;self.active_archive_owner=True;self.relay(watch=True)
 def test_trusted_snapshot_does_not_export_malformed_transaction_records(self):
  self.extinct_source=True;self.uncertified=True;self.source_export_failed=True
  from history_wire import collect
  def damaged(*args,**kwargs):
   rows=collect(*args,**kwargs);rows[0]['record']='00';return rows
  with patch('history_wire.collect',side_effect=damaged):self.relay(watch=True)
 def test_pruned_source_and_receiver_transfer_old_history_using_retained_headers(self):
  # Recreate this test's two isolated nodes with manual pruning enabled.
  self.source.close();self.receiver.close();self._cleanups=[c for c in self._cleanups if getattr(c[0],'__self__',None) not in (self.source,self.receiver)]
  from regtest_support import Regtest
  self.source=Regtest(['-prune=1','-txindex=0','-fastprune=1']);self.receiver=Regtest(['-prune=1','-txindex=0','-fastprune=1']);self.addCleanup(self.source.close);self.addCleanup(self.receiver.close);self.core=self.source.core
  from wallet_ops import rpc
  rpc(self.core,'createwallet',{'wallet_name':'Miner'});rpc(self.core,'generatetoaddress',[1,rpc(self.core,'getnewaddress',[],'Miner')])
  self.extinct_source=True;self.uncertified=True;self.pruned_history=True
  with patch('wallet_recovery.Recovery.register_watch_history',side_effect=AssertionError('A pruned archive transfer must not rescan.')):self.relay(watch=True)
 def test_cancel_connected_receive_without_closing_other_agent(self):
  self.cancel_connected=True;self.pause_started=threading.Event();self.resume_source=threading.Event()
  def delayed(*args,**kwargs):
   self.pause_started.set();self.resume_source.wait(5)
   return __import__('peer_wallet').frame_read(args[1])
  with patch('chain_sync.send',side_effect=delayed):self.relay(watch=True)
 def test_signed_disc_origin_survives_grouped_receive_and_cannot_be_relabelled(self):
  from wallet_preview import verify
  with patch('wallet_traits.source_storage',return_value='disc'):self.relay(watch=True)
  payload=next(iter(self.sender.read()['transfer_previews'].values()));self.assertEqual(payload['preview']['source_storage'],'disc');verify(self.sender,payload)
  changed=copy.deepcopy(payload);changed['preview']['source_storage']='node'
  with self.assertRaises(ValueError):verify(self.sender,changed)
 def test_extinct_import_still_refuses_an_active_local_owner(self):self.extinct_source=True;self.active_archive_owner=True;self.relay(watch=True)
 def test_extinct_history_and_lost_labels_transfer_through_authorise_group(self):self.extinct_source=True;self.relay(watch=True)
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
