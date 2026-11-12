"""Whole-archive migration, not just the current extinction manifest."""
import copy,os,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement
from retirement_phases import prepare_history,readback
from extinct_upgrade import status,snapshot,upgrade,certify
from wallet_recovery import Recovery,staging_timestamp
from wallet_labels import fixed_address
from test_build62 import ExtinctionRecovery
from test_build30 import proposal
from vendor.embit.descriptor.checksum import checksum

class WholeArchive(ExtinctionRecovery):
 def legacy(self):
  rpc(self.core,'createwallet',{'wallet_name':'Long Gone'})
  address=rpc(self.core,'getnewaddress',[],'Long Gone');miner=rpc(self.core,'getnewaddress',[],'Miner')
  rpc(self.core,'generatetoaddress',[1,address]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'sendall',{'recipients':[miner]},'Long Gone');rpc(self.core,'generatetoaddress',[1,miner])
  txids={r['txid'] for r in rpc(self.core,'listtransactions',['*',100,0,True],'Long Gone')}
  rpc(self.core,'setmocktime',[int(time.time())+3*86400]);rpc(self.core,'generatetoaddress',[1,miner])
  label='Long Gone | LOST:02/01/2020 03:04:05 UTC';body='addr('+address+')';desc=body+'#'+checksum(body)
  rpc(self.core,'importdescriptors',[[{'desc':desc,'timestamp':staging_timestamp(self.core),'label':label}]],'Wallaby Extinct')
  from wallet_deletion import target,remove
  old=target(self.core,'Long Gone');rpc(self.core,'unloadwallet',['Long Gone']);remove(old,[Path(self.core.config['cookie']).parent/'wallets'])
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],0)
  return address,label,txids
 def test_same_extinction_recovers_all_old_entries_and_adds_current_history(self):
  address,label,oldtx=self.legacy();owner=Retirement(self.core,self.store)
  facts=owner.review(self.key)['retirement'];self.assertTrue(facts['archive_upgrade']['required']);self.assertEqual(facts['archive_upgrade']['addresses'],1)
  owner.approve(self.key);readback(self.core,self.p)
  for tx in oldtx:self.assertGreater(rpc(self.core,'gettransaction',[tx,True],'Wallaby Extinct')['confirmations'],0)
  self.assertEqual(rpc(self.core,'getaddressinfo',[address],'Wallaby Extinct')['labels'],[label]);self.assertFalse(status(self.core,'Wallaby Extinct')['required'])
  self.assertTrue(self.store.read()['completed'][self.key]['result']['history_verified']);self.assertIn('Old',rpc(self.core,'listwallets'));self.assertNotIn('Long Gone',rpc(self.core,'listwallets'))
  count=rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'];self.assertEqual(count,len(oldtx)+len(self.p['manifest']['transactions']))
  # Coverage lives in the Core wallet, survives reload and a fresh Agent Store.
  rpc(self.core,'unloadwallet',['Wallaby Extinct']);rpc(self.core,'loadwallet',['Wallaby Extinct'])
  other=Store(self.store.root/'fresh-agent');again=proposal(self.raw,self.p['manifest'],'preserve','Wallaby Extinct',operation='d'*64);key=digest(again);other.receive(again);owner=Retirement(self.core,other)
  with patch('wallet_recovery.Recovery.register_watch_history',side_effect=AssertionError('No second full scan')),patch('retirement_phases.imports',side_effect=AssertionError('No repeated imports')):
   self.assertFalse(owner.review(key)['retirement']['archive_upgrade']['required']);owner.approve(key)
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],count)
 def test_new_uncertified_entry_and_missing_tx_invalidate_coverage(self):
  address,label,txids=self.legacy();upgrade(self.core,self.store,'Wallaby Extinct');self.assertFalse(status(self.core,'Wallaby Extinct')['required'])
  state=snapshot(self.core,'Wallaby Extinct');bad=copy.deepcopy(state);bad['txids']=[]
  from extinct_upgrade import valid
  self.assertFalse(valid(self.core,bad))
  added=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+added+')'
  rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now','label':'Another older entry'}]],'Wallaby Extinct')
  self.assertTrue(status(self.core,'Wallaby Extinct')['required'])
 def test_failed_scan_never_certifies_or_completes_or_deletes(self):
  self.legacy();owner=Retirement(self.core,self.store);owner.review(self.key)
  with patch('wallet_recovery.Recovery.register_watch_history',side_effect=ValueError('fixture scan interrupted')),self.assertRaises(ValueError):owner.approve(self.key)
  self.assertTrue(status(self.core,'Wallaby Extinct')['required']);self.assertNotIn(self.key,self.store.read()['completed']);self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_pruned_review_requires_whole_upgrade_even_with_current_active_source(self):
  self.legacy();real=rpc
  def pruned(core,method,params=None,wallet=None,**kw):
   result=real(core,method,params,wallet,**kw)
   if method=='getblockchaininfo':result=dict(result,pruned=True,pruneheight=100)
   return result
  with patch('extinct_upgrade.rpc',side_effect=pruned):
   facts=Retirement(self.core,self.store).review(self.key)['retirement'];self.assertTrue(facts['history_required']);self.assertIn('whole-history verification record',facts['message'])
   result=prepare_history(self.core,self.store,self.key,self.p);self.assertTrue(result['history_prepared'])
  job=self.store.read()['history_jobs'][digest({'local_retirement_history':self.key})];self.assertTrue(job['extinct_upgrade']);self.assertTrue(all(r['timestamp']==0 for r in job['details']['public_wallet']['descriptors']))
  self.assertEqual(len(job['details']['public_wallet']['descriptors']),1+len(self.p['manifest']['addresses']))
 def test_recovery_rescan_certifies_all_entries_and_requires_separate_preservation(self):
  address,label,txids=self.legacy();prepare_history(self.core,self.store,self.key,self.p)
  recovery=Recovery(self.core,self.store);plan=recovery.plan();self.assertEqual(plan['mode'],'rescan');recovery.start(plan['id']);recovery.thread.join(40)
  self.assertFalse(recovery.thread.is_alive());self.assertEqual(self.store.read()['recovery']['state'],'complete',self.store.read()['recovery'])
  self.assertFalse(status(self.core,'Wallaby Extinct')['required']);self.assertIn(self.key,self.store.read()['pending']);self.assertIn('Old',rpc(self.core,'listwallets'))
  owner=Retirement(self.core,self.store);owner.review(self.key);owner.approve(self.key)
  self.assertEqual(rpc(self.core,'getaddressinfo',[address],'Wallaby Extinct')['labels'],[label]);readback(self.core,self.p)

