"""Core-native history, LOST labels, local eligibility and offline block catch-up."""
import copy,hashlib,json,os,socket,struct,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from regtest_support import Regtest
from wallet_ops import rpc
from approval_store import Store,digest
from test_build62 import ExtinctionRecovery
from core_history import collect,install,merge_backup,validate_rows
from archive_swap import exchange
from wallet_deletion import remove
from retirement_phases import imports,readback,review
from wallet_recovery import staging_timestamp
from chain_sync import send,receive,finish
from peer_wallet import frame_read,frame_write,read_exact

class NativeHistory(ExtinctionRecovery):
 def helpers(self):
  allowed=[Path(self.core.config['cookie']).parent/'wallets']
  return [patch('archive_swap.swap',side_effect=lambda a,b:exchange(a,b,allowed)),patch('wallet_deletion.delete',side_effect=lambda r,**kw:remove(r,allowed,allow_extinct=True))]
 def rows(self):
  with tempfile.TemporaryDirectory() as d:return collect(self.core,['Old'],[r['txid'] for r in self.p['manifest']['transactions']],d)
 def test_native_merge_preserves_incoming_and_final_outgoing_without_blocks(self):
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  a,b=self.helpers()
  with a,b,patch('core_history.rpc',wraps=rpc) as calls:install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  self.assertFalse(any(c.args[1] in ('rescanblockchain','getblock','stop','importprunedfunds') for c in calls.call_args_list));readback(self.core,self.p)
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2);self.assertFalse(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['private_keys_enabled'])
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['birthtime'],0)
  self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_repeating_native_merge_is_idempotent(self):
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  for _ in range(2):
   a,b=self.helpers()
   with a,b:install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2)
 def test_lost_labels_are_unchanged_through_native_merge_and_reload(self):
  lost='Treasury | LOST:02/01/2020 03:04:05 UTC';self.p['manifest']['addresses'][0]['label']=lost
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  a,b=self.helpers()
  with a,b:install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  rpc(self.core,'unloadwallet',['Wallaby Extinct']);rpc(self.core,'loadwallet',['Wallaby Extinct'])
  self.assertEqual(rpc(self.core,'getaddressinfo',[self.p['manifest']['addresses'][0]['address']],'Wallaby Extinct')['labels'],[lost])
 def test_wrong_hash_and_missing_spending_record_refuse_before_replacement(self):
  rows=self.rows();bad=copy.deepcopy(rows);bad[0]['record']='00'*100
  with self.assertRaises(ValueError):validate_rows(self.core,bad,self.p['manifest'])
  with self.assertRaises(ValueError):validate_rows(self.core,rows[:1],self.p['manifest'])
 def test_approval_uses_native_records_and_does_not_delete_source(self):
  from wallet_retirement import Retirement
  owner=Retirement(self.core,self.store);facts=owner.review(self.key)['retirement'];self.assertEqual(facts['history_method'],'native')
  a,b=self.helpers()
  with a,b:owner.approve(self.key)
  self.assertTrue(self.store.read()['completed'][self.key]['result']['history_verified']);self.assertIn('Old',rpc(self.core,'listwallets'));readback(self.core,self.p)

