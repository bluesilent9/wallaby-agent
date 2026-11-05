"""Complete Agent signing -> HTTP exchange -> Dashboard workflow tests."""
import base64,copy,json,os,subprocess,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
import socket
root=Path(__file__).resolve().parents[1]
if not os.environ.get('WALLABY_TEST_DASHBOARD'):raise SystemExit('Set WALLABY_TEST_DASHBOARD to the matching Dashboard source checkout.')
dash=Path(os.environ['WALLABY_TEST_DASHBOARD'])
sys.path[:0]=[str(dash),str(dash/'tests')]
from test_build8 import Setup
from test_build11 import Signing
from agent_transactions import queue_sign,eligible,signing_state
from transaction_workflows import WorkflowStore
from signed_psbt import decode,serialize
from vendor.embit import bip32
from vendor.embit.transaction import TransactionOutput
from vendor.embit.descriptor import Descriptor
from vendor.embit.networks import NETWORKS

class Server(HTTPServer):address_family=socket.AF_INET6
results=[]
for case in ('single','multiple_recipients','multisig'):
 fixture=Signing() if case=='multisig' else Setup();fixture.setUp()
 try:
  job=fixture.install_shared() if case=='multisig' else fixture.job()
  if case=='multiple_recipients':
   document=decode(base64.b64decode(fixture.unsigned));spk=document['tx'].vout[0].script_pubkey;other=Descriptor.from_string('wpkh('+bip32.HDKey.from_seed(b'another invented recipient seed!').key.get_public_key().sec().hex()+')').script_pubkey()
   document['tx'].vout=[TransactionOutput(49000,spk),TransactionOutput(50000,other)];document['global'][b'\x00']=document['tx'].serialize();document['outputs']=[{},{}]
   store=WorkflowStore(fixture.config);data=store._read();data['jobs'][job]['psbt']=base64.b64encode(serialize(document)).decode();store._write(data)
  fixture.hub.caps[fixture.a['node_id']]={'partial_signing'}
  if case=='multisig':fixture.hub.caps[fixture.b['node_id']]={'partial_signing'}
  choices=eligible(fixture.hub,fixture.rid);session=type('Session',(),{'user_id':fixture.user})();reports=[]
  for index,choice in enumerate(choices):
   queued=queue_sign(fixture.hub,session,job,fixture.rid,choice['id'],choice['signer_id']);proposal=fixture.hub.read()['requests'][queued['request_hash']]['proposal'];document=decode(base64.b64decode(proposal['psbt']))
   private=[bip32.HDKey.from_seed(bytes([i+1])*32).key for i in range(3)] if case=='multisig' else [fixture.master.derive('m/0/0').key]
   if case=='multisig':body='wsh(multi(2,'+','.join(k.wif(NETWORKS['regtest']) if i==index else k.get_public_key().sec().hex() for i,k in enumerate(private))+'))'
   else:body='wpkh('+private[0].wif(NETWORKS['regtest'])+')'
   token=next(n['connection_token'] for n in (fixture.a,fixture.b) if n['node_id']==choice['id']);requests=[];dropped=[False]
   class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
     try:
      body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body);result=fixture.hub.exchange(token,body)
      # Reproduce a lost acknowledgement after Dashboard already stored the
      # signature. The Agent must deliver again without asking Core to re-sign.
      if case=='single' and not dropped[0]:dropped[0]=True;self.close_connection=True;return
      raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
     except Exception as e:
      raw=json.dumps({'error':str(e)}).encode();self.send_response(400);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   server=Server(('::1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with tempfile.TemporaryDirectory() as directory:
     data=Path(directory)/'input.json';data.write_text(json.dumps({'proposal':proposal,'private_descriptor':body,'previous':document['inputs'][0][b'\x00'].hex(),'port':server.server_port,'token':token}))
     run=subprocess.run([sys.executable,str(root/'tests/signing_delivery_runner.py'),str(data)],capture_output=True,text=True,timeout=90)
     assert run.returncode==0,run.stdout+run.stderr;report=json.loads(run.stdout);assert report['sign_calls']==1;reports.append(report)
     view=signing_state(fixture.hub,fixture.user,job);assert view['all_signed']==(case!='multisig' or index==1),view
   finally:server.shutdown();server.server_close();thread.join()
  results.append({'case':case,'dashboard_all_signed':view['all_signed'],'agents':reports})
 finally:fixture.doCleanups()
print(json.dumps({'Dashboard':int(dash.name.rsplit('build',1)[1]),'Agent':55,'live_wallets_accessed':False,'cases':results},indent=2))
