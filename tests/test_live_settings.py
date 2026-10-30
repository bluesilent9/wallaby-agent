import copy,http.client,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from app import Handler,Server
from configuration import Config

class LiveSettings(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.temp.name,'XDG_RUNTIME_DIR':self.temp.name});self.env.start()
  self.server=Server(('127.0.0.1',0),Handler);self.server.token='test-token';self.server.config_lock=threading.Lock();self.server.preview=True
  self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();self.temp.cleanup()
 def call(self,path,headers=None,body=None,host=None):
  h={'Host':host or '127.0.0.1:'+str(self.server.server_port),**(headers or {})};raw=None if body is None else json.dumps(body)
  if body is not None:h['Content-Type']='application/json'
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);c.request('GET' if body is None else 'POST',path,raw,h);r=c.getresponse();data=r.read();c.close();return r.status,json.loads(data) if path.startswith('/api/') else data
 def test_fresh_tab_without_fragment_bootstraps_local_session(self):
  headers={'Sec-Fetch-Site':'same-origin','X-Wallaby-UI':'1'}
  status,r=self.call('/api/session',headers);self.assertEqual(status,200)
  status,state=self.call('/api/state',{'Authorization':'Bearer '+r['token']});self.assertEqual(status,200);self.assertEqual(state['config']['ssh_port'],22)
 def test_session_cannot_be_read_from_cross_origin_or_rebound_host(self):
  for headers in ({},{'X-Wallaby-UI':'1','Sec-Fetch-Site':'cross-site'},{'X-Wallaby-UI':'1','Sec-Fetch-Site':'same-site'},{'X-Wallaby-UI':'1','Sec-Fetch-Site':'same-origin','Origin':'https://evil.example'}):self.assertEqual(self.call('/api/session',headers)[0],403)
  self.assertEqual(self.call('/api/session',{'X-Wallaby-UI':'1','Sec-Fetch-Site':'same-origin'},host='evil.example:'+str(self.server.server_port))[0],403)
  self.assertEqual(self.call('/api/state')[0],403)
 def test_localhost_alias_and_new_tab_authorise_route_work(self):
  self.assertEqual(self.call('/?page=authorise')[0],200)
  self.assertEqual(self.call('/api/session',{'X-Wallaby-UI':'1','Sec-Fetch-Site':'same-origin'},host='localhost:'+str(self.server.server_port))[0],200)
 def test_partial_live_edits_preserve_other_fields_and_file_reload(self):
  headers={'Authorization':'Bearer test-token'}
  for patchdata in ({'hostname':'calder.vip'},{'ssh_user':'dave-laptop'},{'ssh_port':2222}):self.assertEqual(self.call('/api/patch',headers,patchdata)[0],200)
  c=Config();self.assertEqual(c.values['hostname'],'calder.vip');self.assertEqual(c.values['ssh_user'],'dave-laptop');self.assertEqual(c.values['ssh_port'],2222)
  v=copy.deepcopy(c.values);v['ssh_port']=22;v['enabled']['dashboard']=True;c.save(v)
  status,r=self.call('/api/state',headers);self.assertEqual(r['config']['ssh_port'],22);self.assertTrue(r['config']['enabled']['dashboard'])
 def test_invalid_edit_does_not_replace_last_valid_saved_setting(self):
  headers={'Authorization':'Bearer test-token'}
  self.call('/api/patch',headers,{'hostname':'calder.vip'})
  self.assertEqual(self.call('/api/patch',headers,{'hostname':'192.0.2.1'})[0],400);self.assertEqual(Config().values['hostname'],'calder.vip')
 def test_connect_requests_ssh_and_does_not_change_service_choices(self):
  h={'Authorization':'Bearer test-token'};self.call('/api/patch',h,{'hostname':'calder.vip'})
  self.assertEqual(self.call('/api/connect',h,{})[0],200);self.assertFalse(any(Config().values['enabled'].values()));self.assertTrue((Path(self.temp.name)/'wallaby-agent/connect-request.json').exists())
 def test_no_save_button_or_old_local_access_warning(self):
  raw=self.call('/')[1].decode();self.assertIn('Connect <span>',raw);self.assertNotIn('Save settings',raw);self.assertNotIn('Accept server',raw)

 def test_bootstrap_refreshes_old_services_once_and_keeps_new_master_on_reopen(self):
  from app import bootstrap
  root=Path(self.temp.name)/'wallaby-agent';root.mkdir(exist_ok=True)
  with patch('app.retire_jellyfin'),patch('app.ctl') as ctl:
   bootstrap();self.assertIn(('restart','wallaby-agent-monitor.service'),[c.args for c in ctl.call_args_list])
  (root/'monitor-build.json').write_text(json.dumps({'version':'2.0.0~dev12'}))
  with patch('app.retire_jellyfin'),patch('app.ctl') as ctl:
   bootstrap();self.assertNotIn(('restart','wallaby-agent-monitor.service'),[c.args for c in ctl.call_args_list])
 def test_old_running_ui_is_restarted_and_new_launch_url_contains_no_secret(self):
  from app import launch
  root=Path(self.temp.name)/'wallaby-agent';root.mkdir(exist_ok=True);(root/'ui.json').write_text(json.dumps({'port':1234,'token':'old-test-token','pid':123,'version':'2.0.0~dev5'}))
  with patch('app.bootstrap'),patch('app.os.kill'),patch('app.ctl') as ctl,patch('http.client.HTTPConnection') as conn,patch('app.webbrowser.open') as opened:
   conn.return_value.getresponse.return_value.status=200;launch('authorise')
  self.assertIn(('restart','wallaby-agent-ui.service'),[c.args for c in ctl.call_args_list]);self.assertEqual(opened.call_args.args[0],'http://127.0.0.1:1234/?page=authorise')
 def test_external_rpc_edit_invalidates_old_review_and_local_rpc_client(self):
  from app import wallet_ops
  a=wallet_ops(self.server);a.prepared['old-review']={'test':True};v=copy.deepcopy(Config().values);v['rpc_port']=18332;Config().save(v)
  b=wallet_ops(self.server);self.assertIsNot(a,b);self.assertEqual(b.core.config['rpc_port'],18332);self.assertNotIn('old-review',b.prepared)

 def test_page_launcher_health_does_not_require_bitcoin_core(self):
  with patch('app.wallet_ops',side_effect=AssertionError('Core must not be queried for UI health')):
   status,r=self.call('/api/health',{'Authorization':'Bearer test-token'});self.assertEqual(status,200);self.assertTrue(r['ok'])
