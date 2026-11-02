"""Separate Dashboard interpreter verifies the real Agent receipt and live Core archive."""
import sys,json,copy,base64,urllib.request,contextlib
from pathlib import Path
from types import SimpleNamespace
source=sys.argv[1];sys.path.insert(0,source);data=json.load(sys.stdin)
from wallet_retirement import result,verify_archive,CAPABILITY
from agent_hub import digest
from decimal import Decimal
with __import__('tempfile').TemporaryDirectory() as root:
 config=Path(root)/'config.cfg';node='1'*32;p=data['proposal'];key=digest(p);row={'kind':'wallet_retire','node_id':node,'proposal':p,'delivered':True,'state':'pending'};state={'requests':{key:row}}
 result(state,node,data['result']);assert row['state']=='complete'
 def rpc(n,method,params=None,wallet=None):
  password=Path(data['core']['cookie']).read_text().strip();url='http://127.0.0.1:'+str(data['core']['rpc_port'])+('/wallet/'+urllib.parse.quote(wallet,safe='') if wallet else '/')
  request=urllib.request.Request(url,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or []}).encode(),{'Authorization':'Basic '+base64.b64encode(password.encode()).decode(),'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=30) as response:value=json.load(response,parse_float=Decimal)
  if value.get('error'):raise ValueError('Fixture Core RPC failed')
  return value['result']
 hub=SimpleNamespace(config=config,caps={node:{CAPABILITY}},inventories={node:{'complete':True,'archive_wallets':['Wallaby Extinct']}},registry=SimpleNamespace(snapshot=lambda:{'nodes':[{'id':node,'hostname':'archive-fixture','rpc_ready':True,'blockchain':{'state':'ready'}}]},connections={'fixture':{'node_id':node}}),permissions=SimpleNamespace(current=lambda n:{'identity':data['result']['archive_receipt']['public_key']}),wallet_builder=SimpleNamespace(read=lambda:{'identities':{}}),utc=lambda:'2026-11-03T00:00:00Z',rpc=rpc)
 proof=verify_archive(hub,row);assert proof['manifest_hash']==p['manifest_hash']
 bad=copy.deepcopy(row);bad['result']['archive_receipt']['message']['manifest_hash']='f'*64
 try:verify_archive(hub,bad)
 except ValueError:pass
 else:raise AssertionError('Dashboard accepted altered signed preservation evidence')
 address=p['manifest']['addresses'][0]['address'];label=p['manifest']['addresses'][0]['label'];rpc(node,'setlabel',[address,'fixture deliberately incorrect'],wallet='Wallaby Extinct')
 try:
  try:verify_archive(hub,row)
  except ValueError:pass
  else:raise AssertionError('Dashboard accepted incorrect actual archive readback')
 finally:rpc(node,'setlabel',[address,label],wallet='Wallaby Extinct')
 assert verify_archive(hub,row)['manifest_hash']==p['manifest_hash']
 print(json.dumps({'dashboard_receipt_accepted':True,'live_core_archive_verified':True,'tampered_receipt_rejected':True,'incorrect_core_label_rejected':True}))
