"""Keep control traffic live while public RPC/preview work is slow."""
import hashlib,json,threading,time,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from node_client import NodeClient,HTTPFailure
from diagnostics import ConnectionFailure


def command(ident):return {'id':ident,'kind':'rpc','method':'getblockcount','params':[],'wallet':None,'expires_in_seconds':30}

class ControlTraffic(unittest.TestCase):
 def client(self):
  c=NodeClient({},1,threading.Event(),Mock());self.addCleanup(c.pool.shutdown);return c
 def test_busy_core_does_not_block_heartbeat_command_consumption(self):
  c=self.client();c.pending.acquire();c.pending.acquire()
  try:
   started=time.monotonic();c.consume({'commands':[command('later')]});self.assertLess(time.monotonic()-started,.2);self.assertNotIn('later',c.seen);self.assertFalse(c.failed.is_set())
  finally:c.pending.release();c.pending.release()
  with patch.object(c,'execute') as execute:
   c.consume({'commands':[command('later')]});c.pool.shutdown(wait=True);self.assertEqual(execute.call_count,1)
 def test_temporary_poll_failure_retains_same_session(self):
  c=self.client();c.token='existing';c.on_degraded=Mock()
  with patch.object(c,'post',side_effect=[ConnectionFailure('dashboard','timeout','Slow'),{'commands':[]}]) as post,patch('activity_log.event'):
   self.assertEqual(c.control_post('poll',{'wait_seconds':2}),{'commands':[]})
  self.assertEqual(post.call_count,2);self.assertEqual(c.token,'existing');c.on_degraded.assert_called_once();self.assertFalse(c.failed.is_set())
 def test_expired_control_retry_budget_is_not_reset(self):
  c=self.client();c.on_degraded=Mock()
  with patch.object(c,'post',side_effect=ConnectionFailure('dashboard','timeout','Slow')),patch('node_client.time.monotonic',side_effect=[0,16]),patch('activity_log.event'),self.assertRaises(ConnectionFailure):c.control_post('heartbeat',{})
  c.on_degraded.assert_called_once()
 def test_authentication_refusal_is_not_hidden_by_transport_retries(self):
  c=self.client()
  with patch.object(c,'post',side_effect=HTTPFailure(401)) as post,self.assertRaises(HTTPFailure):c.control_post('poll',{})
  self.assertEqual(post.call_count,1)
 def test_lost_ack_or_result_never_replays_core_or_disconnects_healthy_session(self):
  for phase in ('ack','result'):
   c=self.client();c.pending.acquire();c.token='existing';c.on_degraded=Mock()
   def post(path,body):
    if path==phase:raise ConnectionFailure('dashboard','timeout','Slow')
    return {'execute':True}
   with patch.object(c,'post',side_effect=post) as sent,patch('node_client.LOCAL_PUBLIC_RPC',return_value={'result':1}) as core,patch('activity_log.event'):
    c.execute(command('one'),time.monotonic())
   self.assertEqual(core.call_count,0 if phase=='ack' else 1);self.assertEqual([x.args[0] for x in sent.call_args_list].count(phase),1);self.assertFalse(c.failed.is_set());c.on_degraded.assert_called_once()

 def test_transient_exchange_retries_promptly_without_speeding_protocol_errors(self):
  from agent_exchange import Exchange
  from approval_store import Store
  with tempfile.TemporaryDirectory() as tmp:
   e=Exchange(1,'existing',Store(tmp));stop=Mock();stop.is_set.return_value=False;stop.wait.side_effect=lambda delay:setattr(stop.is_set,'return_value',True)
   with patch.object(e,'once',side_effect=ConnectionFailure('dashboard','timeout','Slow')),patch('activity_log.event') as log:e.run(stop)
   stop.wait.assert_called_once_with(1);self.assertIn('retry_s=1',log.call_args.args[1])
 def test_protected_window_recovers_same_client_after_short_control_delay(self):
  from test_build22 import worker
  w=worker();instances=[];finished=threading.Event();states=[]
  class Client:
   def __init__(self,config,port,stop,status):self.status=status;instances.append(self)
   def run(self):
    self.status('green','Connected');self.on_degraded(ConnectionFailure('dashboard','timeout','Slow'));states.append(w.node_status['color']);states.append(w.recovery_state()['active']);self.status('green','Connected');states.append(w.node_status['color']);states.append(w.recovery_state()['active']);finished.set()
  with patch('node_client.NodeClient',Client),patch('activity_log.event'):
   w.start_node(1234);self.assertTrue(finished.wait(2));w.node_stop.set();w.node.join(2)
  self.assertEqual(states,['amber',True,'green',False]);self.assertEqual(len(instances),1)

 def test_direct_ipv6_peer_route_does_not_go_through_hostname_validation(self):
  from peer_wallet import local_ipv6
  with patch('peer_wallet.resolve_ipv6',side_effect=AssertionError('A literal peer needs no DNS')),patch('peer_wallet.socket.socket') as sockets:
   sock=sockets.return_value.__enter__.return_value;sock.getsockname.return_value=('2001:db8::1',40000,0,0)
   self.assertEqual(local_ipv6('2001:db8::2'),'2001:db8::1');sock.connect.assert_called_once_with(('2001:db8::2',22,0,0))
 def test_named_route_uses_native_ipv6_resolver(self):
  from peer_wallet import local_ipv6
  with patch('peer_wallet.resolve_ipv6',return_value=[('2001:db8::2',22,0,0)]) as resolve,patch('peer_wallet.socket.socket') as sockets:
   sockets.return_value.__enter__.return_value.getsockname.return_value=('2001:db8::1',40000,0,0)
   self.assertEqual(local_ipv6('server.test'),'2001:db8::1');resolve.assert_called_once_with('server.test',22,timeout=2)

