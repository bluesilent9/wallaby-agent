"""Real Core rename failure checkpoints; no wallet byte copying in production."""
import copy,unittest,os,socket,struct,json,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from wallet_ops import rpc
from wallet_rename import move,RenameFailure
from approval_store import digest
from rename_requests import snapshot
import test_build25 as fixture

class RenameRecovery(unittest.TestCase):
 def setUp(self):
  self.f=fixture.RealRenames();self.f.setUp();self.addCleanup(self.f.doCleanups);self.f.addCleanup(self.f.cleanup)
  rpc(self.f.core,'createwallet',{'wallet_name':'treasury','passphrase':'fixture-only password'})
  self.p=fixture.task(rpc(self.f.core,'listdescriptors',[False],'treasury'),'Treasury (2022 - 2026)');snapshot(self.f.store,fixture.queue([self.p]));self.key=digest(self.p)
  with patch('wallet_deletion.bases',return_value=[self.f.base]):self.f.renames.review(self.key)
 def approve(self,fn):
  with patch('wallet_deletion.bases',return_value=[self.f.base]),patch('wallet_rename.rename',side_effect=fn):return self.f.renames.approve(self.key)
 def helper(self,source,new,**kw):return move({'source':source,'new_name':new},[self.f.base],**kw)
 def test_preflight_failure_keeps_wallet_loaded_and_request_unstarted(self):
  with self.assertRaisesRegex(ValueError,'remains loaded'):self.approve(lambda *a,**kw:(_ for _ in ()).throw(RenameFailure('permission_denied','Fixture inaccessible helper')))
  self.assertIn('treasury',rpc(self.f.core,'listwallets'));self.assertEqual(self.f.store.read()['pending'][self.key]['state'],'pending');self.f.renames.deny(self.key)
 def test_failed_move_restores_original_and_startup_without_repeating_move(self):
  calls=[]
  def helper(source,new,**kw):
   calls.append(bool(kw.get('check_only')))
   if kw.get('check_only'):return self.helper(source,new,**kw)
   raise RenameFailure('read_only','Fixture helper filesystem is read-only')
  with self.assertRaisesRegex(ValueError,'reloaded and verified'):self.approve(helper)
  self.assertEqual(calls,[True,False]);self.assertIn('treasury',rpc(self.f.core,'listwallets'));self.assertEqual(self.f.store.read()['pending'][self.key]['state'],'pending');self.assertTrue((self.f.base/'treasury/wallet.dat').exists());self.assertFalse((self.f.base/self.p['new_name']).exists());self.f.renames.deny(self.key)
 def test_move_succeeded_reply_lost_reconciles_target_without_another_move(self):
  def helper(source,new,**kw):
   result=self.helper(source,new,**kw)
   if not kw.get('check_only'):raise RenameFailure('worker_closed','Fixture reply lost after atomic move')
   return result
  with self.assertRaisesRegex(ValueError,'Review and reconcile'):self.approve(helper)
  snapshot(self.f.store,fixture.queue([],2));shown=self.f.renames.review(self.key)['rename'];self.assertTrue(shown['withdrawn']);self.assertTrue(shown['applied']);self.assertFalse(shown['loaded'])
  with patch('wallet_rename.rename',side_effect=AssertionError('Rename must not replay')):self.f.renames.reconcile(self.key,True)
  self.assertIn(self.p['new_name'],rpc(self.f.core,'listwallets'));self.assertIn(self.key,self.f.store.read()['completed'])
 def test_failed_original_reload_can_be_reconciled_locally_after_core_recovers(self):
  real=rpc
  def call(core,method,*a,**kw):
   if method=='loadwallet':raise ValueError('Fixture Core temporarily busy')
   return real(core,method,*a,**kw)
  def helper(source,new,**kw):
   if kw.get('check_only'):return self.helper(source,new,**kw)
   raise RenameFailure('helper_failure','Fixture rename refused')
  with patch('rename_requests.rpc',side_effect=call),self.assertRaisesRegex(ValueError,'Review and reconcile'):self.approve(helper)
  self.assertFalse(self.f.renames.review(self.key)['rename']['applied']);self.f.renames.reconcile(self.key,True);self.assertIn('treasury',rpc(self.f.core,'listwallets'));result=self.f.store.read()['completed'][self.key]['result'];self.assertFalse(result['outcome_uncertain']);self.assertTrue(result['original_wallet_restored'])
 def test_unexpected_file_is_refused_before_unloading_and_collision_is_not_overwritten(self):
  (self.f.base/'treasury'/'unrecognised').write_text('fixture')
  with self.assertRaisesRegex(ValueError,'remains loaded'):self.approve(self.helper)
  self.assertIn('treasury',rpc(self.f.core,'listwallets'))
 def test_success_with_parentheses_and_spaces_keeps_the_exact_database_inode(self):
  inode=(self.f.base/'treasury/wallet.dat').stat().st_ino;self.approve(self.helper)
  self.assertEqual((self.f.base/self.p['new_name']/'wallet.dat').stat().st_ino,inode);self.assertIn(self.p['new_name'],rpc(self.f.core,'listwallets'))

