"""Local rename approval, exact signer duplication and immutable archive identities."""
import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store,digest
from rename_requests import Renames,snapshot,validate_task
from wallet_rename import move,name,watch_name
from wallet_ops import rpc
from regtest_support import Regtest
from archive_operations import Operations
from disc_restore import Archives
from wallet_setup import WalletSetup
from disc_backup import pack
from archive_format import identity,bundle
BINARY=os.environ.get('WALLABY_TEST_BITCOIND')

def task(raw,new='Retired Treasury',storage='node',wallet=None,archive_id=None):
 p={'kind':'wallet_rename','version':1,'nonce':'a'*64,'rename_id':'b'*64,'chain':'regtest','wallet':wallet or raw['wallet_name'],'new_name':new,'public_wallet':raw,'storage':storage}
 if storage=='disc':p['archive_id']=archive_id
 p['request_id']=digest(p);return p

def queue(rows,revision=1):return {'kind':'wallet_rename_queue','version':1,'queue_id':'c'*64,'revision':revision,'requests':rows}

class Queue(unittest.TestCase):
 def test_bound_queue_withdrawal_and_attempted_outcome(self):
  from test_build7 import public
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);p=task(public());snapshot(store,queue([p]));k=digest(p);snapshot(store,queue([] ,2));self.assertFalse(store.read()['pending']);snapshot(store,queue([p],3))
   with store.edit() as s:s['pending'][k]['state']='attempted'
   snapshot(store,queue([],4));self.assertTrue(store.read()['pending'][k]['withdrawn'])
   with self.assertRaises(ValueError):snapshot(store,queue([],3))
   bad=copy.deepcopy(p);bad['new_name']='Changed without new binding'
   with self.assertRaises(ValueError):validate_task(bad)
 def test_names_paths_and_watch_suffix(self):
  for value in ('../wallet','/tmp/wallet','a/b','a\\b','..','Wallaby Extinct','Extinct','space ','line\nname','x'*101):
   with self.subTest(value=value),self.assertRaises(ValueError):name(value)
  self.assertEqual(watch_name('Treasury'),'Treasury_watch');self.assertEqual(watch_name('Treasury_watch'),'Treasury_watch');self.assertEqual(watch_name('david_smsf_old'),'david_smsf_old_watch');self.assertEqual(watch_name('david_smsf_old_watch'),'david_smsf_old_watch')

