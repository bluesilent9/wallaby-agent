"""Failure stages stay actionable without exposing raw credentials."""
import contextlib, io, json, os, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from configuration import Config
from diagnostics import ConnectionFailure, describe, ssh_failure
from node_client import Core, HTTPFailure, NodeClient
from runtime import read_status, worker
from transport import Tunnel,MasterConnection

class DiagnosticsTests(unittest.TestCase):
 def test_ssh_categories_do_not_echo_raw_lines(self):
  cases=[('Permission denied (publickey).','authentication'),('Host key verification failed.','host_key'),('Could not resolve hostname example','dns'),('Network is unreachable','ipv6_route'),('Connection timed out','timeout'),('Connection refused','refused'),('bind: Address already in use','port_busy'),('ControlPath too long','control_socket'),('channel 1: open failed: administratively prohibited','forward_denied'),('channel 1: open failed: connect failed: Connection refused','target_refused')]
  for raw,code in cases:
   with self.subTest(code=code):
    failure=ssh_failure([raw,'Cookie: private-test-value'],56443,255)
    self.assertEqual(failure.code,code);self.assertNotIn('private-test-value',str(failure))
    if code in ('forward_denied','target_refused'):self.assertIn('56443',str(failure));self.assertEqual(failure.stage,'ssh_forward')
 def test_absent_invalid_and_unreadable_cookies_report_rpc(self):
  with tempfile.TemporaryDirectory() as root:
   config=Config(root).values
   for value,code in [('', 'cookie_missing'),(str(Path(root)/'.missing'),'cookie_missing')]:
    config['cookie']=value
    with self.subTest(code=code),self.assertRaises(ConnectionFailure) as failure:Core(config).ready()
    self.assertEqual(failure.exception.stage,'rpc');self.assertEqual(failure.exception.code,code)
   cookie=Path(root)/'.cookie';cookie.write_text('not-a-cookie-private-test-value');config['cookie']=str(cookie)
   with self.assertRaises(ConnectionFailure) as failure:Core(config).ready()
   self.assertEqual(failure.exception.code,'cookie_invalid');self.assertNotIn('private-test-value',str(failure.exception))
   with patch('node_client.Path.read_text',side_effect=PermissionError),self.assertRaises(ConnectionFailure) as failure:Core(config).ready()
   self.assertEqual(failure.exception.code,'cookie_access')
 def test_rpc_http_auth_refusal_and_timeout_are_not_ssh(self):
  with tempfile.TemporaryDirectory() as root:
   cookie=Path(root)/'.cookie';cookie.write_text('__cookie__:private-test-value');config=Config(root).values;config['cookie']=str(cookie)
   for error,code in [(HTTPFailure(401),'http_auth'),(ConnectionRefusedError(),'refused'),(TimeoutError(),'timeout')]:
    with self.subTest(code=code),patch('node_client.http_json',side_effect=error),self.assertRaises(ConnectionFailure) as failure:Core(config).ready()
    self.assertEqual(failure.exception.stage,'rpc');self.assertEqual(failure.exception.code,code);self.assertNotIn('private-test-value',str(failure.exception))
 def test_core_warming_up_is_distinct_from_auth(self):
  with tempfile.TemporaryDirectory() as root:
   cookie=Path(root)/'.cookie';cookie.write_text('u:p');config=Config(root).values;config['cookie']=str(cookie)
   with patch('node_client.http_json',return_value={'id':'wallaby-health','error':{'code':-28,'message':'private-test-value'}}),self.assertRaises(ConnectionFailure) as failure:Core(config).ready()
   self.assertEqual(failure.exception.code,'warming_up');self.assertNotIn('private-test-value',str(failure.exception))
 def test_dashboard_http_and_protocol_errors(self):
  client=NodeClient({},1234,threading.Event(),Mock())
  with patch('node_client.http_json',side_effect=HTTPFailure(403)),self.assertRaises(ConnectionFailure) as failure:client.post('register',{})
  self.assertEqual(failure.exception.stage,'dashboard')
  with patch.object(client.core,'ready'),patch.object(client,'post',return_value={'protocol':'wrong'}),patch('node_client.adapter_mac',return_value='02:11:22:33:44:55'),self.assertRaises(ConnectionFailure) as failure:client.run()
  self.assertEqual(failure.exception.code,'protocol')
 def test_rpc_failure_prevents_registration_and_green(self):
  status=Mock();client=NodeClient({},1234,threading.Event(),status);original=ConnectionFailure('rpc','cookie_missing','Choose the cookie.')
  with patch.object(client.core,'ready',side_effect=original),patch.object(client,'post') as post,self.assertRaises(ConnectionFailure) as failure:client.run()
  self.assertIs(failure.exception,original);post.assert_not_called();status.assert_not_called()
 def test_first_session_failure_is_preserved(self):
  client=NodeClient({},1234,threading.Event(),Mock());original=ConnectionFailure('rpc','refused','Local RPC refused connection.')
  client.fail(original);client.fail(HTTPFailure(401));self.assertIs(client.error,original);self.assertEqual(client.status.call_count,1);client.pool.shutdown()
 def test_raw_exception_messages_are_not_exposed(self):
  for error in (ValueError('secret-cookie-value'),OSError('Bearer secret-token'),RuntimeError('private RPC response')):self.assertNotIn(str(error),str(describe('dashboard',error)))
 def test_long_retry_preserves_original_status(self):
  with tempfile.TemporaryDirectory() as root,patch('runtime.runtime_dir',return_value=Path(root)),patch('runtime.time.time',return_value=1000):
   status={'updated':900,'color':'red','message':'Local RPC failed.','retry_at':1200};(Path(root)/'node.json').write_text(json.dumps(status));self.assertEqual(read_status('node')['message'],status['message'])
 def test_real_ssh_stderr_is_drained_and_classified(self):
  with tempfile.TemporaryDirectory() as root:
   config=Config(root).values;config['hostname']='server.test';tunnel=MasterConnection(config,root)
   process=subprocess.Popen([sys.executable,'-c','import sys; print("Permission denied (publickey).",file=sys.stderr)'],stderr=subprocess.PIPE)
   with patch('transport.subprocess.Popen',return_value=process):tunnel.start()
   process.wait(timeout=5);self.assertEqual(tunnel.failure().code,'authentication');tunnel.close()
 def test_worker_preserves_rpc_and_forwarding_errors(self):
  real_event=threading.Event
  for original,forwarded,expected in [(ConnectionFailure('rpc','cookie_missing','Choose the cookie.'),None,'cookie_missing'),(ConnectionFailure('dashboard','transport','Dashboard closed the connection.'),ConnectionFailure('ssh_forward','forward_denied','Server denied node forwarding.'),'forward_denied')]:
   class Stop:
    done=False
    def is_set(self):return self.done
    def set(self):self.done=True
    def wait(self,delay):
     if delay==2:real_event().wait(.02);return False
     self.done=True;return True
   stop=Stop();count=0
   def factory():
    nonlocal count
    count+=1;return stop if count==1 else real_event()
   with self.subTest(code=expected),tempfile.TemporaryDirectory() as root:
    config=Config(root).values;config['hostname']='server.test';config['enabled']['node']=True;tunnel=Mock();tunnel.alive.return_value=True;tunnel.failure.return_value=forwarded or ConnectionFailure('ssh','transport','SSH failed.')
    with patch('capabilities.node_support',return_value={'available':True}),patch('runtime.threading.Event',side_effect=factory),patch('runtime.signal.signal'),patch('runtime.Config') as cfg,patch('runtime.runtime_dir',return_value=Path(root)),patch('runtime.discover_cookie',return_value=''),patch('runtime.Tunnel',return_value=tunnel),patch('runtime.NodeClient') as node,patch('runtime.write_status') as status,patch('runtime.random.uniform',return_value=0),contextlib.redirect_stderr(io.StringIO()) as logs:
     cfg.return_value.values=config;node.return_value.run.side_effect=original;worker('node')
    failures=[call for call in status.call_args_list if call.kwargs.get('code')];self.assertEqual(failures[-1].kwargs['code'],expected);self.assertNotIn('Check IPv6, SSH key',failures[-1].args[2]);self.assertIn('code='+expected,logs.getvalue())
