"""Independent Wallet Server interpreter validates real Agent cancellation receipts."""
import copy,hashlib,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]);data=json.load(sys.stdin)
from archive_queue import ArchiveQueue
with tempfile.TemporaryDirectory() as root:
 p=data['task'];receipt=data['result'];original=p['archive_request'];node='1'*32;public=receipt['signed_receipt']['public_key']
 hub=SimpleNamespace(config=Path(root)/'config.cfg',caps={node:{'wallet_archive_queue_v1','wallet_archive_cancel_v1'}},permissions=SimpleNamespace(current=lambda n:{'identity':public}),wallet_builder=SimpleNamespace(read=lambda:{'identities':{}}),registry=SimpleNamespace(snapshot=lambda:{'nodes':[{'id':node,'hostname':'cancel-fixture','connected':True}]}),utc=lambda:'2026-11-03T00:00:00Z')
 original_result=p['completed_receipt']['message'] if p['completed_receipt'] else {}
 queue=ArchiveQueue(hub);row={'node_id':node,'hostname':'cancel-fixture','user_id':'fixture','created_utc':hub.utc(),'state':'active','status':'Awaiting local cleanup'}
 source={**row,'state':'complete' if original_result.get('status')=='complete' else 'withdrawn','request':original,'cancel_requested':True,'cancellation_id':p['request_id'],'result':original_result}
 queue.write({'version':1,'queue_id':receipt['queue_id'],'revision':1,'requests':{original['request_id']:source,p['request_id']:{**row,'request':p}}})
 queue.accept(node,receipt);assert queue.read()['requests'][p['request_id']]['state']=='complete';revision=queue.read()['revision'];queue.accept(node,receipt);assert queue.read()['revision']==revision;assert not queue.proposal(node)['requests']
 altered=copy.deepcopy(receipt);altered['disc_created']=not altered['disc_created']
 try:queue.accept(node,altered)
 except ValueError:pass
 else:raise AssertionError('Changed signed outcome accepted')
 try:queue.accept('2'*32,receipt)
 except ValueError:pass
 else:raise AssertionError('Other Agent accepted')
 print(json.dumps({'disc_created':receipt['disc_created'],'dashboard_accepted':True,'idempotent_retry':True,'tampered_outcome_rejected':True,'wrong_agent_rejected':True,'archive_queue_sha256':hashlib.sha256((Path(sys.argv[1])/'archive_queue.py').read_bytes()).hexdigest()}))
