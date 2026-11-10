"""Loss recovery using actual node/session code, IPC and monotonic deadlines."""
import threading,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from diagnostics import ConnectionFailure
from node_client import NodeClient,HTTPFailure
from node_recovery import Recovery,notice
from secure_worker import Workspace

class Budget(unittest.TestCase):
 def test_repeated_failures_cannot_extend_fifteen_second_budget(self):
  clock=[100];r=Recovery(lambda:clock[0]);self.assertTrue(r.connected());r.lost(ConnectionFailure('rpc','refused','Core offline'));clock[0]=114;r.lost(HTTPFailure(401));self.assertEqual(r.snapshot()['remaining'],1);self.assertEqual(r.snapshot()['stage'],'rpc');clock[0]=115;self.assertTrue(r.tick());self.assertFalse(r.connected())
 def test_success_clears_budget_and_next_drop_gets_a_new_budget(self):
  clock=[0];r=Recovery(lambda:clock[0]);r.connected();r.lost(HTTPFailure(401));clock[0]=10;self.assertTrue(r.connected());self.assertFalse(r.snapshot()['active']);clock[0]=20;r.lost(HTTPFailure(401));self.assertEqual(r.snapshot()['remaining'],15)
 def test_initial_failed_start_is_not_misrepresented_as_established_connection_loss(self):
  r=Recovery();r.lost(HTTPFailure(401));self.assertFalse(r.snapshot()['active'])
 def test_notifications_distinguish_core_and_dashboard(self):
  self.assertIn('Bitcoin Core',notice('rpc'));self.assertIn('Wallet Server Server',notice('ssh_forward'));self.assertIn('Wallet Server Server',notice('dashboard'))

class SessionFailure(unittest.TestCase):
 def test_real_session_limit_cannot_be_overwritten_by_late_heartbeat_401(self):
  client=NodeClient({},1,threading.Event(),Mock());self.addCleanup(client.pool.shutdown);client.check_core=Mock();client.seen={str(i) for i in range(10000)};client.on_failure=Mock()
  command={'id':'new','kind':'rpc','method':'getblockcount','params':[],'wallet':None,'expires_in_seconds':5}
  def post(path,*args,**kwargs):
   if path=='register':return {'protocol':'wallaby-agent','version':1,'connection_token':'fixture','commands':[command]}
   if path=='disconnect':client.fail(HTTPFailure(401));return {}
   raise AssertionError(path)
  client.post=post
  with patch('node_client.adapter_mac',return_value='00:11:22:33:44:55'),self.assertRaises(ConnectionFailure) as caught:client.run()
  self.assertEqual(caught.exception.code,'session_limit');self.assertEqual(client.error.code,'session_limit');self.assertEqual(client.on_failure.call_count,1);self.assertEqual(len(client.seen),10000)
 def test_late_heartbeat_response_cannot_publish_green_after_failure(self):
  stop=Mock();stop.wait.side_effect=[False,True];status=Mock();client=NodeClient({},1,stop,status);self.addCleanup(client.pool.shutdown);client.check_core=Mock();stop.is_set.return_value=False
  def post(*a,**kw):client.fail(HTTPFailure(401));return {}
  client.post=post;client.heartbeat();self.assertNotIn('green',[c.args[0] for c in status.call_args_list])

def worker(clock=None):
 w=Workspace.__new__(Workspace);w.store=Mock(name='workspace_store');w.recovery=Recovery(clock or time.monotonic);w.node_epoch=0;w.node_generation=None;w.node_stop=threading.Event();w.node_status={'color':'red','message':'Off'};w.ops=SimpleNamespace(core=SimpleNamespace(config={}));w.viewers=[];w.closing=False;return w

class AutomaticRecovery(unittest.TestCase):
 def test_failed_session_is_recreated_and_old_callbacks_cannot_override_new_success(self):
  w=worker();clients=[];ready=threading.Event()
  class Client:
   def __init__(self,config,port,stop,status):self.stop=stop;self.status=status;clients.append(self)
   def run(self):
    self.status('green','Connected')
    if len(clients)==1:self.on_failure(ConnectionFailure('dashboard','session_limit','Rotate session'));raise ConnectionFailure('dashboard','session_limit','Rotate session')
    ready.set();self.stop.wait(5)
  with patch('node_client.NodeClient',Client),patch('activity_log.event'):
   w.start_node(1234)
   try:
    self.assertTrue(ready.wait(4));self.assertEqual(len(clients),2);self.assertEqual(w.node_status['color'],'green');self.assertFalse(w.recovery.snapshot()['active'])
    clients[0].status('green','Stale response');clients[0].on_failure(HTTPFailure(401));self.assertEqual(w.node_status['message'],'Connected')
   finally:w.node_stop.set();w.node.join(2)
 def test_deadline_closes_only_tracked_window_even_with_wallet_lock_held(self):
  clock=[0];w=worker(lambda:clock[0]);w.node_generation='session';w.node_stop=threading.Event();w.lock=threading.Lock();w.lock.acquire();w.archives=object();archive=w.archives;viewer=Mock();viewer.poll.return_value=None;w.viewers=[viewer];w.recovery.connected();w.connection_lost(ConnectionFailure('rpc','refused','Core offline'));clock[0]=15
  with patch('activity_log.event'):w.recovery_watch('session')
  viewer.terminate.assert_called_once();self.assertTrue(w.closing);self.assertTrue(w.node_stop.is_set());self.assertIs(w.archives,archive);self.assertTrue(w.lock.locked());w.lock.release()
 def test_fresh_user_start_resets_expired_budget_only_via_arm(self):
  from test_build21 import workspace
  w=workspace();w.recovery=Recovery(lambda:100);w.recovery.connected();w.recovery.lost(HTTPFailure(401));w.recovery.expired=True;w.viewers=[]
  with patch('secure_worker.enforce'):self.assertEqual(w.dispatch('ui.arm',[],{}),{'ok':True})
  self.assertFalse(w.recovery.snapshot()['active']);self.assertFalse(w.recovery.snapshot()['expired'])

