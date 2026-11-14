"""Paired direct discovery/receiving with no Server wallet proposals at all."""
import copy,shutil,time
from pathlib import Path
from unittest.mock import patch
from fixture_direct_peers import DirectCore
from wallet_ops import rpc
from approval_store import digest
from direct_wallet_catalogue import Catalogue,snapshot,missing,reconcile_preservation
from batch_transfer import BatchTransfer
from wallet_pull import Pull

class DirectDiscovery(DirectCore):
 def boot(self,kind='single'):
  self.raw=self.wallet(self.core,'Original',kind);self.setup_peers()
  self.send=BatchTransfer(self.core,self.sender);self.receive=BatchTransfer(self.receiver.core,self.store)
  self.addCleanup(self.send.close);self.addCleanup(self.receive.close)
  self.a.catalogue=Catalogue(self.a,self.send);self.b.catalogue=Catalogue(self.b,self.receive)
  self.a.wallet_pull=Pull(self.a,self.send);self.b.wallet_pull=Pull(self.b,self.receive)
  self.channel=self.b.channel(self.a.identity['identity_key'])
 def discover(self):
  self.a.catalogue.cache=None;self.b.catalogue.cache=None;self.b.catalogue.exchange(self.channel)
  self.assertFalse(self.pump_error,self.pump_error)
 def incoming(self,name='Original'):
  return next((k for k,r in self.store.read()['pending'].items() if r['proposal'].get('kind')=='wallet_transfer' and r['proposal']['direction']=='receive' and r['proposal']['public_wallet']['wallet_name']==name),None)
 def approve(self,key,watch=False):
  from sync_table import choose
  from sync_approvals import groups
  choose(self.store,key,True,watch);group=next(g for g in groups(self.store) if key in g['keys']);review=self.receive.review_receive(group['id']);self.receive.authorise_receive(group['id'],review['token']);self.receive.thread.join(25)
  for t in self.a.wallet_pull.threads:t.join(10)
  self.assertFalse(self.receive.thread.is_alive());self.assertFalse(self.receive.error,self.receive.error);self.assertIn(key,self.store.read()['completed'])
 def test_single_sig_discovery_and_private_transfer_ignore_server_withdrawal(self):
  self.boot();self.discover();key=self.incoming();self.assertIsNotNone(key)
  from sync_queue import apply_snapshot
  from sync_offers import apply
  apply_snapshot(self.store,999,[],session='malicious-server')
  with self.assertRaises(ValueError):apply(self.store,{'malformed':'server'},'server')
  self.assertIn(key,self.store.read()['pending'])
  self.approve(key)
  self.assertFalse(any(r['kind'] in ('wallet_transfer_result','wallet_transfer_preview') for s in (self.sender,self.store) for r in s.read()['outbox'].values()))
 def test_denial_visible_and_reenable_works_without_server_or_sender_approval(self):
  self.boot();self.discover();key=self.incoming()
  from sync_preferences import change,enable,policy_id
  policy=policy_id(self.store.read()['pending'][key]['proposal']);change(self.store,key,True);self.discover();self.assertIsNone(self.incoming())
  offers=list(self.store.read()['direct_sync_offers'].values());self.assertTrue(any(o['status']=='disabled' and o['public_wallet']['wallet_name']=='Original' for o in offers))
  enable(self.store,policy);self.discover();self.assertIsNotNone(self.incoming());self.approve(self.incoming(),True)
 def test_advisory_denial_before_first_discovery_suppresses_direct_receiving(self):
  self.boot()
  from sync_offers import apply
  from sync_preferences import change,policy_id
  offer={'id':'a'*64,'transfer_id':'b'*64,'direction':'receive','peer':{'node_id':'server-hint-source','hostname':'source'},'public_wallet':self.raw,'status':'discovery_pending','source_online':True}
  apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[offer]},'server');change(self.store,offer['id'],True)
  self.discover();self.assertIsNone(self.incoming());self.assertIn(policy_id(offer),self.store.read()['sync_exclusions']);self.assertFalse(any(policy_id(r['proposal'])==policy_id(offer) for r in self.store.read()['pending'].values()))
 def test_unloaded_wallets_are_detected_and_restored_not_treated_as_missing(self):
  self.boot();self.wallet(self.receiver.core,'Existing copy','single');rpc(self.receiver.core,'unloadwallet',{'wallet_name':'Existing copy'});self.discover()
  self.assertNotIn('Existing copy',rpc(self.receiver.core,'listwallets'));self.assertIsNone(self.incoming())
 def test_multisig_watch_transfer_and_reoffer_after_deletion(self):
  self.boot('multi');self.discover();key=self.incoming();self.assertIsNotNone(key);self.approve(key,True)
  # Completed outcomes cannot suppress a fresh direct generation after deletion.
  name='Wallaby Sync '+self.store.read()['completed'][key].get('transfer_id','')
  matches=[n for n in rpc(self.receiver.core,'listwallets') if __import__('public_policy').descriptors(rpc(self.receiver.core,'listdescriptors',[False],n))==__import__('public_policy').descriptors(self.raw)]
  self.assertEqual(len(matches),1);rpc(self.receiver.core,'unloadwallet',{'wallet_name':matches[0]});shutil.rmtree(Path(self.receiver.core.config['cookie']).parent/'wallets'/matches[0])
  self.discover();new=self.incoming();self.assertIsNotNone(new);self.assertNotEqual(new,key);self.assertIn(key,self.store.read()['completed'])
 def test_whole_extinct_history_updates_partial_receiver_and_keeps_lost_labels(self):
  from vendor.embit.descriptor.checksum import checksum
  self.boot();miner=rpc(self.core,'getnewaddress',[],'Miner');old=rpc(self.core,'deriveaddresses',[self.raw['descriptors'][0]['desc'],[0,0]])[0]
  rpc(self.core,'generatetoaddress',[1,old]);rpc(self.core,'generatetoaddress',[101,miner])
  rpc(self.core,'createwallet',{'wallet_name':'extinct_watch','disable_private_keys':True,'blank':True})
  lost='Treasury old | LOST:06/11/2026 01:02:03 UTC'
  second=rpc(self.core,'getnewaddress',[],'Miner')
  requests=[{'desc':'addr('+a+')#'+checksum('addr('+a+')'),'timestamp':0,'label':label} for a,label in ((old,lost),(second,'Other old wallet'))]
  rpc(self.core,'importdescriptors',[requests],'extinct_watch')
  if getattr(self,'retained_stage',False):
   stage='.wallaby-history-'+'a'*24;rpc(self.core,'createwallet',{'wallet_name':stage,'disable_private_keys':True,'blank':True})
   rpc(self.core,'importdescriptors',[[{**r,'timestamp':'now','label':'Stale retained staging label'} for r in requests]],stage)
   self.retained_stage_name=stage
   from sync_preferences import policy_id
   others=[r for r in snapshot(self.core,self.sender)['wallets'] if not r['archive']]
   with self.store.edit() as saved:
    for row in others:
     ident=policy_id(row);saved.setdefault('sync_exclusions',{})[ident]={'policy_id':ident,'wallet_name':row['public_wallet']['wallet_name']}
  # Old receiver subset exists before direct comparison; missing tx records and
  # another address must trigger the same ordinary receiving approval.
  rpc(self.receiver.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True})
  partial=[{**r,'timestamp':'now'} for r in (requests if getattr(self,'same_addresses',False) else requests[:1])];rpc(self.receiver.core,'importdescriptors',[partial],'Wallaby Extinct')
  if getattr(self,'pruned_nodes',False):
   rpc(self.core,'generatetoaddress',[600,miner])
   for height in range(1,rpc(self.core,'getblockcount')+1):rpc(self.receiver.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
   for core in (self.core,self.receiver.core):rpc(core,'pruneblockchain',[300]);self.assertGreater(rpc(core,'getblockchaininfo')['pruneheight'],2)
  self.discover();key=self.incoming('Wallaby Extinct');self.assertIsNotNone(key)
  p=self.store.read()['pending'][key]['proposal'];self.assertEqual(len(p['public_wallet']['descriptors']),2)
  if getattr(self,'retained_stage',False):
   from sync_table import choose,state as table
   from sync_approvals import groups
   choose(self.store,key,True,True)
   for _ in range(3):
    self.discover();self.assertEqual(self.incoming('Wallaby Extinct'),key);self.assertTrue(self.store.read()['sync_choices'][key]['selected']);self.assertTrue(any(key in g['keys'] for g in groups(self.store)))
   view=self.receive.state();rows=view['wallets'];self.assertFalse(any(__import__('wallet_visibility').internal(r['wallet_name']) for r in rows));self.assertEqual(next(r for r in rows if r['policy_id']==__import__('sync_preferences').policy_id(p))['availability'],'ready');self.assertEqual([r['wallet_name'] for r in rows if r['availability']=='ready'],['Wallaby Extinct']);self.assertTrue(all(r['availability']=='denied' for r in rows if r['wallet_name']!='Wallaby Extinct'))
  self.approve(key,True)
  from extinct_upgrade import snapshot as snap
  source=snap(self.core,'extinct_watch');received=snap(self.receiver.core,'Wallaby Extinct')
  self.assertEqual(source['addresses'],received['addresses']);self.assertEqual(source['txids'],received['txids']);self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[old],'Wallaby Extinct')['labels'],[lost])
  self.discover();self.assertIsNone(self.incoming('Wallaby Extinct'))
  if getattr(self,'denial_growth',False):
   from sync_preferences import change
   def add():
    address=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+address+')';rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now','label':'Additional retired history'}]],'extinct_watch')
   add();self.discover();key=self.incoming('Wallaby Extinct');self.assertIsNotNone(key);change(self.store,key,True)
   add();self.discover();self.assertIsNone(self.incoming('Wallaby Extinct'))
   self.assertTrue(any(o['public_wallet']['wallet_name']=='Wallaby Extinct' and o['status']=='disabled' for o in self.store.read()['direct_sync_offers'].values()))
 def test_retained_history_stage_never_shadows_extinct_or_loses_receive_selection(self):
  self.retained_stage=True;self.test_whole_extinct_history_updates_partial_receiver_and_keeps_lost_labels()
  self.assertIn(self.retained_stage_name,{r['name'] for r in rpc(self.core,'listwalletdir')['wallets']})
  self.assertEqual(rpc(self.core,'listlabels',[],self.retained_stage_name),['Stale retained staging label'])
 def test_extinct_same_addresses_but_missing_transactions_is_offered_as_normal_sync(self):
  self.same_addresses=True;self.test_whole_extinct_history_updates_partial_receiver_and_keeps_lost_labels()
 def test_old_and_new_vault_policies_transfer_watch_only_without_private_signer_clone(self):
  self.boot('vault');self.discover();key=self.incoming();self.assertIsNotNone(key)
  p=self.store.read()['pending'][key]['proposal'];self.assertFalse(p['source_has_private_keys']);self.assertEqual(len(p['public_wallet']['descriptors']),4)
  self.approve(key,True)
  names=rpc(self.receiver.core,'listwallets');self.assertTrue(names);self.assertTrue(all(not rpc(self.receiver.core,'getwalletinfo',[],name)['private_keys_enabled'] for name in names))
 def test_pruned_agents_offer_and_merge_complete_extinct_history_without_server_jobs(self):
  from regtest_support import Regtest
  self.source.close();self.receiver.close()
  self.source=Regtest(['-prune=1','-txindex=0','-fastprune=1']);self.receiver=Regtest(['-prune=1','-txindex=0','-fastprune=1']);self.addCleanup(self.source.close);self.addCleanup(self.receiver.close);self.core=self.source.core
  rpc(self.core,'createwallet',{'wallet_name':'Miner'});rpc(self.core,'generatetoaddress',[1,rpc(self.core,'getnewaddress',[],'Miner')])
  self.pruned_nodes=True;self.test_whole_extinct_history_updates_partial_receiver_and_keeps_lost_labels()
 def test_extinct_denial_survives_real_source_archive_growth(self):
  self.denial_growth=True;self.test_whole_extinct_history_updates_partial_receiver_and_keeps_lost_labels()
 def test_managed_monitor_subset_does_not_appear_as_a_separate_wallet(self):
  self.boot('vault');name='Wallaby policy '+'a'*20
  rpc(self.core,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True})
  rpc(self.core,'importdescriptors',[[{**r,'timestamp':'now','active':False} for r in self.raw['descriptors'][:2]]],name)
  rows=snapshot(self.core,self.sender)['wallets'];self.assertFalse(any(r['public_wallet']['wallet_name']==name for r in rows));self.discover();self.assertIsNotNone(self.incoming())
 def test_extinct_preview_failure_keeps_exact_archive_visible_then_recovers_after_enable(self):
  from vendor.embit.descriptor.checksum import checksum
  from sync_preferences import change,enable,policy_id
  self.boot();address=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+address+')'
  rpc(self.core,'createwallet',{'wallet_name':'extinct_watch','disable_private_keys':True,'blank':True});rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now','label':'Old Treasury | LOST:06/11/2026 01:02:03 UTC'}]],'extinct_watch')
  import threading
  held=threading.Event()
  def inventory_read():
   with self.a.catalogue.lock:held.set();time.sleep(.15)
  reader=threading.Thread(target=inventory_read);reader.start();held.wait(2)
  self.discover();reader.join(2);key=self.incoming('Wallaby Extinct');self.assertIsNotNone(key);ident=policy_id(self.store.read()['pending'][key]['proposal']);change(self.store,key,True);self.discover();self.assertIsNone(self.incoming('Wallaby Extinct'));enable(self.store,ident)
  from wallet_preview import prepare
  def unavailable(core,store,key,p):
   if p['public_wallet']['wallet_name']=='Wallaby Extinct':raise ValueError('Transient local preview failure')
   return prepare(core,store,key,p)
  with patch('wallet_preview.prepare',side_effect=unavailable):self.discover()
  self.assertIsNone(self.incoming('Wallaby Extinct'))
  offers=[o for o in self.store.read()['direct_sync_offers'].values() if o['public_wallet']['wallet_name']=='Wallaby Extinct'];self.assertEqual(len(offers),1);self.assertEqual(offers[0]['status'],'discovery_pending')
  self.discover();self.assertIsNotNone(self.incoming('Wallaby Extinct'));self.approve(self.incoming('Wallaby Extinct'),True)
 def test_source_subsets_cannot_replace_complete_direct_wallet_offer(self):
  self.boot();self.discover();origin=self.a.catalogue.inventory();dest=self.b.catalogue.inventory();offers=self.a.catalogue.proposals(self.a.channel(self.b.identity['identity_key']),origin,dest)
  offer=next(o for o in offers if o['proposal']['public_wallet']['wallet_name']=='Original');bad=copy.deepcopy(offer);bad['proposal']['public_wallet']['descriptors']=bad['proposal']['public_wallet']['descriptors'][:1]
  with self.assertRaisesRegex(ValueError,'complete source'):self.b.catalogue.receive(self.channel,[bad],origin,dest)
  self.assertFalse(self.store.read().get('sync_batch'))

