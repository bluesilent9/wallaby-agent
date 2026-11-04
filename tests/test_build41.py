"""Real independent nodes: combined policies, signer isolation, idle archive queue."""
import copy,os,tempfile,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from setup_policy import policy
from wallet_setup import WalletSetup
from build8_policy import descriptors
from managed_accounts import classify,guard
from combined_wallet import wallet_name
from regtest_support import Regtest

PASSWORD='fixture-combined-passphrase'
class CombinedCluster(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.nodes=[];self.agents=[]
  for i in range(3):
   n=Regtest();self.nodes.append(n);self.addCleanup(n.close)
   a=WalletSetup(n.core,Store(Path(self.tmp.name)/str(i)),binary=os.environ['WALLABY_TEST_BITCOIND']);self.agents.append(a)
   self.addCleanup(lambda a=a:[s['core'].close() for s in a.sessions.values() if s.get('core')])
  own=[a.own_identity() for a in self.agents]
  roles=[{'id':'r'+str(i),'name':['Disc A','Disc B','Node Live','Australia','Russia'][i],'agent_key':own[j]['public_key'],'storage':'disc' if i<2 else 'node'} for i,j in enumerate((1,1,0,1,2))]
  self.p={'kind':'wallet_setup','version':1,'session_id':'9'*64,'chain':'regtest','name':'Treasury','threshold':3,'height':100,'expires_at':int(time.time())+3600,'cosigners':roles};self.h=digest(self.p)
  for a in self.agents:
   a.store.receive(self.p)
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):a.approve_proposal(self.h,{o['fingerprint']:o['fingerprint'] for o in own})
  self.contributions=[e for a in self.agents for e in a.sessions[self.h]['contributions']];self.descs=policy(self.p,[e['message'] for e in self.contributions])
  self.final={'kind':'wallet_setup_policy','version':1,'proposal':self.p,'contributions':self.contributions,'receive_descriptor':self.descs[0],'change_descriptor':self.descs[1]}
  for a in self.agents:
   a.store.receive(self.final);a.review(digest(self.final))
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):a.approve_policy(digest(self.final))
 def test_full_policy_named_wallets_sign_and_unrelated_archive_remains_available(self):
  from test_build8 import paired
  records=[next(iter(a.store.read()['approved_wallets'].values())) for a in self.agents];names=[next(iter(r['signing_wallets'].values())) for r in records]
  for n,a,r,name in zip(self.nodes,self.agents,records,names):
   self.assertEqual(r['monitor_wallet'],name);self.assertEqual(rpc(n.core,'listwallets'),[name]);self.assertFalse(name.startswith('Wallaby '));self.assertEqual(len(rpc(n.core,'listdescriptors',[False],name)['descriptors']),2)
   self.assertEqual(rpc(n.core,'getwalletinfo',[],name)['unlocked_until'],0);self.assertEqual(classify(a.store.read(),name,rpc(n.core,'listdescriptors',[False],name))['kind'],'combined')
   req=paired(name,'send');req.update(public_wallet=rpc(n.core,'listdescriptors',[False],name),source_has_private_keys=True)
   with self.assertRaisesRegex(ValueError,'Managed signing'):guard(n.core,req,a.store)
  # The Australia node can still serve public RPC and stage David SMSF while
  # its original encrypted physical signing roles wait untouched in RAM.
  n=self.nodes[1];a=self.agents[1]
  rpc(n.core,'createwallet',{'wallet_name':'David SMSF','passphrase':PASSWORD});raw=rpc(n.core,'listdescriptors',[False],'David SMSF')
  task={'kind':'archive_wallet','version':1,'nonce':'4'*64,'wallet':'David SMSF','public_wallet':raw,'related_policies':[],'require_local_authorisation':True};task['request_id']=digest(task);key=digest(task);a.store.receive(task)
  from secure_worker import Workspace
  from archive_operations import Operations
  w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.store=a.store;w.setup=a;w.ops=SimpleNamespace(core=n.core);w.closing=False;w.configure=lambda env:None;w.recovery_state=lambda:{};w.archives=SimpleNamespace(reading=False,loaded={},staged={},catalogs={});w.transfer=SimpleNamespace(sending=False);w.archive_ops=Operations(n.core,a.store,a,w.archives,lambda:None)
  before=copy.deepcopy(a.sessions[self.h]['contributions']);self.assertEqual(a.sessions[self.h]['phase'],'awaiting_disc')
  with patch('secure_worker.enforce'):
   for method,wallet in [('listwallets',None),('getwalletinfo','David SMSF'),('listdescriptors','David SMSF')]:self.assertIn('result',w.public_rpc('availability',method,[],wallet,30))
   self.assertEqual(w.dispatch('authorise.review',[key],{})['kind'],'archive_wallet');w.dispatch('authorise.approve',[key],{})
  self.assertEqual(w.archive_ops.jobs[key]['phase'],'queued');self.assertEqual(a.sessions[self.h]['contributions'],before);self.assertEqual(len(a.disc_sessions),2)
  # Assemble a spend of dummy regtest funds and obtain one signature from each
  # named Core wallet, without any separate key-only/policy wallet.
  c=self.nodes[0].core;rpc(c,'createwallet',{'wallet_name':'fixture miner'});miner=rpc(c,'getnewaddress',[],'fixture miner');rpc(c,'generatetoaddress',[101,miner])
  address=rpc(c,'deriveaddresses',[self.descs[0],[0,0]])[0];txid=rpc(c,'sendtoaddress',[address,1],'fixture miner');rpc(c,'generatetoaddress',[1,miner]);fund=rpc(c,'getrawtransaction',[txid,True]);vout=next(v for v in fund['vout'] if v['scriptPubKey'].get('address')==address)['n']
  packet=rpc(c,'createpsbt',[[{'txid':txid,'vout':vout,'sequence':0}],{miner:0.99998},100]);packet=rpc(c,'utxoupdatepsbt',[packet,self.descs])
  for n,name in zip(self.nodes,names):
   rpc(n.core,'walletpassphrase',[PASSWORD,120],name)
   try:packet=rpc(n.core,'walletprocesspsbt',[packet,True,'ALL',True],name)['psbt']
   finally:rpc(n.core,'walletlock',[],name)
  self.assertTrue(rpc(c,'finalizepsbt',[packet])['complete'])
  # Refresh the private wallet in-place. No additional monitor wallet is made;
  # old funded policies remain readable and the wallet is locked afterwards.
  from combined_wallet import extend
  from vendor.embit.descriptor.checksum import checksum
  updated=[]
  for desc in self.descs:
   body=desc.split('#')[0].replace('after(100)','after(200)');updated.append(body+'#'+checksum(body))
  before_names=rpc(c,'listwallets')
  with patch('wallet_setup.secret_dialog',return_value=PASSWORD):extend(c,names[0],updated,'now',{})
  self.assertEqual(rpc(c,'listwallets'),before_names)
  self.assertEqual(len(rpc(c,'listdescriptors',[False],names[0])['descriptors']),4)
  self.assertEqual(rpc(c,'getwalletinfo',[],names[0])['unlocked_until'],0)
  # The disc wallet carries the same full public policy but only its one private
  # role. Loading rejects a different role even though its public policy matches.
  import zipfile
  from disc_restore import Archives
  pool=Archives(n.core,a.store,a.binary,lambda:None);pool.environment={}
  job=a.burner.job;recovery=job['recovery'];folder=Path(self.tmp.name)/'disc-read';folder.mkdir()
  zpath=Path(self.tmp.name)/'disc.zip'
  with zipfile.ZipFile(zpath,'w') as z:z.write(next(iter(job['wallets'].values())),'wallet.dat')
  with zipfile.ZipFile(zpath) as z:ident,row=pool.stage_entry(recovery,z,'wallet.dat',folder,'f'*64)
  pool.staged[ident]=row
  with patch('disc_restore.secret_dialog',return_value=PASSWORD):pool.load(ident,True)
  self.addCleanup(lambda:[pool.unload(k) for k in list(pool.loaded)])
  loaded=pool.loaded[ident];self.assertEqual(loaded['recovery']['physical_cosigner_file'],recovery['physical_cosigner_file'])
  self.assertEqual(len(rpc(loaded['node'].core,'listdescriptors',[False],'archive-key')['descriptors']),2)
  pool.unload(ident)
  wrong=Path(self.tmp.name)/'wrong-role.zip';wrong_folder=Path(self.tmp.name)/'wrong-role';wrong_folder.mkdir()
  with zipfile.ZipFile(wrong,'w') as z:z.write(next(iter(a.burner.pending[0][1].values())),'wallet.dat')
  with zipfile.ZipFile(wrong) as z:ident,row=pool.stage_entry(recovery,z,'wallet.dat',wrong_folder,'e'*64)
  pool.staged[ident]=row
  with patch('disc_restore.secret_dialog',return_value=PASSWORD),self.assertRaises(ValueError):pool.load(ident,True)

