"""Historical private policies retain exact branch, role and approved history."""
import copy,re,time,zipfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from combined_wallet import verify_private_role
from vendor.embit import bip32
from vendor.embit.descriptor.checksum import checksum
from wallet_ops import rpc
from approval_store import digest

class RecoveryValidation(unittest.TestCase):
 def setUp(self):
  self.key=bip32.HDKey.from_seed(b'57 role fixture'*3);self.other=bip32.HDKey.from_seed(b'57 unrelated key'*3)
  self.contribution={field:str(self.key.to_public())+'/'+str(branch)+'/*' for branch,field in enumerate(('receive_key','change_key'))}
  self.policies=[self.pair(height) for height in (100,200,300,400)]
  self.rows=[{'desc':self.private(desc),'active':generation==3,**({'internal':bool(branch)} if generation==3 else {})} for generation,pair in enumerate(self.policies) for branch,desc in enumerate(pair)]
 def pair(self,height):
  result=[]
  for branch in range(2):
   body='wsh(and_v(v:pk('+str(self.key.to_public())+'/'+str(branch)+'/*),after('+str(height)+')))';result.append(body+'#'+checksum(body))
  return result
 def private(self,desc):
  body=desc.split('#')[0].replace(str(self.key.to_public()),str(self.key));return body+'#'+checksum(body)
 def verify(self,rows=None,policies=None):
  return verify_private_role(SimpleNamespace(private_descriptors=lambda name:copy.deepcopy(self.rows if rows is None else rows)),'archive',self.contribution,self.policies if policies is None else policies)
 def test_inactive_rows_without_branch_flags_match_actual_private_derivation(self):self.verify()
 def test_wrong_role_rejected_even_with_same_public_policy(self):
  rows=copy.deepcopy(self.rows);body=rows[0]['desc'].split('#')[0].replace(str(self.key),str(self.other));rows[0]['desc']=body+'#'+checksum(body)
  with self.assertRaises(ValueError):self.verify(rows)
 def test_missing_or_extra_private_role_rejected(self):
  for replacement in (self.policies[0][0],'wsh(multi(1,'+str(self.key)+'/0/*,'+str(self.other)+'/0/*))'):
   rows=copy.deepcopy(self.rows);body=replacement.split('#')[0];rows[0]['desc']=body+'#'+checksum(body)
   with self.assertRaises(ValueError):self.verify(rows)
 def test_unapproved_policy_generation_rejected(self):
  with self.assertRaisesRegex(ValueError,'approved recovery history'):self.verify(policies=self.policies[:-1])
 def test_substituted_policy_with_same_private_role_rejected(self):
  rows=copy.deepcopy(self.rows);body=rows[0]['desc'].split('#')[0].replace('after(100)','after(99)');rows[0]['desc']=body+'#'+checksum(body)
  with self.assertRaisesRegex(ValueError,'approved recovery history'):self.verify(rows)
 def test_explicit_wrong_branch_flag_rejected(self):
  rows=copy.deepcopy(self.rows);rows[1]['internal']=False
  with self.assertRaisesRegex(ValueError,'contradicts'):self.verify(rows)
 def test_receive_only_archive_rejected(self):
  with self.assertRaisesRegex(ValueError,'complete receive/change'):self.verify(self.rows[::2])

 def test_extension_uses_inactive_change_key_without_a_branch_flag(self):
  from combined_wallet import extend
  rows=self.rows[:2];calls=[]
  def call(core,method,params=None,wallet=None,**kwargs):
   if method=='importdescriptors':calls.extend(params[0]);return [{'success':True},{'success':True}]
  with patch('wallet_setup.secret_dialog',return_value='dummy'),patch('combined_wallet.rpc',side_effect=call):extend(object(),'fixture',self.policies[1],'now',{},lambda:copy.deepcopy(rows))
  self.assertEqual([r['internal'] for r in calls],[False,True])
  for branch,row in enumerate(calls):self.assertIn(str(self.key)+'/'+str(branch)+'/*',row['desc'])

