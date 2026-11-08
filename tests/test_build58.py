"""One grouped consent, signed delivery receipt, exact local batch boundaries."""
import copy,time,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from approval_store import Store,digest
from policy_refresh import Refresh
from policy_refresh_group import received
from vendor.embit.descriptor.checksum import checksum
from wallet_ops import rpc

class Receipt(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from test_build57 import RecoveryValidation
  f=RecoveryValidation();f.setUp();pairs=[]
  for height in (100,200):
   pair=[]
   for field in ('receive_key','change_key'):
    body='wsh(and_v(v:after('+str(height)+'),pk('+f.contribution[field]+')))';pair.append(body+'#'+checksum(body))
   pairs.append(pair)
  f.policies=pairs;self.p={'kind':'wallet_policy_refresh','version':1,'request_id':'8'*64,'chain':'regtest','wallet':'primary','previous_descriptors':f.policies[0],'receive_descriptor':f.policies[1][0],'change_descriptor':f.policies[1][1],'timestamp':0,'expires_at':int(time.time())+3600};self.key=digest(self.p)
 def test_receipt_only_after_durable_acceptance_and_no_duplicate(self):
  received(self.store,self.p);self.assertFalse(self.store.read()['outbox']);self.store.receive(self.p);received(self.store,self.p);received(self.store,self.p)
  saved=self.store.read();self.assertEqual(len(saved['outbox']),1);envelope=next(iter(saved['outbox'].values()))['payload'];from setup_messages import verify
  payload=verify(self.store,envelope,envelope['public_key']);self.assertEqual(payload,{'version':1,'request_id':self.p['request_id'],'request_hash':self.key,'status':'received'});self.assertEqual(saved['pending'][self.key]['state'],'pending')
  self.store.receive(self.p);received(self.store,self.p);self.assertEqual(len(self.store.read()['outbox']),1)
 def test_signed_denial_clears_one_request_and_blocks_repeated_receive(self):
  self.store.receive(self.p);Refresh(None,self.store,SimpleNamespace(loaded={})).deny(self.key);saved=self.store.read();self.assertNotIn(self.key,saved['pending']);self.assertIn(self.key,saved['denied']);self.assertEqual(next(iter(saved['outbox'].values()))['payload']['message']['status'],'denied');self.assertFalse(self.store.receive(self.p))
 def test_attempted_request_cannot_be_denied_or_replayed(self):
  self.store.receive(self.p)
  with self.store.edit() as saved:saved['pending'][self.key]['state']='attempted'
  ops=Refresh(None,self.store,SimpleNamespace(loaded={}))
  with self.assertRaises(ValueError):ops.deny(self.key)
  with self.assertRaises(ValueError):ops.review(self.key)
 def test_exchange_accepts_receipt_capability_and_queues_receipt(self):
  from agent_exchange import Exchange
  captured=[]
  def http(port,path,body,*args,**kwargs):
   captured.append(body);return {'version':1,'accepted':[],'proposals':[self.p]}
  with patch('agent_exchange.http_json',side_effect=http),patch('agent_exchange.local_ipv6',return_value=None):Exchange(12345,'fixture',self.store).once(False)
  self.assertIn('wallet_policy_refresh_batch_v1',captured[0]['capabilities']);self.assertEqual(next(iter(self.store.read()['outbox'].values()))['kind'],'wallet_policy_refresh_receipt')

class BatchIsolation(unittest.TestCase):
 def setUp(self):
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.store=f.store;self.p=f.p;self.key=f.key;self.store.receive(self.p)
  self.ops=Refresh(object(),self.store,SimpleNamespace(loaded={}));self.facts={'funded_outputs':[],'height':200,'policy_hash':digest(__import__('policy_refresh').transition(self.p))};self.targets=[{'wallet':n,'storage':'node','private':False,'archive':None,'history':None,'public':'same','already_installed':False} for n in ('one','two')];self.ops.reviews[self.key]=(self.p,self.facts,time.monotonic(),self.targets);self.imports=[]
 def call(self,core,method,params=None,wallet=None,**kwargs):
  if method=='getblockchaininfo':return {'chain':'regtest','blocks':100}
  if method=='importdescriptors':
   self.imports.append(wallet)
   if wallet=='two':raise ValueError('fixture failed second import')
   return [{'success':True},{'success':True}]
  if method=='listdescriptors':return {'wallet_name':wallet,'descriptors':[{'desc':d} for d in self.p['previous_descriptors']+[self.p['receive_descriptor'],self.p['change_descriptor']]]}
  if method=='deriveaddresses':return ['fixture address']
  if method=='setlabel':return None
  raise AssertionError(method)
 def test_partial_failure_is_not_approval_and_is_not_replayed(self):
  with patch('policy_refresh_group.targets',return_value=self.targets),patch('policy_refresh_group.rpc',side_effect=self.call):
   with self.assertRaisesRegex(ValueError,'incomplete or uncertain'):self.ops.approve(self.key)
   self.assertEqual(self.imports,['one','two']);saved=self.store.read();self.assertEqual(saved['pending'][self.key]['state'],'attempted');self.assertEqual(saved['pending'][self.key]['batch_completed'],['one']);self.assertFalse(saved['completed']);self.assertEqual(next(iter(saved['outbox'].values()))['payload']['message']['status'],'error')
   with self.assertRaises(ValueError):self.ops.approve(self.key)
   self.assertEqual(self.imports,['one','two'])
 def test_changed_local_set_refuses_before_import(self):
  with patch('policy_refresh_group.targets',return_value=self.targets[:1]),patch('policy_refresh_group.rpc',side_effect=self.call):
   with self.assertRaisesRegex(ValueError,'changed'):self.ops.approve(self.key)
  self.assertFalse(self.imports);self.assertEqual(self.store.read()['pending'][self.key]['state'],'pending')

class RealBatch(unittest.TestCase):
 def setUp(self):
  from test_build41 import CombinedCluster
  CombinedCluster.setUp(self)
 def test_one_approval_updates_node_and_two_loaded_disc_signers_then_reloads(self):
  from test_build41 import PASSWORD
  from disc_restore import Archives
  import zipfile
  from setup_completion import mark
  a=self.agents[1];root=Path(self.tmp.name);approved=next(iter(a.store.read()['approved_wallets'].values()));mark(a.core,approved,True)
  pool=Archives(a.core,a.store,a.binary,lambda:None);pool.environment={};self.addCleanup(lambda:[pool.unload(k) for k in list(pool.loaded)])
  items=[(a.burner.job['wallets'],a.burner.job['recovery'])]+[(r[1],r[2]) for r in a.burner.pending];self.assertEqual(len(items),2)
  def load(wallet,recovery,label):
   folder=root/label;folder.mkdir();package=root/(label+'.zip')
   with zipfile.ZipFile(package,'w') as z:z.write(wallet,'wallet.dat')
   with zipfile.ZipFile(package) as z:ident,row=pool.stage_entry(recovery,z,'wallet.dat',folder,'f'*64)
   pool.staged[ident]=row
   with patch('disc_restore.secret_dialog',return_value=PASSWORD):pool.load(ident,True)
   return ident,pool.loaded[ident]
  for i,(wallets,recovery) in enumerate(items):load(next(iter(wallets.values())),copy.deepcopy(recovery),'original-'+str(i))
  # An unrelated private wallet and staged archive must not join the batch.
  rpc(a.core,'createwallet',{'wallet_name':'Unrelated','passphrase':PASSWORD});unrelated=rpc(a.core,'listdescriptors',[False],'Unrelated');pool.staged['unrelated']={'marker':'untouched'}
  new=[]
  for desc in self.descs:
   body=desc.split('#')[0].replace('after(100)','after(200)');new.append(body+'#'+checksum(body))
  primary=next(iter(approved['signing_wallets'].values()));p={'kind':'wallet_policy_refresh','version':1,'request_id':'b'*64,'chain':'regtest','wallet':primary,'previous_descriptors':self.descs,'receive_descriptor':new[0],'change_descriptor':new[1],'timestamp':int(time.time()),'expires_at':int(time.time())+3600};key=digest(p);a.store.receive(p);received(a.store,p);ops=Refresh(a.core,a.store,pool)
  from archive_operations import Operations
  from archive_format import identity
  ops.archive_ops=Operations(a.core,a.store,a,pool,lambda:None)
  pool.catalogs['f'*64]={identity(r['recovery']):copy.deepcopy(r['recovery']) for r in pool.loaded.values()}
  with patch('node_client.LOCAL_ROUTER',pool):
   shown=ops.review(key);self.assertEqual(len(shown['refresh']['targets']),5);self.assertEqual(sum(r['private'] for r in shown['refresh']['targets']),3)
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD) as ask:result=ops.approve(key)
   self.assertEqual(ask.call_count,3);self.assertEqual(len(result['updated_wallets']),5)
   self.assertTrue(result['burn_authorised']);self.assertEqual(len(ops.archive_ops.jobs),2)
   self.assertEqual(a.store.read()['pending'][key]['state'],'awaiting_backups');self.assertTrue(ops.review(key)['refresh']['backups_pending'])
   self.assertFalse(any(v['kind']=='wallet_policy_refresh_result' for v in a.store.read()['outbox'].values()))
   from policy_refresh_backups import destroyed
   ops.archive_ops.verified_replacements['f'*64]={'image_sha256':'1'*64,'members':list(pool.catalogs['f'*64]),'member_policies':{k:digest(new) for k in pool.catalogs['f'*64]},'old_policies_retained':True,'readback_verified':True}
   destroyed(ops.archive_ops,'f'*64)
   outcome=next(v['payload']['message'] for v in a.store.read()['outbox'].values() if v['kind']=='wallet_policy_refresh_result' and v['payload']['message']['request_id']==p['request_id']);self.assertEqual(outcome['status'],'approved');self.assertEqual(set(outcome['updated_wallets']),{primary,*[name for r in pool.loaded.values() for name in r['routes']]})
   for name in result['updated_wallets']:
    from build8_policy import descriptors
    self.assertTrue(descriptors({'wallet_name':'wanted','descriptors':[{'desc':d} for d in self.descs+new]})<=descriptors(rpc(a.core,'listdescriptors',[False],name)))
   self.assertEqual(rpc(a.core,'listdescriptors',[False],'Unrelated'),unrelated);self.assertEqual(pool.staged['unrelated'],{'marker':'untouched'})
   # Both encrypted disc roles remain recoverable with updated metadata.
   snapshots=[]
   for i,(ident,record) in enumerate(list(pool.loaded.items())):
    self.assertEqual(len(record['recovery']['policy_extensions']),1);self.assertEqual(record['review']['height'],200);backup=root/('updated-'+str(i)+'.dat');rpc(record['node'].core,'backupwallet',[str(backup)],'archive-key');snapshots.append((backup,copy.deepcopy(record['recovery'])));pool.unload(ident)
   for i,(backup,recovery) in enumerate(snapshots):
    ident,record=load(backup,recovery,'reloaded-'+str(i));self.assertEqual(record['review']['height'],200)
   # Retirement preserves the wallets, then the identical height/address can be
   # explicitly approved again without producing new keys or duplicate history.
   from cancellation import Cancellations
   from wallet_ops import WalletOps
   from policy_refresh_cancel import policy_id
   from policy_refresh import validate_extensions
   from archive_operations import Operations
   cancel=Cancellations(a.core,a.store,a,WalletOps(a.core,a.store));cancel.archives=pool;cancel.archive_ops=ops.archive_ops
   def cancellation(original,nonce):
    value={'kind':'builder_cancel','version':1,'builder':'wallet','workspace_id':nonce*32,'cancellation_id':nonce*32,'operations':[],'request_hashes':[original],'require_local_authorisation':True,'backup_option':True};value['request_id']=digest(value);return cancel.receive(value)
   core=a.core;rpc(core,'createwallet',{'wallet_name':'miner'});miner=rpc(core,'getnewaddress',[],'miner');rpc(core,'generatetoaddress',[101,miner],timeout=120)
   before_names=rpc(a.core,'listwallets');cancel_key=cancellation(key,'c');shown=cancel.review(cancel_key);self.assertFalse(shown['cancellation']['funded'])
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):cancel.confirm(cancel_key,'delete')
   self.assertEqual(rpc(a.core,'listwallets'),before_names);self.assertIn(policy_id(p),a.store.read()['retired_policies']);self.assertFalse(ops.archive_ops.jobs,'cancelled unstarted refresh captures must be removed')
   for record in pool.loaded.values():self.assertEqual(validate_extensions(record['recovery']),self.descs)
   retired_backups=[]
   for i,(ident,record) in enumerate(list(pool.loaded.items())):
    backup=root/('retired-'+str(i)+'.dat');rpc(record['node'].core,'backupwallet',[str(backup)],'archive-key');retired_backups.append((backup,copy.deepcopy(record['recovery'])));pool.unload(ident)
   for i,(backup,recovery) in enumerate(retired_backups):
    ident,record=load(backup,recovery,'retired-reload-'+str(i));self.assertEqual(record['review']['height'],100)
   again=copy.deepcopy(p);again.update(request_id='d'*64,timestamp=p['timestamp']+1);again_key=digest(again);a.store.receive(again);ops.review(again_key)
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):ops.approve(again_key)
   destroyed(ops.archive_ops,'f'*64)
   self.assertNotIn(policy_id(p),a.store.read().get('retired_policies',{}));self.assertEqual(rpc(a.core,'listwallets'),before_names)
   for record in pool.loaded.values():self.assertEqual(validate_extensions(record['recovery']),new);self.assertEqual(len(record['recovery']['policy_extensions']),1)
   # Independently detect the output vault and forecast its height from local
   # Core, even when Wallet Server supplies no output_policies binding.
   address=rpc(core,'deriveaddresses',[new[0],[0,0]])[0]
   coin=rpc(core,'listunspent',[1],'miner')[0];packet=rpc(core,'walletcreatefundedpsbt',{'inputs':[{'txid':coin['txid'],'vout':coin['vout']}],'outputs':[{address:'0.01'}],'options':{'add_inputs':False,'fee_rate':1}},'miner')['psbt']
   sign={'kind':'sign_psbt_partial','request_id':'e'*64,'chain':'regtest','wallet':'miner','psbt':packet};a.store.receive(sign);shown=cancel.ops.prepare_request(digest(sign));forecast=next(v for v in shown['unlock_estimates'] if v['height']==200);self.assertIn('utc',forecast);self.assertIn('local',forecast);self.assertIn('local_zone',forecast);self.assertTrue(any(o.get('vault_policy',{}).get('height')==200 for o in shown['review']['outputs']))
   a.store.deny(digest(sign));cancel.ops.prepared.clear()
   # Unconfirmed AND confirmed funding both block retirement; retention is an
   # explicit alternative, never a successful deletion/retirement result.
   rpc(core,'sendtoaddress',[address,'0.001'],'miner');funded_cancel=cancellation(again_key,'f');self.assertTrue(cancel.review(funded_cancel)['cancellation']['funded'])
   with self.assertRaisesRegex(ValueError,'funded'):cancel.confirm(funded_cancel,'delete')
   rpc(core,'generatetoaddress',[1,miner]);self.assertTrue(cancel.review(funded_cancel)['cancellation']['funded'])
   with self.assertRaisesRegex(ValueError,'funded'):cancel.confirm(funded_cancel,'delete')
   cancel.confirm(funded_cancel,'retain');self.assertNotIn(funded_cancel,a.store.read()['pending']);outcomes=[v['payload']['message'] for v in a.store.read()['outbox'].values() if v['kind']=='wallet_policy_refresh_cancel_result'];self.assertEqual(outcomes[-1]['status'],'retained_funded');self.assertFalse(outcomes[-1]['retired_policy_hashes']);self.assertNotIn(policy_id(p),a.store.read().get('retired_policies',{}))

