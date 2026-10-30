"""Tunnel-only installation and optional Bitcoin dependencies; no live service changes."""
import http.client,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from capabilities import node_support,require_node,NodeUnavailable
from configuration import Config
from app import Server,Handler

class OptionalDependencies(unittest.TestCase):
 def test_missing_bitcoin_desktop_components_are_actionable_without_probing_rpc(self):
    with patch('capabilities.importlib.util.find_spec',side_effect=ModuleNotFoundError),patch('capabilities.shutil.which',return_value=None),patch('capabilities.discover_cookie',return_value=''):
     status=node_support({'cookie':''});self.assertFalse(status['available']);self.assertIn('python3-pyqt6.qtwebengine',status['message']);self.assertIn('pkexec polkitd',status['message']);self.assertIn('kdialog',status['message']);self.assertIn('RPC',status['message']);self.assertIn('tunnels remain available',status['message'])
     with self.assertRaises(NodeUnavailable):require_node({'cookie':''})
 def test_existing_snap_or_manual_core_cookie_does_not_require_apt_bitcoind_binary(self):
    with tempfile.TemporaryDirectory() as tmp,patch('capabilities.importlib.util.find_spec',return_value=object()),patch('capabilities.shutil.which',return_value='/fixture/tool'):
     cookie=Path(tmp)/'.cookie';cookie.write_text('fixture:never-read')
     self.assertTrue(node_support({'cookie':str(cookie)})['available'])
 def test_disc_tool_is_optional_and_reports_its_own_install_command(self):
    from disc_backup import media
    with patch('disc_backup.shutil.which',return_value=None):
     with self.assertRaisesRegex(ValueError,'sudo apt install xorriso'):media('/dev/sr0')
 def test_package_has_only_tunnel_runtime_dependencies_and_no_core_recommendation(self):
    script=(Path(__file__).resolve().parents[1]/'packaging/build.py').read_text();control=script.split("put('DEBIAN/control',f'''",1)[1].split("''')",1)[0]
    depends=next(x for x in control.splitlines() if x.startswith('Depends:'))
    for name in ('policykit-1','python3-pyqt6','pkexec','polkitd','xorriso','bitcoind'):self.assertNotIn(name,depends)
    self.assertNotIn('Recommends:',control);self.assertNotIn('policykit-1',control);self.assertIn('Suggests: pkexec, polkitd',control)
 def test_protected_start_refuses_before_os_auth_when_optional_requirements_missing(self):
    from secure_bridge import start
    with patch('capabilities.require_node',side_effect=NodeUnavailable('Optional components missing')),patch('secure_bridge.subprocess.run') as command:
     with self.assertRaises(NodeUnavailable):start()
     command.assert_not_called()

class TunnelOnlyAPI(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'XDG_RUNTIME_DIR':self.tmp.name});self.env.start();self.server=Server(('127.0.0.1',0),Handler);self.server.token='fixture';self.server.config_lock=threading.Lock();self.server.preview=True;self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
    self.missing=patch('app.node_support',return_value={'available':False,'message':'Node unavailable: install optional Bitcoin components. SSH tunnels remain available.','missing':['viewer','cookie']});self.missing.start()
 def tearDown(self):self.missing.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();self.tmp.cleanup()
 def call(self,path,body=None):
    origin='http://127.0.0.1:'+str(self.server.server_port);headers={'Host':origin[7:],'Origin':origin,'Authorization':'Bearer fixture','Content-Type':'application/json'}
    connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port);connection.request('POST' if body is not None else 'GET',path,None if body is None else json.dumps(body),headers);response=connection.getresponse();data=json.loads(response.read());connection.close();return response.status,data
 def test_tunnel_settings_and_both_services_work_while_node_is_unavailable(self):
    self.assertEqual(self.call('/api/hostname',{'hostname':'server.example.com'})[0],200)
    for service in ('ddns','dashboard'):
     self.assertEqual(self.call('/api/toggle',{'service':service,'enabled':True})[0],200)
    status,state=self.call('/api/state');self.assertEqual(status,200);self.assertFalse(state['node_support']['available']);self.assertTrue(state['config']['enabled']['ddns']);self.assertTrue(state['config']['enabled']['dashboard']);self.assertFalse(state['config']['enabled']['node'])
 def test_node_enable_failure_never_saves_enabled_flag_or_changes_other_tunnels(self):
    config=Config();v=config.values;v['hostname']='server.example.com';v['enabled']['dashboard']=True;config.save(v)
    with patch('app.require_node',side_effect=NodeUnavailable('Install optional viewer and configure Core RPC. SSH tunnels remain available.')):
     status,result=self.call('/api/toggle',{'service':'node','enabled':True})
    self.assertEqual(status,400);self.assertIn('configure Core RPC',result['error']);v=Config().values;self.assertFalse(v['enabled']['node']);self.assertTrue(v['enabled']['dashboard'])
 def test_switching_off_old_node_preference_always_works(self):
    config=Config();v=config.values;v['enabled']['node']=True;config.save(v)
    with patch('app.require_node',side_effect=AssertionError('Must allow off')):
     self.assertEqual(self.call('/api/toggle',{'service':'node','enabled':False})[0],200)

class StartupGuards(unittest.TestCase):
 def test_node_worker_checks_optional_components_before_creating_ssh_tunnel(self):
    from runtime import worker
    class Stop:
     done=False
     def is_set(self):return self.done
     def wait(self,delay):self.done=True;return True
    with tempfile.TemporaryDirectory() as tmp:
     v=Config(tmp).values;v['hostname']='server.example.com';v['enabled']['node']=True
     with patch('runtime.threading.Event',return_value=Stop()),patch('runtime.signal.signal'),patch('runtime.Config') as config,patch('runtime.discover_cookie',return_value=''),patch('capabilities.node_support',return_value={'available':False,'message':'Optional Bitcoin components missing.'}),patch('runtime.Tunnel') as tunnel,patch('runtime.write_status') as status,patch('runtime.random.uniform',return_value=0):
      config.return_value.values=v;worker('node');tunnel.assert_not_called();self.assertTrue(any(call.kwargs.get('code')=='node_prerequisites' for call in status.call_args_list))
 def test_login_keeps_ssh_monitor_without_launching_unavailable_protected_workspace(self):
    from app import bootstrap
    with tempfile.TemporaryDirectory() as tmp:
     config=Config(tmp);v=config.values;v['enabled']['node']=True;config.save(v)
     with patch('app.Config',return_value=config),patch('app.runtime_dir',return_value=Path(tmp)),patch('app.retire_jellyfin'),patch('app.ctl') as ctl,patch('protected_memory.required',return_value=True),patch('app.require_node',side_effect=NodeUnavailable('Optional Bitcoin components missing.')),patch('app.write_status'),patch('secure_bridge.ensure_running') as launch:
      bootstrap();launch.assert_not_called();self.assertIn(('enable','--now','wallaby-agent-monitor.service'),[call.args for call in ctl.call_args_list])
