"""Real test-chain broadcast through the Wallet Server/Agent exchange protocol."""
import base64,json,os,socket,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
dash=Path(os.environ['WALLABY_TEST_DASHBOARD']);sys.path[:0]=[str(dash),str(dash/'tests')]
from test_build8 import Setup
from agent_transactions import queue_broadcast,signing_state
from transaction_workflows import WorkflowStore
from multisig_psbt import validate_partial
fixture=Setup();fixture.setUp()
import subprocess
fixture_source=dash/'tests/core31_psbt_check.py'
namespace={'__file__':str(fixture_source)}
exec(fixture_source.read_text().split('from vault_composition import')[0],namespace)
Regtest,rpc=namespace['Regtest'],namespace['rpc']
node=Regtest()
class Server(HTTPServer):address_family=socket.AF_INET6
try:
 c=node.core;rpc(c,'createwallet',{'wallet_name':'miner'});miner=rpc(c,'getnewaddress',[],'miner');rpc(c,'generatetoaddress',[105,miner]);rpc(c,'createwallet',{'wallet_name':'sender','passphrase':'test-password'});address=rpc(c,'getnewaddress',[],'sender');txid=rpc(c,'sendtoaddress',[address,'0.1'],'miner');rpc(c,'generatetoaddress',[1,miner]);coin=next(r for r in rpc(c,'listunspent',[0],'sender') if r['txid']==txid)
 built=rpc(c,'walletcreatefundedpsbt',{'inputs':[{'txid':txid,'vout':coin['vout']}],'outputs':[{miner:'0.1'}],'options':{'add_inputs':False,'subtractFeeFromOutputs':[0],'fee_rate':1}},'sender')
 rpc(c,'walletpassphrase',['test-password',60],'sender');signed=rpc(c,'walletprocesspsbt',{'psbt':built['psbt'],'sign':True,'finalize':False},'sender')['psbt'];rpc(c,'walletlock',[],'sender')
 expected=rpc(c,'decoderawtransaction',[rpc(c,'finalizepsbt',[signed])['hex']])['txid'];assert expected not in rpc(c,'getrawmempool')
 job=fixture.job();workflow=WorkflowStore(fixture.config);data=workflow._read();proofs,_=validate_partial(built['psbt'],signed.encode(),[0]);data['jobs'][job].update(psbt=built['psbt'],signed_uploads={fixture.rid:{'proofs':proofs}});workflow._write(data)
 fixture.hub.caps[fixture.a['node_id']]={'automatic_broadcast_v1','partial_signing','broadcast'};session=type('Session',(),{'user_id':fixture.user})();queued=queue_broadcast(fixture.hub,session,job,fixture.a['node_id']);assert queued['txid']==expected
 fixture.hub.rpc=lambda node_id,method,params=None,wallet=None:rpc(c,method,params,wallet)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   try:
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));result=fixture.hub.exchange(fixture.a['connection_token'],body);raw=json.dumps(result).encode();self.send_response(200)
   except Exception as e:raw=json.dumps({'error':str(e)}).encode();self.send_response(400)
   self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 server=Server(('::1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  with tempfile.TemporaryDirectory() as directory:
   data=Path(directory)/'input.json';data.write_text(json.dumps({'rpc_port':node.port,'cookie':str(Path(node.root.name)/'regtest/.cookie'),'port':server.server_port,'token':fixture.a['connection_token'],'txid':expected,'key':queued['request_hash']}))
   run=subprocess.run([sys.executable,str(root/'tests/automatic_broadcast_runner.py'),str(data)],capture_output=True,text=True,timeout=40)
   assert run.returncode==0,run.stdout+run.stderr
   report=json.loads(run.stdout);assert report['pending']==0 and report['acknowledged'] and report['prompts']==0
   result=signing_state(fixture.hub,fixture.user,job);assert result['broadcast_txid']==expected;assert result['broadcast_request']['state']=='complete';assert result['can_complete']
   print(json.dumps({'Agent':56,'Wallet Server':64,'signed_without_broadcast':True,'later_dashboard_request_published':True,'core_mempool_confirmed':True,'dashboard_confirmed_exact_raw_transaction':True,'broadcast_receipt_acknowledged':True,'agent_pending_requests':0,'native_prompts':0,'live_wallets_accessed':False},indent=2))
 finally:server.shutdown();server.server_close();thread.join()
finally:node.close();fixture.doCleanups()
