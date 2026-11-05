"""Child process for Dashboard/Agent interoperability, using only invented keys."""
import base64,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from regtest_support import Regtest
from wallet_ops import WalletOps,rpc
from approval_store import Store,digest
from agent_exchange import Exchange
from vendor.embit.descriptor.checksum import checksum

args=json.loads(Path(sys.argv[1]).read_text());node=Regtest()
try:
 core=node.core;name=args['proposal']['wallet'];password='disposable-test-password'
 rpc(core,'createwallet',{'wallet_name':name,'blank':True,'passphrase':password})
 rpc(core,'walletpassphrase',[password,60],name)
 body=args['private_descriptor'];result=rpc(core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':'now','active':False}]],name);assert all(r.get('success') for r in result),result
 rpc(core,'walletlock',[],name)
 previous=rpc(core,'decoderawtransaction',[args['previous']]);original=core.call;sign_calls=[0]
 def call(ident,method,params,wallet=None,timeout=30):
  if method=='getrawtransaction' and params[0]==previous['txid']:return {'result':previous}
  if method=='gettxout' and params[0]==previous['txid']:return {'result':previous['vout'][params[1]]}
  if method=='walletprocesspsbt' and isinstance(params,dict) and params.get('sign'):sign_calls[0]+=1
  r=original(ident,method,params,wallet,timeout=timeout)
  # The fixture transaction is network-independent, but Dashboard's protocol
  # deliberately only accepts mainnet proposals. No real chain is contacted.
  if method=='getblockchaininfo' and 'result' in r:r['result']['chain']='main'
  return r
 core.call=call
 with tempfile.TemporaryDirectory() as directory:
  store=Store(directory);ops=WalletOps(core,store);store.receive(args['proposal']);key=digest(args['proposal']);ops.prepare_request(key);signed=ops.sign(key,password,'partial',True)
  assert signed['queued'];assert store.read()['completed'][key]['delivery']=='queued';assert rpc(core,'getwalletinfo',[],name)['unlocked_until']==0
  exchange=Exchange(args['port'],args['token'],store);failures=0
  with patch('agent_exchange.local_ipv6',return_value=None),patch('activity_log.event'):
   for _ in range(3):
    try:exchange.once(previews=False)
    except (OSError,ConnectionError):failures+=1
    if store.read()['completed'][key]['delivery']=='acknowledged':break
  saved=store.read();record=saved['completed'][key];assert record['delivery']=='acknowledged',saved['outbox'];assert sign_calls[0]==1
  print(json.dumps({'signed':True,'acknowledged':True,'sign_calls':sign_calls[0],'delivery_retries':failures,'new_signature_fields':record['signature_fields_added']}))
finally:node.close()
