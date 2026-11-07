"""Real Core 31: original private roles, all policy generations, SSH gating."""
import copy,hashlib,io,socket,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from regtest_support import Regtest
from vendor.embit import bip32
from vendor.embit.networks import NETWORKS
from vendor.embit.descriptor.checksum import checksum
from signer_restoration import capture,backup_keys,policy_id,offer,permit_backup,verify_received,requested
from local_extinction import prepare,complete
from test_build8 import paired,signed
from wallet_preview import receive,fingerprint,verify_bound
from peer_wallet import wallet_details,frame_read,frame_write,socket_path
from batch_transfer import BatchTransfer
from sync_queue import apply_snapshot,choose
from chain_sync import send

PASSWORD='fixture-role-password'

def policies(kind,private_role):
 if kind.startswith('static-'):return static_policies(kind,private_role)
 private_role={private_role} if isinstance(private_role,int) else set(private_role)
 keys=[bip32.HDKey.from_seed(bytes([n])*32) for n in (1,2,3)]
 result=[]
 for height in ((None,) if kind in ('single','multi') else (100,200)):
  for branch in (0,1):
   pubs=[(k if i in private_role else k.to_public()).to_base58(NETWORKS['regtest']['xprv' if i in private_role else 'xpub'])+'/'+str(branch)+'/*' for i,k in enumerate(keys)]
   body='wpkh('+pubs[0]+')' if kind=='single' else 'wsh(sortedmulti(2,'+','.join(pubs)+'))' if kind=='multi' else 'wsh(and_v(v:after('+str(height)+'),multi(2,'+','.join(pubs)+')))' 
   result.append({'desc':body+'#'+checksum(body),'timestamp':'now','active':False,'internal':bool(branch),'range':[0,5]})
 return result

def static_policies(kind,private_role):
 from vendor.embit import ec
 private_role={private_role} if isinstance(private_role,int) else set(private_role);result=[]
 for height in ((None,) if kind in ('static-single','static-multi') else (100,200)):
  for branch in (0,1):
   keys=[ec.PrivateKey(bytes([10+branch*3+i])*32) for i in range(3)];values=[k.wif(NETWORKS['regtest']) if i in private_role else k.get_public_key().sec().hex() for i,k in enumerate(keys)]
   body='wpkh('+values[0]+')' if kind=='static-single' else 'wsh(sortedmulti(2,'+','.join(values)+'))' if kind=='static-multi' else 'wsh(and_v(v:after('+str(height)+'),multi(2,'+','.join(values)+')))'
   result.append({'desc':body+'#'+checksum(body),'timestamp':'now','active':False,'internal':bool(branch)})
 return result

