"""Isolated process fixture: production Workspace -> NodeClient -> HTTP exchange.

Only regtest/network identity, protected memory attestation and helper storage are
adapted. No peer.rpc/connect/tick or Exchange is manually supplied by the test.
"""
import os,sys,json,time,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from integration_sync_cluster import reply,commands
if sys.argv[1]=='server':
 from integration_sync_cluster import dashboard
 dashboard(sys.argv[2],sys.argv[3]);raise SystemExit
source,folder,cookie,rpc_port,server_port,name,mac=sys.argv[2:]
folder=Path(folder);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
os.environ['XDG_CONFIG_HOME']=str(folder/'config');os.environ['XDG_RUNTIME_DIR']=str(folder/'runtime');Path(os.environ['XDG_RUNTIME_DIR']).mkdir(mode=0o700,exist_ok=True)
os.environ.pop('WALLABY_REQUIRE_PROTECTION',None);os.environ.pop('WALLABY_PROTECTED_WORKER',None)
sys.path.insert(0,source)
from unittest.mock import patch
from contextlib import ExitStack
from configuration import Config
from peer_storage import FileStore
from direct_peers import Direct
from secure_worker import Workspace
cfg=Config();cfg.values.update(cookie=cookie,rpc_port=int(rpc_port),hostname='fixture.invalid');cfg.save(cfg.values)
trust=folder/'trust';trust.mkdir(mode=0o700,exist_ok=True)
def trust_store():
 # Finish after the first normal exchange, exercising late optional startup.
 time.sleep(float(os.environ.get('WALLABY_STARTUP_PEER_DELAY','2.5')));return FileStore(trust)
with ExitStack() as stack:
 for target,value in [('secure_worker.root',lambda:folder/'protected'),('secure_worker.enforce',lambda:{}),('peer_storage.Client',trust_store),('direct_peers.Direct',lambda peers:Direct(peers,addresses=lambda:['127.0.0.1'],loopback=True)),('node_client.adapter_mac',lambda:mac),('node_client.socket.gethostname',lambda:name),('peer_wallet.local_ipv6',lambda:'2001:db8::76')]:stack.enter_context(patch(target,value))
 w=Workspace();w.configure({});w.start_node(int(server_port));received=[]
 def control(c):
  peers=getattr(w,'peers',None)
  if c['op']=='status':return {'node':w.node_status,'peer':w.peer_action('status',{}),'relay_thread':bool(peers and peers.thread and peers.thread.is_alive()),'rpc_attached':bool(peers and peers.rpc),'received':len(received)}
  if c['op']=='invite':
   route={'host':'example.test','user':'fixture','port':22,'host_public_key':peers.identity['identity_key'],'host_fingerprint':__import__('wallet_preview').fingerprint(peers.identity['identity_key']),'agent_port':56443,'mobile_port':56444}
   with patch('peer_actions.route',return_value=route):return w.peer_action('invite',{})
  if c['op']=='scan':return w.peer_action('import',{'envelope':c['envelope'],'independent':True})
  if c['op']=='listen':peers.listeners.insert(0,lambda channel,record:(received.append(record) or True) if record['payload_type']=='stream_fixture' else False);return True
  if c['op']=='send':
   pair=peers.status()['pairs'][0];channel=peers.channels[pair['id']];return channel.send('stream_fixture','a'*64,{'fixture':'startup-to-direct-only'})
  if c['op']=='stop':
   w.node_stop.set();w.node.join(10)
   if peers:peers.close()
   w.transfer.close();return True
  raise ValueError('Unknown startup fixture control')
 reply({'started':True});commands(control)
