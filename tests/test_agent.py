import copy, http.client, json, os, socket, sys, tempfile, threading, time, unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from configuration import Config,hostname,discover_cookie
from transport import ssh_command,Tunnel
from node_client import Core,NodeClient,decode
from runtime import apply_config
from agent_rpc import request
from app import Server,Handler

def setUpModule():
 global test_root,test_environment
 test_root=tempfile.TemporaryDirectory()
 test_environment=patch.dict(os.environ,{'XDG_CONFIG_HOME':test_root.name,'XDG_RUNTIME_DIR':test_root.name})
 test_environment.start()

def tearDownModule():
 test_environment.stop();test_root.cleanup()

class ConfigurationTests(unittest.TestCase):
 def test_hostname_rejects_ip_and_injection(self):
  for value in ['127.0.0.1','::1','[::1]','192.168.1.2','2130706433','http://host','host:22','-option','host;whoami','1.2.3','server/name']:
   with self.subTest(value=value),self.assertRaises(ValueError):hostname(value)
  self.assertEqual(hostname('Server.Example.COM.'),'server.example.com')
  self.assertEqual(hostname('myserver'),'myserver')
 def test_first_install_and_persistence(self):
  with tempfile.TemporaryDirectory() as root:
   c=Config(root);self.assertEqual(c.values['enabled'],dict(ddns=False,dashboard=False,node=False));self.assertEqual(c.values['hostname'],'')
   v=copy.deepcopy(c.values);v['hostname']='example.test';v['enabled']['ddns']=True;c.save(v)
   self.assertEqual(Config(root).values,v);self.assertEqual(c.path.stat().st_mode&0o777,0o600)
 def test_snap_cookie_discovery(self):
  with tempfile.TemporaryDirectory() as root:
   home=Path(root);cookie=home/'snap/bitcoin-core/common/.bitcoin/.cookie';cookie.parent.mkdir(parents=True);cookie.write_text('__cookie__:private')
   self.assertEqual(discover_cookie(home,home/'no-proc'),str(cookie))
 def test_running_core_custom_datadir(self):
  with tempfile.TemporaryDirectory() as root:
   home=Path(root);data=home/'custom';data.mkdir();(data/'.cookie').write_text('secret');proc=home/'proc/12';proc.mkdir(parents=True);(proc/'cmdline').write_bytes(b'bitcoin-qt\0-datadir='+str(data).encode()+b'\0')
   self.assertEqual(discover_cookie(home,home/'proc'),str(data/'.cookie'))
 def test_toggle_uses_only_user_units(self):
  with tempfile.TemporaryDirectory() as root,patch('runtime.ctl') as ctl,patch('runtime.write_status'):
   c=Config(root);v=copy.deepcopy(c.values);v['hostname']='server.test';v['enabled']['ddns']=True;apply_config(c,v)
   calls=[x.args for x in ctl.call_args_list];self.assertIn(('enable','--now','wallaby-agent-ddns.service'),calls);self.assertNotIn(('restart','wallaby-agent-ddns.service'),calls)
 def test_ssh_forces_ipv6_trust_and_loopback(self):
  c=Config().values;c['hostname']='server.test';args=ssh_command(c,'ddns',9876,'/tmp/test.sock')
  self.assertIn('-6',args);self.assertIn('StrictHostKeyChecking=yes',args);self.assertIn('[::1]:9876:[::1]:9876',args);self.assertEqual(args[-2:],['--','server.test']);self.assertNotIn('0.0.0.0',args)
 def test_busy_local_port_fails_before_ssh(self):
  with socket.socket(socket.AF_INET6) as s,tempfile.TemporaryDirectory() as root:
   s.bind(('::1',0));t=Tunnel(Config().values,'ddns',root);t.port=s.getsockname()[1]
   with patch('transport.master_info',return_value={'control':str(Path(root)/'ssh-test.sock')}):
    with self.assertRaises(OSError):t.start()

