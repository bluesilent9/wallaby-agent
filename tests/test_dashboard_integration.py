"""Real V155 registry, HTTP handler and broker with a simulated local Core."""
import http.server,json,os,re,sys,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).parent/'fixtures/dashboard_v155'))
# Isolate the one HTTP authority helper from the full browser/tax application.
stub=types.ModuleType('launch_wallaby_bitcoin_dashboard')
def loopback_authority(authority):
 match=re.fullmatch(r'(127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?',authority or '')
 return bool(match and (match[2] is None or 1<=int(match[2])<=65535))
stub.loopback_authority=loopback_authority
sys.modules.setdefault('launch_wallaby_bitcoin_dashboard',stub)
from nodes import NodeRegistry,create_agent_server
from node_client import NodeClient
from configuration import Config

class FakeCore(http.server.BaseHTTPRequestHandler):
 calls=[]
 def log_message(self,*_):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.calls.append((self.path,body,self.headers.get('Authorization')))
  if body['method']=='getbalances':
   result='{"mine":{"trusted":0.00000001}}'
  else:result='{"chain":"main","blocks":970000}'
  raw=('{"jsonrpc":"2.0","id":'+json.dumps(body['id'])+',"result":'+result+'}').encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class DashboardIntegration(unittest.TestCase):
 def test_real_hub_registration_rpc_decimal_and_disconnect(self):
  with tempfile.TemporaryDirectory() as root:
   registry=NodeRegistry(Path(root)/'dashboard.cfg');hub=create_agent_server(registry,port=0,ipv6=False);hub.start()
   core=http.server.ThreadingHTTPServer(('127.0.0.1',0),FakeCore);ct=threading.Thread(target=core.serve_forever);ct.start();cookie=Path(root)/'.cookie';cookie.write_text('__cookie__:TEST_ONLY')
   config=Config().values;config['cookie']=str(cookie);config['rpc_port']=core.server_port
   stop=threading.Event();statuses=[];errors=[];client=NodeClient(config,hub.server_port,stop,lambda *s:statuses.append(s))
   def run():
    try:client.run()
    except Exception as e:errors.append(e)
   with patch('node_client.adapter_mac',return_value='02:11:22:33:44:55'):
    t=threading.Thread(target=run);t.start()
    try:
     deadline=time.monotonic()+8
     while not statuses and not errors and time.monotonic()<deadline:time.sleep(.02)
     self.assertFalse(errors);self.assertEqual(statuses[0][0],'green');node_id=next(iter(registry.connections.values()))['node_id']
     queued=registry.rpc.queue(node_id,'getbalances',[],wallet='Family / node',timeout_seconds=10)
     deadline=time.monotonic()+8
     while time.monotonic()<deadline:
      row=registry.rpc.status(queued['id'])
      if row['state'] in ('succeeded','failed'):break
      time.sleep(.02)
     self.assertEqual(row['state'],'succeeded',row);self.assertEqual(row['result']['mine']['trusted'],'0.00000001')
     self.assertTrue(any(p=='/wallet/Family%20%2F%20node/' for p,_,_ in FakeCore.calls))
     # Wake any long poll, then end gracefully.
     stop.set();registry.rpc.queue(node_id,'getblockcount',[],timeout_seconds=5);t.join(5)
     self.assertFalse(t.is_alive());self.assertFalse(registry.connections);self.assertFalse(errors)
    finally:
     stop.set();registry.reset();t.join(5);hub.close();core.shutdown();core.server_close();ct.join()