class OriginalRoles(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.source=Regtest();self.receiver=Regtest();self.addCleanup(self.source.close);self.addCleanup(self.receiver.close);self.core=self.source.core;self.store=Store(self.root/'receiver')
  rpc(self.core,'createwallet',{'wallet_name':'Miner'});miner=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[1,miner])
 def wallet(self,core,name,kind='vault',role=0):
  rpc(core,'createwallet',{'wallet_name':name,'blank':True,'passphrase':PASSWORD});rpc(core,'walletpassphrase',[PASSWORD,60],name)
  try:result=rpc(core,'importdescriptors',{'requests':policies(kind,role)},name);self.assertTrue(all(r['success'] for r in result),result)
  finally:rpc(core,'walletlock',[],name)
  return rpc(core,'listdescriptors',[False],name)
 def fixture(self,kind='vault',extra_role=False):
  raw=self.wallet(self.core,'Original',kind);local=self.wallet(self.receiver.core,'Original',kind)
  self.assertEqual(policy_id(raw),policy_id(local));p=paired('Original');p['public_wallet']=raw;p['restoration']={'version':1,'policy_id':policy_id(raw)}
  self.ret={'public_wallet':local,'manifest':{'addresses':[{'address':'fixture-hash-only','label':'Original'}]},'operation_id':'a'*64};names=['Original']
  if extra_role:self.wallet(self.receiver.core,'Other original role',kind,1);names.append('Other original role')
  ident=prepare(self.store,self.ret,names,core=self.receiver.core);complete(self.store,ident)
  return p,ident
 def test_every_policy_generation_and_original_key_set_is_recorded_without_unlock(self):
  p,ident=self.fixture();rows=self.store.read()['local_retirements'][ident]['wallet_bindings'];self.assertEqual(len(rows),1);self.assertTrue(rows[0]['had_private']);self.assertEqual(len(p['public_wallet']['descriptors']),4);self.assertEqual(rpc(self.receiver.core,'getwalletinfo',[],'Original')['unlocked_until'],0)
  self.assertTrue(rows[0]['private_key_ids']);self.assertTrue(all(len(k)==64 for k in rows[0]['private_key_ids']))
 def test_identical_public_policy_with_a_different_private_signer_is_rejected(self):
  p,ident=self.fixture();wrong=self.wallet(self.core,'Wrong role','vault',1);self.assertEqual(policy_id(wrong),policy_id(p['public_wallet']))
  file=self.root/'wrong.dat';rpc(self.core,'backupwallet',[str(file)],'Wrong role');permit=offer(self.store,p,False)
  with self.assertRaisesRegex(ValueError,'different signer'):permit_backup(p,permit,file)
  self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'complete')
 def test_extra_or_missing_keys_and_wrong_transfer_proof_are_rejected(self):
  p,ident=self.fixture();file=self.root/'good.dat';rpc(self.core,'backupwallet',[str(file)],'Original');permit=offer(self.store,p,False);proof=permit_backup(p,permit,file);self.assertEqual(verify_received(p,permit,file,proof),proof['binding_id'])
  with self.assertRaises(ValueError):verify_received(p,permit,file,{**proof,'permit_hash':'0'*64})
  changed=copy.deepcopy(p);changed['transfer_id']='e'*64
  with self.assertRaises(ValueError):permit_backup(changed,permit,file)
 def test_dashboard_flag_without_local_assignment_cannot_authorise_restore(self):
  raw=self.wallet(self.core,'Original');p=paired('Original');p['public_wallet']=raw;p['restoration']={'version':1,'policy_id':policy_id(raw)}
  with self.assertRaisesRegex(ValueError,'original wallet assignment'):offer(self.store,p,False)
  from managed_accounts import guard
  with self.assertRaisesRegex(ValueError,'SSH restoration permit'):guard(self.core,p)
  guard(self.core,p,public_preview=True)
 def test_signed_preview_cannot_be_relabelled_as_restore(self):
  p,ident=self.fixture();details=wallet_details(self.core,{**p,'direction':'send'},None);plain={k:v for k,v in p.items() if k!='restoration'};payload=signed(Store(self.root/'sender'),plain,details)
  with self.assertRaisesRegex(ValueError,'restoration purpose'):verify_bound(self.store,payload,p)
 def transfer(self,kind,watch=False,extra_role=False):
  p,ident=self.fixture(kind,extra_role);r=self.receiver.core;rpc(r,'unloadwallet',['Original'])
  # Isolated fixture deletion models the completed local deletion, no real wallet.
  import shutil
  shutil.rmtree(Path(r.config['cookie']).parent/'wallets'/'Original')
  if extra_role:
   rpc(r,'unloadwallet',['Other original role']);shutil.rmtree(Path(r.config['cookie']).parent/'wallets'/'Other original role')
  details=wallet_details(self.core,{**p,'direction':'send'},None);sender=Store(self.root/'sender');payload=signed(sender,p,details);payload['preview']['restoration']=p['restoration']
  from wallet_preview import sign
  payload=sign(sender,payload['preview']);apply_snapshot(self.store,1,[p]);key=digest(p);choose(self.store,key,True,watch);receive(self.store,payload)
  t=BatchTransfer(r,self.store);self.addCleanup(t.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(payload['public_key'])})
  file=self.root/'encrypted.dat'
  if watch:
   from watch_snapshot import create
   create(self.core,'Original',file);self.assertFalse(backup_keys(file)['private_key_ids'])
  else:rpc(self.core,'backupwallet',[str(file)],'Original')
  raw=file.read_bytes()
  with socket.socket(socket.AF_UNIX) as sock:
   sock.settimeout(60);sock.connect(str(socket_path(self.store)));stream=sock.makefile('rwb',buffering=0)
   frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':details,'watch_only':watch});self.assertEqual(frame_read(stream)['status'],'review_required');ready=frame_read(stream);self.assertIn('restore_roles_v1',ready['features']);permit=ready['restoration'];proof={'permit_hash':digest(permit),'binding_id':permit['bindings'][0]['binding_id']} if watch else permit_backup(p,permit,file)
   send(self.core,stream,frame_read,frame_write);frame_write(stream,{**({'operation':'watch_snapshot'} if watch else {}),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'restoration':proof});stream.write(raw);stream.flush();reply=frame_read(stream);self.assertEqual(reply['status'],'loaded',reply);frame_write(stream,{'status':'confirmed'})
  t.thread.join(10);self.assertFalse(t.thread.is_alive(),t.error);self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'restored');self.assertIn(key,self.store.read()['completed']);loaded='Wallaby Sync '+p['transfer_id'][:24];self.assertEqual(policy_id(rpc(r,'listdescriptors',[False],loaded)),policy_id(p['public_wallet']));self.assertEqual(rpc(r,'getwalletinfo',[],loaded)['private_keys_enabled'],not watch)
  if extra_role:
   bindings=self.store.read()['local_retirements'][ident]['wallet_bindings'];self.assertEqual(sorted(b['restored'] for b in bindings),[False,True]);from signer_restoration import candidates;self.assertEqual(len(candidates(self.store.read(),p['public_wallet'])),1)
  if not watch:
   self.assertEqual(rpc(r,'getwalletinfo',[],loaded)['unlocked_until'],0)
   import base64
   from core_history import compact_read,compact_write
   from vendor.embit.transaction import TransactionOutput
   from vendor.embit.descriptor import Descriptor
   for row in p['public_wallet']['descriptors']:
    desc=Descriptor.from_string(row['desc'].split('#')[0]).derive(0);destination=rpc(self.core,'getnewaddress',[],'Miner')
    raw_packet=base64.b64decode(rpc(r,'createpsbt',[[{'txid':'1'*64,'vout':0,'sequence':0}],{destination:'0.0009'},201]));reader=io.BytesIO(raw_packet);reader.read(5)
    while True:
     count=compact_read(reader)
     if not count:break
     reader.read(count);reader.read(compact_read(reader))
    def field(key,value):return compact_write(len(key))+key+compact_write(len(value))+value
    input_map=field(b'\x01',TransactionOutput(100000,desc.script_pubkey()).serialize());witness=desc.witness_script()
    if witness is not None:input_map+=field(b'\x05',witness.data)
    packet=base64.b64encode(raw_packet[:reader.tell()]+input_map+b'\x00\x00').decode()
    rpc(r,'walletpassphrase',[PASSWORD,60],loaded)
    try:answer=rpc(r,'walletprocesspsbt',[packet,True,'ALL',True,False],loaded)
    finally:rpc(r,'walletlock',[],loaded)
    signed_packet=rpc(r,'decodepsbt',[answer['psbt']]);self.assertEqual(len(signed_packet['inputs'][0].get('partial_signatures',{})),1,'Exactly the original role must sign every current/historical policy')
    self.assertEqual(rpc(r,'finalizepsbt',[answer['psbt']])['complete'],kind in ('single','static-single'))
 def test_single_signature_private_restoration(self):self.transfer('single')
 def test_multisig_private_restoration(self):self.transfer('multi')
 def test_current_and_old_vault_private_restoration(self):self.transfer('vault')
 def test_one_available_role_restores_while_another_original_role_is_missing(self):self.transfer('vault',extra_role=True)

 def test_old_and_current_vault_watch_restoration_keeps_no_private_keys(self):self.transfer('vault',True)