class RPCTests(unittest.TestCase):
 def test_rejects_dangerous_calls_and_private_exports(self):
  for method,params,wallet in [('sendtoaddress',[],None),('walletpassphrase',[],None),('listdescriptors',[True],'wallet'),('createwallet',{'wallet_name':'unsafe'},None)]:
   with self.assertRaises(ValueError):request(method,params,wallet)
 def test_public_watchonly_policy(self):
  p={'wallet_name':'watch','disable_private_keys':True,'blank':True,'descriptors':True}
  with self.assertRaises(ValueError):request('createwallet',p,None)
 def test_duplicate_command_executes_once(self):
  n=NodeClient(Config().values,1234,threading.Event(),lambda *_:None);c={'id':'id','kind':'rpc','method':'getblockchaininfo','params':[],'wallet':None,'expires_in_seconds':10}
  with patch.object(n,'post',side_effect=[{'execute':True},{'accepted':True}]) as post,patch.object(n.core,'call',return_value={'result':1}) as core:
   n.consume({'commands':[c]});n.consume({'commands':[c]});n.pool.shutdown(wait=True)
   self.assertEqual(core.call_count,1);self.assertEqual(post.call_count,2)
 def test_lost_ack_does_not_execute(self):
  n=NodeClient(Config().values,1234,threading.Event(),lambda *_:None);c={'id':'id','kind':'rpc','method':'getblockchaininfo','params':[],'wallet':None,'expires_in_seconds':10};n.pending.acquire()
  with patch.object(n,'post',side_effect=ConnectionError),patch.object(n.core,'call') as core:n.execute(c,time.monotonic());core.assert_not_called()
  n.pool.shutdown()
 def test_core_wallet_encoding_cookie_rotation_and_decimals(self):
  with tempfile.TemporaryDirectory() as root:
   cookie=Path(root)/'.cookie';cookie.write_text('u:first');c=Config().values;c['cookie']=str(cookie);core=Core(c)
   with patch('node_client.http_json',return_value={'id':'test','result':{'balance':Decimal('0.00000001')}}) as http:
    self.assertEqual(core.call('test','getbalances',[],'family/wallet #1')['result']['balance'],'0.00000001');self.assertEqual(http.call_args.args[1],'/wallet/family%2Fwallet%20%231');self.assertEqual(http.call_args.kwargs['auth'],'u:first')
    cookie.write_text('u:second');core.call('test','getbalances',[]);self.assertEqual(http.call_args.kwargs['auth'],'u:second')
 def test_core_id_mismatch_and_duplicate_json_rejected(self):
  with self.assertRaises(ValueError):decode('{"a":1,"a":2}')
  with self.assertRaises(ValueError):decode('{"a":NaN}')
 def test_node_never_green_without_core(self):
  status=Mock();n=NodeClient(Config().values,1234,threading.Event(),status)
  with patch.object(n.core,'ready',side_effect=ConnectionError),self.assertRaises(ConnectionError):n.run()
  status.assert_not_called();n.pool.shutdown()

class WebSecurityTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.temp.name,'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
  self.server=Server(('127.0.0.1',0),Handler);self.server.token='secret';self.server.config_lock=threading.Lock();self.server.preview=True;self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();self.temp.cleanup()
 def call(self,path,headers=None,body=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);c.request('POST' if body is not None else 'GET',path,body,headers or {});r=c.getresponse();data=r.read();c.close();return r.status,json.loads(data) if path.startswith('/api') else data
 def test_retired_vault_builder_assets_are_not_served(self):
  self.assertEqual(self.call('/timezones.json')[0],404)
  self.assertEqual(self.call('/api/wallets',{'Authorization':'Bearer secret'})[0],404)
 def test_token_and_origin(self):
  self.assertEqual(self.call('/api/state')[0],403)
  self.assertEqual(self.call('/api/state',{'Authorization':'Bearer secret','Origin':'https://evil.test'})[0],403)
  self.assertEqual(self.call('/api/state',{'Authorization':'Bearer secret','Host':'evil.test'})[0],403)
  code,data=self.call('/api/state',{'Authorization':'Bearer secret'});self.assertEqual(code,200);self.assertFalse(any(data['config']['enabled'].values()))
 def test_ip_rejected_and_name_saved(self):
  headers={'Authorization':'Bearer secret','Content-Type':'application/json'}
  self.assertEqual(self.call('/api/hostname',headers,json.dumps({'hostname':'::1'}))[0],400)
  self.assertEqual(self.call('/api/hostname',headers,json.dumps({'hostname':'server.test'}))[0],200)
  self.assertEqual(Config().values['hostname'],'server.test')
 def test_retired_service_is_not_exposed_or_accepted(self):
  headers={'Authorization':'Bearer secret','Content-Type':'application/json'}
  code,data=self.call('/api/state',headers)
  self.assertEqual(code,200);self.assertEqual(data['version'],'V2 Development build 9')
  self.assertEqual(set(data['config']['enabled']),{'ddns','dashboard','node'});self.assertNotIn('jellyfin',data['status'])
  self.assertEqual(self.call('/api/toggle',headers,json.dumps({'service':'jellyfin','enabled':True}))[0],400)
 def test_dashboard_toggle_does_not_require_cookie_or_enable_node(self):
  headers={'Authorization':'Bearer secret','Content-Type':'application/json'}
  self.assertEqual(self.call('/api/hostname',headers,json.dumps({'hostname':'server.test'}))[0],200)
  self.assertEqual(self.call('/api/toggle',headers,json.dumps({'service':'dashboard','enabled':True}))[0],200)
  config=Config().values;self.assertTrue(config['enabled']['dashboard']);self.assertFalse(config['enabled']['node']);self.assertEqual(config['cookie'],'')

if __name__=='__main__':unittest.main()

class LifecycleTests(unittest.TestCase):
 def test_retry_backoff_and_red_before_retry(self):
  import runtime
  class Stop:
   def __init__(self):self.delays=[]
   def is_set(self):return len(self.delays)>=3
   def set(self):pass
   def clear(self):pass
   def wait(self,d):self.delays.append(d);return self.is_set()
  event=Stop();v=Config().values;v['hostname']='server.test';v['enabled']['ddns']=True;tunnel=Mock();tunnel.start.side_effect=ConnectionError
  with tempfile.TemporaryDirectory() as root,patch('runtime.signal.signal'),patch('runtime.threading.Event',return_value=event),patch('runtime.Config') as config,patch('runtime.Tunnel',return_value=tunnel),patch('runtime.runtime_dir',return_value=Path(root)),patch('runtime.random.uniform',return_value=0),patch('runtime.write_status') as status:
   config.return_value.values=v;runtime.worker('ddns')
   self.assertEqual(event.delays,[15,30,60]);self.assertEqual([x.args[1] for x in status.call_args_list],['amber','red','amber','red','amber','red','red'])