class RecoveryWire(unittest.TestCase):
 def test_transport_loss_and_wallet_action_pause_cross_real_json_socket(self):
  from test_build21 import NativeWire
  from secure_bridge import call,WorkspaceFailure
  fixture=NativeWire();fixture.setUp();self.addCleanup(fixture.doCleanups);w=fixture.worker;w.recovery=Recovery();w.recovery.connected();w.node_stop=threading.Event();w.node_status={'color':'green','message':'Connected'}
  call('node.connection_lost','ssh','ipv6_route')
  self.assertEqual(w.recovery.snapshot()['stage'],'ssh');self.assertEqual(w.node_status['color'],'amber')
  with self.assertRaisesRegex(WorkspaceFailure,'operations are paused'):call('message.wallets')

class TimedOutLifecycle(unittest.TestCase):
 def fixture(self,busy=False):
  from test_build17 import LifecycleTests
  t=LifecycleTests();t.setUp();self.addCleanup(t.doCleanups);t.state.update(viewer_open=False,busy=busy,recovery={'expired':True,'message':notice('rpc')});return t
 def test_timeout_disables_node_and_preserves_notice_after_safe_cleanup(self):
  from configuration import Config
  from runtime import read_status
  t=self.fixture();t.life.poll();self.assertFalse(Config().values['enabled']['node']);self.assertTrue(Config().values['enabled']['ddns']);self.assertEqual(read_status('node')['recovery_notice'],notice('rpc'))
  with patch('secure_bridge.stop',return_value={}):t.life.clean(notice('rpc'))
  self.assertEqual(read_status('node')['recovery_notice'],notice('rpc'));self.assertIn('15 seconds',read_status('node')['message'])
 def test_timeout_retains_active_wallet_material_without_stopping_secure_service(self):
  from runtime import read_status
  t=self.fixture(True)
  with patch('secure_bridge.stop') as stop:t.life.poll()
  stop.assert_not_called();self.assertIsNone(t.life.thread);self.assertIn('retained',read_status('node')['message']);self.assertEqual(read_status('node')['recovery_notice'],notice('rpc'))

class HTTPRecovery(unittest.TestCase):
 def test_real_ipv6_http_session_limit_rotates_token_and_recovers(self):
  import http.server,json,socket
  registrations=[];clients=[];ready=threading.Event();owner=worker()
  class Server(http.server.ThreadingHTTPServer):address_family=socket.AF_INET6;daemon_threads=True
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));path=self.path.rsplit('/',1)[-1]
    if path=='register':
     token='session-'+str(len(registrations));registrations.append(token);reply={'protocol':'wallaby-agent','version':1,'connection_token':token}
    elif path=='poll':
     time.sleep(.05)
     if self.headers.get('Authorization')=='Bearer session-0':reply={'commands':[{'id':'next','kind':'rpc','method':'getblockcount','params':[],'wallet':None,'expires_in_seconds':5}]}
     else:reply={};ready.set()
    else:reply={}
    raw=json.dumps(reply).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers()
    try:self.wfile.write(raw)
    except BrokenPipeError:pass
  server=Server(('::1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  class Client(NodeClient):
   def __init__(self,*args):
    super().__init__(*args);clients.append(self)
    if len(clients)==1:self.seen={str(i) for i in range(10000)}
  with patch('node_client.NodeClient',Client),patch('node_client.Core',return_value=SimpleNamespace(ready=lambda:None)),patch('node_client.adapter_mac',return_value='00:11:22:33:44:55'),patch('agent_exchange.Exchange',return_value=SimpleNamespace(run=lambda *_:None)),patch('activity_log.event'):
   owner.start_node(server.server_port)
   try:
    self.assertTrue(ready.wait(5));self.assertEqual(registrations,['session-0','session-1']);self.assertTrue(all(c.store is owner.store for c in clients));self.assertEqual(clients[0].error.code,'session_limit');self.assertEqual(owner.node_status['color'],'green');self.assertFalse(owner.recovery.snapshot()['active']);self.assertEqual(len(clients[0].seen),10000)
   finally:owner.node_stop.set();owner.node.join(6);self.assertFalse(owner.node.is_alive())
