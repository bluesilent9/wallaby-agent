"""Build19 cancellation, diagnostic export and typed public RPC failures."""
import copy,datetime as dt,hashlib,json,multiprocessing,os,secrets,stat,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from cancellation import Cancellations,validate,blocked,held_item
from activity_log import DiagnosticLog,redact,handoff
from cancel_backup import create_export,export_bundle
from secure_bridge import WorkspaceFailure
from wallet_ops import WalletOps,rpc
from wallet_retirement import Retirement
from regtest_support import Regtest

def cancel(builder='transaction',operations=None,hashes=None):
 p={'kind':'builder_cancel','version':1,'builder':builder,'workspace_id':'a'*32,'cancellation_id':'b'*32,'operations':operations or [],'request_hashes':hashes or [],'require_local_authorisation':True,'backup_option':True};p['request_id']=digest(p);return p

def row(message='service connected',origin='unprotected',at=None):return {'id':secrets.token_hex(16),'at':at or time.time(),'origin':origin,'source':'test.event','message':message}

def append_process(path):
 log=DiagnosticLog(path)
 for i in range(12):log.merge([row('concurrent '+str(i))])

class LogTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.log=DiagnosticLog(self.root/'logs')
 def test_typed_redactions_before_storage_and_export(self):
  values=[('xprv'+'A'*100,'private key'),('xpub'+'B'*100,'public key'),('K'+'a'*51,'private key'),('bc1q'+'a'*38,'Bitcoin address'),('1'+'B'*33,'Bitcoin address'),('02'+'a'*64,'key or transaction data'),('cHNidP'+'A'*100,'PSBT'),('wsh(sortedmulti(2,xpubABC))','descriptor'),('password=actual-secret','credential'),('__cookie__:never-export-this','credential')]
  for value,kind in values:
   with self.subTest(kind=kind):
    self.log.merge([row('Wallet Family · '+value)]);text=self.log.text();self.assertNotIn(value,text);self.assertIn('[REDACTED: '+kind+']',text)
    self.assertNotIn(value,b''.join(p.read_bytes() for p in self.log.path.glob('*.log')).decode())
  self.assertIn('Wallet Family',self.log.text())
 def test_merge_sorted_deduplicated_origin_and_restart(self):
  a=row('ordinary',at=time.time()-5);b=row('protected',origin='protected');self.log.merge([b,a,b]);self.log.merge([b]);text=DiagnosticLog(self.log.path).text();self.assertEqual(len(text.splitlines()),2);self.assertTrue(text.splitlines()[0].endswith('ordinary'));self.assertTrue(text.splitlines()[1].endswith('protected'));self.assertIn('· protected ·',text);self.assertIn('· unprotected ·',text)
 def test_retention_and_daily_bounds(self):
  now=time.time();self.log.merge([row('expired',at=now-8*86400),row('recent')]);self.assertNotIn('expired',self.log.text())
  self.log.merge([row('message '+('word '*315)) for _ in range(900)]);self.assertTrue(all(p.stat().st_size<=1024*1024 for p in self.log.path.glob('*.log')))
  old=self.log.path/'diagnostics-2000-01-01.log';old.write_text('expired');self.log.records();self.assertFalse(old.exists());self.assertEqual(stat.S_IMODE(self.log.path.stat().st_mode),0o700)
 def test_cross_process_append_does_not_lose_records(self):
  children=[multiprocessing.Process(target=append_process,args=(self.log.path,)) for _ in range(3)]
  for p in children:p.start()
  for p in children:p.join(10);self.assertEqual(p.exitcode,0)
  self.assertEqual(len(self.log.records()),36)
 def test_symlinks_and_unsafe_permissions_refused(self):
  self.log.merge([row()]);name=next(self.log.path.glob('*.log'));name.unlink();outside=self.root/'outside';outside.write_text('KEEP');name.symlink_to(outside)
  with self.assertRaises((ValueError,OSError)):self.log.merge([row()])
  self.assertEqual(outside.read_text(),'KEEP');name.unlink();self.log.path.chmod(0o755)
  with self.assertRaises(ValueError):self.log.records()
 def test_handoff_persists_only_valid_protected_events(self):
  events=[row('wallet reviewed',origin='protected')]
  with patch('secure_bridge.call',return_value=events),patch('activity_log.DiagnosticLog',return_value=self.log):handoff()
  self.assertIn('wallet reviewed',self.log.text())
  with patch('secure_bridge.call',return_value=[row()]),self.assertRaisesRegex(ValueError,'origin'):handoff()
 def test_handoff_failure_prevents_service_stop(self):
  from secure_bridge import _stop_service
  with patch('activity_log.handoff',side_effect=ValueError('RAM retained')),patch('secure_bridge.subprocess.run') as run,self.assertRaises(ValueError):_stop_service()
  run.assert_not_called()
 def test_old_worker_without_logs_can_close_but_current_cannot_skip(self):
  for version,allowed in [('2.0.0~dev18',True),('2.0.0~dev28',False)]:
   with patch('secure_bridge.call',side_effect=[WorkspaceFailure('worker_rejected','Unsupported protected action.'),{'worker_version':version}]):
    if allowed:handoff()
    else:
     with self.assertRaisesRegex(ValueError,'retained'):handoff()
 def test_protected_location_does_not_touch_persistent_config(self):
  with patch('protected_memory.inside',return_value=True),patch('protected_memory.root',return_value=self.root/'ram'),patch('configuration.Config') as config:
   self.assertEqual(DiagnosticLog().path,self.root/'ram/diagnostics')
  config.assert_not_called()

class CancellationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.core=Mock();self.core.call.return_value={'result':[]};self.ops=SimpleNamespace(prepared={});self.setup=SimpleNamespace(sessions={},disc_sessions={},reviews={},burner=__import__('disc_backup').Burner(self.root/'jobs',lambda *a:None));self.c=Cancellations(self.core,self.store,self.setup,self.ops)
 def test_strict_wire_and_hash(self):
  p=cancel();self.assertEqual(validate(p),p)
  for change in [{'backup_option':False},{'require_local_authorisation':False},{'operations':['../wallet']},{'request_hashes':['a'*32]},{'path':'/home/secret'},{'request_id':'0'*64}]:
   q={**p,**change}
   with self.assertRaises(ValueError):validate(q)
 def test_receipt_is_exact_delivery_only_without_deletion(self):
  p=cancel();key=self.c.receive(p);self.c.receive(p);saved=self.store.read();self.assertIn(key,saved['pending']);self.assertEqual(len(saved['outbox']),1);self.core.call.assert_not_called()
  item=next(iter(saved['outbox'].values()));self.assertEqual(item,{'kind':'builder_cancel_receipt','payload':{'version':1,'cancellation_id':p['cancellation_id'],'request_hash':key,'status':'received'}})
 def test_freezes_original_and_late_replay_and_output(self):
  original={'kind':'sign_psbt_partial','psbt':'fixture'};key=digest(original)
  with self.store.edit() as s:s['pending'][key]={'proposal':original,'state':'pending'}
  self.store.queue('partial_sign_result',{'request_hash':key,'psbt':'fixture-signed'});self.c.receive(cancel(hashes=[key]));s=self.store.read();self.assertEqual(s['pending'][key]['state'],'cancellation_requested');self.assertTrue(blocked(s,original));self.assertTrue(held_item(s,next(i for i in s['outbox'].values() if i['kind']=='partial_sign_result')))
  with patch('vault_policy.validate_proposal',return_value=original):self.assertFalse(self.store.receive(original))
 def test_no_generic_denial_bypass(self):
  key=self.c.receive(cancel())
  with self.assertRaisesRegex(ValueError,'Delete and Cancel'):self.store.deny(key)
 def test_early_cancel_completes_only_after_review_and_preserves_other_requests(self):
  key=self.c.receive(cancel());self.store.queue('other_result',{'status':'signed'})
  with self.assertRaisesRegex(ValueError,'Review'):self.c.confirm(key,'delete')
  self.c.review(key);self.c.confirm(key,'delete');s=self.store.read();self.assertNotIn(key,s['pending']);self.assertIn(key,s['completed']);self.assertTrue(any(x['kind']=='other_result' for x in s['outbox'].values()));self.core.call.assert_not_called()
 def test_active_disc_and_changed_artifacts_block_cleanup(self):
  key=self.c.receive(cancel());self.c.review(key);self.setup.burner.thread=Mock();self.setup.burner.thread.is_alive.return_value=True
  with self.assertRaisesRegex(ValueError,'optical'):self.c.confirm(key,'delete')
  self.setup.burner.thread=None;self.c.review(key)
  with patch.object(self.c,'_facts',return_value={'changed':True,'active_disc_write':False}),self.assertRaisesRegex(ValueError,'changed'):self.c.confirm(key,'delete')
  self.assertEqual(self.store.read()['pending'][key]['state'],'pending')
 def test_backup_failure_never_marks_attempted_or_deletes(self):
  key=self.c.receive(cancel());self.c.review(key)
  with patch.object(self.c,'_backup',side_effect=ValueError('disk full')),patch('wallet_deletion.delete') as delete,self.assertRaisesRegex(ValueError,'disk full'):self.c.confirm(key,'backup')
  delete.assert_not_called();self.assertEqual(self.store.read()['pending'][key]['state'],'pending')
 def test_cancelled_setup_cannot_use_old_discard_actions(self):
  from wallet_setup import WalletSetup
  setup=WalletSetup(self.core,self.store);binding='a'*64
  with self.store.edit() as s:s['cancelled_setups']={binding:'b'*64}
  with self.assertRaisesRegex(ValueError,'Wallet Server requested cancellation'):setup.cancel(binding)
 def test_transaction_broadcast_evidence_from_local_core(self):
  txid='d'*64;original='c'*64
  with self.store.edit() as s:s['completed'][original]={'kind':'broadcast_transaction','artifact_txid':txid}
  def call(ident,method,*args,**kw):return {'result':{'confirmations':3}} if method=='getrawtransaction' else {'error':{'code':-5}} if method=='getmempoolentry' else {'result':[]}
  self.core.call.side_effect=call;key=self.c.receive(cancel(hashes=[original]));facts=self.c.review(key)['cancellation'];self.assertTrue(facts['broadcast_detected']);self.assertEqual(facts['broadcasts'][0]['location'],'chain')
 def test_unknown_history_is_not_claimed_unbroadcast(self):
  txid='d'*64;original='c'*64
  with self.store.edit() as s:s['completed'][original]={'artifact_txid':txid}
  self.core.call.side_effect=lambda ident,method,*args,**kw:{'result':[]} if method=='listwallets' else {'error':{'code':-5}}
  facts=self.c.review(self.c.receive(cancel(hashes=[original])))['cancellation'];self.assertFalse(facts['broadcast_detected']);self.assertTrue(facts['broadcast_incomplete'])
 def test_retirement_withdrawal_tombstone_and_attempted_unknown(self):
  key='e'*64;ret=Retirement(self.core,self.store)
  with self.store.edit() as s:s['pending'][key]={'proposal':{'kind':'wallet_retire'},'state':'pending'}
  ret.cancel_remote(key);s=self.store.read();self.assertNotIn(key,s['pending']);self.assertEqual(s['completed'][key]['result']['status'],'cancelled')
  key='f'*64
  with self.store.edit() as s:s['pending'][key]={'proposal':{'kind':'wallet_retire'},'state':'attempted'}
  ret.cancel_remote(key);s=self.store.read();self.assertIn(key,s['pending']);self.assertTrue(any(i['payload'].get('status')=='error' for i in s['outbox'].values()))
 def test_completed_retirement_reports_actual_outcome(self):
  key='a'*64;result={'request_hash':key,'status':'complete','wallet_deleted':True}
  with self.store.edit() as s:s['completed'][key]={'kind':'wallet_retire','result':result}
  Retirement(self.core,self.store).cancel_remote(key);self.assertEqual(next(iter(self.store.read()['outbox'].values()))['payload'],result)

