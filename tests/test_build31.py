"""Archive cancellation: real encrypted Core captures, real signatures, simulated optical I/O."""
import copy,hashlib,json,tempfile,time,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from archive_cancel import validate
from archive_requests import snapshot,delete
from archive_operations import Operations
from archive_format import identity
from disc_backup import Burner
import test_archive_queue30 as queue_fixture

def cancel_task(original,receipt=None,nonce='a'*64):
 p={'kind':'archive_cancel','version':1,'nonce':nonce,'wallet':original['wallet'],'archive_request':copy.deepcopy(original),'completed_receipt':receipt,'finish_inflight_burn_and_verify':True,'require_local_destruction_confirmation':True,'preserve_unrelated_members':True};p['request_id']=digest(p);return p

class Cancellation(queue_fixture.ArchiveQueue):
 def setUp(self):
  super().setUp();self.setup.own_identity=lambda:{'public_key':' '.join((getattr(self.store,'identity_root',self.store.root)/'preview_identity.pub').read_text().split()[:2])}
 def pack(self,root,wallets,recovery,password):
  self.packed_names=[r['name'] for r in recovery['entries']];disc=root/'disc';disc.mkdir();(disc/'recovery.wallaby').write_bytes((json.dumps(recovery,sort_keys=True)+'fixture encrypted optical payload').encode());return disc
 def request_cancel(self,index=0,receipt=None,other=True):
  p=cancel_task(self.tasks[index],receipt);rows=[r for i,r in enumerate(self.tasks) if i!=index] if other else [];self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':rows+[p]});return digest(p),p
 def wire(self,key,p):
  source=os.environ.get('WALLABY_TEST_DASHBOARD_CANCEL_SRC')
  if not source:return
  result=self.store.read()['completed'][key]['result'];run=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('dashboard40_cancel_probe.py')),source],input=json.dumps({'task':p,'result':result}),text=True,capture_output=True,timeout=30);self.assertEqual(run.returncode,0,run.stderr);print('Wallet Server cancellation interoperability:',run.stdout.strip(),flush=True)
 def test_unattempted_and_unused_staged_requests_disappear_without_a_disc(self):
  first=self.add('First');k,p=self.request_cancel();self.ops.cancellations.observe();self.assertNotIn(k,self.store.read()['pending']);self.assertEqual(self.store.read()['completed'][k]['result']['disc_created'],False);self.wire(k,p)
  second=self.add('Second');self.stage(second);folder=self.ops.jobs[second]['folder'];k,p=self.request_cancel(1);self.ops.cancellations.observe();self.assertFalse(folder.exists());self.assertFalse(self.ops.busy());self.assertIsNone(self.burner.job);self.assertFalse(self.store.read()['completed'][k]['result']['disc_created']);self.wire(k,p)
 def test_cancel_during_write_finishes_verification_but_never_starts_next_copy(self):
  original=self.add('First');self.stage(original);saved={}
  def write(*args):
   saved['key'],saved['task']=self.request_cancel();self.ops.cancellations.observe(mark_only=True);self.assertTrue(self.burner.job['_cancel_pending']);return self.write(*args)
  with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.pack',side_effect=self.pack),patch('disc_backup.image',side_effect=lambda d,i:i.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=write) as writer,patch('disc_backup.readback') as read:
   self.burner.start('/dev/sr0',True,'fixture',2);self.burner.thread.join(15);self.assertFalse(self.burner.thread.is_alive());self.assertEqual(writer.call_count,1);self.assertEqual(read.call_count,1)
  self.assertEqual(self.burner.job['phase'],'cancel_cleanup');self.assertNotIn(original,self.store.read()['completed']);self.assertTrue(self.ops.cancellations.review(saved['key'])['cancellation']['verification_finished'])
  with self.assertRaisesRegex(ValueError,'cancelled'):self.burner.start('/dev/sr0',True,'fixture',2)
  with self.assertRaises(ValueError):self.ops.cancellations.confirm(saved['key'],False)
  self.ops.cancellations.confirm(saved['key'],True);result=self.store.read()['completed'][saved['key']]['result'];self.assertTrue(result['disc_created']);self.assertTrue(result['destruction_confirmed_locally']);self.assertFalse(self.ops.busy());self.wire(saved['key'],saved['task'])
 def test_mixed_disc_needs_all_other_members_on_verified_replacement(self):
  first=self.add('First');second=self.add('Second');third=self.add('Third')
  for k in (first,second,third):self.stage(k)
  self.burner.select([first,second]);saved={}
  def write(*args):saved['key'],saved['task']=self.request_cancel();self.ops.cancellations.observe(mark_only=True);return self.write(*args)
  with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.pack',side_effect=self.pack),patch('disc_backup.image',side_effect=lambda d,i:i.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=write),patch('disc_backup.readback'):
   self.burner.start('/dev/sr0',True,'fixture');self.burner.thread.join(15)
  key=saved['key'];r=self.ops.cancellations.review(key)['cancellation'];self.assertTrue(r['replacement_required']);self.assertEqual([v['name'] for v in r['remaining_members']],['Second'])
  with self.assertRaisesRegex(ValueError,'Preserve every'):self.ops.cancellations.confirm(key,True)
  self.ops.cancellations.stage(key,True)
  with self.assertRaises(ValueError):self.burner.select([third])
  self.burn();self.assertEqual(self.packed_names,['Second']);self.assertTrue(self.ops.cancellations.review(key)['cancellation']['replacement_verified']);self.assertIn(second,self.store.read()['completed']);self.assertNotIn(third,self.store.read()['completed']);self.ops.cancellations.confirm(key,True);self.wire(key,saved['task']);self.burner.job['finished']=time.time()-6;self.assertEqual(self.burner.state()['queue'][0]['id'],third);self.assertTrue((self.ops.jobs[third]['folder']/'wallet.dat').exists())
 def test_completed_receipt_survives_worker_reset_and_requires_read_members(self):
  first=self.add('First');second=self.add('Second')
  for k in (first,second):self.stage(k)
  backups={k:{'recovery':copy.deepcopy(self.ops.jobs[k]['recovery']),'wallet':(self.ops.jobs[k]['folder']/'wallet.dat').read_bytes()} for k in (first,second)}
  self.burner.select([first,second]);self.burn();receipt=self.store.read()['completed'][first]['result']['signed_receipt'];k,p=self.request_cancel(receipt=receipt)
  # Simulate a fresh volatile worker: only its persistent signing identity and
  # the Wallet Server's exact signed original completion survive.
  previous=self.store;self.store=Store(self.root/'new-worker');self.store.identity_root=previous.root;self.ops.store=self.store;self.ops.cancellations.store=self.store;self.ops.jobs={};self.burner.job=None;self.burner.pending=[];self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':[p]})
  facts=self.ops.cancellations.review(k)['cancellation'];self.assertTrue(facts['disc_created'])
  with self.assertRaisesRegex(ValueError,'Read the original'):self.ops.cancellations.stage(k,True)
  archive_id=facts['archive_id'];catalog={};staged={}
  for ident,r in backups.items():
   folder=self.root/('disc-read-'+ident);folder.mkdir();wallet=folder/'wallet.dat';wallet.write_bytes(r['wallet']);catalog[identity(r['recovery'])]=r['recovery'];staged[ident]={'archive_id':archive_id,'recovery':r['recovery'],'wallet':wallet}
  self.ops.archives.catalogs={archive_id:catalog};self.ops.archives.staged=staged;self.ops.cancellations.stage(k,True);self.burn();self.assertEqual(self.packed_names,['Second']);self.ops.cancellations.confirm(k,True);self.assertTrue(self.store.read()['completed'][k]['result']['replacement_readback_verified']);self.wire(k,p)
 def test_recovered_receipt_counts_partial_attempts_in_physical_cleanup(self):
  from setup_messages import sign
  first=self.add('First');self.stage(first);self.burn();receipt=self.store.read()['completed'][first]['result']['signed_receipt'];message=copy.deepcopy(receipt['message']);message['attempted_disc_count']=3;receipt=sign(self.store,message);key,p=self.request_cancel(receipt=receipt)
  self.ops.jobs={};self.burner.job=None;self.burner.pending=[]
  facts=self.ops.cancellations.review(key)['cancellation'];self.assertEqual(facts['disc_count'],3)
  with self.assertRaisesRegex(ValueError,'count'):self.ops.cancellations.confirm(key,True,destroyed_disc_count=2)
  self.ops.cancellations.confirm(key,True,destroyed_disc_count=3);self.assertEqual(self.store.read()['completed'][key]['result']['destroyed_disc_count'],3);self.wire(key,p)
 def test_no_evidence_is_not_proof_no_disc_and_cleanup_cannot_be_denied(self):
  original=self.add('First');p=cancel_task(self.tasks[0]);self.revision+=1
  with self.store.edit() as s:s['pending'].clear()
  snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':[p]});k=digest(p);self.ops.cancellations.observe();self.assertTrue(self.ops.cancellations.review(k)['cancellation']['unknown_prior_disc'])
  with self.assertRaises(ValueError):self.ops.cancellations.confirm(k,True)
  with self.assertRaises(ValueError):delete(self.store,k)
  with self.assertRaises(ValueError):self.store.deny(k)
  self.ops.cancellations.confirm(k,True,True);self.assertFalse(self.store.read()['completed'][k]['result']['disc_created'])
 def test_tampered_receipt_wrong_source_and_missing_safeguards_refused(self):
  first=self.add('First');self.stage(first);self.burn();receipt=copy.deepcopy(self.store.read()['completed'][first]['result']['signed_receipt']);receipt['message']['request_id']='e'*64;k,p=self.request_cancel(receipt=receipt)
  with self.assertRaises(ValueError):self.ops.cancellations.review(k)
  for field in ('finish_inflight_burn_and_verify','require_local_destruction_confirmation','preserve_unrelated_members'):
   bad=copy.deepcopy(p);bad[field]=False;bad['request_id']=digest({k:v for k,v in bad.items() if k!='request_id'})
   with self.assertRaises(ValueError):validate(bad)
 def cancelled_burn(self,ids,tasks,fail=False):
  self.burner.select(ids)
  def write(*args):
   self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':tasks});self.ops.cancellations.observe(mark_only=True)
   if fail:raise ValueError('Simulated write failure')
   return self.write(*args)
  with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.pack',side_effect=self.pack),patch('disc_backup.image',side_effect=lambda d,i:i.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=write),patch('disc_backup.readback',side_effect=ValueError('Simulated unreadable partial disc') if fail else None) as check:
   self.burner.start('/dev/sr0',True,'fixture');self.burner.thread.join(15);self.assertFalse(self.burner.thread.is_alive());self.assertEqual(check.call_count,1)
 def test_failed_writer_still_finishes_verification_attempt_before_local_cleanup(self):
  original=self.add('First');self.stage(original);p=cancel_task(self.tasks[0]);key=digest(p);self.cancelled_burn([original],[p],True);self.assertEqual(self.burner.job['phase'],'cancel_cleanup');facts=self.ops.cancellations.review(key)['cancellation'];self.assertTrue(facts['verification_finished']);self.assertFalse(facts['verification_succeeded']);self.ops.cancellations.confirm(key,True);self.assertFalse(self.store.read()['completed'][key]['result']['verification_succeeded']);self.wire(key,p)
 def test_two_requests_share_cleanup_evidence_but_have_distinct_signed_outcomes(self):
  first=self.add('First');second=self.add('Second');self.stage(first);self.stage(second);a=cancel_task(self.tasks[0]);b=cancel_task(self.tasks[1],nonce='b'*64);self.cancelled_burn([first,second],[a,b])
  for p in (a,b):
   key=digest(p);facts=self.ops.cancellations.review(key)['cancellation'];self.assertFalse(facts['replacement_required']);self.assertEqual(len(facts['cancelled_members']),2);self.ops.cancellations.confirm(key,True);self.wire(key,p)
  self.assertFalse(self.ops.busy());self.assertEqual({digest(a),digest(b)},{k for k,r in self.store.read()['completed'].items() if r['kind']=='archive_cancel'})
 def test_cancellation_never_discards_fresh_request_for_same_policy(self):
  original=self.add('First');self.stage(original);p=cancel_task(self.tasks[0]);fresh=copy.deepcopy(self.tasks[0]);fresh['nonce']='9'*64;fresh['request_id']=digest({k:v for k,v in fresh.items() if k!='request_id'});self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':[p,fresh]});self.ops.cancellations.observe();self.assertIn(digest(fresh),self.store.read()['pending']);self.assertEqual(self.store.read()['pending'][digest(fresh)]['state'],'pending');self.assertNotIn(original,self.store.read()['pending'])
 def test_late_cancel_tracks_account_on_shared_replacement_and_preserves_remaining_wallet(self):
  first=self.add('First');second=self.add('Second');third=self.add('Third')
  for ident in (first,second,third):self.stage(ident)
  backups={i:{'recovery':copy.deepcopy(self.ops.jobs[i]['recovery']),'wallet':(self.ops.jobs[i]['folder']/'wallet.dat').read_bytes()} for i in (second,third)}
  a=cancel_task(self.tasks[0]);ka=digest(a);self.cancelled_burn([first,second,third],[a,self.tasks[1],self.tasks[2]]);self.ops.cancellations.review(ka);self.ops.cancellations.stage(ka,True);self.burn();replacement_id=self.burner.job['archive_id']
  b=cancel_task(self.tasks[1],nonce='b'*64);kb=digest(b);self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':[a,b]});self.ops.cancellations.observe();self.ops.cancellations.review(ka);self.ops.cancellations.confirm(ka,True)
  self.ops.cancellations.review(kb);outcome=self.ops.cancellations.confirm(kb,True);self.assertTrue(outcome['more_cleanup']);self.assertNotIn(kb,self.store.read()['completed']);facts=self.ops.cancellations.review(kb)['cancellation'];self.assertEqual(facts['archive_id'],replacement_id);self.assertEqual([r['name'] for r in facts['remaining_members']],['Third'])
  with self.assertRaisesRegex(ValueError,'Read the original'):self.ops.cancellations.stage(kb,True)
  catalog={};staged={}
  for i,r in backups.items():
   folder=self.root/('read-replacement-'+i);folder.mkdir();wallet=folder/'wallet.dat';wallet.write_bytes(r['wallet']);catalog[identity(r['recovery'])]=r['recovery'];staged[i]={'archive_id':replacement_id,'recovery':r['recovery'],'wallet':wallet}
  self.ops.archives.catalogs[replacement_id]=catalog;self.ops.archives.staged=staged;self.ops.cancellations.stage(kb,True);self.burn();self.assertEqual(self.packed_names,['Third']);self.ops.cancellations.confirm(kb,True);result=self.store.read()['completed'][kb]['result'];self.assertEqual(result['destroyed_disc_count'],2);self.assertEqual(len(result['destroyed_archives']),2);self.assertTrue(result['replacement_readback_verified']);self.wire(kb,b)
 def test_another_agent_requires_original_fingerprint_and_actual_disc_before_cleanup(self):
  from setup_messages import sign
  from wallet_preview import fingerprint
  original=self.add('First');self.stage(original);recovery=copy.deepcopy(self.ops.jobs[original]['recovery']);self.burn();receipt=self.store.read()['completed'][original]['result']['signed_receipt'];key,p=self.request_cancel(receipt=receipt)
  self.store=Store(self.root/'different-agent');new=sign(self.store,{'purpose':'fixture identity'});self.ops.store=self.store;self.ops.cancellations.store=self.store;self.ops.jobs={};self.burner.job=None;self.burner.pending=[];self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':[p]})
  facts=self.ops.cancellations.review(key)['cancellation'];self.assertTrue(facts['creator_confirmation_required']);self.assertFalse(facts['disc_read_verified']);pin=fingerprint(receipt['public_key'])
  with self.assertRaisesRegex(ValueError,'fingerprint'):self.ops.cancellations.confirm(key,True)
  with self.assertRaisesRegex(ValueError,'Read the original'):self.ops.cancellations.confirm(key,True,False,None,pin)
  self.ops.archives.catalogs[facts['archive_id']]={identity(recovery):recovery};self.assertTrue(self.ops.cancellations.review(key)['cancellation']['disc_read_verified']);self.ops.cancellations.confirm(key,True,False,None,pin);result=self.store.read()['completed'][key]['result'];self.assertEqual(result['signed_receipt']['public_key'],new['public_key']);self.wire(key,p)