class FundingAndDiscs(unittest.TestCase):
 setUp=Receipt.setUp
 def test_confirmed_or_unconfirmed_funding_and_unknown_scan_are_blocking(self):
  from policy_refresh_cancel import funding
  c=SimpleNamespace(core=object())
  for confirmed,mempool,expected in (([],[],False),([{'amount':1}],[],True),([],[{'type':'receive','amount':1}],True)):
   def call(core,method,*args,**kwargs):return {'chain':'regtest','blocks':100,'headers':100,'initialblockdownload':False} if method=='getblockchaininfo' else {'success':True,'unspents':confirmed} if method=='scantxoutset' else {'activity':mempool}
   with patch('policy_refresh_cancel.rpc',side_effect=call):self.assertEqual(funding(c,self.p,[])['funded'],expected)
  with patch('policy_refresh_cancel.rpc',side_effect=[{'blocks':100},{'success':False}]):
   with self.assertRaises(ValueError):funding(c,self.p,[])
 def test_retired_replacement_does_not_become_another_disc_to_destroy(self):
  from policy_refresh_cancel import disc_plans,policy_id
  raw={'wallet_name':'role','descriptors':[{'desc':self.p[k]} for k in ('receive_descriptor','change_descriptor')]};member={'member_id':'a'*64,'name':'Treasury','public_wallet':raw,'related_policies':[]}
  with self.store.edit() as saved:saved['verified_archive_discs']={'b'*64:{'members':[member]},'c'*64:{'members':[member],'retired_members':{member['member_id']:[policy_id(self.p)]}}}
  c=SimpleNamespace(store=self.store,archives=None);plans=disc_plans(c,{self.key:self.p});self.assertEqual([r['archive_id'] for r in plans],['b'*64])
 def test_destruction_requires_every_member_in_a_verified_replacement(self):
  from policy_refresh_cancel import confirm
  self.store.receive(self.p)
  with self.store.edit() as saved:
   saved['completed'][self.key]={'kind':'wallet_policy_refresh','proposal':self.p};saved['pending'].pop(self.key)
   saved['pending']['c'*64]={'state':'policy_retired','proposal':{'builder':'wallet','operations':[],'request_hashes':[self.key],'cancellation_id':'d'*32}}
  c=SimpleNamespace(store=self.store,archive_ops=SimpleNamespace(verified_replacements={}),ops=SimpleNamespace(prepared={}))
  facts={'funded':False,'active_disc_write':False,'discs':[{'archive_id':'e'*64,'members':['first','unrelated-wallet'],'copies':1}]}
  with patch('policy_refresh_cancel.facts',return_value=facts):
   with self.assertRaisesRegex(ValueError,'verified replacement'):confirm(c,'c'*64,'destroy:'+'e'*64)
   c.archive_ops.verified_replacements['e'*64]={'readback_verified':True,'members':['first']}
   with self.assertRaisesRegex(ValueError,'verified replacement'):confirm(c,'c'*64,'destroy:'+'e'*64)
   c.archive_ops.verified_replacements['e'*64]={'readback_verified':True,'members':['first','unrelated-wallet']}
   with patch('policy_refresh_cancel.complete',return_value={'message':'complete'}) as complete:confirm(c,'c'*64,'destroy:'+'e'*64);complete.assert_called_once()
   facts['funded']=True
   with self.assertRaisesRegex(ValueError,'funded'):confirm(c,'c'*64,'destroy:'+'e'*64)

