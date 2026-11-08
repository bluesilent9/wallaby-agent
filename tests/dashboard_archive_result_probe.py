"""Run Wallet Server archive result verification in its own interpreter, unchanged source."""
import sys,json,tempfile,copy,hashlib
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]);data=json.load(sys.stdin)
from archive_queue import ArchiveQueue
with tempfile.TemporaryDirectory() as root:
 node='1'*32;key=data['receipt']['signed_receipt']['public_key'];p=data['request'];receipt=data['receipt']
 hub=SimpleNamespace(config=Path(root)/'config.cfg',permissions=SimpleNamespace(current=lambda n:{'identity':key}),wallet_builder=SimpleNamespace(read=lambda:{'identities':{}}),registry=SimpleNamespace(snapshot=lambda:{'nodes':[{'id':node,'hostname':'archive-fixture'}]}),utc=lambda:'2026-11-03T00:00:00Z')
 q=ArchiveQueue(hub);q.write({'version':1,'queue_id':receipt['queue_id'],'revision':1,'requests':{p['request_id']:{'node_id':node,'hostname':'archive-fixture','user_id':'user','resource_id':None,'created_utc':hub.utc(),'state':'active','status':'Awaiting Agent','request':p}}})
 q.accept(node,receipt);saved=q.read();assert saved['requests'][p['request_id']]['state']==receipt['status'];revision=saved['revision'];q.accept(node,receipt);assert q.read()['revision']==revision
 assert not q.snapshot()['requests'];assert not q.proposal(node)['requests']
 altered=copy.deepcopy(receipt);altered['status']='error'
 try:q.accept(node,altered)
 except ValueError:pass
 else:raise AssertionError('Wallet Server accepted altered signed outcome')
 try:q.accept('2'*32,receipt)
 except ValueError:pass
 else:raise AssertionError('Wallet Server accepted result for another Agent')
 print(json.dumps({'status':receipt['status'],'signed_outcome_accepted':True,'terminal_snapshot_empty':True,'replay_idempotent':True,'tampered_result_rejected':True,'wrong_agent_rejected':True,'dashboard_sha256':{name:hashlib.sha256((Path(sys.argv[1])/name).read_bytes()).hexdigest() for name in ('archive_queue.py','wallet_policy_updates.py','setup_signatures.py')}}))
