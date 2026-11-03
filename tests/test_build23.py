"""Archive queue authority, multi-wallet media and independently verified policies."""
import copy,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store,digest
from archive_requests import snapshot,delete
from archive_format import bundle,validate
from disc_backup import pack,Burner
from disc_restore import Archives
from archive_operations import Operations
from wallet_setup import WalletSetup
from wallet_ops import rpc
from regtest_support import Regtest
from policy_refresh import Refresh,transition
from build8_policy import descriptors
BINARY=os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind')

def task(raw):
 p={'kind':'archive_wallet','version':1,'nonce':__import__('secrets').token_hex(32),'wallet':raw['wallet_name'],'public_wallet':raw,'related_policies':[],'require_local_authorisation':True};p['request_id']=digest(p);return p

def queue(rows,revision=1):return {'kind':'wallet_archive_queue','version':1,'queue_id':'a'*64,'revision':revision,'requests':rows}

def store_pending(s,p):
 with s.edit() as v:v['pending'][digest(p)]={'proposal':p,'state':'pending'}

class LiveArchiveQueue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from test_build7 import public
  self.raw=public();self.p=task(self.raw)
 def test_deleted_archive_is_reported_terminal_and_new_request_is_still_allowed(self):
  p=self.p;s=self.store;snapshot(s,queue([p]));key=digest(p);delete(s,key);self.assertNotIn(key,s.read()['pending']);snapshot(s,queue([p]));self.assertNotIn(key,s.read()['pending']);self.assertEqual(s.read()['completed'][key]['result']['status'],'deleted')
  again=copy.deepcopy(p);again['nonce']='c'*64;again['request_id']=digest({k:v for k,v in again.items() if k!='request_id'});snapshot(s,queue([again],2));self.assertIn(digest(again),s.read()['pending'])
 def test_withdrawal_requires_valid_complete_snapshot_not_disconnect(self):
  s=self.store;snapshot(s,queue([self.p]));before=s.read()['pending'];self.assertTrue(before)
  with self.assertRaises(ValueError):snapshot(s,{'kind':'wallet_archive_queue'})
  self.assertEqual(before,s.read()['pending']);snapshot(s,queue([],2));self.assertFalse(s.read()['pending'])
 def test_reordered_or_forged_snapshot_and_changed_task_id_refused(self):
  snapshot(self.store,queue([self.p],2))
  for p in (queue([],1),queue([],2)):
   with self.assertRaises(ValueError):snapshot(self.store,p)
  changed=copy.deepcopy(self.p);changed['wallet']='someone else'
  with self.assertRaises(ValueError):snapshot(self.store,queue([changed],3))
 def test_legacy_archive_denials_are_removed_without_changing_sync_preferences(self):
  from denial_storage import project,overlay
  sync={'policy_id':'a'*64,'wallet_name':'Sync wallet'};archive={'policy_id':'b'*64,'wallet_name':'Archive wallet','purpose':'archive'}
  state={'pending':{},'archive_exclusions':{'b'*64:archive}};overlay(state,{'version':1,'revision':1,'wallets':{'a'*64:sync,'b'*64:archive}})
  self.assertEqual(state['sync_exclusions'],{'a'*64:sync});self.assertNotIn('archive_exclusions',state);self.assertEqual(project(state,2)['wallets'],{'a'*64:sync})
 def test_withdrawal_does_not_erase_an_authorised_private_capture(self):
  snapshot(self.store,queue([self.p]));k=digest(self.p)
  with self.store.edit() as s:s['pending'][k]['state']='attempted'
  snapshot(self.store,queue([],2));self.assertTrue(self.store.read()['pending'][k]['withdrawn'])

