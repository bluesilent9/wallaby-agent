"""Actual Dashboard/Agent implementations in separate interpreters; public JSON only."""
import sys,tempfile,json,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'));dashboard=Path(sys.argv[1]).resolve()
from approval_store import Store,digest
from archive_requests import snapshot,delete,result
from setup_messages import sign
from vendor.embit import bip32
from vendor.embit.descriptor.checksum import checksum
from archive_operations import Operations
from agent_exchange import Exchange
from types import SimpleNamespace
CHILD=r'''
import sys,json
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]);p=json.load(sys.stdin)
from archive_queue import ArchiveQueue
from agent_hub import CAPS
node='node-fixture';hub=SimpleNamespace(config=Path(p['root'])/'config.cfg',permissions=SimpleNamespace(current=lambda n:{'identity':p['identity']}),wallet_builder=SimpleNamespace(read=lambda:{'identities':{}}),registry=SimpleNamespace(snapshot=lambda:{'nodes':[{'id':node,'hostname':'test-node'}]}),utc=lambda:'2026-11-02T00:00:00Z')
q=ArchiveQueue(hub)
if p['action']=='init':
 task=p['task'];q.write({'version':1,'queue_id':'d'*64,'revision':1,'requests':{task['request_id']:{'node_id':node,'hostname':'test-node','user_id':None,'resource_id':None,'created_utc':hub.utc(),'state':'active','status':'test','request':task}}})
elif p['action']=='accept':q.accept(node,p['receipt'])
print(json.dumps({'proposal':q.proposal(node),'caps':sorted(CAPS),'snapshot':q.snapshot()}))
'''
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);store=Store(root/'agent');identity=sign(store,{'init':True})['public_key']
 def server(action,**payload):
  r=subprocess.run([sys.executable,'-B','-c',CHILD,str(dashboard)],input=json.dumps({'root':str(root),'identity':identity,'action':action,**payload}),text=True,capture_output=True,timeout=30)
  if r.returncode:raise RuntimeError(r.stderr)
  return json.loads(r.stdout)
 key=bip32.HDKey.from_seed(b'protocol test seed only'*2).to_public().to_base58();body='wpkh('+key+'/0/*)';raw={'wallet_name':'Treasury','descriptors':[{'desc':body+'#'+checksum(body),'timestamp':0,'internal':False,'active':True,'range':[0,999]}]}
 p={'kind':'archive_wallet','version':1,'nonce':'c'*64,'wallet':'Treasury','public_wallet':raw,'related_policies':[],'require_local_authorisation':True};p['request_id']=digest(p)
 wire=server('init',task=p);snapshot(store,wire['proposal']);assert digest(p) in store.read()['pending'];delete(store,digest(p));snapshot(store,wire['proposal']);assert digest(p) in store.read()['pending']
 queued=result(store,p,'queued');reply=server('accept',receipt=queued);assert reply['snapshot']['requests'][0]['state']=='active'
 old='a'*64;image='b'*64;proof={'archive_id':old,'image_sha256':image,'members':['e'*64],'old_policies_retained':True,'readback_verified':True};complete=result(store,p,'complete',readback_verified=True,image_sha256=image,archive_members=['e'*64],replacements=[proof]);reply=server('accept',receipt=complete)
 snapshot(store,reply['proposal']);tasks=[r for r in reply['proposal']['requests'] if r['kind']=='destroy_disc'];assert len(tasks)==1
 operations=Operations.__new__(Operations);operations.store=store;operations.setup=SimpleNamespace(own_identity=lambda:{'public_key':identity});operations.verified_replacements={};operations.enforce=lambda:None
 operations.destruction_proof(tasks[0]);operations.destroyed(digest(tasks[0]),True)
 outcome=next(v['payload'] for v in store.read()['outbox'].values() if v['kind']=='archive_queue_result' and v['payload'].get('destruction_confirmed_locally'));reply=server('accept',receipt=outcome);assert not reply['proposal']['requests']
 body=[]
 with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',side_effect=lambda port,path,data,*a,**k:body.append(data) or {'version':1,'accepted':[],'proposals':[]}):Exchange(1,'fixture',store).once()
 assert set(body[0]['capabilities'])<=set(reply['caps'])
 print('Production Dashboard/Agent: full archive queue, local delete/reoffer, signed verified completion, generated destruction task, own-key proof after RAM restart, local confirmation, withdrawal and advertised capabilities passed.')
