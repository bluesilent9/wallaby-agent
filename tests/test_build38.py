"""Idle disc waits permit public queries, never closure or private RPC."""
import tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store
from secure_worker import Workspace
from wallet_setup import secret_dialog

class IdleDiscReads(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);w=Workspace.__new__(Workspace);self.w=w;w.store=Store(Path(self.tmp.name)/'state');w.setup=SimpleNamespace(sessions={'setup':{'phase':'awaiting_disc'}},burner=SimpleNamespace(thread=None));w.archive_ops=SimpleNamespace(jobs={},busy=lambda:bool(w.archive_ops.jobs));w.archives=SimpleNamespace(reading=False);w.transfer=SimpleNamespace(sending=False);w.lock=threading.RLock();w.configure=lambda env:None;w.closing=False;w.ops=SimpleNamespace(core=Mock());w.ops.core.call.return_value={'result':{'chain':'regtest'}}
 def query(self,method='getblockchaininfo'):
  with patch('secure_worker.enforce'):return self.w.dispatch('core.public',['fixture',method,[],None,30],{})
 def test_idle_setup_and_staged_archive_allow_only_public_queries_but_block_close(self):
  self.assertTrue(self.w.busy());self.assertFalse(self.w.busy(public_reads=True));self.assertIn('result',self.query())
  self.w.archive_ops.jobs={'backup':{'phase':'queued'}};self.assertFalse(self.w.busy(public_reads=True));self.assertIn('result',self.query())
  with self.assertRaisesRegex(ValueError,'Finish active wallet'):self.w.begin_close()
  with self.assertRaises(ValueError):self.query('walletpassphrase')
 def test_generation_installation_capture_failure_reading_and_writing_still_block_queries(self):
  for phase in ('generating','contributed','installing','error'):
   self.w.setup.sessions['setup']['phase']=phase;self.assertEqual(self.query()['error']['code'],'synchronisation_busy')
  self.w.setup.sessions['setup']['phase']='awaiting_disc'
  for phase in ('capturing','error','discarding'):
   self.w.archive_ops.jobs={'backup':{'phase':phase}};self.assertEqual(self.query()['error']['code'],'synchronisation_busy')
  self.w.archive_ops.jobs={};self.w.archives.reading=True;self.assertIn('error',self.query());self.w.archives.reading=False
  self.w.setup.burner.thread=Mock();self.w.setup.burner.thread.is_alive.return_value=True;self.assertIn('error',self.query())
 def test_pending_cleanup_transfer_and_history_guards_are_unchanged(self):
  for kind in ('destroy_disc','archive_cancel','builder_cancel'):
   with self.w.store.edit() as s:s['pending']={'task':{'proposal':{'kind':kind},'state':'pending'}}
   self.assertIn('error',self.query())
  with self.w.store.edit() as s:s['pending']={}
  for key,value in [('setup_active','setup'),('active_transfer','transfer'),('sync_batch',{'ids':['a']}),('history_jobs',{'history':{}}),('recovery',{'state':'downloading'})]:
   with self.w.store.edit() as s:s[key]=value
   self.assertIn('error',self.query())
   with self.w.store.edit() as s:s.pop(key)

class ConfirmationPrompts(unittest.TestCase):
 def test_kdialog_and_zenity_confirmation_explicitly_request_retyping(self):
  for program in ('kdialog','zenity'):
   seen=[]
   def available(name):return '/usr/bin/'+name if name==program else None
   def ask(command,**kwargs):seen.append(command);return SimpleNamespace(returncode=0,stdout=b'fixture-passphrase\n')
   with patch('wallet_setup.shutil.which',side_effect=available),patch('wallet_setup.subprocess.run',side_effect=ask):self.assertEqual(secret_dialog('Signing role: Archive alpha',{},confirm=True),'fixture-passphrase')
   first=' '.join(seen[0]);second=' '.join(seen[1]);self.assertNotIn('Retype',first);self.assertIn('Retype the passphrase to confirm.',second);self.assertIn('Archive alpha',first);self.assertIn('Archive alpha',second)
 def test_mismatch_still_refuses_confirmation(self):
  with patch('wallet_setup.shutil.which',return_value='/usr/bin/kdialog'),patch('wallet_setup.subprocess.run',side_effect=[SimpleNamespace(returncode=0,stdout=b'first\n'),SimpleNamespace(returncode=0,stdout=b'second\n')]),self.assertRaisesRegex(ValueError,'did not match'):secret_dialog('Role',{},confirm=True)