class PreservationReconciliation(DirectCore):
 def test_missing_archive_cancels_but_unloaded_or_authorised_work_is_retained(self):
  p={'kind':'wallet_retire','phase':'preserve','wallet':'Wallaby Extinct','manifest_hash':'a'*64};key=digest(p)
  with self.store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
  with self.store.edit() as state:state['retirement_continuations']={key:{'state':'authorised'}}
  reconcile_preservation(self.receiver.core,self.store);self.assertIn(key,self.store.read()['pending'])
  with self.store.edit() as state:state['retirement_continuations']={}
  reconcile_preservation(self.receiver.core,self.store);self.assertNotIn(key,self.store.read()['pending']);self.assertEqual(self.store.read()['completed'][key]['outcome'],'cancelled_archive_absent')
  result=next(iter(self.store.read()['outbox'].values()))['payload'];self.assertEqual(result['status'],'cancelled');self.assertNotIn('wallet_deleted',result)
  from wallet_retirement import Retirement
  Retirement(self.receiver.core,self.store).cancel_remote(key);self.assertEqual(len(self.store.read()['outbox']),1);self.assertEqual(self.store.read()['completed'][key]['result'],result)
  rpc(self.receiver.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True});rpc(self.receiver.core,'unloadwallet',{'wallet_name':'Wallaby Extinct'})
  with self.store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
  reconcile_preservation(self.receiver.core,self.store);self.assertIn(key,self.store.read()['pending']);self.assertNotIn('Wallaby Extinct',rpc(self.receiver.core,'listwallets'))