class ExportBoundary(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def test_no_traversal_symlink_or_overwrite(self):
  request={'export_directory':str(self.root),'export_name':'wallaby-cancel-'+'a'*32+'.wallaby'}
  with patch('cancel_backup.Path.home',return_value=self.root):
   fd=create_export(request);os.close(fd);self.assertEqual(stat.S_IMODE((self.root/request['export_name']).stat().st_mode),0o600)
   with self.assertRaises(FileExistsError):create_export(request)
   for path in [str(self.root/'..'),str(self.root/'missing')]:
    with self.assertRaises((ValueError,OSError)):create_export({**request,'export_directory':path})
   link=self.root/'linked';link.symlink_to(self.root,target_is_directory=True)
   with self.assertRaises(ValueError):create_export({**request,'export_directory':str(link)})

class RealCoreCancellation(unittest.TestCase):
 def setUp(self):
  from wallet_setup import WalletSetup
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.setup=WalletSetup(self.core,self.store,binary=os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind'));self.ops=WalletOps(self.core,self.store);self.c=Cancellations(self.core,self.store,self.setup,self.ops)
  def cleanup():
   for session in self.setup.sessions.values():
    if session.get('core'):session['core'].close()
  self.addCleanup(cleanup)
 def setup_wallet(self,installed=False):
  own=self.setup.own_identity();p={'kind':'wallet_setup','version':1,'session_id':'a'*64,'chain':'regtest','name':'Cancel fixture','threshold':2,'height':50,'expires_at':int(time.time())+3600,'cosigners':[{'id':str(i),'name':'Role '+str(i),'agent_key':own['public_key'],'storage':'disc' if i==2 else 'node'} for i in range(3)]};self.store.receive(p)
  with patch('wallet_setup.secret_dialog',return_value='fixture-Core-passphrase'):self.setup.approve_proposal(digest(p),{own['fingerprint']:own['fingerprint']})
  if installed:
   from setup_policy import policy
   contributions=self.setup.sessions[digest(p)]['contributions'];descs=policy(p,[e['message'] for e in contributions]);complete={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};self.store.receive(complete);self.setup.review(digest(complete))
   with patch('wallet_setup.secret_dialog',return_value='fixture-Core-passphrase'):self.setup.approve_policy(digest(complete))
  return p
 def test_receipt_preserves_keys_then_encrypted_backup_restores_every_wallet(self):
  from disc_backup import decrypt_file
  p=self.setup_wallet();binding=digest(p);session=self.setup.sessions[binding];core=session['core'].core;names=rpc(core,'listwallets');expected={n:rpc(core,'listdescriptors',[False],n) for n in names};key=self.c.receive(cancel('wallet',[binding],[binding]));self.assertIsNone(session['core'].process.poll());self.c.review(key)
  def fd(directory,name):
   with patch('cancel_backup.Path.home',return_value=self.root):return create_export({'export_directory':directory,'export_name':name})
  with patch('wallet_setup.secret_dialog',return_value='fixture-backup-passphrase'),patch.object(self.c,'_directory',return_value=str(self.root)),patch('cancel_backup.export_fd',side_effect=fd),patch('protected_memory.enforce'):result=self.c.confirm(key,'backup')
  self.assertNotIn(binding,self.setup.sessions);self.assertFalse(session['core'].root.exists());archive=self.root/'restore.zip';decrypt_file(Path(result['backup']['path']),archive,'fixture-backup-passphrase')
  with zipfile.ZipFile(archive) as z:
   manifest=json.loads(z.read('manifest.json'));self.assertEqual(len(manifest['wallets']),3)
   for i,w in enumerate(manifest['wallets']):
    temp=self.root/('restore-'+str(i)+'.dat');temp.write_bytes(z.read(w['file']));name='Restored'+str(i);rpc(self.core,'restorewallet',{'wallet_name':name,'backup_file':str(temp)});actual=rpc(self.core,'listdescriptors',[False],name);self.assertEqual(actual['descriptors'],expected[w['name']]['descriptors'])
 def test_installed_group_and_disc_session_cancelled_without_unrelated_deletion(self):
  from wallet_deletion import remove
  rpc(self.core,'createwallet',{'wallet_name':'Unrelated'});p=self.setup_wallet(True);binding=digest(p);session=self.setup.sessions[binding];names=set(session['installed_wallets']);self.assertEqual(len(names),2);key=self.c.receive(cancel('wallet',[binding],[binding]));self.c.review(key)
  with patch('wallet_deletion.delete',side_effect=lambda request,**options:remove(request,[Path(request['path']).parent],**options)):self.c.confirm(key,'delete')
  self.assertFalse(names&set(rpc(self.core,'listwallets')));self.assertIn('Unrelated',rpc(self.core,'listwallets'));self.assertFalse(self.setup.burner.pending);self.assertFalse(self.store.read().get('approved_wallets'));self.assertNotIn('setup_active',self.store.read())

class ContractAndRPCTests(unittest.TestCase):
 def test_current_dashboard_export_binding_exactness(self):
  p=cancel();p.pop('request_id');p['exports']=[{'outbox_id':'c'*64,'txid':'d'*64,'psbt_sha256':'e'*64}];p['request_id']=digest(p);self.assertEqual(validate(p),p)
  q=copy.deepcopy(p);q['exports'][0]['path']='/home/wallet'
  with self.assertRaises(ValueError):validate(q)
 def test_rpc_error_categories_reveal_no_raw_exception(self):
  from diagnostics import describe
  from agent_rpc import PublicDataFailure
  for error,category in [(PublicDataFailure('response_limit','xprv-DO-NOT-LOG'),'response_limit'),(TimeoutError('cookie=SECRET'),'timeout'),(ValueError('wallet private payload'),'response')]:
   failure=describe('rpc',error);self.assertEqual(failure.code,category);self.assertNotIn('SECRET',str(failure));self.assertNotIn('DO-NOT-LOG',str(failure))
 def test_logs_endpoint_auth_and_protected_refusal(self):
  import http.client,threading
  from app import Server,Handler
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}):
   server=Server(('::1',0),Handler);server.token='fixture-token';thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    log=DiagnosticLog();log.merge([row('service test')])
    def request(token):
     connection=http.client.HTTPConnection('::1',server.server_port);connection.request('GET','/api/logs',headers={'Authorization':'Bearer '+token});r=connection.getresponse();result=(r.status,r.getheader('Content-Type'),r.read());connection.close();return result
    self.assertEqual(request('wrong')[0],403);result=request('fixture-token');self.assertEqual(result[0],200);self.assertIn('text/plain',result[1]);self.assertIn(b'service test',result[2])
    with patch('protected_memory.inside',return_value=True):self.assertEqual(request('fixture-token')[0],403)
   finally:server.shutdown();server.server_close();thread.join()

