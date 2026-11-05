"""Server-only address fallback and explicit, immutable signing delivery."""
import array,copy,socket,subprocess,sys,tempfile,threading,unittest
from unittest.mock import Mock,patch
from pathlib import Path
from server_connector import connect,resolve_ipv4
from diagnostics import ConnectionFailure,ssh_failure
from approval_store import Store,digest
from agent_exchange import Exchange

class ServerFallback(unittest.TestCase):
 def listener(self,family):
  s=socket.socket(family,socket.SOCK_STREAM)
  if family==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
  s.bind(('::1',0) if family==socket.AF_INET6 else ('127.0.0.1',0));s.listen(1);self.addCleanup(s.close);return s
 def test_ipv6_is_preferred_and_ipv4_is_not_even_resolved_on_success(self):
  server=self.listener(socket.AF_INET6)
  with patch('server_connector.resolve_ipv6',return_value=[server.getsockname()]),patch('server_connector.resolve_ipv4') as fallback:
   with connect('server.test',22) as client:accepted,_=server.accept();accepted.close();self.assertEqual(client.family,socket.AF_INET6)
  fallback.assert_not_called()
 def test_ipv6_route_failure_or_missing_aaaa_falls_back_to_real_ipv4_socket(self):
  server=self.listener(socket.AF_INET)
  for missing in (False,True):
   with patch('server_connector.resolve_ipv6',side_effect=ConnectionFailure('ssh','dns_no_ipv6','None') if missing else None,return_value=[('::1',0,0,0)]),patch('server_connector.resolve_ipv4',return_value=[server.getsockname()]):
    with connect('server.test',22) as client:accepted,_=server.accept();accepted.close();self.assertEqual(client.family,socket.AF_INET)
 def test_unavailable_ipv6_socket_family_still_permits_server_fallback(self):
  server=self.listener(socket.AF_INET);native=socket.socket
  def factory(family,*args,**kwargs):
   if family==socket.AF_INET6:raise OSError('IPv6 sockets unavailable')
   return native(family,*args,**kwargs)
  with patch('server_connector.resolve_ipv6',return_value=[('::1',22,0,0)]),patch('server_connector.resolve_ipv4',return_value=[server.getsockname()]),patch('server_connector.socket.socket',side_effect=factory):
   with connect('server.test',22) as client:accepted,_=server.accept();accepted.close();self.assertEqual(client.family,socket.AF_INET)
 def test_ipv4_resolution_uses_native_ipc_and_requests_only_ipv4_addresses(self):
  from test_build43 import resolver
  reply={'parameters':{'addresses':[{'family':2,'address':[192,0,2,1]},{'family':10,'address':[0]*16}]}}
  with resolver(reply) as (path,requests),patch('server_connector.SOCKET',path):self.assertEqual(resolve_ipv4('server.test',2222),[('192.0.2.1',2222)])
  self.assertEqual(requests[0]['parameters']['family'],socket.AF_INET)
 def test_both_unavailable_report_both_families_without_authentication_bypass(self):
  with patch('server_connector.resolve_ipv6',side_effect=OSError()),patch('server_connector.resolve_ipv4',side_effect=OSError()),self.assertRaises(ConnectionFailure) as error:connect('server.test',22)
  self.assertEqual(error.exception.code,'server_unreachable');self.assertIn('IPv6 or IPv4',str(error.exception));self.assertEqual(ssh_failure(['WALLABY_CONNECT server_unreachable: fixed text'],0).code,'server_unreachable')
 def test_ipv4_master_socket_is_handed_to_ssh_without_a_second_connection(self):
  server=self.listener(socket.AF_INET);parent,child=socket.socketpair();source=Path(__file__).resolve().parents[1]/'src'
  script="""import socket,sys
sys.path.insert(0,sys.argv[1]);import server_connector as connector
connector.resolve_ipv6=lambda *a,**k:[]
connector.resolve_ipv4=lambda *a,**k:[('127.0.0.1',int(sys.argv[2]))]
sys.argv=['connector','server.test',sys.argv[2]];sys.exit(connector.main())
"""
  process=subprocess.Popen([sys.executable,'-c',script,str(source),str(server.getsockname()[1])],stdout=child,stderr=subprocess.PIPE);child.close();parent.settimeout(10)
  try:
   _,ancillary,_,_=parent.recvmsg(1,socket.CMSG_SPACE(array.array('i').itemsize));fds=array.array('i')
   for level,kind,data in ancillary:
    if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:fds.frombytes(data)
   self.assertEqual(len(fds),1)
   with socket.socket(fileno=fds[0]) as handed:
    accepted,_=server.accept()
    with accepted:accepted.sendall(b'server-only fallback');self.assertEqual(handed.recv(64),b'server-only fallback');self.assertEqual(handed.family,socket.AF_INET)
   self.assertEqual(process.wait(5),0);self.assertIn('WALLABY_SERVER IPv4:',process.stderr.read().decode())
  finally:
   parent.close()
   if process.poll() is None:process.kill();process.wait()
   process.stderr.close()
 def test_only_initial_master_uses_fallback_peer_and_loopbacks_stay_ipv6(self):
  from configuration import Config
  from transport import ssh_command,control_command
  c=Config().values;c['hostname']='server.test';cmd=ssh_command(c,'dashboard',38951,'/tmp/test.sock')
  self.assertIn('StrictHostKeyChecking=yes',cmd);self.assertIn('ProxyUseFdpass=yes',cmd);self.assertTrue(any('server_connector.py' in arg for arg in cmd));self.assertEqual(cmd[-1],'server.test');self.assertIn('[::1]:38951:[::1]:38951',cmd)
  self.assertIn('-6',control_command(c,'/tmp/test.sock','check'))
  source=Path(__file__).resolve().parents[1]/'src';self.assertNotIn('server_connector',(source/'peer_wallet.py').read_text());self.assertNotIn('server_connector',(source/'loopback.py').read_text())

