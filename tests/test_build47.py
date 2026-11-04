"""Disc stage outcomes and queue safety with simulated optical I/O."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from disc_backup import Burner,writer_bytes

class DiscStages(unittest.TestCase):
 def execute(self,failure=None):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);callback=Mock(side_effect=ValueError('completion fixture') if failure=='completion' else None)
  b=Burner(folder.name,callback);b.authorise('a'*64,{'wallet':'fixture.dat'},{'policy_hash':'b'*64,'name':'Treasury'})
  seen=[]
  def pack(root,*args):
   seen.append((b.job['phase'],b.job['preparation_percent']))
   if failure=='preparation':raise ValueError('preparation fixture')
   disc=root/'disc';disc.mkdir();(disc/'recovery.wallaby').write_bytes(b'fixture encrypted package'*20);return disc
  def write(device,source,total,progress,speed):
   seen.append((b.job['phase'],b.job['written_bytes']));self.assertEqual(b.job['preparation_percent'],100)
   if failure=='burn':raise ValueError('writer fixture')
   progress(total//2);seen.append((b.job['phase'],b.job['written_bytes']));progress(total);return 'c'*64
  def read(device,total,sha,progress):
   seen.append((b.job['phase'],b.job['verified_bytes']))
   if failure=='verification':raise ValueError('verification fixture')
   progress(total//2);seen.append((b.job['phase'],b.job['verified_bytes']));progress(total)
  with patch('disc_backup.pack',side_effect=pack),patch('disc_backup.image',side_effect=lambda d,p:p.write_bytes(b'iso')),patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.write_stream',side_effect=write),patch('disc_backup.readback',side_effect=read):
   b.start('/dev/sr0',True,'fixture-backup-password');b.thread.join(5)
  self.assertFalse(b.thread.is_alive());return b,callback,seen
 def test_success_resets_each_stage_and_retains_outcome_after_job_advances(self):
  b,callback,seen=self.execute();self.assertEqual(seen[0],('preparing',0));self.assertIn(('burning',0),seen);self.assertIn(('verifying',0),seen);self.assertEqual(b.job['phase'],'complete');callback.assert_called_once();self.assertEqual(b.outcomes[-1]['kind'],'verified')
  b.job['finished']=time.time()-10;state=b.state();self.assertNotIn('id',state);self.assertEqual(state['outcomes'][-1]['kind'],'verified')
 def test_burn_failure_has_own_outcome_and_keeps_job_without_completing(self):
  b,callback,_=self.execute('burn');self.assertEqual(b.job['phase'],'uncertain');self.assertEqual(b.outcomes[-1]['kind'],'burn_failed');callback.assert_not_called()
 def test_verification_failure_does_not_claim_success_or_complete_archive(self):
  b,callback,_=self.execute('verification');self.assertEqual(b.outcomes[-1]['kind'],'verification_failed');self.assertEqual(b.job['failed_stage'],'verifying');self.assertEqual(b.job['discs_verified'],0);callback.assert_not_called()
 def test_preparation_failure_does_not_claim_any_disc_was_written(self):
  b,callback,_=self.execute('preparation');self.assertEqual(b.outcomes[-1]['kind'],'preparation_failed');self.assertFalse(b.job.get('_write_started'));callback.assert_not_called()
 def test_completion_failure_is_separate_from_physical_verification(self):
  b,callback,_=self.execute('completion');self.assertEqual([r['kind'] for r in b.outcomes],['verified','completion_failed']);self.assertEqual(b.job['phase'],'completion_uncertain')
 def test_only_writer_report_counts_as_physical_progress(self):
  total=25*1024**3;self.assertEqual(writer_bytes('Track 01: 12 of 23842 MB written (fifo 99%)',total),12*1024**2);self.assertIsNone(writer_bytes('Writing to pipe: 999 MB',total));self.assertIsNone(writer_bytes('sensitive-looking arbitrary text',total))
 def test_unapproved_archive_snapshot_never_enters_burn_queue(self):
  from approval_store import Store,digest
  from archive_requests import snapshot
  from test_build8 import paired
  from test_build23 import task,queue
  with tempfile.TemporaryDirectory() as folder:
   store=Store(Path(folder)/'state');b=Burner(Path(folder)/'jobs',Mock());p=task(paired()['public_wallet']);snapshot(store,queue([p]));self.assertEqual(store.read()['pending'][digest(p)]['state'],'pending');self.assertIsNone(b.job);self.assertEqual(b.state()['queue'],[])

class DiscStatus(unittest.TestCase):
 def check(self,text,code=0):
  import os,stat
  from types import SimpleNamespace
  from disc_backup import disc_status
  with patch('disc_backup.shutil.which',return_value='/usr/bin/xorriso'),patch('disc_backup.os.stat',return_value=SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(11,0))),patch('disc_backup.subprocess.run',return_value=SimpleNamespace(returncode=code,stdout=text.encode(),stderr=b'')) as run:
   result=disc_status('/dev/sr0')
  command=run.call_args.args[0];self.assertIn('-indev',command);self.assertIn('-toc',command);self.assertNotIn('-outdev',command);self.assertNotIn('-as',command);self.assertTrue(result['read_only']);return result
 def test_blank_and_written_are_different_and_do_not_verify_a_backup(self):
  self.assertEqual(self.check('Media current : BD-R\nMedia status : is blank')['status'],'blank')
  result=self.check('Media current : BD-R\nMedia status : is written , is closed');self.assertEqual(result['status'],'written');self.assertIn('does not verify',result['message'])
 def test_empty_drive_unknown_and_failed_probe_do_not_claim_blank(self):
  self.assertEqual(self.check('No medium present',5)['status'],'no_disc');self.assertEqual(self.check('Cannot read medium',5)['status'],'unknown');self.assertEqual(self.check('Media status : is blank',5)['status'],'unknown')
 def test_non_optical_or_injected_device_is_refused_before_probe(self):
  from disc_backup import disc_status
  with patch('disc_backup.shutil.which',return_value='/usr/bin/xorriso'),patch('disc_backup.subprocess.run') as run:
   for value in ('/dev/sda','/dev/sr0;touch /tmp/unwanted','stdio:/tmp/file'):
    with self.assertRaises(ValueError):disc_status(value)
  run.assert_not_called()

class MemoryBudget(unittest.TestCase):
 def test_cgroup_shortfall_is_rejected_before_encryption_not_by_raising_limit(self):
  from disc_backup import memory_budget
  def read(path,*a,**k):return {'/proc/self/cgroup':'0::/fixture','/sys/fs/cgroup/fixture/memory.max':'1000','/sys/fs/cgroup/fixture/memory.current':'900'}[str(path)]
  with patch('disc_backup.Path.read_text',read):
   memory_budget(50)
   with self.assertRaisesRegex(ValueError,'memory is too full'):memory_budget(200)
 def test_unknown_budget_stops_preparation_without_disk_fallback(self):
  from disc_backup import memory_budget
  with patch('disc_backup.Path.read_text',side_effect=OSError('fixture')),self.assertRaisesRegex(ValueError,'could not be checked'):memory_budget(100)

class OpticalAdmission(unittest.TestCase):
 def test_status_probe_does_not_contend_with_active_writer_and_is_read_only_when_idle(self):
  from test_build38 import IdleDiscReads
  f=IdleDiscReads();f.setUp();self.addCleanup(f.doCleanups);w=f.w
  from types import SimpleNamespace
  w.setup.burner.thread=SimpleNamespace(is_alive=lambda:True)
  with patch('secure_worker.enforce'),patch('disc_backup.disc_status',return_value={'status':'blank','read_only':True}) as status:
   with self.assertRaisesRegex(ValueError,'Another optical'):w.dispatch('disc.status',['/dev/sr0'],{})
   status.assert_not_called();w.setup.burner.thread=None
   self.assertEqual(w.dispatch('disc.status',['/dev/sr0'],{})['status'],'blank');status.assert_called_once_with('/dev/sr0')
 def test_new_burn_waits_for_optical_read(self):
  from test_build38 import IdleDiscReads
  f=IdleDiscReads();f.setUp();self.addCleanup(f.doCleanups);f.w.archives.reading=True
  with patch('secure_worker.enforce'),self.assertRaisesRegex(ValueError,'optical read'):f.w.dispatch('disc.burn',['/dev/sr0',True,1,'slowest'],{})


class RepeatedArchiveDiscs(unittest.TestCase):
 def test_three_agents_archive_can_be_requested_again_after_first_signer_disc_verifies(self):
  import hashlib
  from types import SimpleNamespace
  from test_build41 import CombinedCluster,PASSWORD
  from test_build23 import task
  from archive_operations import Operations
  from approval_store import digest
  from wallet_ops import rpc
  from disc_backup import write_stream,readback
  f=CombinedCluster();f.setUp();self.addCleanup(f.doCleanups);a=f.agents[1];core=f.nodes[1].core
  rpc(core,'createwallet',{'wallet_name':'David SMSF','passphrase':PASSWORD})
  ops=Operations(core,a.store,a,SimpleNamespace(loaded={},catalogs={}),lambda:None)
  raw=rpc(core,'listdescriptors',[False],'David SMSF');requests=[];tracks=[]
  signer_ids=[f.h+'-'+hashlib.sha256(r['id'].encode()).hexdigest()[:12] for r in f.p['cosigners'][:2]]
  def write(device,source,total,progress,speed):
   target=Path(f.tmp.name)/('track-'+str(len(tracks)));tracks.append(target);return write_stream('stdio:'+str(target),source,total,progress,speed)
  def verify(device,total,sha,progress):return readback(str(tracks[-1]),total,sha,progress)
  b=a.burner
  for index in range(2):
   p=task(raw);key=digest(p);requests.append(key);a.store.receive(p);ops.review(key);ops.approve(key)
   self.assertEqual(len(b.state()['queue']),3-index);b.select([signer_ids[index],key])
   with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':12*1024*1024}),patch('disc_backup.write_stream',side_effect=write),patch('disc_backup.readback',side_effect=verify):
    b.start('/dev/sr0',True,'fixture-backup-password');b.thread.join(30)
   self.assertFalse(b.thread.is_alive());self.assertEqual(b.job['phase'],'complete',b.job.get('message'));self.assertEqual(ops.jobs[key]['phase'],'complete');self.assertFalse(ops.jobs[key]['folder'].exists())
   completed=a.store.read()['completed'][key]['result'];self.assertEqual(completed['status'],'complete');self.assertTrue(completed['readback_verified'])
   self.assertFalse(a.store.receive(p),'The completed request cannot capture or burn again by replay')
   if index==0:
    self.assertEqual(a.sessions[f.h]['phase'],'awaiting_disc');self.assertEqual(len(a.sessions[f.h]['discs_remaining']),1);b.job['finished']=time.time()-10;self.assertEqual(len(b.state()['queue']),1)
  self.assertNotEqual(*requests);self.assertEqual(a.sessions[f.h]['phase'],'complete');self.assertFalse(a.sessions[f.h]['discs_remaining']);self.assertEqual(len(tracks),2);self.assertEqual(len(b.completed_sets),2)
  first=a.store.read()['completed'][requests[0]]['result'];second=a.store.read()['completed'][requests[1]]['result'];self.assertNotEqual(first['archive_id'],second['archive_id']);self.assertTrue(rpc(core,'getwalletinfo',[],'David SMSF')['private_keys_enabled'])