class ExportContractTests(unittest.TestCase):
 def test_export_binding_uses_local_psbt_bytes_and_core_identity(self):
  import base64
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');psbt=base64.b64encode(b'synthetic PSBT bytes').decode();item={'kind':'transaction_builder_psbt','payload':{'psbt':psbt,'txid':'d'*64}};ident=digest(item)
   with store.edit() as state:state['delivered_artifacts']={ident:item}
   p=cancel();p.pop('request_id');p['exports']=[{'outbox_id':ident,'txid':'d'*64,'psbt_sha256':hashlib.sha256(base64.b64decode(psbt)).hexdigest()}];p['request_id']=digest(p)
   core=Mock();core.call.return_value={'result':{'tx':{'txid':'d'*64}}};c=Cancellations(core,store,SimpleNamespace(sessions={}),SimpleNamespace(prepared={}))
   saved,keys,proposals,psbts,txids,wallets,sessions=c._data(p);self.assertEqual(psbts,[psbt]);self.assertEqual(txids,{'d'*64})
   p['exports'][0]['psbt_sha256']='e'*64
   with self.assertRaisesRegex(ValueError,'differs'):c._data(p)
 def test_actual_fd_transfer_accepts_one_write_only_owned_file(self):
  import array,socket,socketserver,struct,threading
  from cancel_backup import export_fd
  from secure_bridge import receive
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'export.sock';name='wallaby-cancel-'+'f'*32+'.wallaby'
   class Handler(socketserver.BaseRequestHandler):
    def handle(self):
     n=int.from_bytes(receive(self.request,4),'big');request=json.loads(receive(self.request,n))
     with patch('cancel_backup.Path.home',return_value=root):fd=create_export(request)
     try:
      data=b'{"export":true}';self.request.sendmsg([struct.pack('!I',len(data))+data],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
     finally:os.close(fd)
   with socketserver.UnixStreamServer(str(path),Handler) as server:
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
     with patch('wallet_deletion.socket_path',return_value=path):fd=export_fd(str(root),name)
     try:os.write(fd,b'CIPHERTEXT-FIXTURE')
     finally:os.close(fd)
     self.assertEqual((root/name).read_bytes(),b'CIPHERTEXT-FIXTURE')
    finally:server.shutdown();thread.join()

class RetirementRaceTests(unittest.TestCase):
 def test_inflight_archive_withdrawal_stops_before_wallet_deletion(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');key='a'*64;p={'kind':'wallet_retire','version':2};facts={'addresses':[{'address':'fixture','label':'history'}]};ret=Retirement(Mock(),store);ret.reviews[key]=(facts,time.time())
   with store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
   def local(core,method,*args,**kw):
    if method=='listwallets':return ['Wallaby Extinct']
    if method=='getwalletinfo':return {'private_keys_enabled':False}
    if method=='importdescriptors':ret.cancel_remote(key);return [{'success':True}]
    raise AssertionError('Unexpected mutation: '+method)
   with patch('wallet_retirement.inventory',return_value=facts),patch('wallet_retirement.rpc',side_effect=local),patch('wallet_retirement.apply_labels'),patch('wallet_deletion.delete') as delete:result=ret.approve(key)
   delete.assert_not_called();self.assertIn('withdrawn',result['message']);self.assertEqual(store.read()['completed'][key]['result']['status'],'cancelled')
 def test_old_completed_retirement_never_becomes_cancelled(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');key='a'*64
   with store.edit() as s:s['completed'][key]={'kind':'wallet_retire'}
   Retirement(Mock(),store).cancel_remote(key);self.assertEqual(next(iter(store.read()['outbox'].values()))['payload']['status'],'error')
 def test_uninstalled_reserved_wallet_name_is_not_assumed_present(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');operation='a'*64;core=Mock();core.call.side_effect=lambda ident,method,*args,**kw:{'result':{'wallets':[]}} if method=='listwalletdir' else {'result':[]}
   setup=SimpleNamespace(sessions={operation:{'core':None,'installed_wallets':{'not-created':None},'discs_remaining':{'fixture'}}})
   c=Cancellations(core,store,setup,SimpleNamespace(prepared={}));data=c._data(cancel('wallet',[operation]));self.assertEqual(data[5],[]);self.assertEqual(data[6][operation]['discs_remaining'],['fixture'])

class PublicFailureWireTests(unittest.TestCase):
 def test_acknowledged_getrawmempool_failure_is_categorical_and_not_replayed(self):
  import threading
  from configuration import Config
  from node_client import NodeClient
  from agent_rpc import PublicDataFailure
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp}):
   client=NodeClient(Config().values,1,threading.Event(),lambda *_:None);command={'id':'fixture','kind':'rpc','method':'getrawmempool','params':[True],'wallet':None,'expires_in_seconds':30};client.pending.acquire()
   try:
    with patch.object(client,'post',side_effect=[{'execute':True},{'accepted':True}]) as post,patch.object(client.core,'call',side_effect=PublicDataFailure('response_limit','private key material MUST NOT LEAK')) as call,patch('activity_log.event') as event:client.execute(command,time.monotonic())
    call.assert_called_once();result=post.call_args.args[1];self.assertEqual(result['error']['code'],'local_rpc_response_limit');self.assertEqual(result['error']['data'],{'stage':'rpc','category':'response_limit','method':'getrawmempool'});self.assertNotIn('MUST NOT LEAK',json.dumps(result));event.assert_called_once_with('rpc.getrawmempool','Local public RPC failed · response_limit')
   finally:client.pool.shutdown()

class Wallet ServerReceiptFixture(unittest.TestCase):
 def test_actual_receipt_method_completes_delivery_while_local_choice_is_pending(self):
  import contextlib,importlib.util
  fixture=Path(__file__).parent/'fixtures/dashboard_builder_cancel_v1.py';spec=importlib.util.spec_from_file_location('cancel_receipt_fixture',fixture);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.storage_lock=lambda _:contextlib.nullcontext();module.stamp=lambda:'UTC fixture'
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');c=Cancellations(Mock(),store,SimpleNamespace(),SimpleNamespace());p=cancel();key=c.receive(p);payload=next(iter(store.read()['outbox'].values()))['payload'];state={'cancellations':{p['cancellation_id']:{'kind':'transaction','targets':{'node':{'request_hash':key,'sent_utc':'UTC fixture'}}}},'workspaces':{'transaction':{'cancellation_id':p['cancellation_id']}}};owner=SimpleNamespace(config=None,read=lambda:state,write=lambda s:None)
   module.receipt(owner,'node',payload);self.assertTrue(state['cancellations'][p['cancellation_id']]['complete']);self.assertFalse(state['workspaces']);self.assertIn(key,store.read()['pending'])
   with self.assertRaises(ValueError):module.receipt(owner,'node',{**payload,'deleted':True})

class CancellationDispatchGates(unittest.TestCase):
 def test_active_transfer_blocks_cleanup_and_cancelled_signing_cannot_prompt(self):
  import threading
  from secure_worker import Workspace
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state');p=cancel();key=digest(p)
   with store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'};s['active_transfer']='fixture'
   worker=Workspace.__new__(Workspace);worker.lock=threading.RLock();worker.configure=Mock();worker.store=store;worker.closing=False;worker.ops=SimpleNamespace(prepared={});worker.archives=None;worker.cancellations=Mock()
   with patch('secure_worker.enforce'),self.assertRaisesRegex(ValueError,'active transfer'):worker.dispatch('cancel.confirm',[key,'delete'],{})
   worker.cancellations.confirm.assert_not_called()
   original={'kind':'sign_psbt_partial','psbt':'fixture'};original_hash=digest(original)
   with store.edit() as s:s.pop('active_transfer');s['pending'][original_hash]={'proposal':original,'state':'cancellation_requested'};s['cancelled_requests']={original_hash:key}
   with patch('secure_worker.enforce'),patch('secure_worker.secret_dialog') as prompt,self.assertRaisesRegex(ValueError,'cancelled'):worker.dispatch('wallet.sign',[original_hash,'partial',False],{})
   prompt.assert_not_called()
