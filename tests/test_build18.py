"""Mixed worker versions, guarded retirement and real-Core deletion checks."""
import copy,json,os,socket,socketserver,struct,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from secure_bridge import compatible,WorkspaceFailure,call,prepare_stop
from worker_upgrade import VERSION,PROTOCOL,current,inspect_legacy,inspect_request,private_idle,identity
from approval_store import Store,digest
from wallet_retirement import Retirement,validate
from wallet_deletion import target,remove
from wallet_ops import rpc
from regtest_support import Regtest

def ready():return {'worker_version':VERSION,'worker_protocol':PROTOCOL,'protected':{'running':True},'busy':False,'viewer_open':False}

class UpgradeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.patches=[patch('runtime.runtime_dir',return_value=self.root),patch('worker_upgrade.root',return_value=self.root)]
  for p in self.patches:p.start();self.addCleanup(p.stop)
 def test_current_worker_is_reused_without_restart(self):
  with patch('secure_bridge._stop_service') as stop:self.assertEqual(compatible(ready()),ready())
  stop.assert_not_called()
 def test_in_use_legacy_is_retained(self):
  for status in [{'busy':True,'viewer_open':False},{'busy':False,'viewer_open':True}]:
   with patch('secure_bridge.call',return_value=status),patch('secure_bridge._stop_service') as stop,self.assertRaisesRegex(WorkspaceFailure,'older protected worker'):compatible(status)
   stop.assert_not_called()
 def test_legacy_prepare_close_refusal_does_not_fall_back_to_inspector(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_rejected','Finish active work.')),patch('worker_upgrade.inspect_legacy') as inspect,self.assertRaisesRegex(WorkspaceFailure,'active work'):prepare_stop({'pid':1})
  inspect.assert_not_called()
 def test_only_exact_unsupported_action_uses_protected_inspection(self):
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_rejected','Unsupported protected action.')),patch('worker_upgrade.inspect_legacy') as inspect:prepare_stop({'pid':1})
  inspect.assert_called_once_with({'pid':1})
 def test_unconfirmed_inspection_never_stops_worker(self):
  with patch('secure_bridge.call',return_value={'busy':False,'viewer_open':False}),patch('secure_bridge.prepare_stop',side_effect=WorkspaceFailure('upgrade_busy','Retained')),patch('secure_bridge._stop_service') as stop,self.assertRaisesRegex(WorkspaceFailure,'Retained'):compatible({})
  stop.assert_not_called();self.assertFalse((self.root/'worker-upgrading').exists())
 def test_verified_idle_worker_replaced_once_and_fresh_version_checked(self):
  with patch('secure_bridge.call',return_value={'busy':False,'viewer_open':False}),patch('secure_bridge.prepare_stop') as gate,patch('secure_bridge._stop_service') as stop,patch('secure_bridge._ensure_running',return_value=ready()) as start:self.assertEqual(compatible({}),ready())
  gate.assert_called_once();stop.assert_called_once();start.assert_called_once();self.assertFalse((self.root/'worker-upgrading').exists())
 def test_new_process_still_old_is_an_error_not_restart_loop(self):
  with patch('secure_bridge.call',return_value={'busy':False,'viewer_open':False}),patch('secure_bridge.prepare_stop'),patch('secure_bridge._stop_service') as stop,patch('secure_bridge._ensure_running',return_value={}),self.assertRaisesRegex(WorkspaceFailure,'still an older build'):compatible({})
  stop.assert_called_once()
 def test_inspector_nonce_and_peer_are_required(self):
  peer={'pid':123,'start':'456'}
  def worker(method,*args,**kwargs):
   if method=='ui.open':
    request=json.loads((self.root/'upgrade-request.json').read_text());(self.root/'upgrade-result.json').write_text(json.dumps({'nonce':'wrong','worker':peer,'ready':True}))
   return {'busy':False,'viewer_open':False}
  with patch('secure_bridge.call',side_effect=worker),self.assertRaises(WorkspaceFailure):inspect_legacy(peer,timeout=.5)
  self.assertFalse((self.root/'upgrade-request.json').exists());self.assertFalse((self.root/'upgrade-result.json').exists())
 def test_inspector_exports_no_private_status(self):
  peer=identity(os.getpid());request={'nonce':'a'*64,'worker':peer,'deadline':time.monotonic()+10};(self.root/'upgrade-request.json').write_text(json.dumps(request))
  def worker(*args,**kw):kw['peer'].update(peer);return {'private':'NEVER-EXPORT-ME'}
  with patch('worker_upgrade.enforce'),patch('secure_bridge.call',side_effect=worker),patch('worker_upgrade.private_idle',return_value=True):self.assertTrue(inspect_request())
  result=json.loads((self.root/'upgrade-result.json').read_text());self.assertEqual(result,{'nonce':'a'*64,'worker':peer,'ready':True});self.assertNotIn('NEVER',json.dumps(result))
 def test_private_idle_preserves_archive_setup_and_real_result_but_not_denials(self):
  state={'busy':False,'archives':{'loaded':[],'staged':[],'reading':False},'pending':[],'setups':[]}
  storage=Store(self.root/'state');storage.queue('partial_sign_result',{'status':'denied'})
  self.assertTrue(private_idle(state));self.assertFalse(private_idle({'busy':False,'archives':{}}))
  for field in ['pending','setups']:
   changed=copy.deepcopy(state);changed[field]=[{'private':'fixture'}];self.assertFalse(private_idle(changed))
  for field in ['loaded','staged','reading']:
   changed=copy.deepcopy(state);changed['archives'][field]=True;self.assertFalse(private_idle(changed))
  storage.queue('partial_sign_result',{'status':'signed','psbt':'fixture'});self.assertFalse(private_idle(state))
 def test_mixed_version_real_unix_protocol_routes_only_explicit_unsupported_to_inspector(self):
  # Actual framed socket and SO_PEERCRED, rather than a mocked bridge API.
  class Handler(socketserver.BaseRequestHandler):
   def handle(self):
    from secure_bridge import receive
    n=int.from_bytes(receive(self.request,4),'big');request=json.loads(receive(self.request,n))
    response={'result':{'protected':{'running':True},'busy':False,'viewer_open':False}} if request['method']=='service_status' else {'error':'Unsupported protected action.'}
    raw=json.dumps(response).encode();self.request.sendall(struct.pack('!I',len(raw))+raw)
  with socketserver.UnixStreamServer(str(self.root/'worker.sock'),Handler) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with patch('secure_bridge.root',return_value=self.root):
     peer={};state=call('service_status',peer=peer);self.assertFalse(current(state));self.assertEqual(peer,identity(os.getpid()))
     with patch('worker_upgrade.inspect_legacy') as inspect:prepare_stop(peer)
     inspect.assert_called_once_with(peer)
   finally:server.shutdown();thread.join()
 def test_retirement_denial_is_delivered_before_cleanup_but_sync_preferences_do_not_block(self):
  from secure_worker import delivery_pending
  self.assertTrue(delivery_pending({'outbox':{'cancel':{'kind':'wallet_retirement_result','payload':{'status':'denied'}}}}))
  self.assertFalse(delivery_pending({'outbox':{'disabled':{'kind':'wallet_sync_preferences','payload':{'status':'denied'}}}}))
 def test_native_close_explains_unsupported_legacy_busy_and_other_failure(self):
  import protected_viewer
  with patch('secure_bridge.call',side_effect=[WorkspaceFailure('worker_rejected','Unsupported protected action.'),{}]),patch('worker_upgrade.private_idle',return_value=True):self.assertTrue(protected_viewer.close_allowed())
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','Local worker timed out.')):self.assertFalse(protected_viewer.close_allowed())
  self.assertEqual(protected_viewer.close_error,'Local worker timed out.')

class DeletionBoundary(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.wallet=self.base/'Old';self.wallet.mkdir();(self.wallet/'wallet.dat').write_bytes(b'SYNTHETIC-NOT-A-WALLET')
  st=self.wallet.stat();db=(self.wallet/'wallet.dat').stat();self.request={'path':str(self.wallet),'directory':[st.st_dev,st.st_ino],'database':[db.st_dev,db.st_ino]}
 def test_exact_approved_directory_removed_without_reading_database_bytes(self):
  self.assertEqual(remove(self.request,[self.base]),{'deleted':True});self.assertFalse(self.wallet.exists())
 def test_outside_location_symlink_extra_files_and_changed_inode_refused(self):
  with self.assertRaises(ValueError):remove(self.request,[])
  (self.wallet/'extra.txt').write_text('unrelated')
  with self.assertRaisesRegex(ValueError,'Unexpected'):remove(self.request,[self.base])
  (self.wallet/'extra.txt').unlink();r=copy.deepcopy(self.request);r['database'][1]+=1
  with self.assertRaisesRegex(ValueError,'changed'):remove(r,[self.base])
  (self.wallet/'wallet.dat').unlink();(self.wallet/'wallet.dat').symlink_to(self.base/'outside')
  with self.assertRaises((ValueError,OSError)):remove(self.request,[self.base])
 def test_archive_cannot_be_deleted(self):
  p=copy.deepcopy(self.request);p['path']=str(self.base/'Wallaby Extinct')
  with self.assertRaises(ValueError):remove(p,[self.base])
 def test_active_posix_database_lock_prevents_deletion(self):
  script='import fcntl,sys; f=open(sys.argv[1],"r+b"); fcntl.lockf(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.readline()'
  child=subprocess.Popen([sys.executable,'-c',script,str(self.wallet/'wallet.dat')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   self.assertEqual(child.stdout.readline().strip(),'locked')
   with self.assertRaises(BlockingIOError):remove(self.request,[self.base])
   self.assertTrue((self.wallet/'wallet.dat').exists())
  finally:child.communicate('\n',timeout=5)
 def test_helper_success_without_actual_directory_removal_is_not_accepted(self):
  from wallet_deletion import delete
  class Handler(socketserver.BaseRequestHandler):
   def handle(self):
    from secure_bridge import receive
    n=int.from_bytes(receive(self.request,4),'big');receive(self.request,n)
    raw=b'{"deleted":true}';self.request.sendall(struct.pack('!I',len(raw))+raw)
  path=self.base/'fake.sock'
  with socketserver.UnixStreamServer(str(path),Handler) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with patch('wallet_deletion.socket_path',return_value=path),self.assertRaisesRegex(ValueError,'still exists'):delete(self.request)
   finally:server.shutdown();thread.join()
 def test_v2_deletion_explicit_and_hash_bound(self):
  from test_build7 import public
  p={'kind':'wallet_retire','version':2,'nonce':'a'*64,'wallet':'Old','public_wallet':public('Old'),'archive_label':'Old history','require_zero_balance':True,'delete_wallet':True,'delete_wallets':[{'wallet':'Old','public_wallet':public('Old'),'private_keys_enabled':True}]};p['request_id']=digest(p);self.assertEqual(validate(p),p)
  for field,value in [('version',1),('delete_wallet',False),('require_zero_balance',False),('wallet','Wallaby Extinct'),('nonce','invalid'),('delete_wallets',[])]:
   q=copy.deepcopy(p);q[field]=value
   with self.assertRaises(ValueError):validate(q)

class RealCoreRetirement(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'state')
  rpc(self.core,'createwallet',{'wallet_name':'Old'});rpc(self.core,'createwallet',{'wallet_name':'Destination'});self.old=rpc(self.core,'getnewaddress',['source'],'Old');self.dest=rpc(self.core,'getnewaddress',[],'Destination');rpc(self.core,'generatetoaddress',[1,self.old]);rpc(self.core,'generatetoaddress',[101,self.dest]);rpc(self.core,'sendall',{'recipients':[self.dest]},'Old');rpc(self.core,'generatetoaddress',[1,self.dest]);self.raw=rpc(self.core,'listdescriptors',[False],'Old')
 def request(self,name,names=None):
  raw=rpc(self.core,'listdescriptors',[False],name);p={'kind':'wallet_retire','version':2,'nonce':'a'*64,'wallet':name,'public_wallet':raw,'archive_label':'Historical source','require_zero_balance':True,'delete_wallet':True,'delete_wallets':[{'wallet':n,'public_wallet':rpc(self.core,'listdescriptors',[False],n),'private_keys_enabled':rpc(self.core,'getwalletinfo',[],n)['private_keys_enabled']} for n in (names or [name])]};p['request_id']=digest(p);self.store.receive(p);return digest(p)
 def local_delete(self,request):return remove(request,[Path(request['path']).parent])
 def test_private_and_watch_copies_deleted_together_and_dashboard_accepts_result(self):
  rpc(self.core,'createwallet',{'wallet_name':'Watch','disable_private_keys':True,'blank':True,'descriptors':True});rpc(self.core,'importdescriptors',{'requests':[{**d,'timestamp':0} for d in self.raw['descriptors']]},'Watch')
  key=self.request('Old',['Old','Watch']);ret=Retirement(self.core,self.store);loss='Historical source | LOST:01/01/2020 00:00:00 UTC';rpc(self.core,'setlabel',[self.old,loss],'Old');rpc(self.core,'setlabel',[self.old,'Different | LOST:02/01/2020 00:00:00 UTC'],'Watch')
  with self.assertRaisesRegex(ValueError,'Conflicting loss'):ret.review(key)
  rpc(self.core,'setlabel',[self.old,'ordinary label'],'Watch');facts=ret.review(key)['retirement'];self.assertEqual(facts['local_wallets'],['Old','Watch'])
  with patch('wallet_deletion.delete',side_effect=self.local_delete):self.assertIn('deleted',ret.approve(key)['message'])
  for name in ['Old','Watch']:
   self.assertNotIn(name,rpc(self.core,'listwallets'));self.assertNotIn(name,[w['name'] for w in rpc(self.core,'listwalletdir')['wallets']])
  for item in facts['deletion']:self.assertFalse(Path(item['target']['path']).exists())
  self.assertEqual(rpc(self.core,'getaddressinfo',[self.old],'Wallaby Extinct')['labels'],[loss])
  result=next(x['payload'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_retirement_result');self.assertTrue(result['wallet_deleted']);self.assertEqual(result['deleted_wallets'],['Old','Watch'])
  import importlib.util
  fixture=Path(__file__).parent/'fixtures/dashboard_retirement_v2.py';spec=importlib.util.spec_from_file_location('dashboard_retirement_contract',fixture);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  state={'requests':{key:{'kind':'wallet_retire','node_id':'fixture-node','delivered':True,'proposal':{'version':2,'wallet':'Old','delete_wallets':[{'wallet':n} for n in ['Old','Watch']]},'state':'pending'}}};module.result(state,'fixture-node',result);self.assertEqual(state['requests'][key]['state'],'complete')
 def test_watch_only_holder_can_retire_without_a_private_signer_loaded(self):
  rpc(self.core,'createwallet',{'wallet_name':'Watch','disable_private_keys':True,'blank':True,'descriptors':True});rpc(self.core,'importdescriptors',{'requests':[{**d,'timestamp':0} for d in self.raw['descriptors']]},'Watch');rpc(self.core,'unloadwallet',['Old'])
  key=self.request('Watch');ret=Retirement(self.core,self.store);facts=ret.review(key)['retirement'];self.assertTrue(facts['watch_only']);self.assertEqual(facts['local_wallets'],['Watch'])
  with patch('wallet_deletion.delete',side_effect=self.local_delete):ret.approve(key)
  self.assertNotIn('Watch',[w['name'] for w in rpc(self.core,'listwalletdir')['wallets']]);self.assertTrue(Path(self.core.config['cookie']).parent.joinpath('wallets/Old/wallet.dat').exists())
 def test_shared_multisig_monitor_and_dedicated_local_keys_are_reviewed_then_deleted(self):
  from vendor.embit.descriptor import Descriptor
  from vendor.embit.descriptor.checksum import checksum
  sources=[]
  for name in ['KeyA','KeyB']:
   rpc(self.core,'createwallet',{'wallet_name':name});sources.append(rpc(self.core,'listdescriptors',[False],name)['descriptors'])
  requests=[]
  for internal in [False,True]:
   keys=[str(Descriptor.from_string(next(d['desc'] for d in rows if d.get('internal')==internal and d['desc'].startswith('wpkh('))).keys[0]) for rows in sources];body='wsh(sortedmulti(2,'+','.join(keys)+'))';requests.append({'desc':body+'#'+checksum(body),'timestamp':0,'active':True,'internal':internal,'range':[0,100]})
  rpc(self.core,'createwallet',{'wallet_name':'Shared','disable_private_keys':True,'blank':True,'descriptors':True});self.assertTrue(all(r['success'] for r in rpc(self.core,'importdescriptors',{'requests':requests},'Shared')))
  address=rpc(self.core,'getnewaddress',[],'Shared');rpc(self.core,'sendtoaddress',[address,'1'],'Destination');rpc(self.core,'generatetoaddress',[1,self.dest]);psbt=rpc(self.core,'walletcreatefundedpsbt',[[],[{self.dest:1}],0,{'subtractFeeFromOutputs':[0]},True],'Shared')['psbt']
  for name in ['KeyA','KeyB']:psbt=rpc(self.core,'walletprocesspsbt',{'psbt':psbt,'sign':True,'finalize':False},name)['psbt']
  final=rpc(self.core,'finalizepsbt',[psbt]);self.assertTrue(final['complete']);rpc(self.core,'sendrawtransaction',[final['hex']]);rpc(self.core,'generatetoaddress',[1,self.dest])
  key=self.request('Shared',['KeyA','KeyB','Shared']);ret=Retirement(self.core,self.store);facts=ret.review(key)['retirement'];self.assertEqual(facts['local_wallets'],['KeyA','KeyB','Shared'])
  with patch('wallet_deletion.delete',side_effect=self.local_delete):ret.approve(key)
  self.assertFalse(set(['KeyA','KeyB','Shared'])&set(rpc(self.core,'listwallets')));self.assertIn('Destination',rpc(self.core,'listwallets'))
 def test_loaded_real_core_sqlite_wallet_cannot_be_deleted(self):
  request=target(self.core,'Old')
  with self.assertRaises(BlockingIOError):self.local_delete(request)
  self.assertIn('Old',rpc(self.core,'listwallets'));self.assertTrue(Path(request['path']).exists())
 def test_funded_after_review_refuses_archive_and_deletion(self):
  key=self.request('Old');ret=Retirement(self.core,self.store);ret.review(key);rpc(self.core,'sendtoaddress',[self.old,'1'],'Destination');rpc(self.core,'generatetoaddress',[1,self.dest])
  with patch('wallet_deletion.delete') as delete,self.assertRaises(ValueError):ret.approve(key)
  delete.assert_not_called();self.assertIn('Old',rpc(self.core,'listwallets'))
 def test_missing_or_mismatched_local_targets_block_before_archiving(self):
  key=self.request('Old');p=self.store.read()['pending'][key]['proposal'];p['delete_wallets'][0]['private_keys_enabled']=False;p.pop('request_id');p['request_id']=digest(p);self.store.receive(p)
  with patch('wallet_deletion.delete') as delete,self.assertRaisesRegex(ValueError,'private-key status'):Retirement(self.core,self.store).review(digest(p))
  delete.assert_not_called();self.assertNotIn('Wallaby Extinct',rpc(self.core,'listwallets'))
 def test_helper_failure_never_reports_complete_or_replays_request(self):
  key=self.request('Old');ret=Retirement(self.core,self.store);ret.review(key)
  with patch('wallet_deletion.delete',side_effect=ValueError('Local deletion refused.')),self.assertRaises(ValueError):ret.approve(key)
  saved=self.store.read();self.assertEqual(saved['pending'][key]['state'],'attempted');self.assertTrue(Path(self.core.config['cookie']).parent.joinpath('wallets/Old/wallet.dat').exists());self.assertFalse(any(i['payload'].get('status')=='complete' for i in saved['outbox'].values()))
  with self.assertRaisesRegex(ValueError,'Review'):ret.approve(key)

if __name__=='__main__':unittest.main()