class CleanupPreflight(unittest.TestCase):
 def test_read_only_helper_is_detected_without_unlinking_or_locking(self):
  import os
  from wallet_deletion import remove
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);wallet=base/'Generated';wallet.mkdir();db=wallet/'wallet.dat';db.write_bytes(b'fixture');a=wallet.stat();b=db.stat();request={'path':str(wallet),'directory':[a.st_dev,a.st_ino],'database':[b.st_dev,b.st_ino]}
   with patch('wallet_deletion.fcntl.lockf') as lock,patch('wallet_deletion.os.unlink') as unlink:
    self.assertEqual(remove(request,[base],check_only=True),{'ready':True});lock.assert_not_called();unlink.assert_not_called()
    with patch('wallet_deletion.os.access',return_value=False),self.assertRaises(PermissionError):remove(request,[base],check_only=True)
   self.assertEqual(db.read_bytes(),b'fixture')
 def test_retirement_gets_explicit_snap_exceptions_without_changing_export_policy(self):
  import importlib.util
  p=Path(__file__).resolve().parents[1]/'packaging/secure_start.py';spec=importlib.util.spec_from_file_location('start38',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'runtime_parent',side_effect=lambda p:p.mkdir(parents=True,exist_ok=True)):
   m.retirement_paths(1000,'/home/example',Path(d));text=(Path(d)/'wallaby-agent-retirement@1000.service.d/30-wallet-paths.conf').read_text()
   self.assertIn('snap/bitcoin-core/common/.bitcoin/wallets',text);self.assertEqual(text.count('ReadWritePaths='),10);self.assertNotIn('ReadWritePaths=\n',text)

class InterruptedCleanup(unittest.TestCase):
 def fixture(self):
  from test_build19 import RealCoreCancellation
  f=RealCoreCancellation();f.setUp();self.addCleanup(f.doCleanups);return f
 def test_failed_preflight_keeps_all_wallets_loaded_and_request_reviewable(self):
  from test_build19 import cancel
  from approval_store import digest
  from wallet_ops import rpc
  f=self.fixture();p=f.setup_wallet(True);binding=digest(p);names=set(f.setup.sessions[binding]['installed_wallets']);key=f.c.receive(cancel('wallet',[binding],[binding]));f.c.review(key)
  with patch('wallet_deletion.delete',side_effect=ValueError('Preflight failed')),self.assertRaises(ValueError):f.c.confirm(key,'delete')
  self.assertTrue(names<=set(rpc(f.core,'listwallets')));self.assertEqual(f.store.read()['pending'][key]['state'],'pending')
 def test_uncertain_attempt_reloads_exact_survivors_then_requires_new_review(self):
  from test_build19 import cancel
  from approval_store import digest
  from wallet_ops import rpc
  from wallet_deletion import remove
  f=self.fixture();p=f.setup_wallet(True);binding=digest(p);names=set(f.setup.sessions[binding]['installed_wallets']);key=f.c.receive(cancel('wallet',[binding],[binding]));f.c.review(key)
  def fail(request,check_only=False):
   if check_only:return remove(request,[Path(request['path']).parent],check_only=True)
   raise PermissionError(30,'read-only')
  with patch('wallet_deletion.delete',side_effect=fail),self.assertRaisesRegex(ValueError,'incomplete'):f.c.confirm(key,'delete')
  self.assertFalse(names&set(rpc(f.core,'listwallets')));self.assertEqual(f.store.read()['pending'][key]['state'],'attempted')
  with patch('wallet_deletion.delete',side_effect=lambda request,**kw:remove(request,[Path(request['path']).parent],**kw)):
   with self.assertRaises(ValueError):f.c.reconcile(key,False)
   f.c.reconcile(key,True);self.assertTrue(names<=set(rpc(f.core,'listwallets')))
   with self.assertRaisesRegex(ValueError,'Review'):f.c.confirm(key,'delete')
   f.c.review(key);f.c.confirm(key,'delete')
  self.assertNotIn(binding,f.setup.sessions);self.assertFalse(names&{w['name'] for w in rpc(f.core,'listwalletdir')['wallets']})

class CancellationReconciliationBoundary(unittest.TestCase):
 def test_endpoint_requires_explicit_public_confirmation_and_accepts_no_secrets(self):
  import test_build13
  f=test_build13.TunnelOnlyAPI();f.setUp();self.addCleanup(f.tearDown);f.server.preview=False
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'message':'Review again'}) as call:
   status,result=f.call('/api/authorise/reconcile-cancellation',{'id':'cancelled-build','confirmed':True});self.assertEqual(status,200,result);self.assertEqual(call.call_args.args,('cancel.reconcile','cancelled-build',True));before=call.call_count
   status,result=f.call('/api/authorise/reconcile-cancellation',{'id':'cancelled-build','confirmed':True,'password':'rejected'});self.assertEqual(status,400);self.assertEqual(call.call_count,before)

class AssetRoutes(unittest.TestCase):
 def test_every_page_script_is_served_by_the_actual_http_handler(self):
  import http.client,re,test_build13
  f=test_build13.TunnelOnlyAPI();f.setUp();self.addCleanup(f.tearDown)
  html=(Path(__file__).resolve().parents[1]/'web/index.html').read_text()
  for path in re.findall(r'<script src="([^"]+)"',html):
   conn=http.client.HTTPConnection('127.0.0.1',f.server.server_port);conn.request('GET',path);response=conn.getresponse();raw=response.read();self.assertEqual(response.status,200,path);self.assertIn('javascript',response.getheader('Content-Type'));self.assertTrue(raw);conn.close()
