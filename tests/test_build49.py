"""Regression: refreshing a combined disc must not include its unselected next role."""
import hashlib,tempfile,unittest,os,time
from pathlib import Path
from unittest.mock import patch,Mock
from disc_backup import Burner,readback

class Readback(unittest.TestCase):
 def track(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)/'track';p.write_bytes(os.urandom(128*1024));return p,hashlib.sha256(p.read_bytes()).hexdigest()
 def test_initial_empty_read_reopens_then_compares_entire_track(self):
  p,sha=self.track();original=os.readv;calls=0;progress=[]
  def transient(fd,views):
   nonlocal calls
   calls+=1
   return 0 if calls==1 else original(fd,views)
  with patch('disc_backup.os.readv',side_effect=transient),patch('disc_backup.time.sleep'):readback(str(p),p.stat().st_size,sha,progress.append)
  self.assertEqual(calls,2);self.assertEqual(progress[-1],p.stat().st_size)
 def test_partial_sector_aligned_reads_continue_without_skipping_bytes(self):
  p,sha=self.track();original=os.readv;progress=[]
  def partial(fd,views):
   view=views[0][:4096]
   try:return original(fd,[view])
   finally:view.release()
  with patch('disc_backup.os.readv',side_effect=partial):readback(str(p),p.stat().st_size,sha,progress.append)
  self.assertEqual(len(progress),32);self.assertEqual(progress[-1],p.stat().st_size)
 def test_wrong_full_track_checksum_is_not_success(self):
  p,sha=self.track()
  with self.assertRaisesRegex(ValueError,'checksum differs'):readback(str(p),p.stat().st_size,'0'*64)
 def test_error_after_first_sector_is_not_silently_retried_or_counted(self):
  p,sha=self.track();original=os.readv;calls=0;progress=[]
  def interrupted(fd,views):
   nonlocal calls
   calls+=1
   if calls>1:raise OSError(5,'dummy I/O failure')
   view=views[0][:4096]
   try:return original(fd,[view])
   finally:view.release()
  with patch('disc_backup.os.readv',side_effect=interrupted),patch('disc_backup.time.sleep') as sleep,self.assertRaisesRegex(ValueError,'byte 4096'):
   readback(str(p),p.stat().st_size,sha,progress.append)
  self.assertEqual(progress,[4096]);sleep.assert_not_called()

class VerifyAgain(unittest.TestCase):
 def failed(self):
  from test_build47 import DiscStages
  f=DiscStages();self.addCleanup(f.doCleanups);b,callback,_=f.execute('verification');return b,callback
 def test_same_disc_retry_only_reads_then_completes_original_job(self):
  b,callback=self.failed();key=b.job['id']
  with patch('disc_backup.readback',side_effect=lambda d,n,s,p:p(n)),patch('disc_backup.write_stream') as writer:
   b.verify_written(key);b.thread.join(5)
  writer.assert_not_called();self.assertEqual(b.job['phase'],'complete',b.job['message']);self.assertEqual(b.job['discs_verified'],1);callback.assert_called_once_with(key,'c'*64)
 def test_wrong_disc_keeps_ram_and_does_not_issue_receipt(self):
  b,callback=self.failed()
  with patch('disc_backup.readback',side_effect=ValueError('fixture mismatch')),patch('disc_backup.write_stream') as writer:
   b.verify_written(b.job['id']);b.thread.join(5)
  self.assertEqual(b.job['phase'],'uncertain');self.assertEqual(b.job['discs_verified'],0);self.assertTrue((b.root/b.job['id']).is_dir());callback.assert_not_called();writer.assert_not_called()
 def test_stale_job_cancelled_or_active_verification_is_refused(self):
  b,_=self.failed()
  with self.assertRaises(ValueError):b.verify_written('wrong job')
  b.job['_cancel_pending']=True
  with self.assertRaises(ValueError):b.verify_written(b.job['id'])

class QueueRefresh(unittest.TestCase):
 def test_thousands_of_polls_keep_next_wallet_pending_and_fixed_members_unchanged(self):
  from test_build8 import paired
  from test_build23 import task
  from archive_format import bundle
  from approval_store import digest
  with tempfile.TemporaryDirectory() as tmp:
   b=Burner(tmp,Mock());rows=[]
   for i in range(3):
    r=task(paired()['public_wallet'])
    # Node-wallet recovery records are the actual bundle inputs, not Dashboard tasks.
    recovery={'version':1,'kind':'node_wallet','chain':'regtest','name':'wallet '+str(i),'policy_hash':digest(r['public_wallet']),'public_wallet':r['public_wallet'],'labels':{}}
    # Distinct wallet identities use distinct descriptors from paired().
    rows.append((str(i)*64,{'wallet':str(i)+'.dat'},recovery))
   # A minimal compiled queue reproduces the status alias without requiring encryption.
   b.authorise(*rows[0]);b.job['_members']=list(rows[:2]);b.pending=[rows[2]]
   for _ in range(2000):self.assertEqual(len(b.state()['queue']),3)
   self.assertEqual(b.job['_members'],rows[:2]);self.assertEqual(b.pending,[rows[2]])

class PollingThreeAgentDiscs(unittest.TestCase):
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
   members=tuple(b.job['_members']);pending=tuple(b.pending)
   for _ in range(2000):b.state()
   self.assertEqual(tuple(b.job['_members']),members);self.assertEqual(tuple(b.pending),pending);self.assertEqual(len(b.state()['queue']),len(members)+len(pending))
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