class StaticRoleKeys(OriginalRoles):
 def test_static_single_signature_restoration(self):self.transfer('static-single')
 def test_static_multisig_restoration(self):self.transfer('static-multi')
 def test_static_old_and_current_vault_restoration(self):self.transfer('static-vault')

class LostSignerExtinction(OriginalRoles):
 def test_empty_multisig_extinction_works_with_no_local_private_signers(self):self.extinguish()
 def test_cancellation_during_role_capture_keeps_original_wallet(self):self.extinguish(cancel=True)
 def extinguish(self,cancel=False):
  from watch_snapshot import create
  from wallet_retirement import inventory,Retirement
  from test_build30 import legacy,proposal
  from wallet_preview import fingerprint
  from wallet_deletion import remove
  raw=self.wallet(self.core,'Spent multisig','multi',(0,1));address=rpc(self.core,'deriveaddresses',[raw['descriptors'][0]['desc'],[0,0]])[0];miner=rpc(self.core,'getnewaddress',[],'Miner')
  rpc(self.core,'generatetoaddress',[1,address]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'walletpassphrase',[PASSWORD,120],'Spent multisig')
  try:rpc(self.core,'sendall',{'recipients':[miner]},'Spent multisig')
  finally:rpc(self.core,'walletlock',[],'Spent multisig')
  rpc(self.core,'generatetoaddress',[1,miner]);lost='Retired Treasury | LOST:06/11/2026 01:02:03 UTC';rpc(self.core,'setlabel',[address,lost],'Spent multisig');public_file=create(self.core,'Spent multisig',self.root/'history-only.dat');r=self.receiver.core
  for height in range(1,rpc(self.core,'getblockcount')+1):rpc(r,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
  name='Only surviving public policy';rpc(r,'restorewallet',{'wallet_name':name,'backup_file':str(public_file)})
  raw=rpc(r,'listdescriptors',[False],name);self.assertFalse(rpc(r,'getwalletinfo',[],name)['private_keys_enabled']);self.assertEqual(rpc(r,'listwallets'),[name])
  facts=inventory(r,self.store,legacy(raw,[{'wallet':name,'public_wallet':raw,'private_keys_enabled':False}],wallet=name),collect_only=True);manifest={'addresses':[{k:row[k] for k in ('address','label')} for row in facts['addresses']],'transactions':facts['transaction_records']}
  rpc(r,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True});p=proposal(raw,manifest,'preserve','Wallaby Extinct');key=digest(p);self.store.receive(p);owner=Retirement(r,self.store);owner.review(key);owner.approve(key)
  outcome=self.store.read()['completed'][key]['result'];self.assertTrue(outcome['history_verified']);self.assertEqual(rpc(r,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2);self.assertEqual(rpc(r,'getaddressinfo',[address],'Wallaby Extinct')['labels'],[lost])
  proof={'node_id':'1'*32,'request_hash':key,'archive_wallet':'Wallaby Extinct','manifest_hash':p['manifest_hash'],'verified_utc':'2026-11-08T00:00:00Z','receipt':outcome['archive_receipt']}
  delete=proposal(raw,manifest,'delete',name,[{'wallet':name,'public_wallet':raw,'private_keys_enabled':False}],proof);delete_key=digest(delete);self.store.receive(delete);owner.review(delete_key)
  if cancel:
   from signer_restoration import capture as original_capture
   def cancel_during_capture(*args,**kwargs):
    result=original_capture(*args,**kwargs)
    with self.store.edit() as state:state.setdefault('retirement_cancel_pending',{})[delete_key]=True
    return result
   with patch('signer_restoration.capture',side_effect=cancel_during_capture),patch('wallet_deletion.delete') as deletion:
    owner.approve(delete_key,fingerprint(outcome['archive_receipt']['public_key']));deletion.assert_not_called()
   self.assertIn(name,rpc(r,'listwallets'));self.assertNotIn(delete_key,self.store.read()['pending']);self.assertEqual(rpc(r,'getwalletinfo',[],name)['txcount'],2);return
  with patch('wallet_deletion.delete',side_effect=lambda record:remove(record,[Path(r.config['cookie']).parent/'wallets'])):owner.approve(delete_key,fingerprint(outcome['archive_receipt']['public_key']))
  self.assertNotIn(name,rpc(r,'listwallets'));self.assertEqual(self.store.read()['completed'][delete_key]['result']['deleted_wallets'],[name]);self.assertEqual(rpc(r,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2)

class SenderBoundary(OriginalRoles):
 def production_send(self,wrong=False,watch=False):
  import base64,subprocess,shutil
  from types import SimpleNamespace
  from peer_wallet import Transfer
  from wallet_preview import sign
  p,ident=self.fixture();receiver_core=self.receiver.core;rpc(receiver_core,'unloadwallet',['Original']);shutil.rmtree(Path(receiver_core.config['cookie']).parent/'wallets'/'Original')
  if wrong:
   self.wallet(self.core,'Different private role','vault',1);p['public_wallet']['wallet_name']='Different private role'
  sender_p={**p,'direction':'send','node_ipv6':p['peer']['ipv6'],'peer':{**p['peer'],'ipv6':p['node_ipv6']}}
  sender_store=Store(self.root/'sender');details=wallet_details(self.core,sender_p,sender_store);payload=signed(sender_store,p,details);payload['preview']['restoration']=p['restoration'];payload=sign(sender_store,payload['preview'])
  apply_snapshot(self.store,1,[p]);key=digest(p);choose(self.store,key,True,watch);receive(self.store,payload)
  apply_snapshot(sender_store,1,[sender_p]);sender_key=digest(sender_p)
  with sender_store.edit() as s:s.setdefault('transfer_previews',{})[sender_key]=payload;s['active_transfer']=sender_key
  t=BatchTransfer(receiver_core,self.store);self.addCleanup(t.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(payload['public_key'])})
  real_run=subprocess.run;real_popen=subprocess.Popen;connections=[]
  class Process:
   def __init__(self,env):
    auth=socket.socket(socket.AF_UNIX);auth.connect(env['WALLABY_ASKPASS_SOCKET']);password=auth.recv(1024);auth.close();self.password_ok=password==b'fixture-login\n'
    self.sock=socket.socket(socket.AF_UNIX);self.sock.connect(str(socket_path(self_store)));self.stdin=self.sock.makefile('wb',buffering=0);self.stdout=self.sock.makefile('rb',buffering=0);self.stderr=io.BytesIO();connections.append(self)
   def poll(self):return None
   def kill(self):
    self.stdin.close();self.stdout.close();self.sock.close()
   def wait(self,timeout=None):return 0
  self_store=self.store
  def launch(args,*a,**kw):return Process(kw['env']) if args[0]=='/usr/bin/ssh' else real_popen(args,*a,**kw)
  def run(args,*a,**kw):
   if args[0]=='/usr/bin/ssh-keyscan':return SimpleNamespace(stdout=p['node_ipv6']+' '+payload['public_key']+'\n',returncode=0)
   return real_run(args,*a,**kw)
  tx=Transfer(self.core,sender_store)
  with patch('peer_wallet.local_ipv6',return_value=sender_p['node_ipv6']),patch('peer_wallet.subprocess.run',side_effect=run),patch('peer_wallet.subprocess.Popen',side_effect=launch):
   if wrong:
    with self.assertRaisesRegex(ValueError,'different signer'):tx.send(sender_key,'fixture','fixture-login',fingerprint(payload['public_key']))
   else:self.assertTrue(tx.send(sender_key,'fixture','fixture-login',fingerprint(payload['public_key']))['ok'])
  t.thread.join(10);self.assertTrue(connections[0].password_ok)
  if wrong:
   self.assertEqual(sender_store.read()['pending'][sender_key]['state'],'pending');self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertFalse(any(n.startswith('Wallaby Sync') for n in rpc(receiver_core,'listwallets')))
  else:
   self.assertIn(sender_key,sender_store.read()['completed']);self.assertIn(key,self.store.read()['completed']);self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'restored')
   loaded='Wallaby Sync '+p['transfer_id'][:24];self.assertEqual(rpc(receiver_core,'getwalletinfo',[],loaded)['private_keys_enabled'],not watch)
 def test_production_sender_releases_only_original_role(self):self.production_send()
 def test_production_sender_refuses_wrong_role_before_file_release(self):self.production_send(True)
 def test_production_sender_watch_snapshot_contains_no_private_keys(self):self.production_send(watch=True)