class Names(unittest.TestCase):
 def test_friendly_names_and_unsafe_or_duplicate_paths_refused(self):
  p={'name':'Treasury','cosigners':[{},{}]};self.assertEqual(wallet_name(p,{'name':'Node Live'}),'Treasury Node Live - Signer')
  with self.assertRaises(ValueError):wallet_name({**p,'name':'../unsafe'},{'name':'Node Live'})

class PublicAvailability(unittest.TestCase):
 def test_parallel_inventory_waits_for_read_lock_and_optical_write_does_not_block(self):
  from test_build38 import IdleDiscReads
  f=IdleDiscReads();f.setUp();self.addCleanup(f.doCleanups);w=f.w
  from unittest.mock import Mock
  w.setup.burner.thread=Mock();w.setup.burner.thread.is_alive.return_value=True
  entered=threading.Event();release=threading.Event();answers=[]
  def slow(*args):entered.set();release.wait(2);return {'result':{'chain':'regtest'}}
  w.ops.core.call.side_effect=slow
  with patch('secure_worker.enforce'):
   first=threading.Thread(target=lambda:answers.append(w.public_rpc('one','getblockchaininfo',[],None,30)));first.start();self.assertTrue(entered.wait(1))
   second=threading.Thread(target=lambda:answers.append(w.public_rpc('two','getblockchaininfo',[],None,30)));second.start();time.sleep(.1);release.set();first.join(3);second.join(3)
  self.assertEqual(len(answers),2);self.assertTrue(all('result' in a for a in answers))
  self.assertTrue(w.busy(),'unfinished disc work still prevents unsafe closure')
