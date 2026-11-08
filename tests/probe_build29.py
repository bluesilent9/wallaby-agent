"""Production rename task/result protocol, using separate Agent/Wallet Server interpreters."""
import sys,json,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from setup_messages import sign
from rename_requests import result,snapshot
from test_build7 import public
CHILD=r'''
import sys,json,copy
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]);data=json.load(sys.stdin)
from wallet_renames import RenameQueue
node='rename-node';hub=SimpleNamespace(config=Path(data['root'])/'config.cfg',permissions=SimpleNamespace(current=lambda n:{'identity':data['identity']}),wallet_builder=SimpleNamespace(read=lambda:{'identities':{},'sessions':{}}),registry=SimpleNamespace(snapshot=lambda:{'nodes':[{'id':node,'hostname':'rename fixture','rpc_ready':True},{'id':'other-node','hostname':'other fixture','rpc_ready':True}]}),caps={node:{'wallet_rename_v1'},'other-node':{'wallet_rename_v1'}},inventories={},read=lambda:{'nodes':{}},inventory_times={})
hub.registry._read=hub.registry.snapshot
import contextlib
statefile=Path(data['root'])/'public-hub.json'
def read():return json.loads(statefile.read_text()) if statefile.exists() else {'nodes':{}}
@contextlib.contextmanager
def edit():
 state=read();yield state;statefile.write_text(json.dumps(state))
hub.read=read;hub.edit=edit
queue=RenameQueue(hub)
if data['action']=='init':
 op={'id':'b'*64,'user_id':'user','resource_id':'descriptor:fixture','old_name':'david_smsf','new_name':'david_smsf_old','raw':data['raw'],'created_utc':'2026-11-02T00:00:00Z','state':'active','locked':False,'targets':{}}
 for ident in (node,'other-node'):
  t={'node_id':ident,'hostname':ident,'wallet':'david_smsf','raw':data['raw'],'storage':'node','private':False,'new_name':'david_smsf_old_watch','status':'Awaiting local approval','state':'pending','request':None,'result':None};t['request']=queue.task(op,t);op['targets'][ident]=t
 queue.write({'version':1,'queue_id':'c'*64,'revision':1,'operations':{op['id']:op}})
elif data['action']=='accept':queue.accept(node,data['receipt'])
elif data['action']=='inventory':__import__('archive_queue').ArchiveQueue(hub).followup(node,data['receipt'])
view=queue.snapshot();cancel_refused=False
if data['action']=='accept':
 try:queue.cancel('user','b'*64)
 except ValueError:cancel_refused=True
print(json.dumps({'proposal':queue.proposal(node),'snapshot':view,'cancel_refused':cancel_refused}))
'''
with tempfile.TemporaryDirectory() as root:
 root=Path(root);store=Store(root/'agent');identity=sign(store,{'init':True})['public_key'];raw=public('david_smsf')
 def server(action,**more):
  p=subprocess.run([sys.executable,'-B','-c',CHILD,sys.argv[1]],input=json.dumps({'root':str(root),'identity':identity,'action':action,'raw':raw,**more}),text=True,capture_output=True,timeout=30)
  if p.returncode:raise RuntimeError(p.stderr)
  return json.loads(p.stdout)
 wire=server('init');snapshot(store,wire['proposal']);p=wire['proposal']['requests'][0];assert p['new_name']=='david_smsf_old_watch';assert wire['snapshot']['operations'][0]['can_cancel']
 result(store,p,'complete',new_wallet='david_smsf_old_watch',identity_verified=True,archive_skipped=False)
 receipt=next(r['payload'] for r in store.read()['outbox'].values() if r['kind']=='wallet_rename_result');reply=server('accept',receipt=receipt);assert reply['cancel_refused'];op=reply['snapshot']['operations'][0];assert not op['can_cancel'] and op['state']=='active';assert [r['state'] for r in op['targets']].count('complete')==1;assert not reply['proposal']['requests']
 archive={'version':1,'event':'archive_verified','archive_id':'d'*64,'image_sha256':'e'*64,'readback_verified':True,'disc_count':1,'replacements':[],'members':[{'member_id':digest(raw),'policy_hash':digest(raw),'name':'david_smsf','role_id':'node-wallet','public_wallet':raw,'related_policies':[]}]};wire=server('inventory',receipt=sign(store,archive));wire=server('inspect');assert any(t['storage']=='disc' for t in wire['snapshot']['operations'][0]['targets'])
 print('Production Wallet Server Build29/Agent Build25: strict queued watch rename, david_smsf_old_watch target, signed per-node completion, other node pending and cancellation locked after first confirmation, verified public archive inventory and archive rename target discovery passed.')