class BackupHandoff(unittest.TestCase):
 setUp=Receipt.setUp
 def test_each_refreshed_signer_is_required_but_other_archives_can_be_omitted(self):
  from policy_refresh_backups import hold,destroyed,guard,review
  self.store.receive(self.p);outcome={'status':'approved','extra':{'updated_wallets':['local','disc-a','disc-b'],'policy_hash':digest(__import__('policy_refresh').transition(self.p))}}
  ops=SimpleNamespace(store=self.store,archive_ops=SimpleNamespace(store=self.store,verified_replacements={}))
  hold(ops,self.key,{'wallet':'Treasury'},outcome,{'a':{'members':['signer-a','David SMSF'],'updated_members':['signer-a'],'destroyed':False},'b':{'members':['signer-b'],'destroyed':False}})
  bad={'outputs':[{'vault_policy':{'descriptors':[self.p['receive_descriptor']]}}]}
  with self.assertRaisesRegex(ValueError,'replacement-disc'):guard(self.store,bad)
  guard(self.store,{'outputs':[{'vault_policy':{'descriptors':['different vault at same height']}}]})
  ops.archive_ops.verified_replacements['a']={'readback_verified':True,'old_policies_retained':True,'members':['signer-a']}
  with self.assertRaisesRegex(ValueError,'approved new policy'):destroyed(ops.archive_ops,'a')
  ops.archive_ops.verified_replacements['a']['member_policies']={'signer-a':digest([self.p['receive_descriptor'],self.p['change_descriptor']])};destroyed(ops.archive_ops,'a')
  self.assertIn(self.key,self.store.read()['pending']);self.assertTrue(review(ops,self.key)['refresh']['backups_pending']);self.assertEqual(review(ops,self.key)['refresh']['backup_discs'][0]['omitted'],['David SMSF'])
  ops.archive_ops.verified_replacements['b']={'readback_verified':True,'old_policies_retained':True,'members':['signer-b']};destroyed(ops.archive_ops,'b')
  self.assertNotIn(self.key,self.store.read()['pending']);guard(self.store,bad)
  results=[v for v in self.store.read()['outbox'].values() if v['kind']=='wallet_policy_refresh_result'];self.assertEqual(len(results),1);self.assertEqual(results[0]['payload']['message']['status'],'approved')
 def test_missing_catalogue_blocks_and_only_refreshed_signers_are_auto_queued(self):
  from policy_refresh_backups import plan,stage
  loaded={'signer':{'archive_id':'disc','recovery':{'policy_hash':'a'*64,'physical_cosigner_file':'role'}},'unrelated':{'archive_id':'disc','recovery':{'policy_hash':'b'*64,'physical_cosigner_file':'other'}},'other':{'archive_id':'elsewhere'}}
  queue=Mock();ops=SimpleNamespace(archives=SimpleNamespace(loaded=loaded,catalogs={}),archive_ops=SimpleNamespace(queue_loaded=queue,jobs={}))
  with self.assertRaisesRegex(ValueError,'catalogue'):plan(ops,[{'archive':'signer'}])
  from archive_format import identity
  ops.archives.catalogs['disc']={identity(loaded['signer']['recovery']):{},identity(loaded['unrelated']['recovery']):{}};required=plan(ops,[{'archive':'signer'}]);stage(ops,required)
  self.assertEqual(set(queue.call_args.args[0]),{'signer'})
 def test_verified_refresh_may_omit_old_archive_without_claiming_generic_full_coverage(self):
  from archive_operations import Operations
  from archive_format import identity
  from policy_refresh_backups import hold,review,confirm
  from policy_refresh import transition
  raw={'wallet_name':'Disc signer','descriptors':[{'desc':d,'internal':bool(i)} for i,d in enumerate(self.p['previous_descriptors'])]}
  old={'kind':'node_wallet','version':1,'name':'Disc signer','chain':'regtest','policy_hash':digest(raw),'public_wallet':raw,'labels':[]}
  new=copy.deepcopy(old);new['policy_extensions']=[transition(self.p)];ident=identity(old)
  other=copy.deepcopy(old);other['name']='David SMSF';other['public_wallet']=copy.deepcopy(raw);other['public_wallet']['wallet_name']='David SMSF';other_id=identity(other)
  self.store.receive(self.p);local=Operations.__new__(Operations);local.store=self.store;local.archives=SimpleNamespace(catalogs={'original':{ident:old,other_id:other}});local.verified_replacements={};local.jobs={'job':{'recovery':new,'request':None,'folder':None,'phase':'queued'}};local.cancellations=SimpleNamespace(completed=Mock())
  local.setup=SimpleNamespace(burner=SimpleNamespace(job={'recovery':new,'archive_id':'b'*64,'disc_count':1,'_members':[('job',{},new)]}))
  ops=SimpleNamespace(store=self.store,archive_ops=local)
  hold(ops,self.key,{'wallet':'Treasury'},{'status':'approved','extra':{'updated_wallets':['disc'],'policy_hash':digest(transition(self.p))}},{'original':{'members':[ident,other_id],'updated_members':[ident],'names':{ident:'Signer',other_id:'David SMSF'},'destroyed':False}})
  self.assertEqual(local.replacements([('job',{},new)]),[])
  local.complete('job','c'*64)
  self.assertFalse(local.verified_replacements);self.assertIn('original',local.policy_replacements)
  shown=review(ops,self.key)['refresh']['backup_discs'][0];self.assertTrue(shown['replacement_verified']);self.assertEqual(shown['omitted'],['David SMSF'])
  inventory=next(v['payload']['message'] for v in self.store.read()['outbox'].values() if v['kind']=='archive_inventory');self.assertEqual(inventory['replacements'],[])
  with self.assertRaisesRegex(ValueError,'choices changed'):confirm(ops,self.key,'original','old-token',True)
  confirm(ops,self.key,'original',shown['token'],True);self.assertNotIn(self.key,self.store.read()['pending'])
