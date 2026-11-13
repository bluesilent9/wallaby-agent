"""Late local controller teardown cannot destroy a newer protected session."""
import os,signal,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import ExitStack

class SessionHandover(unittest.TestCase):
 def fixture(self,root,stack):
  from test_build76 import Process
  from regtest_support import Regtest
  stack.addCleanup=stack.callback
  server=Process(stack,root,'server',os.environ['WALLABY_SERVER_SOURCE'],root/'server');core=Regtest();stack.callback(core.close)
  agent=Process(stack,root,'agent',os.environ.get('WALLABY_STARTUP_AGENT_SOURCE',str(Path(__file__).resolve().parents[1]/'src')),root/'agent',core.core.config['cookie'],core.core.config['rpc_port'],server.initial['port'],'wallet-laptop','02:85:00:00:00:01')
  self.until(lambda:agent.call(op='node_liveness')['node']['color']=='green')
  return server,agent,core
 def until(self,test):
  end=time.monotonic()+15
  while time.monotonic()<end:
   value=test()
   if value:return value
   time.sleep(.05)
  self.fail('Isolated node did not reach expected state.')
 def test_obsolete_unscoped_cleanup_cannot_disconnect_new_controller(self):
  with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
   server,agent,core=self.fixture(Path(folder),stack);port=server.initial['port']
   agent.call(op='node_control',method='node.start',args=[port,'a'*32]);agent.call(op='node_control',method='node.start',args=[port,'b'*32])
   before=server.call(op='identity_status');self.assertEqual(before['connections'],1)
   agent.call(op='node_control',method='node.connection_lost',args=['dashboard','timeout'])
   state=agent.call(op='node_liveness');self.assertFalse(state['stopped'],'Obsolete service cleanup stopped the current protected node.');self.assertEqual(state['node']['color'],'green');self.assertFalse(state['recovery']['active'])
   time.sleep(16);self.assertEqual(server.call(op='identity_status')['sessions'],before['sessions']);self.assertEqual(agent.call(op='node_liveness')['node']['color'],'green')
 def test_controller_handover_reuses_registration_and_only_current_owner_can_stop(self):
  with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
   server,agent,core=self.fixture(Path(folder),stack);port=server.initial['port'];first=agent.call(op='node_control',method='node.start',args=[port,'a'*32]);second=agent.call(op='node_control',method='node.start',args=[port,'b'*32]);self.assertEqual(first,second);gen=second['session']
   status=agent.call(op='node_control',method='node.status',args=[gen,'a'*32]);self.assertTrue(status['superseded'])
   self.assertEqual(agent.call(op='node_control',method='node.stop',args=[gen,'a'*32])['ignored'],'superseded')
   self.assertEqual(agent.call(op='node_control',method='node.connection_lost',args=['dashboard','timeout',gen,'a'*32])['ignored'],'superseded')
   self.assertFalse(agent.call(op='node_liveness')['stopped']);self.assertEqual(server.call(op='identity_status')['connections'],1)
   self.assertEqual(agent.call(op='node_control',method='node.status',args=[gen,'b'*32])['color'],'green')
   agent.call(op='node_control',method='node.stop',args=[gen,'b'*32]);self.until(lambda:not agent.call(op='node_liveness')['alive'])
   from wallet_ops import rpc
   self.assertEqual(rpc(core.core,'getblockcount'),0)

class OwnershipGuards(unittest.TestCase):
 def test_duplicate_runtime_service_cannot_acquire_the_same_lock(self):
  from node_control import runtime_owner
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with runtime_owner(root) as first:
    self.assertTrue(first)
    with runtime_owner(root) as second:self.assertFalse(second)
   with runtime_owner(root) as third:self.assertTrue(third)
   path=root/'node-worker.lock';path.unlink();path.symlink_to(root/'other')
   with self.assertRaises(OSError):
    with runtime_owner(root):pass
 def test_current_failure_still_starts_normal_recovery_and_stale_generation_does_not(self):
  from node_control import control
  w=SimpleNamespace(node_control_lock=threading.RLock(),node_controller='a'*32,node_generation='g',node_stop=threading.Event(),node_status={'color':'green'},connection_lost=Mock())
  self.assertEqual(control(w,'node.connection_lost',['rpc','timeout','old','a'*32])['ignored'],'superseded');w.connection_lost.assert_not_called();self.assertFalse(w.node_stop.is_set())
  control(w,'node.connection_lost',['rpc','timeout','g','a'*32]);w.connection_lost.assert_called_once();self.assertTrue(w.node_stop.is_set())
 def test_proxy_cleanup_and_transport_failure_carry_exact_ownership(self):
  from protected_node import ProtectedNode
  proxy=ProtectedNode({},123,threading.Event(),Mock());generation='fixture-generation'
  def call(method,*args,**kw):
   if method=='node.start':return {'session':generation}
   if method=='node.status':return {'color':'red','message':'Superseded','failed':True,'superseded':True}
   return {'ok':True}
  from diagnostics import ConnectionFailure
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=call) as bridge:
   with self.assertRaises(ConnectionFailure) as failed:proxy.run()
   self.assertEqual(failed.exception.code,'controller_superseded');proxy.status.assert_not_called()
   bridge.assert_any_call('node.stop',generation,proxy.controller)
   proxy.transport_failed('dashboard','timeout');bridge.assert_any_call('node.connection_lost','dashboard','timeout',generation,proxy.controller,timeout=2)
 def test_missing_environment_never_starts_unprotected_node_client(self):
  import runtime
  callbacks={};proxy=Mock();proxy.run.side_effect=lambda:callbacks[signal.SIGTERM](None,None)
  config=SimpleNamespace(values={'enabled':{'node':True},'hostname':'fixture','cookie':'fixture','rpc_port':1})
  with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),patch('runtime.runtime_dir',return_value=Path(folder)),patch('runtime.signal.signal',side_effect=lambda sig,fn:callbacks.__setitem__(sig,fn)),patch('runtime.Config',return_value=config),patch('runtime.Tunnel') as tunnel,patch('runtime.write_status'),patch('capabilities.node_support',return_value={'available':True}),patch('protected_node.ProtectedNode',return_value=proxy) as protected,patch('runtime.NodeClient') as ordinary:
   tunnel.return_value.alive.return_value=True;runtime.worker('node');protected.assert_called_once();ordinary.assert_not_called()