class ChainCatchup(unittest.TestCase):
 def setUp(self):
  self.source=Regtest();self.receiver=Regtest();self.addCleanup(self.source.close);self.addCleanup(self.receiver.close)
  rpc(self.source.core,'createwallet',{'wallet_name':'Miner'});a=rpc(self.source.core,'getnewaddress',[],'Miner');rpc(self.source.core,'generatetoaddress',[15,a])
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name)
 def transfer(self,source=None,receiver=None,store=None):
  source=source or self.source.core;receiver=receiver or self.receiver.core;store=store or self.store
  a,b=socket.socketpair();a.settimeout(20);b.settimeout(20);errors=[]
  def receive_thread():
   try:
    with b,b.makefile('rwb',buffering=0) as stream:receive(receiver,store,stream,frame_read(stream),frame_read,frame_write,read_exact)
   except Exception as e:errors.append(e)
  t=threading.Thread(target=receive_thread);t.start()
  try:
   with a,a.makefile('rwb',buffering=0) as stream:receipt=send(source,stream,frame_read,frame_write)
  finally:t.join(20)
  if errors:raise errors[0]
  self.assertFalse(t.is_alive());return receipt
 def test_core_accepts_blocks_with_p2p_disabled_and_restores_only_on_success(self):
  self.transfer();self.assertEqual(rpc(self.receiver.core,'getbestblockhash'),rpc(self.source.core,'getbestblockhash'))
  self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive']);self.assertEqual(self.store.read()['chain_sync']['state'],'caught_up')
  finish(self.receiver.core,self.store);self.assertTrue(rpc(self.receiver.core,'getnetworkinfo')['networkactive'])
 def test_previously_offline_stays_offline_and_can_send_onward(self):
  rpc(self.receiver.core,'setnetworkactive',[False]);self.transfer();finish(self.receiver.core,self.store);self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive'])
  third=Regtest();self.addCleanup(third.close);other=Store(Path(self.temp.name)/'third');self.transfer(self.receiver.core,third.core,other)
  self.assertEqual(rpc(third.core,'getbestblockhash'),rpc(self.source.core,'getbestblockhash'))
 def test_interrupted_stream_keeps_internet_paused(self):
  a,b=socket.socketpair();errors=[]
  hello={'operation':'chain_sync','version':1,'chain':'regtest','height':15,'hash':rpc(self.source.core,'getbestblockhash')}
  def run():
   try:
    with b,b.makefile('rwb',buffering=0) as stream:receive(self.receiver.core,self.store,stream,hello,frame_read,frame_write,read_exact)
   except Exception as e:errors.append(e)
  t=threading.Thread(target=run);t.start()
  with a,a.makefile('rwb',buffering=0) as stream:self.assertEqual(frame_read(stream)['status'],'chain_state')
  t.join(10);self.assertTrue(errors);self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive']);self.assertEqual(self.store.read()['chain_sync']['state'],'interrupted')