class HelperIPC(unittest.TestCase):
 setUp=RenameRecovery.setUp
 # Exercise real framed Unix I/O with the same real-Core fixture.
 # Only cgroup attribution is simulated; helper/client and Core stay real.
 def server(self):
  import socketserver,wallet_rename
  path=self.f.root/'rename.sock';read=Path.read_text
  def cgroup(p,*args,**kw):
   if p==Path('/proc',str(os.getpid()),'cgroup'):return '0::/system.slice/system-wallaby-agent-secure.slice/wallaby-agent-secure@'+str(os.getuid())+'.service\n'
   return read(p,*args,**kw)
  patches=[patch('wallet_rename.socket_path',return_value=path),patch('wallet_rename.bases',return_value=[self.f.base]),patch.object(Path,'read_text',cgroup),patch('wallet_deletion.bases',return_value=[self.f.base])]
  for p in patches:p.start();self.addCleanup(p.stop)
  server=socketserver.UnixStreamServer(str(path),wallet_rename.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
 def test_real_socket_preflight_move_and_core_reload(self):
  self.server();self.f.renames.approve(self.key);self.assertIn(self.p['new_name'],rpc(self.f.core,'listwallets'));self.assertIn(self.key,self.f.store.read()['completed'])
 def test_real_socket_preflight_permission_failure_never_unloads(self):
  self.server()
  with patch('wallet_rename.os.access',return_value=False),self.assertRaisesRegex(ValueError,'remains loaded'):self.f.renames.approve(self.key)
  self.assertIn('treasury',rpc(self.f.core,'listwallets'));self.assertEqual(self.f.store.read()['pending'][self.key]['state'],'pending')

class UnitConfiguration(unittest.TestCase):
 def load(self):
  import importlib.util
  path=Path(__file__).resolve().parents[1]/'packaging/secure_start.py';spec=importlib.util.spec_from_file_location('start32',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_only_explicit_supported_wallet_roots_are_writable(self):
  m=self.load()
  with tempfile.TemporaryDirectory() as d,patch.object(m,'runtime_parent',side_effect=lambda p:p.mkdir(parents=True,exist_ok=True)):
   m.rename_paths(1000,'/home/dave',Path(d));text=(Path(d)/'wallaby-agent-renames@1000.service.d/30-wallet-paths.conf').read_text();lines=text.splitlines();self.assertEqual(len([v for v in lines if v.startswith('ReadWritePaths="')]),10)
   self.assertIn('ReadWritePaths="-/home/dave/snap/bitcoin-core/common/.bitcoin/wallets"',lines);self.assertIn('ReadWritePaths="-/home/dave/.bitcoin/regtest/wallets"',lines);self.assertNotIn('ReadWritePaths="-/home"',lines)
  source=(Path(__file__).resolve().parents[1]/'packaging/build.py').read_text();body=source.split("put('usr/lib/systemd/system/wallaby-agent-renames@.service','''",1)[1].split("''')",1)[0]
  self.assertIn('ProtectSystem=strict\nProtectHome=read-only',body);self.assertNotIn('ReadWritePaths=-/home',body)
  body=source.split("put('usr/lib/systemd/system/wallaby-agent-secure@.service','''",1)[1].split("''')",1)[0];self.assertIn('ProtectHome=read-only',body);self.assertIn('ReadWritePaths=/run/wallaby-agent-secure/%i/ram',body)
 def test_untrusted_home_control_characters_and_symlink_dropin_are_refused(self):
  m=self.load()
  with self.assertRaises(SystemExit):m.rename_paths(1000,'/home/dave\nReadWritePaths=/')
  with tempfile.TemporaryDirectory() as d,patch.object(m,'runtime_parent',side_effect=lambda p:p.mkdir(parents=True,exist_ok=True)):
   folder=Path(d)/'wallaby-agent-renames@1000.service.d';folder.mkdir();target=Path(d)/'untouched';target.write_text('unchanged');(folder/'30-wallet-paths.conf').symlink_to(target)
   with self.assertRaises(SystemExit):m.rename_paths(1000,'/home/dave',Path(d))
   self.assertEqual(target.read_text(),'unchanged')

class ReconciliationAPI(unittest.TestCase):
 def test_reconcile_accepts_only_explicit_public_local_confirmation(self):
  import test_build13
  f=test_build13.TunnelOnlyAPI();f.setUp();self.addCleanup(f.tearDown);f.server.preview=False
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   status,result=f.call('/api/authorise/reconcile-rename',{'id':'interrupted','confirmed':True});self.assertEqual(status,200,result);self.assertEqual(call.call_args.args,('rename.reconcile','interrupted',True));before=call.call_count
   status,result=f.call('/api/authorise/reconcile-rename',{'id':'interrupted','confirmed':True,'password':'not-accepted'});self.assertEqual(status,400);self.assertEqual(call.call_count,before)

class WithdrawnAttemptVisibility(unittest.TestCase):
 def test_cancelled_dashboard_request_remains_visible_until_local_reconciliation(self):
  from types import SimpleNamespace
  from secure_worker import Workspace
  w=Workspace.__new__(Workspace);saved={'pending':{'key':{'proposal':{'kind':'wallet_rename','wallet':'treasury'},'state':'attempted','withdrawn':True}},'denied':{},'outbox':{},'sync':''}
  w.store=SimpleNamespace(read=lambda:saved);w.node_status={'color':'green'};w.recovery_state=lambda:{};w.busy=lambda:True;w.archive_ops=None;w.transfer=SimpleNamespace(state=lambda:{'rows':[]});w.burn_state=lambda:{};w.archives=SimpleNamespace(state=lambda:{},loaded={},staged={});w.setup=SimpleNamespace(own_identity=lambda:{},sessions={},burner=SimpleNamespace(state=lambda:{}));w.window_required=True;w.viewers=[]
  with patch('secure_worker.enforce',return_value={}),patch('extinct_sync.obsolete_denials',return_value=[]):
   self.assertEqual(w.state()['pending'][0]['id'],'key');self.assertTrue(w.service_status()['has_approvals'])

class UpgradeConfiguration(unittest.TestCase):
 def load(self):
  import importlib.util
  path=Path(__file__).resolve().parents[1]/'packaging/configure_renames.py';spec=importlib.util.spec_from_file_location('configure32',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_unprivileged_invocation_cannot_configure_services(self):
  m=self.load()
  with patch.object(m.os,'geteuid',return_value=1000),patch.object(m.runpy,'run_path') as execute,self.assertRaises(SystemExit):m.configure()
  execute.assert_not_called()
 def test_upgrade_refreshes_only_prepared_root_owned_account_paths(self):
  from types import SimpleNamespace
  m=self.load();prepare=unittest.mock.Mock();original=Path.stat
  with tempfile.TemporaryDirectory() as d:
   runtime=Path(d)/'runtime';runtime.mkdir()
   for n in ('1000','999','9999'):(runtime/n).mkdir()
   (runtime/'1001').symlink_to(runtime/'1000')
   def stat(p,*a,**kw):
    value=original(p,*a,**kw)
    if p.parent==runtime:
     values=list(value);values[4]=0;return os.stat_result(values)
    return value
   def account(uid):
    if uid==1000:return SimpleNamespace(pw_dir='/home/prepared')
    raise KeyError(uid)
   with patch.object(m.os,'geteuid',return_value=0),patch.object(m.runpy,'run_path',return_value={'rename_paths':prepare}),patch.object(m.pwd,'getpwuid',side_effect=account),patch.object(Path,'stat',stat):m.configure(Path(d)/'secure-start',runtime)
   prepare.assert_called_once_with(1000,'/home/prepared')