class AutomaticDiagnostics(unittest.TestCase):
 def test_service_snapshot_never_exports_command_arguments_or_paths(self):
  import json,subprocess
  from node_diagnostics import service
  output='MainPID=1234\nActiveState=active\nSubState=running\nResult=success\nNRestarts=2\nExecMainStatus=0\nMemoryCurrent=123456\nExecStart={ path=/usr/bin/wallaby-agent ; argv[]=/usr/bin/wallaby-agent node password=NEVER_EXPORT cookie=SECRET }\nFragmentPath=/usr/lib/systemd/user/wallaby-agent-node.service\nDropInPaths=/private/NEVER_EXPORT.conf\nControlGroup=\n'
  with patch('node_diagnostics.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=output)):
   value=service(True)
  self.assertEqual(value['MainPID'],1234);self.assertTrue(value['packaged_launcher']);self.assertEqual(value['dropins'],1);self.assertNotIn('NEVER_EXPORT',json.dumps(value));self.assertNotIn('SECRET',json.dumps(value))
  with patch('node_diagnostics.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',.8)):self.assertEqual(service(False),{'available':False})
 def test_export_includes_current_protected_events_without_closing_or_mutating_workspace(self):
  from node_diagnostics import export_text
  from activity_log import DiagnosticLog
  from test_build19 import row
  with tempfile.TemporaryDirectory() as folder:
   log=DiagnosticLog(Path(folder)/'logs');log.merge([row('ordinary fixture')]);protected=row('current protected fixture',origin='protected')
   with patch('node_diagnostics.snapshot') as snap,patch('protected_memory.inside',return_value=False),patch('activity_log.DiagnosticLog',return_value=log),patch('secure_bridge.call',return_value=[protected]) as bridge:
    text=export_text();self.assertIn('ordinary fixture',text);self.assertIn('current protected fixture',text);bridge.assert_called_once_with('diagnostics.export',timeout=5);snap.assert_called_once_with('log_export')
 def test_export_still_contains_ordinary_fault_evidence_when_worker_is_down(self):
  from node_diagnostics import export_text
  from activity_log import DiagnosticLog
  from secure_bridge import WorkspaceFailure
  from test_build19 import row
  with tempfile.TemporaryDirectory() as folder:
   log=DiagnosticLog(Path(folder)/'logs');log.merge([row('node.service fixture MainPID=0')])
   with patch('node_diagnostics.snapshot'),patch('protected_memory.inside',return_value=False),patch('activity_log.DiagnosticLog',return_value=log),patch('secure_bridge.call',side_effect=WorkspaceFailure('worker_unreachable','cookie=NEVER_EXPORT')):
    text=export_text();self.assertIn('MainPID=0',text);self.assertIn('Protected diagnostics unavailable',text);self.assertNotIn('NEVER_EXPORT',text)
 def test_snapshot_reports_builds_and_memory_without_controller_token_or_wallet_fields(self):
  import json
  from node_diagnostics import snapshot
  w=SimpleNamespace(node_epoch=7,node_controller='SECRET-CONTROLLER',node=Mock(),node_stop=threading.Event(),node_status={'color':'green'},viewers=[],wallet_secret='NEVER_EXPORT')
  with patch('node_diagnostics.service',return_value={'available':False}),patch('activity_log.event') as event:
   snapshot('controller_change',w);messages=' '.join(c.args[1] for c in event.call_args_list)
  self.assertIn('loaded_build',messages);self.assertIn('"epoch": 7',messages);self.assertNotIn('SECRET-CONTROLLER',messages);self.assertNotIn('NEVER_EXPORT',messages)
 def test_current_protected_export_does_not_wait_for_wallet_operation_lock(self):
  from secure_worker import Workspace
  from activity_log import DiagnosticLog
  w=Workspace.__new__(Workspace);w.lock=Mock();w.lock.acquire.side_effect=AssertionError('Diagnostic export attempted to take wallet lock')
  with patch('secure_worker.enforce',return_value={}),patch('node_diagnostics.snapshot') as snap,patch('activity_log.DiagnosticLog') as log:
   log.return_value.records.return_value=[];self.assertEqual(w.dispatch('diagnostics.export',[],{}),[]);snap.assert_called_once_with('protected_export',w)