class Delivery(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.store=Store(temp.name);self.key='a'*64
  self.payload={'request_hash':self.key,'status':'signed','psbt':'immutable public fixture'};self.ident=self.store.queue('partial_sign_result',self.payload)
  with self.store.edit() as s:s['completed'][self.key]={'kind':'sign_psbt_partial','at':1,'delivery':'queued','outbox_id':self.ident}
  self.exchange=Exchange(1,'fixture-token',self.store)
 def test_acknowledgement_records_delivery_even_if_unrelated_new_proposal_is_invalid(self):
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value={'version':1,'accepted':[self.ident],'proposals':[{'kind':'bad'}]}),patch('activity_log.event'),self.assertRaises(ValueError):self.exchange.once(False)
  state=self.store.read();self.assertNotIn(self.ident,state['outbox']);self.assertEqual(state['completed'][self.key]['delivery'],'acknowledged')
 def test_unacknowledged_result_is_retained_unchanged_and_retried_without_signing(self):
  sent=[]
  def post(port,path,body,*args,**kwargs):sent.append(copy.deepcopy(body));return {'version':1,'accepted':[] if len(sent)==1 else [self.ident],'proposals':[]}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',side_effect=post),patch('activity_log.event'):
   self.exchange.once(False);self.assertIn(self.ident,self.store.read()['outbox']);self.exchange.once(False)
  self.assertEqual(sent[0]['outbox'],sent[1]['outbox']);self.assertEqual(self.store.read()['completed'][self.key]['delivery'],'acknowledged')
 def test_unexpected_local_failure_cannot_silently_stop_delivery_worker(self):
  stop=threading.Event();attempts=[]
  def work(event):
   attempts.append(1)
   if len(attempts)==1:raise OSError('simulated local storage refusal')
   event.set()
  with patch.object(self.exchange,'_run',side_effect=work),patch.object(stop,'wait',return_value=False),patch('activity_log.event') as log:self.exchange.run(stop)
  self.assertEqual(len(attempts),2);self.assertIn(self.ident,self.store.read()['outbox']);self.assertIn('queued results retained',log.call_args.args[1])
 def test_signed_result_is_not_starved_by_background_outbox_notices(self):
  with self.store.edit() as s:
   original=s['outbox'];s['outbox']={digest({'n':n}):{'kind':'node_identity','payload':{'ipv6':'fd12::1'}} for n in range(20)};s['outbox'].update(original)
  bodies=[]
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',side_effect=lambda port,path,body,*a,**k:(bodies.append(body) or {'version':1,'accepted':[],'proposals':[]})),patch('activity_log.event'):self.exchange.once(False)
  self.assertEqual(bodies[0]['outbox'][0]['id'],self.ident)