class RealMultiWalletArchive(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.core=self.node.core;self.setup=WalletSetup(self.core,self.store,binary=BINARY);self.archives=Archives(self.core,self.store,BINARY,lambda:None);self.ops=Operations(self.core,self.store,self.setup,self.archives,lambda:None)
  self.addCleanup(self.close_archives)
 def close_archives(self):
  import node_client
  node_client.LOCAL_ROUTER=None
  for ident in list(self.archives.loaded):self.archives.unload(ident)
 def test_two_existing_wallets_one_encrypted_package_restore_and_sign(self):
  tasks=[]
  for name in ('Treasury','SMSF'):
   rpc(self.core,'createwallet',{'wallet_name':name,'passphrase':'fixture-wallet-password'});address=rpc(self.core,'getnewaddress',['Owner '+name],name)
   tasks.append(task(rpc(self.core,'listdescriptors',[False],name)))
  snapshot(self.store,queue(tasks))
  for p in tasks:self.ops.review(digest(p));self.ops.approve(digest(p))
  self.setup.burner.select(list(self.ops.jobs));self.setup.burner.combine();job=self.setup.burner.job;self.assertEqual(job['recovery']['version'],2);self.assertEqual(len(job['recovery']['entries']),2)
  disc=pack(self.root/'optical',job['wallets'],job['recovery'],'fixture-backup-password');stage=self.root/'read';stage.mkdir();review=self.archives.inspect_package(disc/'recovery.wallaby','fixture-backup-password',stage);self.assertEqual(len(review['entries']),2)
  for r in review['entries']:self.archives.load(r['id'],True)
  import node_client
  node_client.LOCAL_ROUTER=self.archives
  restored=[r['keys'][0] for r in self.archives.loaded.values()];self.assertEqual(len(restored),2)
  for name in restored:
   info=rpc(self.core,'getwalletinfo',[],name);self.assertEqual(info['wallaby_storage'],'disc');self.assertTrue(info['private_keys_enabled']);self.assertEqual(info['unlocked_until'],0)
  # Queuing and package creation never counts as physical read-back completion.
  results=[v['payload'] for v in self.store.read()['outbox'].values() if v['kind']=='archive_queue_result'];self.assertEqual({r['status'] for r in results},{'queued'})
  entries=list(self.archives.loaded);self.ops.queue_loaded(entries,True);items=[(k,{k:str(self.archives.loaded[i]['wallet'])},self.archives.loaded[i]['recovery']) for k,i in zip(list(self.ops.jobs)[-2:],entries)]
  self.assertEqual(len(self.ops.replacements(items)),1);self.assertFalse(self.ops.replacements(items[:1]))
 def test_disc_only_source_and_descriptor_substitution_cannot_authorise_node_backup(self):
  rpc(self.core,'createwallet',{'wallet_name':'Original','passphrase':'fixture-wallet-password'});p=task(rpc(self.core,'listdescriptors',[False],'Original'));snapshot(self.store,queue([p]));self.archives.loaded={'fake':{'routes':{'Original':'archive-key'}}}
  with self.assertRaisesRegex(ValueError,'persistent'):self.ops.review(digest(p))
  self.archives.loaded={}
 def test_single_generic_burn_is_converted_to_container_even_without_checkbox_edit(self):
  rpc(self.core,'createwallet',{'wallet_name':'One','passphrase':'fixture-wallet-password'});p=task(rpc(self.core,'listdescriptors',[False],'One'));snapshot(self.store,queue([p]));self.ops.review(digest(p));self.ops.approve(digest(p));self.setup.burner.combine();self.assertEqual(self.setup.burner.job['recovery']['version'],2)

class ReadbackAndCoverage(unittest.TestCase):
 def test_replacement_cannot_drop_old_public_policy_or_label(self):
  from test_build7 import public
  raw=public();old={'kind':'node_wallet','public_wallet':raw,'chain':'regtest','public_policies':raw,'policy_extensions':[],'policy_labels':[{'address':'trusted','label':'Owner'}]};new=copy.deepcopy(old);new['policy_labels']=[]
  o=Operations.__new__(Operations);self.assertFalse(o.covers(new,old));self.assertTrue(o.covers(old,old))
 def test_destroy_request_requires_local_verified_replacement_evidence(self):
  o=Operations.__new__(Operations);o.verified_replacements={};p={'archive_id':'b'*64,'replacement_image_sha256':'c'*64}
  with self.assertRaisesRegex(ValueError,'Do not destroy'):o.destruction_proof(p)
  o.verified_replacements[p['archive_id']]={'image_sha256':'c'*64,'members':['d'*64],'readback_verified':True,'old_policies_retained':True};self.assertTrue(o.destruction_proof(p)['readback_verified'])

class RealVaultRefresh(unittest.TestCase):
 def test_three_of_five_two_refreshes_archived_key_and_public_policy_history(self):
  from decimal import Decimal
  from vendor.embit.descriptor.checksum import checksum
  from wallet_ops import WalletOps
  node=Regtest();self.addCleanup(node.close);core=node.core;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name);store=Store(root/'state');setup=WalletSetup(core,store,binary=BINARY);pool=Archives(core,store,BINARY,lambda:None);archive_ops=Operations(core,store,setup,pool,lambda:None);manager=Refresh(core,store,pool)
  import node_client
  def cleanup():
   node_client.LOCAL_ROUTER=None
   for ident in list(pool.loaded):pool.unload(ident)
  self.addCleanup(cleanup)
  rpc(core,'createwallet',{'wallet_name':'Miner'});mining=rpc(core,'getnewaddress',[],'Miner');rpc(core,'generatetoaddress',[101,mining]);keys={0:[],1:[]}
  for i in range(5):
   name='Key '+str(i);rpc(core,'createwallet',{'wallet_name':name,'passphrase':'fixture-wallet-password'});raw=rpc(core,'listdescriptors',[False],name)
   for branch in (0,1):keys[branch].append(next(r['desc'].split('#')[0][5:-1] for r in raw['descriptors'] if r.get('active') and bool(r.get('internal'))==bool(branch) and r['desc'].startswith('wpkh(')))
  def policies(height):
   out=[]
   for branch in (0,1):
    body='wsh(and_v(v:after('+str(height)+'),multi(3,'+','.join(keys[branch])+')))';out.append(body+'#'+checksum(body))
   return out
  first_height=rpc(core,'getblockcount')+3;old=policies(first_height);rpc(core,'createwallet',{'wallet_name':'Treasury','disable_private_keys':True,'blank':True,'descriptors':True});rpc(core,'importdescriptors',[[{'desc':d,'timestamp':'now','range':[0,999],'active':True,'internal':bool(i)} for i,d in enumerate(old)]],'Treasury');first_address=rpc(core,'deriveaddresses',[old[0],[0,0]])[0];rpc(core,'sendtoaddress',[first_address,'2'],'Miner');rpc(core,'generatetoaddress',[1,mining])
  raw=rpc(core,'listdescriptors',[False],'Key 0');p=task(raw);p['related_policies']=[rpc(core,'listdescriptors',[False],'Treasury')];p.pop('request_id');p['request_id']=digest(p);snapshot(store,queue([p]));archive_ops.review(digest(p));archive_ops.approve(digest(p));setup.burner.combine();job=setup.burner.job;disc=pack(root/'disc',job['wallets'],job['recovery'],'fixture-backup-password');stage=root/'read';stage.mkdir();reviews=pool.inspect_package(disc/'recovery.wallaby','fixture-backup-password',stage)['entries'];pool.load(reviews[0]['id'],True);node_client.LOCAL_ROUTER=pool;record=next(iter(pool.loaded.values()));archive_key=record['keys'][0];archive_monitor=record['monitor'];persistent_monitor='Treasury'
  for iteration in (1,2):
   current_height=restricted_height=__import__('wallet_setup_signing').restricted(old[0])['height'];new=policies(current_height+4);new_address=rpc(core,'deriveaddresses',[new[0],[iteration,iteration]])[0]
   for alias in (archive_monitor,persistent_monitor):
    proposal={'kind':'wallet_policy_refresh','version':1,'request_id':digest({'round':iteration,'wallet':alias}),'chain':'regtest','wallet':alias,'previous_descriptors':old,'receive_descriptor':new[0],'change_descriptor':new[1],'timestamp':0,'expires_at':int(time.time())+3600};store_pending(store,proposal);k=digest(proposal);review=manager.review(k);self.assertEqual(review['refresh']['funded_outputs'],[])
    # A new, independently scanned and unfunded future policy needs no old
    # blocks: preserve pruning and avoid an unnecessary genesis rescan.
    with patch('wallet_recovery.history_missing',side_effect=AssertionError('Unfunded future policy must not require old blocks')):manager.approve(k)
    response=next(v['payload']['message'] for v in reversed(list(store.read()['outbox'].values())) if v['kind']=='wallet_policy_refresh_result' and v['payload']['message']['request_id']==proposal['request_id'])
    if alias==archive_monitor:next_archive_monitor=response['monitor_wallet']
    else:next_persistent_monitor=response['monitor_wallet']
   self.assertTrue(rpc(core,'getaddressinfo',[new_address],next_archive_monitor).get('ismine') or rpc(core,'getaddressinfo',[new_address],next_archive_monitor).get('iswatchonly'))
   coin=next(r for r in rpc(core,'listunspent',[1],persistent_monitor) if r['address']==first_address);amount=Decimal(str(coin['amount']))-Decimal('0.00005');unsigned=rpc(core,'createpsbt',[[{'txid':coin['txid'],'vout':coin['vout'],'sequence':0xfffffffe}],{new_address:str(amount)},current_height]);filled=rpc(core,'walletprocesspsbt',[unsigned,False],persistent_monitor)['psbt']
   ops=WalletOps(core,store);request={'kind':'sign_psbt_partial','request_id':digest({'round':iteration,'sign':'archive'}),'chain':'regtest','wallet':archive_key,'psbt':filled,'output_policies':[{'policy_hash':review['refresh']['policy_hash'],'descriptor':new[0],'index':iteration,'address':new_address,'amount_sats':str(int(amount*100000000))}]};store_pending(store,request);ident=digest(request);shown=ops.prepare_request(ident);self.assertIn(current_height+4,[r['height'] for r in shown['unlock_estimates']]);self.assertTrue(all('utc' in r and 'local' in r for r in shown['unlock_estimates']));ops.sign(ident,'fixture-wallet-password','partial',fee_ack=True);partial=next(v['payload']['psbt'] for v in reversed(list(store.read()['outbox'].values())) if v['kind']=='partial_sign_result' and v['payload']['request_hash']==ident)
   for name in ('Key 1','Key 2'):
    rpc(core,'walletpassphrase',['fixture-wallet-password',30],name)
    try:partial=rpc(core,'walletprocesspsbt',[partial],name)['psbt']
    finally:rpc(core,'walletlock',[],name)
   final=rpc(core,'finalizepsbt',[partial]);self.assertTrue(final['complete'])
   if rpc(core,'getblockcount')<current_height:self.assertFalse(rpc(core,'testmempoolaccept',[[final['hex']]])[0]['allowed'])
   missing=current_height-rpc(core,'getblockcount')
   if missing>0:rpc(core,'generatetoaddress',[missing,mining])
   self.assertTrue(rpc(core,'testmempoolaccept',[[final['hex']]])[0]['allowed']);rpc(core,'sendrawtransaction',[final['hex']]);rpc(core,'generatetoaddress',[1,mining]);funds=rpc(core,'listunspent',[1],next_persistent_monitor);self.assertEqual(sum(Decimal(str(c['amount'])) for c in funds),amount);self.assertEqual(funds[0]['address'],new_address)
   self.assertTrue(descriptors({'wallet_name':'old','descriptors':[{'desc':d} for d in old]})<=descriptors(rpc(core,'listdescriptors',[False],persistent_monitor)))
   old=new;first_address=new_address;archive_monitor=next_archive_monitor;persistent_monitor=next_persistent_monitor
  self.assertEqual(len(record['recovery']['policy_extensions']),2)
  from policy_refresh import validate_extensions
  self.assertEqual(validate_extensions(record['recovery']),old)
  # A second-generation recovery package preserves both earlier policies and keys.
  archive_ops.queue_loaded([reviews[0]['id']],True);second=setup.burner.pending[-1];wallets,recovery=bundle([second]);path=pack(root/'second-disc',wallets,recovery,'fixture-backup-password')/'recovery.wallaby';pool.unload(reviews[0]['id']);folder=root/'second-read';folder.mkdir();again=pool.inspect_package(path,'fixture-backup-password',folder)['entries'][0];self.assertEqual(len(again['additional_policies']),2);pool.load(again['id'],True);loaded=next(iter(pool.loaded.values()));self.assertEqual(validate_extensions(loaded['recovery']),old);self.assertTrue(rpc(core,'getaddressinfo',[first_address],loaded['monitor']).get('ismine') or rpc(core,'getaddressinfo',[first_address],loaded['monitor']).get('iswatchonly'))