class RealRepeatedRecovery(unittest.TestCase):
 def setUp(self):
  from test_build41 import CombinedCluster
  CombinedCluster.setUp(self)
 def test_backup_reload_and_sign_both_branches_after_each_refresh(self):
  from test_build41 import PASSWORD
  from disc_restore import Archives
  from policy_refresh import Refresh,validate_extensions
  from archive_operations import Operations
  a=self.agents[1];job=a.burner.job;recovery=copy.deepcopy(job['recovery']);root=Path(self.tmp.name)
  pool=Archives(a.core,a.store,a.binary,lambda:None);pool.environment={}
  self.addCleanup(lambda:[pool.unload(k) for k in list(pool.loaded)])
  serial=[0]
  def load(wallet,recovery):
   serial[0]+=1;folder=root/('load-'+str(serial[0]));folder.mkdir();package=root/('archive-'+str(serial[0])+'.zip')
   with zipfile.ZipFile(package,'w') as z:z.write(wallet,'wallet.dat')
   with zipfile.ZipFile(package) as z:ident,row=pool.stage_entry(recovery,z,'wallet.dat',folder,'f'*64)
   pool.staged[ident]=row
   with patch('disc_restore.secret_dialog',return_value=PASSWORD):pool.load(ident,True)
   return ident,pool.loaded[ident]
  ident,record=load(next(iter(job['wallets'].values())),recovery);alias=record['keys'][0];role=copy.deepcopy(record['role']);original=copy.deepcopy(recovery['proposal']);old=self.descs
  miner_core=self.nodes[0].core;rpc(miner_core,'createwallet',{'wallet_name':'fixture miner'});miner=rpc(miner_core,'getnewaddress',[],'fixture miner');rpc(miner_core,'generatetoaddress',[101,miner],timeout=120)
  with patch('node_client.LOCAL_ROUTER',pool):
   for height in (200,300,400):
    new=[]
    for desc in old:
     body=re.sub(r'after\([0-9]+\)','after('+str(height)+')',desc.split('#')[0]);new.append(body+'#'+checksum(body))
    p={'kind':'wallet_policy_refresh','version':1,'request_id':digest({'cycle':height}),'chain':'regtest','wallet':alias,'previous_descriptors':old,'receive_descriptor':new[0],'change_descriptor':new[1],'timestamp':int(time.time()),'expires_at':int(time.time())+3600};key=digest(p);a.store.receive(p);ops=Refresh(a.core,a.store,pool);ops.review(key)
    with patch('wallet_setup.secret_dialog',return_value=PASSWORD):ops.approve(key)
    updated=copy.deepcopy(record['recovery']);self.assertEqual(validate_extensions(updated),new)
    # Back up the actual refreshed private wallet, including inactive history.
    backup=root/('live-'+str(height)+'.dat');rpc(record['node'].core,'backupwallet',[str(backup)],'archive-key')
    inactive=[r for r in rpc(record['node'].core,'listdescriptors',[False],'archive-key')['descriptors'] if not r.get('active')]
    self.assertTrue(inactive);self.assertTrue(any('internal' not in r for r in inactive),'Core reproduces absent historical branch flags')
    pool.unload(ident);ident,record=load(backup,updated)
    self.assertEqual(record['keys'],[alias]);self.assertEqual(record['role'],role);self.assertEqual(record['review']['name'],'Treasury');self.assertEqual(record['review']['height'],height);self.assertEqual(record['recovery']['proposal'],original)
    self.assertEqual(len(rpc(record['node'].core,'listdescriptors',[False],'archive-key')['descriptors']),2*((height-100)//100+1))
    # Both branches still sign with the restored role; no extra key is present.
    for desc in new:
     address=rpc(miner_core,'deriveaddresses',[desc,[0,0]])[0];fund=rpc(miner_core,'sendtoaddress',[address,'0.001'],'fixture miner');rpc(miner_core,'generatetoaddress',[1,miner]);tx=rpc(miner_core,'getrawtransaction',[fund,True]);vout=next(v['n'] for v in tx['vout'] if v['scriptPubKey'].get('address')==address)
     packet=rpc(miner_core,'createpsbt',[[{'txid':fund,'vout':vout,'sequence':0}],{miner:0.00099},height]);packet=rpc(miner_core,'utxoupdatepsbt',[packet,new]);core=record['node'].core;rpc(core,'walletpassphrase',[PASSWORD,120],'archive-key')
     try:signed=rpc(core,'walletprocesspsbt',[packet,True,'ALL',True,False],'archive-key')['psbt']
     finally:rpc(core,'walletlock',[],'archive-key')
     self.assertEqual(len(rpc(miner_core,'decodepsbt',[signed])['inputs'][0].get('partial_signatures',{})),1)
    old=new
   operations=Operations(a.core,a.store,a,pool,lambda:None);operations.queue_loaded([ident],True);queued=next(t for t in a.burner.pending if t[0] in operations.jobs);file=root/'replacement.dat';__import__('shutil').copyfile(next(iter(queued[1].values())),file);updated=copy.deepcopy(queued[2]);pool.unload(ident);ident,record=load(file,updated)
   self.assertEqual(record['review']['height'],400);self.assertEqual(record['keys'],[alias]);self.assertEqual(record['role'],role)
