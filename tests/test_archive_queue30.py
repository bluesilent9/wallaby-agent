"""Accumulating archive approvals, subset completion and safe local queue controls."""
import copy,hashlib,tempfile,time,unittest,os,sys,json,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from approval_store import Store,digest
from archive_operations import Operations
from archive_requests import snapshot
from disc_backup import Burner
from regtest_support import Regtest
from wallet_ops import rpc

class ArchiveQueue(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'store')
  self.burner=Burner(self.root/'burns',lambda key,image:self.ops.complete(key,image))
  self.setup=SimpleNamespace(burner=self.burner);self.ops=Operations(self.core,self.store,self.setup,SimpleNamespace(loaded={},catalogs={}),lambda:None);self.tasks=[];self.revision=0
 def add(self,name):
  rpc(self.core,'createwallet',{'wallet_name':name});rpc(self.core,'getnewaddress',['Label '+name],'{}'.format(name));rpc(self.core,'encryptwallet',['fixture-archive-passphrase'],name)
  raw=rpc(self.core,'listdescriptors',[False],name);p={'kind':'archive_wallet','version':1,'nonce':digest(name),'wallet':name,'public_wallet':raw,'related_policies':[],'require_local_authorisation':True};p['request_id']=digest(p);self.tasks.append(p);self.offer();return digest(p)
 def offer(self):
  self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':copy.deepcopy(self.tasks)})
 def stage(self,key):self.ops.review(key);self.ops.approve(key);self.assertTrue((self.ops.jobs[key]['folder']/'wallet.dat').is_file())
 def pack(self,root,wallets,recovery,password):
  # Core backups above are real. Optical hardware alone is simulated here.
  self.packed_names=[row['name'] for row in recovery['entries']];disc=root/'disc';disc.mkdir();(disc/'recovery.wallaby').write_bytes(b'encrypted-package-fixture'*100);return disc
 def write(self,device,source,total,progress,speed):
  data=b''.join(source);self.assertEqual(len(data),total);progress(total);return hashlib.sha256(data).hexdigest()
 def burn(self,fail=False,count=1):
  with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.pack',side_effect=self.pack),patch('disc_backup.image',side_effect=lambda disc,iso:iso.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=self.write),patch('disc_backup.readback',side_effect=ValueError('Corrupt readback') if fail else None):
   self.burner.start('/dev/sr0',True,'fixture',count);self.burner.thread.join(10);self.assertFalse(self.burner.thread.is_alive());self.assertNotEqual(self.burner.job['phase'],'error',self.burner.job['message'])
 def dashboard(self,p,receipt):
  source=os.environ.get('WALLABY_TEST_DASHBOARD_ARCHIVE_SRC')
  if not source:return
  run=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('dashboard_archive_result_probe.py')),source],input=json.dumps({'request':p,'receipt':receipt}),text=True,capture_output=True,timeout=30)
  self.assertEqual(run.returncode,0,run.stderr);print('Dashboard/Agent archive outcome interoperability:',run.stdout.strip(),flush=True)
 def test_later_requests_subset_verified_completion_and_unselected_survive(self):
  first=self.add('First');self.stage(first);second=self.add('Second');third=self.add('Third');self.stage(second);self.stage(third)
  self.assertEqual(len(self.burner.state()['queue']),3);self.burner.select([first,third]);self.burn(count=2)
  self.assertEqual(self.burner.job['phase'],'awaiting_disc');self.assertEqual(set(self.store.read()['pending']),{first,second,third})
  with self.assertRaisesRegex(ValueError,'unused staged'):self.ops.delete(first)
  self.burn(count=2);self.assertEqual(self.burner.job['phase'],'complete');self.assertEqual(set(self.packed_names),{'First','Third'})
  self.assertEqual(set(self.store.read()['pending']),{second});self.assertEqual(set(self.store.read()['completed']),{first,third});self.assertTrue((self.ops.jobs[second]['folder']/'wallet.dat').is_file())
  results=[i['payload'] for i in self.store.read()['outbox'].values() if i['kind']=='archive_queue_result' and i['payload']['status']=='complete'];self.assertEqual({r['request_id'] for r in results},{self.tasks[0]['request_id'],self.tasks[2]['request_id']});self.assertTrue(all(r['disc_count']==2 and r['readback_verified'] for r in results))
  self.dashboard(self.tasks[0],next(r for r in results if r['request_id']==self.tasks[0]['request_id']));self.offer();self.assertEqual(set(self.store.read()['pending']),{second});self.burner.job['finished']=time.time()-6;self.assertEqual(self.burner.state()['id'],second)
 def test_delete_staged_capture_reports_terminal_without_disabling_future_archives(self):
  first=self.add('First');second=self.add('Second');third=self.add('Third')
  for key in (first,second,third):self.stage(key)
  self.assertTrue(self.ops.review(first)['archive']['removable']);folder=self.ops.jobs[first]['folder'];self.ops.delete(first);self.assertFalse(folder.exists());self.assertNotIn(first,self.ops.jobs);self.assertEqual({r['id'] for r in self.burner.state()['queue']},{second,third})
  self.offer();self.assertNotIn(first,self.store.read()['pending']);receipt=self.store.read()['completed'][first]['result'];self.assertEqual(receipt['status'],'deleted');self.assertNotIn('readback_verified',receipt);self.dashboard(self.tasks[0],receipt)
  from setup_messages import verify
  self.assertEqual(verify(self.store,receipt['signed_receipt'],' '.join((self.store.root/'preview_identity.pub').read_text().split()[:2])),{k:v for k,v in receipt.items() if k!='signed_receipt'})
  again=copy.deepcopy(self.tasks[0]);again['nonce']='e'*64;again['request_id']=digest({k:v for k,v in again.items() if k!='request_id'});self.tasks[0]=again;self.offer();self.assertIn(digest(again),self.store.read()['pending'])
  self.assertTrue(self.ops.busy());self.assertFalse(self.store.read().get('archive_exclusions'))
 def test_failed_readback_retains_requests_and_refuses_discard_of_uncertain_data(self):
  first=self.add('First');second=self.add('Second');self.stage(first);self.stage(second);self.burner.select([first]);self.burn(fail=True)
  self.assertEqual(self.burner.job['phase'],'uncertain');self.assertEqual(set(self.store.read()['pending']),{first,second});self.assertFalse(self.store.read()['completed'])
  self.assertFalse(self.ops.review(first)['archive']['removable'])
  with self.assertRaisesRegex(ValueError,'unused staged'):self.ops.delete(first)
  # A different, never-written pending member can still be deliberately removed.
  self.ops.delete(second);self.assertEqual(set(self.store.read()['pending']),{first});self.assertEqual(self.burner.job['phase'],'uncertain');self.assertTrue((self.ops.jobs[first]['folder']/'wallet.dat').exists())

