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
import fixture_archive_queue as queue_fixture

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
 def cancelled_burn(self,ids,tasks,fail=False):
  self.burner.select(ids)
  def write(*args):
   self.revision+=1;snapshot(self.store,{'kind':'wallet_archive_queue','version':1,'queue_id':'f'*64,'revision':self.revision,'requests':tasks});self.ops.cancellations.observe(mark_only=True)
   if fail:raise ValueError('Simulated write failure')
   return self.write(*args)
  with patch('disc_backup.media',return_value={'speeds':['2'],'capacity_bytes':4*1024*1024}),patch('disc_backup.pack',side_effect=self.pack),patch('disc_backup.image',side_effect=lambda d,i:i.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=write),patch('disc_backup.readback',side_effect=ValueError('Simulated unreadable partial disc') if fail else None) as check:
   self.burner.start('/dev/sr0',True,'fixture');self.burner.thread.join(15);self.assertFalse(self.burner.thread.is_alive());self.assertEqual(check.call_count,1)

class ForeignDiscEvidence(unittest.TestCase):
 def fixture(self):
  import fixture_retirement
  from setup_messages import sign
  f=fixture_retirement.MixedDiscRetirement();f.setUp();self.addCleanup(f.doCleanups);fresh=Store(Path(f.tmp.name)/'new-agent');public=sign(fresh,{'purpose':'new Agent fixture'})['public_key'];f.ops.store=fresh;f.ops.setup.own_identity=lambda:{'public_key':public};fresh.receive(f.p);return f

class ProtectedCancellationAPI(unittest.TestCase):
 def setUp(self):
  import fixture_native_prompt
  self.fixture=fixture_native_prompt.TunnelOnlyAPI();self.fixture.setUp();self.addCleanup(self.fixture.tearDown);self.fixture.server.preview=False