class PolicyOutputBindings(unittest.TestCase):
 def test_script_amount_index_and_local_approval_cannot_be_replaced(self):
  from vendor.embit import bip32
  from vendor.embit.descriptor import Descriptor
  from vendor.embit.descriptor.checksum import checksum
  from vendor.embit.networks import NETWORKS
  from policy_refresh import verify_output_policies
  key=bip32.HDKey.from_seed(b'\x04'*32).to_public().to_base58();old=[];new=[]
  for branch in (0,1):
   a='wpkh('+key+'/'+str(branch)+'/*)';b='wsh(and_v(v:after(100),pk('+key+'/'+str(branch)+'/*)))';old.append(a+'#'+checksum(a));new.append(b+'#'+checksum(b))
  ext={'previous_descriptors':old,'receive_descriptor':new[0],'change_descriptor':new[1],'timestamp':0};self.assertEqual(transition(ext),ext)
  parsed=Descriptor.from_string(new[0]).derive(1);address=parsed.script_pubkey().address(NETWORKS['regtest']);bind={'policy_hash':digest(ext),'descriptor':new[0],'index':1,'address':address,'amount_sats':'10000'};source={'public_policy_updates':{digest(ext):ext}};ops=Mock();ops.store.read.return_value=source
  review={'outputs':[{'n':0,'script':parsed.script_pubkey().data.hex(),'sats':'10000'}]}
  with patch('policy_refresh.rpc',return_value=[address]):verify_output_policies(ops,{'chain':'regtest','output_policies':[bind]},review)
  self.assertEqual(review['outputs'][0]['vault_policy']['height'],100)
  for changed in ({**bind,'amount_sats':'9999'},{**bind,'address':'bcrt1qwrong'},{**bind,'index':1000},{**bind,'policy_hash':'f'*64}):
   with self.subTest(changed=changed),patch('policy_refresh.rpc',side_effect=lambda core,method,*a,**k:[] if method=='listwallets' else [address]),self.assertRaises(ValueError):verify_output_policies(ops,{'chain':'regtest','output_policies':[changed]},copy.deepcopy(review))
  weaker=copy.deepcopy(ext);weaker['previous_descriptors']=new;weaker['receive_descriptor']=new[0];weaker['change_descriptor']=new[1]
  with self.assertRaises(ValueError):transition(weaker)
 def test_cancellation_of_one_combined_wallet_preserves_other_queue_members(self):
  with tempfile.TemporaryDirectory() as folder:
   b=Burner(folder,Mock());b.authorise('first',{'a':'first-path'},{'policy_hash':'a'*64});b.job['_members']=[('first',{'a':'first-path'},{'policy_hash':'a'*64}),('second',{'b':'second-path'},{'policy_hash':'b'*64})];b.cancel_members({'first'});self.assertEqual(b.job['id'],'second');self.assertEqual(b.job['wallets'],{'b':'second-path'})

