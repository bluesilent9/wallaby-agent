"""Core lock probes may never write to a protected read-only home mount."""
import errno,fcntl,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store
from wallet_recovery import Recovery,lock_released
from node_recovery import Recovery as ConnectionRecovery
from diagnostics import ConnectionFailure
from secure_worker import Workspace


class ReadOnlyLock(unittest.TestCase):
    def test_existing_exclusive_core_lock_is_detected_using_only_read_access(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.lock';path.write_bytes(b'unchanged');before=path.stat().st_mtime_ns
            child=subprocess.Popen([sys.executable,'-c',"import fcntl,sys;f=open(sys.argv[1],'r+b');fcntl.lockf(f,fcntl.LOCK_EX);print('locked',flush=True);sys.stdin.read()",str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            self.addCleanup(lambda:child.kill() if child.poll() is None else None)
            self.assertEqual(child.stdout.readline().strip(),'locked')
            original=Path.open;modes=[]
            def readonly(p,mode='r',*args,**kw):
                if p==path:
                    modes.append(mode)
                    if any(v in mode for v in ('a','w','+')):raise OSError(errno.EROFS,'Read-only file system')
                return original(p,mode,*args,**kw)
            with patch('pathlib.Path.open',readonly):
                # Reproduce Build 79's failure after shutdown with no wallet data.
                with self.assertRaises(OSError) as old:readonly(path,'a')
                self.assertEqual(old.exception.errno,errno.EROFS);modes.clear()
                self.assertFalse(lock_released(folder))
                child.stdin.close();child.wait(timeout=5)
                self.assertTrue(lock_released(folder));self.assertEqual(modes,['rb','rb'])
            self.assertEqual(path.read_bytes(),b'unchanged');self.assertEqual(path.stat().st_mtime_ns,before);child.stdout.close()
    def test_absent_lock_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):lock_released(folder)
            self.assertFalse((Path(folder)/'.lock').exists())


class RestartGuard(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.folder=Path(tmp.name)
        self.store=Store(self.folder/'state');self.manager=Recovery(Mock(),self.store)
        with self.store.edit() as s:s['recovery']={'state':'starting'}
        (self.folder/'.lock').write_bytes(b'')
        self.launch={'pid':999999999,'started':'fixture','netdir':str(self.folder),'argv':['/usr/bin/snap','run','bitcoin-core.qt','-min'],'executable':'/snap/bitcoin-core/1/bitcoin-qt','cwd':str(self.folder),'env':{}}
    def test_actual_snap_launcher_is_checked_before_stopping_and_runs_independently(self):
        commands=[];methods=[]
        def run(command,**kw):commands.append(command);return Mock(returncode=0)
        def rpc(c,m,*a,**kw):methods.append(m);return {'chain':'main'}
        with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',side_effect=rpc),patch('wallet_recovery.subprocess.run',side_effect=run),patch('wallet_recovery.lock_released',return_value=True),patch.object(self.manager,'wait_rpc',return_value={'chain':'main'}):self.manager.restart(self.launch,['-reindex=1','-networkactive=0'])
        self.assertEqual(commands[1][commands[1].index('--')+1:],self.launch['argv']+['-version'])
        self.assertIn('--wait',commands[1]);self.assertIn('--collect',commands[1]);self.assertNotIn('--wait',commands[2])
        self.assertIn('--slice=app.slice',commands[2]);self.assertIn('--property=StandardError=journal',commands[2]);self.assertEqual(methods,['getblockchaininfo','stop'])
    def test_launcher_failure_or_missing_read_access_never_stops_core(self):
        for missing in (False,True):
            if missing:(self.folder/'.lock').unlink()
            def run(command,**kw):return Mock(returncode=1 if not missing and command[-1]=='-version' else 0)
            with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',return_value={'chain':'main'}) as rpc,patch('wallet_recovery.subprocess.run',side_effect=run),self.assertRaisesRegex(ValueError,'Core was not stopped'):self.manager.restart(self.launch,['-reindex=1'])
            self.assertEqual(rpc.call_count,1);self.assertEqual(self.manager.restart_deadline,0)
    def test_late_read_error_reports_no_launch_and_does_not_retry(self):
        commands=[]
        with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',return_value={'chain':'main'}),patch('wallet_recovery.subprocess.run',side_effect=lambda cmd,**kw:(commands.append(cmd) or Mock(returncode=0))),patch('wallet_recovery.lock_released',side_effect=OSError(errno.EACCES,'fixture')),self.assertRaisesRegex(ValueError,'No restart was launched'):self.manager.restart(self.launch,['-reindex=1'])
        self.assertEqual(len(commands),2);self.assertEqual(self.manager.restart_deadline,0)


class RestartBudget(unittest.TestCase):
    def test_live_local_restart_clears_only_unexpired_rpc_budget(self):
        now=[0];budget=ConnectionRecovery(lambda:now[0]);budget.connected();budget.lost(ConnectionFailure('rpc','refused','Core stopping'));now[0]=10
        self.assertTrue(budget.planned_rpc_restart());now[0]=100;self.assertFalse(budget.tick());self.assertTrue(budget.connected())
        budget.lost(ConnectionFailure('dashboard','transport','Server disconnected'));self.assertFalse(budget.planned_rpc_restart());now[0]=116;self.assertTrue(budget.tick());self.assertFalse(budget.planned_rpc_restart())
    def test_already_elapsed_core_timeout_is_not_revived(self):
        now=[0];budget=ConnectionRecovery(lambda:now[0]);budget.connected();budget.lost(ConnectionFailure('rpc','refused','Core offline'));now[0]=15
        self.assertFalse(budget.planned_rpc_restart());self.assertTrue(budget.tick())
    def test_workspace_clears_stale_rpc_failure_but_preserves_server_failure(self):
        w=Workspace.__new__(Workspace);w.recovery=ConnectionRecovery();w.recovery.connected();w.node_status={};w.transfer=Mock();w.transfer.recovery.restart_window.return_value=True
        w.recovery.lost(ConnectionFailure('rpc','refused','Core stopping'));w.connection_lost(ConnectionFailure('rpc','warming_up','Loading wallets'))
        self.assertFalse(w.recovery.snapshot()['active']);self.assertEqual(w.node_status['color'],'amber')
        w.connection_lost(ConnectionFailure('dashboard','transport','Server disconnected'));self.assertTrue(w.recovery.snapshot()['active'])
    def test_watcher_does_not_expire_rpc_budget_owned_by_live_restart(self):
        w=Workspace.__new__(Workspace);w.recovery=ConnectionRecovery();w.recovery.connected();w.recovery.lost(ConnectionFailure('rpc','refused','Core stopping'))
        w.node_generation='fixture';w.node_stop=threading.Event();w.viewers=[Mock()];w.viewers[0].poll.return_value=None;w.closing=False
        w.transfer=Mock();w.transfer.recovery.restart_window.return_value=True
        def finished(_):w.node_stop.set();w.node_generation=None
        with patch('secure_worker.time.sleep',side_effect=finished):w.recovery_watch('fixture')
        self.assertFalse(w.recovery.snapshot()['active']);self.assertFalse(w.closing);w.viewers[0].terminate.assert_not_called()


class ManualContinuation(unittest.TestCase):
    def test_manual_paused_start_uses_resume_without_second_stop_or_reindex(self):
        from regtest_support import Regtest
        from wallet_ops import rpc
        from wallet_recovery import pruning_identity
        node=Regtest();self.addCleanup(node.close);core=node.core
        rpc(core,'createwallet',{'wallet_name':'Existing'});rpc(core,'setnetworkactive',[False])
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);store=Store(tmp.name)
        raw=rpc(core,'listdescriptors',[False],'Existing');chain=rpc(core,'getblockchaininfo')
        with store.edit() as saved:
            saved['recovery']={'state':'error','plan':{'replay':True,'target_height':23,'network_was_active':True,'restore_network_after':True}}
            saved['history_jobs']={'a'*64:{'wallet':'Existing','details':{'public_wallet':raw,'chain':'regtest','funded_outputs':[],'address_labels':[],'vaults':[]},'timestamp':0,'state':'pending','local_only':True,'expected_private_keys':True}}
        manager=Recovery(core,store);pid=node.process.pid
        with patch('wallet_recovery.process_launch',side_effect=AssertionError('No second automatic restart')):
            shown=manager.plan()
        plan=store.read()['recovery_plan']['plan'];self.assertEqual(shown['mode'],'resume');self.assertEqual(plan['target_height'],23);self.assertFalse(rpc(core,'getnetworkinfo')['networkactive'])
        manager.prepare_replay(plan)
        self.assertTrue(store.read()['history_jobs']['a'*64]['registered_for_replay']);self.assertTrue(store.read()['recovery']['replay_ready'])
        self.assertTrue(rpc(core,'getnetworkinfo')['networkactive']);self.assertEqual(node.process.pid,pid);self.assertEqual(pruning_identity(rpc(core,'getblockchaininfo')),pruning_identity(chain))
