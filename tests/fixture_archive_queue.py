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
  self.assertEqual(run.returncode,0,run.stderr);print('Wallet Server/Agent archive outcome interoperability:',run.stdout.strip(),flush=True)

class LoadedWorkspaceClose(unittest.TestCase):
 def worker(self):
  from secure_worker import Workspace
  from unittest.mock import Mock
  import threading
  w=Workspace.__new__(Workspace);w.store=Mock();w.store.read.return_value={'pending':{},'outbox':{}};w.archives=SimpleNamespace(loaded={'one':{}},staged={'two':{}},reading=False);w.busy=Mock(return_value=False);w.closing=False;w.node_stop=threading.Event();w.node_status={'color':'green'};w.setup=SimpleNamespace(sessions={},burner=SimpleNamespace(state=lambda:{}),own_identity=lambda:{});w.transfer=SimpleNamespace(state=lambda:{});w.window_required=True;w.viewers=[];return w

if __name__=='__main__':unittest.main()