class LocalEligibility(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from test_build30 import public
  self.p={'public_wallet':public('Old'),'manifest':{'addresses':[{'address':'fixture-address','label':'Old | LOST:01/01/2020 00:00:00 UTC'}]},'operation_id':'a'*64}
  self.raw={'descriptors':[{'desc':'addr(fixture-address)#ignored'}]}
 def test_prepared_does_not_authorise_and_completion_survives_store_restart(self):
  from local_extinction import prepare,complete,eligible
  from denial_storage import FileStore
  path=Path(self.tmp.name)/'persist';path.mkdir(mode=0o700);self.store=Store(Path(self.tmp.name)/'ram',persistence=FileStore(path));ident=prepare(self.store,self.p,['Old'])
  def call(c,m,*a,**k):return {'wallets':[]} if m=='listwalletdir' else []
  with patch('wallet_labels.fixed_address',return_value='fixture-address'),patch('local_extinction.rpc',side_effect=call):
   with self.assertRaisesRegex(ValueError,'completed extinction'):eligible(None,self.store,self.raw)
   complete(self.store,ident);reopened=Store(Path(self.tmp.name)/'new-ram',persistence=FileStore(path));self.assertTrue(eligible(None,reopened,self.raw))
 def test_recreated_wallet_and_active_ownership_both_refuse(self):
  from local_extinction import prepare,complete,eligible
  ident=prepare(self.store,self.p,['Old']);complete(self.store,ident)
  with patch('wallet_labels.fixed_address',return_value='fixture-address'),patch('local_extinction.rpc',return_value={'wallets':[{'name':'Old'}]}):
   with self.assertRaisesRegex(ValueError,'exists again'):eligible(None,self.store,self.raw)
  def call(c,m,*a,**k):
   return {'wallets':[]} if m=='listwalletdir' else ['Different name'] if m=='listwallets' else {'descriptors':[]} if m=='listdescriptors' else {'ismine':True}
  with patch('wallet_labels.fixed_address',return_value='fixture-address'),patch('local_extinction.address_only',return_value=False),patch('local_extinction.rpc',side_effect=call):
   with self.assertRaisesRegex(ValueError,'active local wallet'):eligible(None,self.store,self.raw)

class PrunedNativeHistory(unittest.TestCase):
 def test_complete_history_and_lost_survive_pruning_and_full_reindex(self):
  from test_pruned_recovery import padding_block
  from test_build30 import legacy,proposal
  from wallet_retirement import inventory,Retirement
  from core_history import database
  import subprocess
  before=int(time.time())-3*86400;after=before+2*86400
  node=Regtest(['-prune=550','-txindex=0','-fastprune=1','-mocktime='+str(before)]);self.addCleanup(node.close);core=node.core
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);store=Store(tmp.name)
  for name in ('Old','Miner'):rpc(core,'createwallet',{'wallet_name':name})
  old=rpc(core,'getnewaddress',[],'Old');miner=rpc(core,'getnewaddress',[],'Miner');rpc(core,'generatetoaddress',[1,old]);rpc(core,'generatetoaddress',[101,miner]);rpc(core,'sendall',{'recipients':[miner]},'Old');rpc(core,'generatetoaddress',[1,miner])
  raw=rpc(core,'listdescriptors',[False],'Old');facts=inventory(core,store,legacy(raw,[{'wallet':'Old','public_wallet':raw,'private_keys_enabled':True}]))
  manifest={'addresses':[{'address':r['address'],'label':'Old | LOST:02/01/2020 03:04:05 UTC'} for r in facts['addresses']],'transactions':facts['transaction_records']}
  for row in manifest['addresses']:rpc(core,'setlabel',[row['address'],row['label']],'Old')
  p=proposal(raw,manifest,'preserve','Wallaby Extinct');key=digest(p);store.receive(p)
  rpc(core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True,'load_on_startup':True})
  rpc(core,'setmocktime',[after]);padding_block(core,before+600);rpc(core,'generatetoaddress',[310,miner],timeout=120);height=rpc(core,'getblockcount')
  # Keep raw fixture blocks only to simulate a deliberate later full download.
  blocks=[rpc(core,'getblock',[rpc(core,'getblockhash',[h]),0]) for h in range(1,height+1)]
  boundary=rpc(core,'pruneblockchain',[height-288]);self.assertGreater(boundary,103)
  with self.assertRaises(ValueError):rpc(core,'getblock',[manifest['transactions'][0]['blockhash'],0])
  owner=Retirement(core,store);self.assertEqual(owner.review(key)['retirement']['history_method'],'native');owner.approve(key);readback(core,p)
  self.assertEqual(rpc(core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2);self.assertFalse(store.read().get('history_jobs'))
  rpc(core,'stop');node.process.wait(timeout=20)
  binary=os.environ['WALLABY_TEST_BITCOIND'];path=Path(node.root.name)
  # Read the original test port from the bound Core configuration. No real node.
  node.process=subprocess.Popen([binary,'-regtest','-server','-listen=0','-connect=0','-dnsseed=0','-discover=0','-onlynet=ipv6','-prune=550','-txindex=0','-fastprune=1','-mocktime='+str(after),'-datadir='+str(path),'-rpcbind=[::1]','-rpcallowip=::1','-rpcport='+str(core.config['rpc_port']),'-reindex=1','-networkactive=0'],stdout=node.log,stderr=subprocess.STDOUT)
  deadline=time.monotonic()+60
  while time.monotonic()<deadline:
   try:rpc(core,'getblockchaininfo');break
   except Exception:time.sleep(.1)
  else:self.fail('Isolated Core did not restart')
  self.assertIn('Wallaby Extinct',rpc(core,'listwallets'))
  for block in blocks:rpc(core,'submitblock',[block])
  rpc(core,'syncwithvalidationinterfacequeue');readback(core,p)
  for row in manifest['addresses']:self.assertEqual(rpc(core,'getaddressinfo',[row['address']],'Wallaby Extinct')['labels'],[row['label']])
  self.assertEqual(rpc(core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2);self.assertFalse(rpc(core,'getwalletinfo',[],'Wallaby Extinct')['private_keys_enabled']);self.assertTrue(rpc(core,'getblockchaininfo')['pruned'])

class NativeGuards(NativeHistory):
 def test_loaded_database_exchange_is_refused_and_original_retained(self):
  from wallet_deletion import target
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'public.dat';rpc(self.core,'backupwallet',[str(file)],'Wallaby Extinct');merge_backup(self.core,file,rows,self.p['manifest'])
   stage='.wallaby-history-testguard';rpc(self.core,'restorewallet',{'wallet_name':stage,'backup_file':str(file),'load_on_startup':False})
   with self.assertRaises(OSError):exchange(target(self.core,'Wallaby Extinct',True),target(self.core,stage,True),[Path(self.core.config['cookie']).parent/'wallets'])
   self.assertIn('Wallaby Extinct',rpc(self.core,'listwallets'))
 def test_failed_final_load_rolls_back_original_public_wallet(self):
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True);failed=[]
  from wallet_deletion import target
  original=target(self.core,'Wallaby Extinct',True)['database']
  def failing(core,method,params=None,wallet=None,**kw):
   if method=='loadwallet' and isinstance(params,dict) and params.get('filename')=='Wallaby Extinct' and not failed:failed.append(True);raise ValueError('fixture load failure')
   return rpc(core,method,params,wallet,**kw)
  with patch('core_history.rpc',side_effect=failing):
   with self.assertRaisesRegex(ValueError,'fixture load failure'):install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  self.assertIn('Wallaby Extinct',rpc(self.core,'listwallets'));self.assertEqual(target(self.core,'Wallaby Extinct',True)['database'],original);self.assertFalse(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['private_keys_enabled']);self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_cleanup_failure_keeps_verified_replacement_and_reports_old_public_copy(self):
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  with patch('archive_swap.cleanup',side_effect=OSError('fixture cleanup failure')):result=install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  self.assertTrue(result['cleanup_required']);readback(self.core,self.p);self.assertEqual(len(self.store.read()['history_cleanup']),1)
 def test_dashboard_cannot_clear_local_extinction_status_without_ssh(self):
  from local_extinction import prepare,complete,restored_from_ssh
  ident=prepare(self.store,self.p,['Old']);complete(self.store,ident)
  with self.assertRaisesRegex(ValueError,'direct SSH'):restored_from_ssh(self.core,self.store,self.p['public_wallet'],'Old')
  self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'complete')