class UpgradeAndCancellation(unittest.TestCase):
 def test_denial_upgrade_has_distinct_socket_but_keeps_original_preferences(self):
  from denial_storage import socket_path,FileStore
  self.assertNotEqual(socket_path(),socket_path(True))
  self.assertIn('wallaby-agent-denials-v2',str(socket_path()))
  with tempfile.TemporaryDirectory() as d:
   Path(d).chmod(0o700);old=FileStore(d);old.commit(0,{'version':1,'revision':1,'wallets':{'a'*64:{'policy_id':'a'*64,'wallet_name':'Treasury'}}})
   new=FileStore(d);state={};__import__('denial_storage').overlay(state,new.read());self.assertIn('a'*64,state['sync_exclusions']);state['archive_exclusions']={'b'*64:{'policy_id':'b'*64,'wallet_name':'SMSF','purpose':'archive'}};new.commit(1,__import__('denial_storage').project(state,2));self.assertEqual(len(new.read()['wallets']),1)
 def test_signed_policy_result_is_held_when_builder_cancels_its_request(self):
  from cancellation import held_item
  state={'cancelled_requests':{'a'*64:'c'*64}};item={'kind':'wallet_policy_refresh_result','payload':{'message':{'request_hash':'a'*64}}};self.assertTrue(held_item(state,item));self.assertFalse(held_item(state,{'kind':item['kind'],'payload':{'message':{'request_hash':'b'*64}}}))