class Filesystem(unittest.TestCase):
 def source(self,root,label='old'):
  directory=root/label;directory.mkdir();db=directory/'wallet.dat';db.write_bytes(b'fixture wallet content');s=directory.stat();b=db.stat();return {'path':str(directory),'directory':[s.st_dev,s.st_ino],'database':[b.st_dev,b.st_ino]}
 def test_atomic_directory_move_preserves_inode_bytes_and_never_overwrites(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=self.source(root);before=(root/'old/wallet.dat').read_bytes();reply=move({'source':source,'new_name':'New name'},[root]);self.assertTrue(reply['renamed']);self.assertFalse((root/'old').exists());self.assertEqual((root/'New name/wallet.dat').stat().st_ino,source['database'][1]);self.assertEqual((root/'New name/wallet.dat').read_bytes(),before)
   other=self.source(root,'another');(root/'collision').mkdir();(root/'collision/keep').write_text('unchanged')
   with self.assertRaises(OSError):move({'source':other,'new_name':'collision'},[root])
   self.assertTrue((root/'another/wallet.dat').exists());self.assertEqual((root/'collision/keep').read_text(),'unchanged')
 def test_replaced_directory_extra_file_hardlink_and_outside_path_refused(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);s=self.source(root);(root/'old/unexpected').write_text('keep')
   with self.assertRaises(ValueError):move({'source':s,'new_name':'new'},[root])
   (root/'old/unexpected').unlink();os.link(root/'old/wallet.dat',root/'second-link')
   with self.assertRaises(ValueError):move({'source':s,'new_name':'new'},[root])
   (root/'second-link').unlink();bad={**s,'directory':[0,0]}
   with self.assertRaises(ValueError):move({'source':bad,'new_name':'new'},[root])
   with self.assertRaises(ValueError):move({'source':s,'new_name':'new'},[])

class RealRenames(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.setup=WalletSetup(self.core,self.store,binary=BINARY);self.archives=Archives(self.core,self.store,BINARY,lambda:None);self.ops=Operations(self.core,self.store,self.setup,self.archives,lambda:None);self.renames=Renames(self.core,self.store,self.archives,self.ops,lambda:None);self.base=Path(self.core.config['cookie']).parent/'wallets'
  self.addCleanup(self.cleanup)
 def cleanup(self):
  import node_client
  node_client.LOCAL_ROUTER=None
  for ident in list(self.archives.loaded):self.archives.unload(ident)
 def approve_node(self,p):
  snapshot(self.store,queue([p]));k=digest(p)
  with patch('wallet_deletion.bases',return_value=[self.base]):review=self.renames.review(k)
  with patch('wallet_deletion.bases',return_value=[self.base]),patch('wallet_rename.rename',side_effect=lambda source,new,**kw:move({'source':source,'new_name':new},[self.base],**kw)):result=self.renames.approve(k)
  return k,review,result
 def test_encrypted_private_wallet_is_renamed_without_copy_unlock_or_policy_change(self):
  rpc(self.core,'createwallet',{'wallet_name':'Treasury','passphrase':'fixture wallet password'});address=rpc(self.core,'getnewaddress',['Trusted owner'],'Treasury');rpc(self.core,'createwallet',{'wallet_name':'Miner'});mining=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[101,mining]);rpc(self.core,'sendtoaddress',[address,'0.1'],'Miner');rpc(self.core,'generatetoaddress',[1,mining]);raw=rpc(self.core,'listdescriptors',[False],'Treasury');db=self.base/'Treasury/wallet.dat';inode=db.stat().st_ino
  k,review,result=self.approve_node(task(raw));self.assertNotIn('Treasury',rpc(self.core,'listwallets'));self.assertIn('Retired Treasury',rpc(self.core,'listwallets'));self.assertEqual((self.base/'Retired Treasury/wallet.dat').stat().st_ino,inode);self.assertEqual(rpc(self.core,'getaddressinfo',[address],'Retired Treasury')['labels'],['Trusted owner']);self.assertEqual(rpc(self.core,'getwalletinfo',[],'Retired Treasury')['unlocked_until'],0);self.assertIn(k,self.store.read()['completed'])
  import subprocess,time
  args=self.node.process.args;rpc(self.core,'stop');self.node.process.wait(timeout=20);self.node.process=subprocess.Popen(args,stdout=self.node.log,stderr=subprocess.STDOUT)
  for _ in range(100):
   try:self.core.ready();break
   except Exception:time.sleep(.1)
  self.assertIn('Retired Treasury',rpc(self.core,'listwallets'));self.assertNotIn('Treasury',rpc(self.core,'listwallets'))
  proof=next(r['payload']['message'] for r in self.store.read()['outbox'].values() if r['kind']=='wallet_rename_result');self.assertEqual(proof['status'],'complete');self.assertTrue(proof['identity_verified'])
 def test_watch_wallet_name_and_collision_are_verified_before_unload(self):
  rpc(self.core,'createwallet',{'wallet_name':'Source keys'});public=rpc(self.core,'listdescriptors',[False],'Source keys');rpc(self.core,'createwallet',{'wallet_name':'Original monitor','disable_private_keys':True,'blank':True});rpc(self.core,'importdescriptors',[[{k:v for k,v in row.items() if k!='next'}|{'timestamp':'now'} for row in public['descriptors']]],'Original monitor');raw=rpc(self.core,'listdescriptors',[False],'Original monitor');k,review,result=self.approve_node(task(raw,'Older monitor'));self.assertEqual(review['rename']['new_wallet'],'Older monitor_watch');self.assertFalse(rpc(self.core,'getwalletinfo',[],'Older monitor_watch')['private_keys_enabled'])
  p=task(rpc(self.core,'listdescriptors',[False],'Older monitor_watch'),'Already there');rpc(self.core,'createwallet',{'wallet_name':'Already there_watch','disable_private_keys':True});snapshot(self.store,queue([p],2))
  with patch('wallet_deletion.bases',return_value=[self.base]),self.assertRaisesRegex(ValueError,'already exists'):self.renames.review(digest(p))
  self.assertIn('Older monitor_watch',rpc(self.core,'listwallets'))
 def test_loaded_wallet_lock_prevents_helper_from_moving_it(self):
  rpc(self.core,'createwallet',{'wallet_name':'Still loaded'});from wallet_deletion import target
  source=target(self.core,'Still loaded')
  # POSIX locks must be tested from another process, as used in production.
  import subprocess,sys
  code='from wallet_rename import move;import json,sys;move(json.loads(sys.argv[1]),[__import__("pathlib").Path(sys.argv[2])])';r=subprocess.run([sys.executable,'-B','-c',code,json.dumps({'source':source,'new_name':'Moved'}),str(self.base)],capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertIn('Still loaded',rpc(self.core,'listwallets'));self.assertTrue((self.base/'Still loaded').exists())
 def archive(self,multi=False):
  folder=self.root/'fixture';folder.mkdir();items=[]
  for i,label in enumerate(('Archive signer','SMSF partner') if multi else ('Archive signer',)):
   rpc(self.core,'createwallet',{'wallet_name':label,'passphrase':'fixture wallet password'});raw=rpc(self.core,'listdescriptors',[False],label);backup=folder/('wallet'+str(i)+'.dat');rpc(self.core,'backupwallet',[str(backup)],label);recovery={'version':1,'kind':'node_wallet','chain':'regtest','name':label,'policy_hash':digest(raw),'public_wallet':raw,'labels':[]};items.append(('fixture'+str(i),{'fixture':str(backup)},recovery))
  wallets,recovery=bundle(items);disc=pack(folder/'disc',wallets,recovery,'fixture archive password');stage=self.root/'read';stage.mkdir();reviews=self.archives.inspect_package(disc/'recovery.wallaby','fixture archive password',stage)['entries']
  for review in reviews:self.archives.load(review['id'],True)
  import node_client
  node_client.LOCAL_ROUTER=self.archives;r=self.archives.loaded[reviews[0]['id']];alias=r['keys'][0];p=task(rpc(self.core,'listdescriptors',[False],alias),'Renamed Treasury',storage='disc',wallet=alias,archive_id=r['archive_id']);snapshot(self.store,queue([p]));return p,r,reviews[0]['id']
 def test_disc_skip_requires_duplicate_of_exact_account_not_another_signer(self):
  p,r,ident=self.archive();k=digest(p);self.assertTrue(self.renames.review(k)['rename']['archive_skip_allowed']);rpc(self.core,'unloadwallet',['Archive signer']);rpc(self.core,'createwallet',{'wallet_name':'Different signer','passphrase':'different fixture password'});self.assertFalse(self.renames.review(k)['rename']['archive_skip_allowed'])
  with self.assertRaisesRegex(ValueError,'exact independently verified duplicate'):self.renames.approve(k,True)
  self.assertEqual(r['review']['name'],'Archive signer');self.assertEqual(self.store.read()['pending'][k]['state'],'pending')
 def test_disc_rename_skip_preserves_original_account_and_stable_member(self):
  p,r,ident=self.archive();k=digest(p);before=identity(r['recovery']);raw=copy.deepcopy(r['recovery']['public_wallet']);self.renames.review(k);self.renames.approve(k,True);self.assertEqual(identity(r['recovery']),before);self.assertEqual(r['recovery']['public_wallet'],raw);self.assertEqual(r['review']['name'],'Renamed Treasury');self.assertEqual(self.archives.state()['loaded'][0]['name'],'Renamed Treasury');self.assertIn('Renamed Treasury',r['keys'][0]);self.assertFalse(self.ops.jobs);self.assertIn(k,self.store.read()['completed'])
 def test_disc_rename_is_not_complete_until_verified_burn_callback_and_restores_name(self):
  p,r,ident=self.archive();k=digest(p);before=identity(r['recovery']);self.renames.review(k);self.renames.approve(k,False);self.assertEqual(self.store.read()['pending'][k]['state'],'attempted');self.assertNotIn(k,self.store.read()['completed']);self.assertEqual(next(x['payload']['message'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_rename_result')['status'],'archive_required')
  jobkey=next(iter(self.renames.archive_jobs));job=self.setup.burner.job;job['disc_count']=1;job['archive_id']='d'*64;self.ops.complete(jobkey,'e'*64);self.assertIn(k,self.store.read()['completed']);self.assertFalse(self.renames.archive_jobs)
  wallets,recovery=bundle([(jobkey,{jobkey:str(r['wallet'])},r['recovery'])]);disc=pack(self.root/'replacement',wallets,recovery,'fixture archive password');self.archives.unload(ident);folder=self.root/'replacement-read';folder.mkdir();review=self.archives.inspect_package(disc/'recovery.wallaby','fixture archive password',folder)['entries'][0];self.assertEqual(review['name'],'Renamed Treasury');self.archives.load(review['id'],True);self.assertEqual(identity(next(iter(self.archives.loaded.values()))['recovery']),before)

 def test_failed_reload_retains_uncertain_outcome_and_never_replays_rename(self):
  rpc(self.core,'createwallet',{'wallet_name':'Before failure','passphrase':'fixture wallet password'});p=task(rpc(self.core,'listdescriptors',[False],'Before failure'),'After failure');snapshot(self.store,queue([p]));k=digest(p)
  with patch('wallet_deletion.bases',return_value=[self.base]):self.renames.review(k)
  original=rpc
  def fail_load(core,method,*args,**kwargs):
   if method=='loadwallet':raise ValueError('Fixture load refusal')
   return original(core,method,*args,**kwargs)
  with patch('wallet_deletion.bases',return_value=[self.base]),patch('wallet_rename.rename',side_effect=lambda source,new,**kw:move({'source':source,'new_name':new},[self.base],**kw)) as rename,patch('rename_requests.rpc',side_effect=fail_load):
   with self.assertRaisesRegex(ValueError,'Review and reconcile'):self.renames.approve(k)
   self.assertEqual(rename.call_count,2)
   with self.assertRaises(ValueError):self.renames.approve(k)
   self.assertEqual(rename.call_count,2)
  self.assertFalse((self.base/'Before failure').exists());self.assertTrue((self.base/'After failure').exists());self.assertEqual(self.store.read()['pending'][k]['state'],'attempted');proof=next(r['payload']['message'] for r in self.store.read()['outbox'].values() if r['kind']=='wallet_rename_result');self.assertTrue(proof['outcome_uncertain']);self.assertNotIn(k,self.store.read()['completed'])

 def test_replacement_keeps_every_other_wallet_on_a_multiwallet_disc(self):
  p,r,ident=self.archive(True);k=digest(p);review=self.renames.review(k)['rename'];self.assertTrue(review['replacement_ready']);self.assertEqual(len(review['replacement_members']),2);self.renames.approve(k,False);self.assertEqual(len(self.ops.jobs),2)
  with self.assertRaisesRegex(ValueError,'Every wallet'):self.setup.burner.select([self.setup.burner.job['id']])
  self.setup.burner.combine();container=self.setup.burner.job['recovery'];self.assertEqual(len(container['entries']),2);self.assertIn(p['archive_id'],container['replaces']);self.assertEqual({e['name'] for e in container['entries']},{'Renamed Treasury','SMSF partner'})