class AssignmentGuards(OriginalRoles):
 def test_local_assignment_survives_restart_without_private_values(self):
  from denial_storage import FileStore,project
  from signer_restoration import candidates
  p,ident=self.fixture();path=self.root/'preferences';path.mkdir(mode=0o700);disk=FileStore(path);disk.commit(0,project(self.store.read(),1));reopened=Store(self.root/'new-ram',persistence=disk)
  self.assertEqual(len(candidates(reopened.read(),p['public_wallet'])),1);self.assertTrue(offer(reopened,p,False)['bindings'])
  saved=(path/'denials.json').read_text();self.assertNotIn(PASSWORD,saved);self.assertNotIn('tprv',saved);self.assertNotIn('xprv',saved)
  record=disk.read();record['revision']+=1;record['retirements'][ident]['wallet_bindings'][0]['private_key_ids']=['tprv-forbidden']
  with self.assertRaises(ValueError):disk.commit(1,record)
 def test_watch_snapshot_rejects_private_records_before_core_load(self):
  import sqlite3
  from watch_snapshot import create,verify
  self.wallet(self.core,'Original');file=create(self.core,'Original',self.root/'public.dat');self.assertTrue(verify(file))
  with sqlite3.connect(file) as db:db.execute('insert into main values(?,?)',(b'\x04mkey\x00\x00\x00\x00',b'fixture-not-a-private-key'));db.commit()
  with self.assertRaisesRegex(ValueError,'private or unsupported'):verify(file)
 def test_receiver_refuses_forged_role_before_loading_wallet(self):
  import shutil
  from wallet_preview import sign
  p,ident=self.fixture();self.wallet(self.core,'Wrong source','vault',1);p['public_wallet']['wallet_name']='Wrong source';r=self.receiver.core;rpc(r,'unloadwallet',['Original']);shutil.rmtree(Path(r.config['cookie']).parent/'wallets'/'Original')
  sender=Store(self.root/'sender');details=wallet_details(self.core,{**p,'direction':'send'},sender);payload=signed(sender,p,details);payload['preview']['restoration']=p['restoration'];payload=sign(sender,payload['preview']);apply_snapshot(self.store,1,[p]);key=digest(p);choose(self.store,key,True,False);receive(self.store,payload)
  t=BatchTransfer(r,self.store);self.addCleanup(t.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(payload['public_key'])})
  file=self.root/'wrong.dat';rpc(self.core,'backupwallet',[str(file)],'Wrong source');data=file.read_bytes()
  with socket.socket(socket.AF_UNIX) as sock:
   sock.settimeout(60);sock.connect(str(socket_path(self.store)));stream=sock.makefile('rwb',buffering=0)
   frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':details,'watch_only':False});frame_read(stream);permit=frame_read(stream)['restoration'];send(self.core,stream,frame_read,frame_write)
   forged={'permit_hash':digest(permit),'binding_id':permit['bindings'][0]['binding_id']};frame_write(stream,{'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'restoration':forged});stream.write(data);stream.flush();reply=frame_read(stream);self.assertEqual(reply['status'],'error');self.assertIn('different signer',reply['message'])
  t.thread.join(10);self.assertFalse(rpc(r,'listwallets'));self.assertEqual(self.store.read()['pending'][key]['state'],'pending');self.assertEqual(self.store.read()['local_retirements'][ident]['state'],'complete')