class PrunedMigration(unittest.TestCase):
 def test_real_missing_blocks_reindex_upgrades_whole_archive_and_reuses_after_pruning(self):
  from regtest_support import Regtest
  from test_pruned_recovery import padding_block
  from test_build30 import legacy
  from wallet_retirement import inventory
  from wallet_recovery import pruning_identity
  from wallet_deletion import target,remove
  import threading
  before=int(time.time())-3*86400;after=int(time.time())
  node=Regtest(['-prune=550','-txindex=0','-fastprune=1','-mocktime='+str(before)]);self.addCleanup(node.close);core=node.core
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);store=Store(tmp.name)
  for name in ('Old','Miner','Gone'):rpc(core,'createwallet',{'wallet_name':name})
  miner=rpc(core,'getnewaddress',[],'Miner');gone=rpc(core,'getnewaddress',[],'Gone');active=rpc(core,'getnewaddress',[],'Old')
  rpc(core,'generatetoaddress',[1,gone]);rpc(core,'generatetoaddress',[101,miner]);rpc(core,'sendall',{'recipients':[miner]},'Gone');rpc(core,'generatetoaddress',[1,miner])
  oldtx={r['txid'] for r in rpc(core,'listtransactions',['*',100,0,True],'Gone')}
  rpc(core,'sendtoaddress',[active,'0.5'],'Miner');rpc(core,'generatetoaddress',[1,miner]);rpc(core,'sendall',{'recipients':[miner]},'Old');rpc(core,'generatetoaddress',[1,miner])
  raw=rpc(core,'listdescriptors',[False],'Old');facts=inventory(core,store,legacy(raw,[{'wallet':'Old','public_wallet':raw,'private_keys_enabled':True}]))
  manifest={'addresses':[{k:r[k] for k in ('address','label')} for r in facts['addresses']],'transactions':facts['transaction_records']};p=proposal(raw,manifest,'preserve','Wallaby Extinct');key=digest(p);store.receive(p)
  rpc(core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True,'load_on_startup':True})
  rpc(core,'setmocktime',[after]);padding_block(core,before+600);rpc(core,'generatetoaddress',[310,miner],timeout=120)
  label='Gone | LOST:02/01/2020 03:04:05 UTC';body='addr('+gone+')'
  rpc(core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':staging_timestamp(core),'label':label}]],'Wallaby Extinct')
  old=target(core,'Gone');rpc(core,'unloadwallet',['Gone']);remove(old,[Path(core.config['cookie']).parent/'wallets'])
  self.assertEqual(rpc(core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],0)
  height=rpc(core,'getblockcount');blocks=[rpc(core,'getblock',[rpc(core,'getblockhash',[h]),0]) for h in range(1,height+1)]
  boundary=rpc(core,'pruneblockchain',[height-288]);self.assertGreater(boundary,105)
  with self.assertRaises(ValueError):rpc(core,'getblock',[rpc(core,'getblockhash',[1]),0])
  manager=Retirement(core,store);self.assertTrue(manager.review(key)['retirement']['history_required']);manager.prepare_history(key)
  recovery=Recovery(core,store);original=pruning_identity(rpc(core,'getblockchaininfo'));real_run=subprocess.run;replayed=[];deadline=time.monotonic()+180
  def deliver():
   try:
    while not store.read().get('recovery',{}).get('replay_ready'):
     if time.monotonic()>deadline:raise TimeoutError('Wallet registration for complete archive replay did not finish')
     time.sleep(.05)
    for block in blocks:rpc(core,'submitblock',[block])
    rpc(core,'syncwithvalidationinterfacequeue');replayed.append(True)
   except Exception as error:replayed.append(repr(error))
  def launch(command,*args,**kw):
   from unittest.mock import Mock
   if command[:3]==['/usr/bin/systemctl','--user','show-environment'] or command[0]=='/usr/bin/systemd-run' and command[-1]=='/usr/bin/true':return Mock(returncode=0)
   if command[0]=='/usr/bin/systemd-run' and command[-1]=='-version':return real_run(command[command.index('--')+1:],capture_output=True,timeout=30)
   if command[0]=='/usr/bin/systemd-run':
    node.process.wait(timeout=15);arguments=command[command.index('--')+1:];node.process=subprocess.Popen(arguments+['-mocktime='+str(after)],stdout=node.log,stderr=subprocess.STDOUT);threading.Thread(target=deliver,daemon=True).start();return Mock(returncode=0)
   return real_run(command,*args,**kw)
  with patch('wallet_recovery.subprocess.run',side_effect=launch):
   plan=recovery.plan();self.assertEqual(plan['mode'],'download');recovery.start(plan['id']);recovery.thread.join(180)
  self.assertFalse(recovery.thread.is_alive());self.assertEqual(store.read()['recovery']['state'],'complete',store.read()['recovery']);self.assertEqual(replayed,[True]);self.assertEqual(pruning_identity(rpc(core,'getblockchaininfo')),original)
  for tx in oldtx:self.assertGreater(rpc(core,'gettransaction',[tx,True],'Wallaby Extinct')['confirmations'],0)
  self.assertEqual(rpc(core,'getaddressinfo',[gone],'Wallaby Extinct')['labels'],[label]);self.assertFalse(status(core,'Wallaby Extinct')['required']);self.assertIn('Old',rpc(core,'listwallets'))
  with patch('wallet_recovery.Recovery.register_watch_history',side_effect=AssertionError('Verified archive must not reindex again')):
   self.assertNotIn(key,store.read()['pending']);self.assertTrue(store.read()['completed'][key]['result']['history_verified']);self.assertFalse(store.read()['completed'][key]['result']['wallet_deleted'])
  rpc(core,'pruneblockchain',[height-288]);rpc(core,'unloadwallet',['Wallaby Extinct']);rpc(core,'loadwallet',['Wallaby Extinct']);self.assertFalse(status(core,'Wallaby Extinct')['required']);readback(core,p)

class RecoveryReload(unittest.TestCase):
 def test_only_local_jobs_reload_existing_wallet_and_check_identity(self):
  from unittest.mock import Mock
  from test_build7 import public
  raw=public('Existing');job={'wallet':'Existing','local_only':True,'expected_private_keys':False,'details':{'public_wallet':raw}}
  def result(core,method,params=None,wallet=None,**kw):
   return {'private_keys_enabled':False} if method=='getwalletinfo' else raw if method=='listdescriptors' else {}
  recovery=Recovery(Mock(),Mock())
  with patch('wallet_recovery.persistent_wallets',return_value=[]),patch('wallet_recovery.rpc',side_effect=result) as call:
   recovery.restore_once('key',job)
   self.assertEqual(sum(c.args[1]=='loadwallet' for c in call.call_args_list),1);self.assertFalse(any(c.args[1]=='importdescriptors' for c in call.call_args_list))
  with patch('wallet_recovery.persistent_wallets',return_value=[]),patch('wallet_recovery.rpc') as call,self.assertRaises(ValueError):recovery.restore_once('key',{**job,'local_only':False})
  call.assert_not_called()
 def test_changed_local_private_capability_refuses_before_import(self):
  from unittest.mock import Mock
  from test_build7 import public
  recovery=Recovery(Mock(),Mock());job={'wallet':'Existing','local_only':True,'expected_private_keys':False,'details':{'public_wallet':public('Existing')}}
  with patch('wallet_recovery.persistent_wallets',return_value=[]),patch('wallet_recovery.rpc',return_value={'private_keys_enabled':True}) as call,self.assertRaises(ValueError):recovery.restore_once('key',job)
  self.assertFalse(any(c.args[1]=='importdescriptors' for c in call.call_args_list))

class CompletionGuards(unittest.TestCase):
 def test_one_pending_block_is_not_misreported_as_missing_legacy_history(self):
  from diagnostics import LocalActionFailure
  state={'info':{'lastprocessedblock':{'height':99}},'addresses':['fixture'],'marker':None,'txids':[]}
  with patch('extinct_upgrade.snapshot',return_value=state),patch('extinct_upgrade.rpc',return_value={'blocks':100,'pruned':True,'pruneheight':50}),self.assertRaises(LocalActionFailure) as error:status(object(),'Extinct')
  self.assertEqual(error.exception.code,'extinct_wallet_sync');self.assertIn('not evidence',str(error.exception))
 def test_partial_descriptor_import_never_counts_as_complete_scan(self):
  from unittest.mock import Mock
  from test_build7 import public
  raw=public('Fixture');second=copy.deepcopy(raw['descriptors'][0]);body=second['desc'].split('#')[0].replace('/0/*','/1/*');second.update(desc=body+'#'+checksum(body),internal=True);raw['descriptors'].append(second)
  with patch('wallet_recovery.rpc',return_value=[{'success':True}]),self.assertRaises(ValueError):Recovery(Mock(),Mock()).register_watch_history('Extinct',{'public_wallet':raw})