class ForeignDiscEvidence(unittest.TestCase):
 def fixture(self):
  import test_build30
  from setup_messages import sign
  f=test_build30.MixedDiscRetirement();f.setUp();self.addCleanup(f.doCleanups);fresh=Store(Path(f.tmp.name)/'new-agent');public=sign(fresh,{'purpose':'new Agent fixture'})['public_key'];f.ops.store=fresh;f.ops.setup.own_identity=lambda:{'public_key':public};fresh.receive(f.p);return f
 def test_extinct_cleanup_on_new_agent_checks_both_disc_and_preservation_identities(self):
  from extinct_discs import review,stage,completed,destroyed
  f=self.fixture();facts=review(f.ops,f.key)['destruction'];self.assertTrue(facts['creator_confirmation_required']);origin=facts['creator_fingerprint']
  with self.assertRaisesRegex(ValueError,'original disc Agent fingerprint'):stage(f.ops,f.key,True,f.pin)
  stage(f.ops,f.key,True,f.pin,origin);completed(f.ops,{identity(f.current):f.current},'f'*64)
  with self.assertRaisesRegex(ValueError,'original disc Agent fingerprint'):destroyed(f.ops,f.key,True,f.pin)
  destroyed(f.ops,f.key,True,f.pin,origin);self.assertIn(f.key,f.ops.store.read()['completed'])
 def test_foreign_replacement_receipt_requires_reading_both_discs_and_original_pin(self):
  from setup_messages import sign
  from wallet_preview import fingerprint
  f=self.fixture();ops=f.ops;ops.verified_replacements={};old=f.archive;new='8'*64;image='9'*64;ids=sorted(ops.archives.catalogs[old]);envelope=sign(f.store,{'version':1,'event':'replacement_verified','archive_id':new,'image_sha256':image,'readback_verified':True,'archive_members':ids,'replacements':[{'archive_id':old,'old_policies_retained':True,'readback_verified':True,'image_sha256':image,'members':ids}]});p={'kind':'destroy_disc','version':1,'nonce':'7'*64,'archive_id':old,'label':'Old disc','replacement_image_sha256':image,'replacement_receipt':envelope};p['request_id']=digest(p)
  with self.assertRaisesRegex(ValueError,'Read the original and replacement'):Operations.destruction_proof(ops,p)
  ops.archives.catalogs[new]=copy.deepcopy(ops.archives.catalogs[old]);proof=Operations.destruction_proof(ops,p);self.assertTrue(proof['creator_confirmation_required']);ops.store.receive(p);ops.destruction_proof=lambda task:Operations.destruction_proof(ops,task)
  with self.assertRaisesRegex(ValueError,'fingerprint'):Operations.destroyed(ops,digest(p),True)
  Operations.destroyed(ops,digest(p),True,fingerprint(envelope['public_key']));self.assertIn(digest(p),ops.store.read()['completed'])