class ThreeAgentControl(unittest.TestCase):
 def test_signed_identities_continue_during_slow_previews_and_one_dropped_poll(self):
  from http.server import BaseHTTPRequestHandler
  from loopback import IPv6HTTPServer
  from regtest_support import Regtest
  from approval_store import Store
  from agent_exchange import Exchange
  from setup_messages import verify
  nodes=[];clients=[];threads=[];stops=[];received={};stores={};registrations=[];drops=set();lock=threading.Lock();release=threading.Event();preview_started=threading.Event()
  with tempfile.TemporaryDirectory() as tmp:
   class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_POST(self):
     data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));path=self.path.rsplit('/',1)[-1];token=self.headers.get('Authorization','Bearer ')[7:]
     if path=='register':
      with lock:token='node-'+str(len(registrations));registrations.append(token)
      reply={'protocol':'wallaby-agent','version':1,'connection_token':token}
     elif path=='exchange':
      accepted=[]
      for item in data['outbox']:
       if item['kind']=='wallet_setup_identity':received[token]=item['payload'];accepted.append(item['id'])
      reply={'version':1,'accepted':accepted,'proposals':[] if token in received else [{'kind':'wallet_setup_identity','version':1,'challenge':hashlib.sha256(token.encode()).hexdigest()}]}
     elif path=='poll':
      with lock:first=token not in drops;drops.add(token)
      if first:self.close_connection=True;return
      time.sleep(.05);reply={'commands':[]}
     else:reply={}
     raw=json.dumps(reply).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   server=IPv6HTTPServer(('::1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
   def exchange(port,token,workspace_store=None):
    from test_build8 import paired
    store=Store(Path(tmp)/token);store.receive(paired('Background wallet','send'));stores[token]=store;return Exchange(port,token,store)
   def slow_preview(self):preview_started.set();release.wait(8)
   errors=[]
   def run(client):
    try:client.run()
    except Exception as error:errors.append(error)
   try:
    with patch('agent_exchange.Exchange',side_effect=exchange),patch.object(Exchange,'prepare_preview',slow_preview),patch('node_client.adapter_mac',return_value='02:11:22:33:44:55'),patch('activity_log.event'):
     for _ in range(3):
      n=Regtest();nodes.append(n);stop=threading.Event();stops.append(stop);c=NodeClient(n.core.config,server.server_port,stop,Mock());c.on_degraded=Mock();clients.append(c);thread=threading.Thread(target=run,args=(c,),daemon=True);threads.append(thread);thread.start()
     self.assertTrue(preview_started.wait(2));deadline=time.monotonic()+4
     while len(received)<3 and not errors and time.monotonic()<deadline:time.sleep(.02)
     self.assertFalse(errors);self.assertEqual(len(received),3);self.assertEqual(len(registrations),3,'Brief transport hiccups must not replace a ceremony session')
     for token,envelope in received.items():self.assertEqual(verify(stores[token],envelope,envelope['public_key'])['challenge'],hashlib.sha256(token.encode()).hexdigest())
     self.assertTrue(all(c.on_degraded.called for c in clients));self.assertFalse(release.is_set())
   finally:
    release.set()
    for stop in stops:stop.set()
    for thread in threads:thread.join(5)
    for node in nodes:node.close()
    server.shutdown();server.server_close();server_thread.join(3)
