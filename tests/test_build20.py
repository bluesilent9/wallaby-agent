from loopback import IPv6HTTPServer
"""Protected-close lease regression, recovery gate and public mempool paging."""
import copy,http.client,json,os,tempfile,threading,time,unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from mempool_snapshot import Snapshot,params,METHOD,LOCAL_BYTES,PAGE,TTL
from agent_rpc import request,PublicDataFailure,MAX_RESULT_BYTES
from secure_worker import Workspace
from secure_bridge import WorkspaceFailure,prepare_stop
from node_client import Core,LIMIT
from diagnostics import describe

def entry(i):return {'vsize':150+i%300,'fees':{'modified':Decimal('0.00001234')},'depends':[f'{i-1:064x}'] if i and i%4 else [],'unused':'public-only metadata'}
def worker():
 w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.busy=Mock(return_value=False);w.archives=None;w.store=Mock();w.store.read.return_value={'outbox':{}};w.closing=False;return w

class CloseTests(unittest.TestCase):
 def test_slow_mandatory_protection_checks_do_not_expire_an_admitted_close(self):
  w=worker();clock=[100.0]
  def slow():clock[0]+=8
  with patch('secure_worker.time.monotonic',side_effect=lambda:clock[0]),patch('secure_worker.enforce',side_effect=slow),patch('activity_log.event'):
   self.assertEqual(w.dispatch('ui.prepare_close',[104],{}),{'ok':True});self.assertTrue(w.closing)
 def test_native_x_uses_the_same_guard_with_slow_checks(self):
  from protected_viewer import close_allowed
  w=worker();clock=[100.0]
  def slow():clock[0]+=8
  with patch('time.monotonic',side_effect=lambda:clock[0]),patch('secure_worker.enforce',side_effect=slow),patch('secure_bridge.call',side_effect=lambda method,*args,**kw:w.dispatch(method,list(args),{})),patch('activity_log.event'):self.assertTrue(close_allowed())
 def test_stale_or_queued_close_and_live_work_are_still_refused(self):
  w=worker()
  with patch('secure_worker.enforce') as enforce,self.assertRaisesRegex(ValueError,'expired'):w.dispatch('ui.prepare_close',[time.monotonic()-1],{})
  enforce.assert_not_called();self.assertFalse(w.closing)
  w.busy.return_value=True
  with patch('secure_worker.enforce'),self.assertRaisesRegex(ValueError,'Finish active'):w.dispatch('ui.prepare_close',[time.monotonic()+4],{})
  self.assertFalse(w.closing)
 def test_only_unsupported_new_action_uses_old_guarded_close(self):
  error=WorkspaceFailure('worker_rejected','Unsupported protected action.')
  with patch('secure_bridge.call',side_effect=[error,{'message':'Closed'}]) as call,patch('worker_upgrade.inspect_legacy') as inspect:prepare_stop({})
  self.assertEqual([c.args[0] for c in call.call_args_list],['ui.request_close','ui.close']);inspect.assert_not_called()
  with patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_rejected','Finish active work.')) as call,self.assertRaises(WorkspaceFailure):prepare_stop({})
  self.assertEqual(call.call_count,1)

class RecoveryAPI(unittest.TestCase):
 def setUp(self):
  from test_build13 import TunnelOnlyAPI
  self.api=TunnelOnlyAPI();self.api.setUp();self.api.server.preview=False;self.addCleanup(self.api.tearDown)
 def test_recovery_requires_confirmed_window_absence_and_failed_cleanup(self):
  for public,failed in [({'viewer_open':True},True),({'viewer_open':False},False),({},True)]:
   with patch('secure_bridge.call',return_value=public),patch('app.read_status',return_value={'cleanup_failed':failed}),patch('secure_bridge.stop') as stop:
    code,_=self.api.call('/api/protected/recover',{});self.assertEqual(code,400);stop.assert_not_called()
 def test_recovery_disconnects_only_node_then_performs_safe_stop(self):
  from configuration import Config
  c=Config();values=c.values;values['enabled']={'node':True,'ddns':True,'dashboard':True};c.save(values)
  def apply(config,values):config.save(values)
  with patch('secure_bridge.call',return_value={'viewer_open':False}),patch('app.read_status',return_value={'cleanup_failed':True}),patch('app.apply_config',side_effect=apply),patch('secure_bridge.stop',return_value={'message':'Cleared'}) as stop,patch('app.write_status'):
   code,result=self.api.call('/api/protected/recover',{})
  self.assertEqual(code,200);stop.assert_called_once();self.assertEqual(Config().values['enabled'],{'node':False,'ddns':True,'dashboard':True})
 def test_public_state_exposes_recovery_only_after_failure_and_confirmed_window_loss(self):
  from app import workspace
  for open_,failed,expected in [(True,True,False),(False,True,True),(False,False,False)]:
   with patch('protected_memory.required',return_value=True),patch('secure_bridge.call',return_value={'viewer_open':open_}),patch('app.read_status',return_value={'cleanup_failed':failed}):self.assertEqual(workspace(self.api.server)['cleanup_recovery'],expected)
 def test_failed_stop_keeps_recovery_failed_and_never_reports_cleared(self):
  with patch('secure_bridge.call',return_value={'viewer_open':False}),patch('app.read_status',return_value={'cleanup_failed':True}),patch('app.apply_config'),patch('secure_bridge.stop',side_effect=ValueError('Unfinished protected work retained')),patch('app.write_status') as write:
   code,result=self.api.call('/api/protected/recover',{});self.assertEqual(code,400);self.assertIn('retained',result['error']);write.assert_not_called()

