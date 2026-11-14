"""Recovery may clear one advisory notice, never a result of a wallet mutation."""
import ast,copy,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store
ROOT=Path(__file__).resolve().parents[1]
module=ast.parse((ROOT/'packaging/close_notice_recovery.py').read_text())
INNER=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='INNER' for t in n.targets))
class Recovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  self.status={'pending':[],'setups':[],'archives':{'loaded':[],'staged':[]},'transfer':{'busy':False,'ready':False,'sending':False,'batch':None},'burn':{}}
 def run_helper(self):
  with patch('protected_memory.enforce'),patch('protected_memory.root',return_value=Path(self.tmp.name)),patch('secure_bridge.call',side_effect=([{'worker_version':'2.0.0~dev98','status_pending':True}] if getattr(self,'transient_lock',False) else [])+[{'worker_version':'2.0.0~dev98'},self.status,{'ok':True}]),patch('approval_store.Store',return_value=self.store),patch('resource.setrlimit'),patch('ctypes.CDLL'),patch('activity_log.event'),patch('builtins.print'):
   exec(compile(INNER,'guarded-close-notice-inspector','exec'),{})
 def test_only_cancelled_advisory_removed_and_durable_decisions_retained(self):
  self.store.queue('wallet_retirement_result',{'request_hash':'a'*64,'status':'cancelled'})
  with self.store.edit() as s:s['request_denials']={'unchanged':{}};s['completed']={'kept':{'result':{'status':'cancelled'}}}
  self.run_helper();self.assertFalse(self.store.read()['outbox']);self.assertIn('kept',self.store.read()['completed']);self.assertIn('unchanged',self.store.read()['request_denials'])
 def test_completed_uncertain_and_mutating_results_are_never_removed(self):
  for kind,p in [('wallet_retirement_result',{'status':'complete'}),('wallet_retirement_result',{'status':'error'}),('wallet_retirement_result',{'status':'cancelled','wallet_deleted':True}),('partial_sign_result',{'status':'complete'})]:
   with self.subTest(kind=kind,p=p):
    with self.store.edit() as s:s['outbox']={}
    self.store.queue(kind,{'request_hash':'a'*64,**p});before=self.store.read()
    with self.assertRaises(SystemExit):self.run_helper()
    self.assertEqual(self.store.read(),before)
 def test_archives_and_active_recovery_stop_before_removing_notice(self):
  self.store.queue('wallet_retirement_result',{'request_hash':'a'*64,'status':'cancelled'});before=self.store.read()
  self.status['archives']['loaded']=[{'id':'held'}]
  with self.assertRaises(SystemExit):self.run_helper()
  self.assertEqual(self.store.read(),before)
  self.status['archives']['loaded']=[]
  with self.store.edit() as s:s['history_jobs']={'ongoing':{}}
  with self.assertRaises(SystemExit):self.run_helper()
  self.assertTrue(self.store.read()['outbox'])

 def test_transient_read_lock_is_retried_without_weakening_notice_checks(self):
  self.transient_lock=True;self.store.queue('wallet_retirement_result',{'request_hash':'a'*64,'status':'cancelled'})
  with patch('time.sleep'):self.run_helper()
  self.assertFalse(self.store.read()['outbox'])