class ProtectedCancellationAPI(unittest.TestCase):
 def setUp(self):
  import test_build13
  self.fixture=test_build13.TunnelOnlyAPI();self.fixture.setUp();self.addCleanup(self.fixture.tearDown);self.fixture.server.preview=False
 def test_all_new_public_actions_reach_protected_rpc_with_exact_fields(self):
  routes=[('cancel-archive-bind',{'id':'key','archive_id':'a'*64,'confirmed':True,'fingerprint':'SHA256:checked'},'archive.cancel_bind'),('cancel-archive-check',{'id':'key','confirmed':True,'fingerprint':''},'archive.cancel_check'),('cancel-archive-stage',{'id':'key','confirmed':True,'fingerprint':''},'archive.cancel_stage'),('cancel-archive-confirm',{'id':'key','confirmed':True,'no_disc':True,'destroyed_disc_count':0,'fingerprint':''},'archive.cancel_confirm'),('cancel-archive-confirm',{'id':'key','confirmed':True,'no_disc':False,'destroyed_disc_count':2,'fingerprint':'SHA256:checked'},'archive.cancel_confirm'),('retire-disc',{'id':'key','confirmed':True,'fingerprint':'SHA256:preserver','creator_fingerprint':'SHA256:creator'},'archive.retire_stage'),('destroy-retired-disc',{'id':'key','confirmed':True,'fingerprint':'SHA256:preserver','creator_fingerprint':'SHA256:creator'},'archive.retire_destroyed'),('destroy-disc',{'id':'key','confirmed':True,'creator_fingerprint':'SHA256:creator'},'archive.destroyed')]
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   for route,body,method in routes:
    with self.subTest(route=route,method=method):
     status,result=self.fixture.call('/api/authorise/'+route,body);self.assertEqual(status,200,result);self.assertEqual(call.call_args.args[0],method);self.assertEqual(list(call.call_args.args[1:]),list(body.values()))
   before=call.call_count;status,result=self.fixture.call('/api/authorise/cancel-archive-confirm',{'id':'key','password':'must-never-be-accepted'});self.assertEqual(status,400);self.assertEqual(call.call_count,before)