class SnapshotTests(unittest.TestCase):
 def test_read_only_method_and_strict_params(self):
  for value in [[],{}, {'snapshot':'a'*32,'offset':1000}]:self.assertEqual(request(METHOD,value,None)[0],value)
  for value in [[True],{'wallet':'secret'},{'snapshot':'a'*32,'offset':1},{'snapshot':'a'*32,'offset':True},{'snapshot':'../','offset':0}]:
   with self.assertRaises(ValueError):request(METHOD,value,None)
  with self.assertRaises(ValueError):request(METHOD,{},'wallet')
  for method in ['walletpassphrase','sendtoaddress','stop','setnetworkactive']:
   with self.assertRaises(ValueError):request(method,[],None)
 def test_38000_entries_are_complete_stable_and_bounded_per_page(self):
  raw={f'{i:064x}':entry(i) for i in range(38000)};snapshot=Snapshot();fetch=Mock(return_value=raw);page=snapshot.call({},fetch);all_={};pages=0;ident=page['snapshot']
  while True:
   self.assertLess(len(json.dumps(page).encode()),MAX_RESULT_BYTES);self.assertEqual(page['snapshot'],ident);self.assertEqual(page['total'],38000);self.assertLessEqual(len(page['entries']),PAGE)
   self.assertFalse(set(all_)&set(page['entries']));all_.update(page['entries']);pages+=1
   if page['next_offset'] is None:break
   page=snapshot.call({'snapshot':ident,'offset':page['next_offset']},fetch)
  fetch.assert_called_once();self.assertEqual(len(all_),38000);self.assertEqual(pages,38);self.assertEqual(all_['0'*64]['fees']['modified'],'0.00001234');self.assertNotIn('unused',all_['0'*64]);self.assertEqual(all_[f'{1:064x}']['depends'],['0'*64])
 def test_page_and_original_mutation_cannot_change_cached_snapshot(self):
  raw={'0'*64:entry(0)};s=Snapshot();p=s.call({},lambda:raw);ident=p['snapshot'];raw['0'*64]['vsize']=999;p['entries']['0'*64]['vsize']=888
  self.assertEqual(s.call({'snapshot':ident,'offset':0},lambda:None)['entries']['0'*64]['vsize'],150)
 def test_expired_replaced_and_invalid_offsets_are_explicit(self):
  s=Snapshot();p=s.call({},lambda:{'0'*64:entry(0)});s.until=0
  with self.assertRaises(PublicDataFailure) as e:s.call({'snapshot':p['snapshot'],'offset':0},lambda:None)
  self.assertEqual(e.exception.code,'mempool_expired');p=s.call({},lambda:{'0'*64:entry(0)});s.call({},lambda:{})
  with self.assertRaises(PublicDataFailure):s.call({'snapshot':p['snapshot'],'offset':0},lambda:None)
  p=s.call({},lambda:{})
  self.assertEqual(p['total'],0);self.assertEqual(p['entries'],{});self.assertIsNone(p['next_offset'])
  with self.assertRaises(PublicDataFailure):s.call({'snapshot':p['snapshot'],'offset':1000},lambda:None)
 def test_incomplete_graph_bad_fees_and_overlap_refused_without_partial_data(self):
  for changed in [{'depends':['a'*64]},{'fees':{'modified':'NaN'}},{'vsize':True},{'fees':{'modified':'0.000000001'}}]:
   s=Snapshot()
   with self.assertRaises(PublicDataFailure):s.call({},lambda:{'0'*64:{**entry(0),**changed}})
   self.assertIsNone(s.ident)
  s=Snapshot();s.lock.acquire()
  try:
   with self.assertRaises(PublicDataFailure) as error:s.call({},lambda:{})
   self.assertEqual(error.exception.code,'mempool_busy')
  finally:s.lock.release()