class LoadedWorkspaceClose(unittest.TestCase):
 def worker(self):
  from secure_worker import Workspace
  from unittest.mock import Mock
  import threading
  w=Workspace.__new__(Workspace);w.store=Mock();w.store.read.return_value={'pending':{},'outbox':{}};w.archives=SimpleNamespace(loaded={'one':{}},staged={'two':{}},reading=False);w.busy=Mock(return_value=False);w.closing=False;w.node_stop=threading.Event();w.node_status={'color':'green'};w.setup=SimpleNamespace(sessions={},burner=SimpleNamespace(state=lambda:{}),own_identity=lambda:{});w.transfer=SimpleNamespace(state=lambda:{});w.window_required=True;w.viewers=[];return w
 def test_idle_loaded_accounts_allow_x_close_and_supervised_ram_cleanup(self):
  w=self.worker();self.assertTrue(w.service_status()['busy']);w.begin_close();self.assertTrue(w.closing);self.assertTrue(w.node_stop.is_set());self.assertFalse(w.service_status()['busy'])
  from secure_supervisor import cleanup
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);(p/'disc-one').mkdir();(p/'disc-one'/'wallet.dat').write_bytes(b'fixture');(p/'disc-two').mkdir();(p/'disc-two'/'wallet.dat').write_bytes(b'fixture');(p/'supervisor.sock').touch()
   with patch('secure_supervisor.members',return_value=[]):cleanup(set(),p)
   self.assertEqual([i.name for i in p.iterdir()],['supervisor.sock'])
 def test_active_jobs_or_undelivered_signatures_still_prevent_archive_cleanup(self):
  w=self.worker();w.busy.return_value=True
  with self.assertRaisesRegex(ValueError,'wallet operations'):w.begin_close()
  self.assertFalse(w.closing);self.assertFalse(w.node_stop.is_set());w.busy.return_value=False;w.store.read.return_value['outbox']={'signed':{'kind':'partial_sign_result','payload':{'status':'signed'}}}
  with self.assertRaisesRegex(ValueError,'completed operation results'):w.begin_close()
  self.assertFalse(w.closing);self.assertTrue(w.archives.loaded)

if __name__=='__main__':unittest.main()
