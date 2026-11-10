"""Planned Core restart boundaries; never operates on desktop Core."""
import sys,tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src')]
from wallet_recovery import Recovery
from approval_store import Store
from node_client import NodeClient
from secure_worker import Workspace
from node_recovery import Recovery as ConnectionRecovery
from diagnostics import ConnectionFailure

class Restart(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(self.tmp.name);self.manager=Recovery(Mock(),self.store)
  with self.store.edit() as s:s['recovery']={'state':'starting'}
  (Path(self.tmp.name)/'.lock').write_bytes(b'')
  self.launch={'pid':999999999,'started':'fixture','netdir':self.tmp.name,'argv':['/fixture/bitcoin-qt'],'executable':'/fixture/bitcoin-qt','cwd':self.tmp.name,'env':{'HOME':self.tmp.name}}
 def test_failed_launch_preflight_never_stops_core(self):
  calls=[]
  def rpc(c,m,*a,**k):calls.append(m);return {'chain':'main'}
  with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',side_effect=rpc),patch('wallet_recovery.subprocess.run',return_value=Mock(returncode=1)):
   with self.assertRaisesRegex(ValueError,'Core was not stopped'):self.manager.restart(self.launch,['-reindex=1'])
  self.assertEqual(calls,['getblockchaininfo']);self.assertFalse(self.manager.restart_window())
 def test_launch_timeout_preflight_never_stops_core(self):
  import subprocess
  with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',return_value={'chain':'main'}) as rpc,patch('wallet_recovery.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',30)):
   with self.assertRaisesRegex(ValueError,'Core was not stopped'):self.manager.restart(self.launch,['-reindex=1'])
  self.assertEqual(rpc.call_count,1)
 def test_separate_launch_refusal_clears_grace_and_never_retries(self):
  order=[]
  def rpc(c,m,*a,**k):order.append(m);return {'chain':'main'}
  def run(cmd,**kw):
   order.append('probe' if cmd[-1]=='/usr/bin/true' else 'version' if cmd[-1]=='-version' else 'launch');return Mock(returncode=0 if cmd[-1] in ('/usr/bin/true','-version') else 1)
  with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',side_effect=rpc),patch('wallet_recovery.lock_released',return_value=True),patch('wallet_recovery.subprocess.run',side_effect=run):
   with self.assertRaisesRegex(ValueError,'No duplicate Core'):self.manager.restart(self.launch,['-reindex=1','-networkactive=0'])
  self.assertEqual(order,['getblockchaininfo','probe','version','stop','launch']);self.assertEqual(self.manager.restart_deadline,0)
 def test_restart_uses_journal_outside_private_ram_and_preserves_args(self):
  command=self.manager.launch_command(self.launch,['/fixture/bitcoin-qt','-datadir=/fixture','-prune=550'],'unit',True)
  self.assertIn('--wait',command);self.assertIn('--property=StandardError=journal',command)
  self.assertFalse(any('append:' in v for v in command));self.assertEqual(command[command.index('--')+1:],['/fixture/bitcoin-qt','-datadir=/fixture','-prune=550'])
 def test_restart_grace_requires_live_local_thread_and_expires(self):
  self.manager.restart_deadline=time.monotonic()+900
  self.assertFalse(self.manager.restart_window())
  self.manager.thread=Mock();self.manager.thread.is_alive.return_value=True
  self.assertTrue(self.manager.restart_window());self.manager.thread.is_alive.return_value=False
  self.assertFalse(self.manager.restart_window());self.manager.thread.is_alive.return_value=True;self.manager.restart_deadline=time.monotonic()-1
  self.assertFalse(self.manager.restart_window())
 def test_planned_restart_only_skips_health_check_during_grace(self):
  client=NodeClient({},0,threading.Event(),Mock());client.core=Mock();client.planned_core_restart=lambda:True
  self.assertIs(client.check_core(),False);client.core.ready.assert_not_called()
  client.planned_core_restart=lambda:False;self.assertTrue(client.check_core());client.core.ready.assert_called_once()
  client.pool.shutdown()
 def test_planned_restart_does_not_mask_dashboard_failure(self):
  w=Workspace.__new__(Workspace);w.recovery=ConnectionRecovery();w.recovery.connected();w.node_status={}
  w.transfer=Mock();w.transfer.recovery.restart_window.return_value=True
  w.connection_lost(ConnectionFailure('rpc','warming_up','fixture'));self.assertFalse(w.recovery.snapshot()['active']);self.assertEqual(w.node_status['color'],'amber')
  w.connection_lost(ConnectionFailure('dashboard','transport','fixture'));self.assertTrue(w.recovery.snapshot()['active'])
 def test_unexpected_core_failure_keeps_normal_connection_deadline(self):
  w=Workspace.__new__(Workspace);w.recovery=ConnectionRecovery();w.recovery.connected();w.node_status={};w.transfer=Mock();w.transfer.recovery.restart_window.return_value=False
  w.connection_lost(ConnectionFailure('rpc','transport','fixture'));self.assertTrue(w.recovery.snapshot()['active']);self.assertLessEqual(w.recovery.snapshot()['remaining'],15)

 def test_grace_lasts_until_rpc_is_ready_not_only_until_launcher_returns(self):
  self.manager.thread=Mock();self.manager.thread.is_alive.return_value=True
  def ready(**kwargs):
   self.assertTrue(self.manager.restart_window());return {'chain':'main'}
  with patch('wallet_recovery.process_launch',return_value=self.launch),patch('wallet_recovery.rpc',return_value={'chain':'main'}),patch('wallet_recovery.lock_released',return_value=True),patch('wallet_recovery.subprocess.run',return_value=Mock(returncode=0)),patch.object(self.manager,'wait_rpc',side_effect=ready):
   self.manager.restart(self.launch,['-reindex=1'])
  self.assertFalse(self.manager.restart_window())

 def test_core_service_failure_is_reported_before_waiting_ten_minutes(self):
  with patch('wallet_recovery.rpc',side_effect=ValueError('not ready')),patch('wallet_recovery.subprocess.run',return_value=Mock(returncode=0,stdout='ActiveState=failed\nExecMainStatus=203\n')),patch('wallet_recovery.time.sleep') as sleep:
   with self.assertRaisesRegex(ValueError,'exit status 203'):self.manager.wait_rpc(startup_unit='fixture')
  sleep.assert_not_called()

 def test_restart_starting_during_inflight_health_check_does_not_fail_session(self):
  client=NodeClient({},0,threading.Event(),Mock());client.core=Mock();client.core.ready.side_effect=ValueError('Core stopped during health request')
  client.planned_core_restart=Mock(side_effect=[False,True])
  self.assertIs(client.check_core(),False);self.assertFalse(client.failed.is_set());client.pool.shutdown()
