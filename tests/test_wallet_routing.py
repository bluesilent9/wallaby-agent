"""Regression for actual Core wallet endpoint identity, not a reimplemented proxy."""
import json,sys,tempfile,threading,time,unittest
from pathlib import Path
from urllib.parse import quote,unquote
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from node_client import Core,NodeClient
from agent_rpc import request

class WalletRouting(unittest.TestCase):
 def test_exact_core_endpoints_including_empty_spaces_unicode_slashes_and_trailing_slash(self):
    names=['','sample_wallet','Family Wallet/Watch','wallet/','name # percent%','épargne']
    paths=[]
    class Handler(BaseHTTPRequestHandler):
      def log_message(self,*args):pass
      def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));paths.append(self.path)
        name=unquote(self.path[len('/wallet/'):]) if self.path.startswith('/wallet/') else None
        result={'jsonrpc':'2.0','id':body['id']}
        if name in names:result['result']={'walletname':name}
        else:result['error']={'code':-18,'message':'Requested wallet does not exist or is not loaded'}
        data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
      with tempfile.TemporaryDirectory() as d:
        cookie=Path(d)/'.cookie';cookie.write_text('fixture:fixture');core=Core({'cookie':str(cookie),'rpc_port':server.server_port})
        for name in names:
          self.assertEqual(core.call('test','getwalletinfo',[],wallet=name)['result']['walletname'],name)
          self.assertEqual(paths[-1],'/wallet/'+quote(name,safe=''))
          self.assertEqual(request('getwalletinfo',[],name)[0],[])
    finally:server.shutdown();server.server_close();thread.join()
 def test_busy_agent_waits_for_worker_instead_of_dropping_session(self):
    node=NodeClient({},1,threading.Event(),lambda *_:None);active=0;peak=0;count=0;lock=threading.Lock()
    def core(*args,**kwargs):
      nonlocal active,peak,count
      with lock:active+=1;count+=1;peak=max(peak,active)
      time.sleep(.03)
      with lock:active-=1
      return {'result':{}}
    with patch.object(node.core,'call',side_effect=core),patch.object(node,'post',side_effect=lambda path,body:{'execute':True} if path=='ack' else {'accepted':True}):
      for i in range(8):node.consume({'commands':[{'id':str(i),'kind':'rpc','method':'getwalletinfo','params':[],'wallet':'fixture','expires_in_seconds':10}]})
      node.pool.shutdown(wait=True)
    self.assertEqual(count,8);self.assertLessEqual(peak,2);self.assertFalse(node.failed.is_set())

if __name__=='__main__':unittest.main()
