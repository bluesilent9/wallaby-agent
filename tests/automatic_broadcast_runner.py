"""Agent half of the isolated Wallet Server broadcast integration check."""
import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from node_client import Core
from wallet_ops import rpc
from approval_store import Store
from automatic_broadcast import Broadcasts
from agent_exchange import Exchange
config=json.loads(Path(sys.argv[1]).read_text());core=Core(config);original=core.call
def call(ident,method,params,wallet=None,timeout=30):
 result=original(ident,method,params,wallet,timeout=timeout)
 # Wallet Server's wire network is main; all coins and RPC here are isolated regtest.
 if method=='getblockchaininfo' and 'result' in result:result['result']['chain']='main'
 return result
core.call=call
with tempfile.TemporaryDirectory() as directory:
 store=Store(directory);worker=Broadcasts(core,store);exchange=Exchange(config['port'],config['token'],store)
 with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.LOCAL_BROADCASTS',worker),patch('wallet_setup.secret_dialog',side_effect=AssertionError('Broadcast requested a secret')):
  exchange.once(False);worker.thread.join(15);assert not worker.active
  assert config['txid'] in rpc(core,'getrawmempool');assert not store.read()['pending']
  exchange.once(False);saved=store.read();assert not saved['pending'] and not saved['outbox']
  assert saved['completed'][config['key']]['delivery']=='acknowledged'
 print(json.dumps({'pending':0,'acknowledged':True,'prompts':0}))
