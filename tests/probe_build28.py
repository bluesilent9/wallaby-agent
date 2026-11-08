"""Separate production interpreters: grouped historical queue and signed preview."""
import sys,json,tempfile,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from wallet_preview import sign,receive
from extinct_sync import children
from vendor.embit import ec
from vendor.embit.script import p2wpkh
from vendor.embit.networks import NETWORKS
from vendor.embit.descriptor.checksum import checksum
CHILD=r'''
import sys,json
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]);data=json.load(sys.stdin)
from extinct_sync import containers
from agent_hub import AgentHub,digest
from wallet_transfers import Transfers
from wallet_preview import verify
wallets=data['wallets'];group=containers(wallets)[0];hub=AgentHub.__new__(AgentHub);hub.registry=SimpleNamespace(connections={'s':{'node_id':'sender','hostname':'sender-machine'},'r':{'node_id':'receiver','hostname':'receiver-machine'}})
state={'nodes':{'sender':{'ipv6':'2001:db8::1'},'receiver':{'ipv6':'2001:db8::2'}},'requests':{}}
for node,peer,direction in [('sender','receiver','send'),('receiver','sender','receive')]:
 row={'kind':'wallet_transfer','node_id':node,'peer_id':peer,'direction':direction,'transfer_id':'a'*64,'public_wallet':group['raw'],'source_has_private_keys':False,'earliest_timestamp':0,'requires_blockchain_redownload':False,'challenge':'b'*64,'state':'pending','base_sent':1,'queue_visible':True};row['proposal']=hub.transfer_proposal(state,row);state['requests'][direction]=row
if data.get('payload'):
 payload=data['payload'];proof=verify(Path(data['root'])/'config.cfg',{k:payload[k] for k in ('preview','public_key','signature')});Transfers(hub).accept_preview(state,'sender',payload,proof)
 assert state['requests']['send']['signed_preview']['preview']['address_labels']==payload['preview']['address_labels']
print(json.dumps({'send':state['requests']['send']['proposal'],'receive':state['requests']['receive']['proposal'],'group':group,'verified':bool(data.get('payload'))}))
'''
with tempfile.TemporaryDirectory() as root:
 root=Path(root);wallets=[];labels=[]
 for i,name in enumerate(('Old Treasury','Old SMSF')):
  address=p2wpkh(ec.PrivateKey(bytes([i+1])*32).get_public_key()).address(NETWORKS['main']);body='addr('+address+')';wallets.append({'id':digest(name),'name':name,'raw':{'wallet_name':name,'descriptors':[{'desc':body+'#'+checksum(body),'timestamp':0,'active':False,'internal':False}]},'private_keys_enabled':False,'extinct':True,'address_labels':{address:name}});labels.append({'address':address,'label':name,'is_change':False})
 def dashboard(**more):
  p=subprocess.run([sys.executable,'-B','-c',CHILD,sys.argv[1]],input=json.dumps({'wallets':wallets,'root':str(root),**more}),text=True,capture_output=True,timeout=30)
  if p.returncode:raise RuntimeError(p.stderr)
  return json.loads(p.stdout)
 wire=dashboard();store=Store(root/'sender');store.receive({'kind':'wallet_sync_queue','revision':1,'requests':[wire['send']]});preview={'version':2,'transfer_id':'a'*64,'challenge':'b'*64,'sender_ipv6':'2001:db8::1','receiver_ipv6':'2001:db8::2','public_wallet':wire['group']['raw'],'chain':'main','funded_outputs':[],'vaults':[],'address_labels':labels,'node_tip':{'height':1,'hash':'c'*64},'generated_at':int(time.time())};payload=sign(store,preview);reply=dashboard(payload={'request_hash':digest(wire['send']),**payload});assert reply['verified'];receiver=Store(root/'receiver');receiver.receive({'kind':'wallet_sync_queue','revision':1,'requests':[wire['receive']]});receive(receiver,payload);assert len(children(preview))==2
 print('Production Wallet Server Build28 → Agent Build24: one two-child Extinct request, strict full queue, sender-signed public labels, Wallet Server signature/binding check and receiver acceptance passed.')