class LargeLocalHTTP(unittest.TestCase):
 def test_large_core_reply_is_only_allowed_for_paged_capture(self):
  from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
  payload={'0'*64:{**entry(0),'unused':'A'*(17*1024*1024)}};payload['0'*64]['fees']['modified']='0.00001234'
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));body=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':payload}).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
    try:self.wfile.write(body)
    except (BrokenPipeError,ConnectionResetError):pass
  server=IPv6HTTPServer(('::1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with tempfile.TemporaryDirectory() as tmp:
    cookie=Path(tmp)/'.cookie';cookie.write_text('fixture:never-log-credential');core=Core({'rpc_port':server.server_port,'cookie':str(cookie)})
    with self.assertRaises(Exception) as error:core.call('legacy','getrawmempool',[True])
    failure=describe('rpc',error.exception);self.assertEqual(failure.code,'response_limit');self.assertEqual(failure.measurements['boundary'],'local_core_http');self.assertEqual(failure.measurements['limit_bytes'],LIMIT);self.assertNotIn('never-log',str(failure))
    page=core.call('paged',METHOD,{})['result'];self.assertEqual(page['total'],1);self.assertEqual(page['entries']['0'*64]['vsize'],150);self.assertLess(len(json.dumps(page)),1000)
  finally:server.shutdown();server.server_close();thread.join()

class ConsumerCompatibility(unittest.TestCase):
 def test_existing_dashboard_projection_uses_exact_paged_fields_and_dependencies(self):
  import importlib.util
  p=Path(__file__).parent/'fixtures/dashboard_fee_projection.py';spec=importlib.util.spec_from_file_location('fee_projection_contract',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  raw={f'{i:064x}':entry(i) for i in range(75)};page=Snapshot().call({},lambda:raw)
  self.assertEqual(module.project(raw,capacity=1000),module.project(page['entries'],capacity=1000))
 def test_real_core_public_snapshot_preserves_modified_fee_and_tx_identity(self):
  from regtest_support import Regtest
  from wallet_ops import rpc
  node=Regtest();self.addCleanup(node.close);c=node.core;rpc(c,'createwallet',{'wallet_name':'Miner'});address=rpc(c,'getnewaddress',[],'Miner');rpc(c,'generatetoaddress',[101,address]);dest=rpc(c,'getnewaddress',[],'Miner');txid=rpc(c,'sendtoaddress',[dest,'1'],'Miner');raw=rpc(c,'getrawmempool',[True]);page=rpc(c,METHOD,{})
  self.assertEqual(page['total'],len(raw));self.assertIn(txid,page['entries']);self.assertEqual(page['entries'][txid]['vsize'],raw[txid]['vsize']);self.assertEqual(Decimal(page['entries'][txid]['fees']['modified']),Decimal(raw[txid]['fees']['modified']));self.assertIn('ancestorsize',raw[txid]);self.assertNotIn('ancestorsize',page['entries'][txid])

class FinalBoundaryTests(unittest.TestCase):
 def test_close_never_waits_for_a_busy_local_action(self):
  w=worker();w.lock=Mock();w.lock.acquire.return_value=False
  with patch('secure_worker.enforce') as enforce,self.assertRaisesRegex(ValueError,'active protected operation'):w.dispatch('ui.prepare_close',[time.monotonic()+4],{})
  enforce.assert_not_called();w.lock.acquire.assert_called_once_with(blocking=False);self.assertFalse(w.closing)
 def test_response_measurements_and_local_refusal_categories_contain_no_raw_payload(self):
  from agent_rpc import clean_json
  from diagnostics import action_code
  with self.assertRaises(PublicDataFailure) as e:clean_json({'value':'PUBLIC-FIXTURE'},5)
  failure=describe('rpc',e.exception);self.assertEqual(failure.measurements['boundary'],'public_result');self.assertEqual(failure.measurements['limit_bytes'],5);self.assertGreater(failure.measurements['observed_bytes'],5)
  self.assertNotIn('PUBLIC-FIXTURE',str(failure));self.assertEqual(action_code(ValueError('Close request expired; no workspace state was changed.')),'close_admission_expired');self.assertEqual(action_code(ValueError('cookie=DO-NOT-LOG')),'local_action_refused')
 def test_preview_cannot_start_workspace_recovery(self):
  from test_build13 import TunnelOnlyAPI
  api=TunnelOnlyAPI();api.setUp()
  try:
   with patch('secure_bridge.call') as call,patch('secure_bridge.stop') as stop:
    code,data=api.call('/api/protected/recover',{});self.assertEqual(code,400);self.assertIn('preview',data['error']);call.assert_not_called();stop.assert_not_called()
  finally:api.tearDown()

class DiagnosticSocketTests(unittest.TestCase):
 def test_actual_worker_failure_log_records_action_category_and_duration_not_payload(self):
  import socket
  from secure_worker import Server
  from secure_bridge import receive
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'worker.sock'
   with Server(str(path),__import__('secure_worker').Handler) as server:
    server.workspace=Mock();server.workspace.dispatch.side_effect=ValueError('DO-NOT-LOG-PRIVATE-FIXTURE');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
     with patch('activity_log.event') as event,socket.socket(socket.AF_UNIX) as client:
      client.connect(str(path));raw=json.dumps({'method':'wallet.sign','args':['DO-NOT-LOG-ARGUMENT'],'environment':{}}).encode();client.sendall(len(raw).to_bytes(4,'big')+raw);size=int.from_bytes(receive(client,4),'big');reply=json.loads(receive(client,size))
      self.assertIn('error',reply);self.assertEqual(event.call_args.args[0],'wallet.sign');message=event.call_args.args[1];self.assertIn('local_action_refused',message);self.assertIn('elapsed_ms=',message);self.assertNotIn('DO-NOT-LOG',message)
    finally:server.shutdown();thread.join()