class ChainFailureGuards(ChainCatchup):
 def test_wrong_block_hash_stops_without_internet_fallback(self):
  original_write=frame_write
  def corrupt(stream,value):
   if value.get('operation')=='chain_block':value={**value,'hash':'0'*64}
   return original_write(stream,value)
  with patch('test_build64.frame_write',side_effect=corrupt):
   with self.assertRaises(ValueError):self.transfer()
  self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive']);self.assertEqual(self.store.read()['chain_sync']['state'],'interrupted');self.assertEqual(rpc(self.receiver.core,'getblockcount'),0)
 def test_pruned_sender_gap_refuses_before_streaming_blocks(self):
  def limited(core,method,*args,**kwargs):
   result=rpc(core,method,*args,**kwargs)
   return {**result,'pruned':True,'pruneheight':10} if core is self.source.core and method=='getblockchaininfo' else result
  with patch('chain_sync.rpc',side_effect=limited):
   with self.assertRaisesRegex(ValueError,'pruned blocks'):self.transfer()
  self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive']);self.assertEqual(rpc(self.receiver.core,'getblockcount'),0)
 def test_internet_resume_requires_ending_authorised_batch(self):
  from chain_sync import resume_network
  rpc(self.receiver.core,'setnetworkactive',[False])
  with self.store.edit() as s:s['sync_batch']={'fixture':True}
  with self.assertRaises(ValueError):resume_network(self.receiver.core,self.store)
  self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive'])
  with self.store.edit() as s:s.pop('sync_batch')
  resume_network(self.receiver.core,self.store);self.assertTrue(rpc(self.receiver.core,'getnetworkinfo')['networkactive'])
