"""Tunnel-only installation and optional Bitcoin dependencies; no live service changes."""
import http.client,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from capabilities import node_support,require_node,NodeUnavailable
from configuration import Config
from app import Server,Handler

class OptionalDependencies(unittest.TestCase):
 pass

class TunnelOnlyAPI(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'XDG_RUNTIME_DIR':self.tmp.name});self.env.start();self.server=Server(('::1',0),Handler);self.server.token='fixture';self.server.config_lock=threading.Lock();self.server.preview=True;self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
    self.missing=patch('app.node_support',return_value={'available':False,'message':'Node unavailable: install optional Bitcoin components. SSH tunnels remain available.','missing':['viewer','cookie']});self.missing.start()
 def tearDown(self):self.missing.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();self.tmp.cleanup()
 def call(self,path,body=None):
    origin='http://[::1]:'+str(self.server.server_port);headers={'Host':origin[7:],'Origin':origin,'Authorization':'Bearer fixture','Content-Type':'application/json'}
    connection=http.client.HTTPConnection('::1',self.server.server_port);connection.request('POST' if body is not None else 'GET',path,None if body is None else json.dumps(body),headers);response=connection.getresponse();data=json.loads(response.read());connection.close();return response.status,data

class StartupGuards(unittest.TestCase):
 pass
