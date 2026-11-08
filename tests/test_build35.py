"""Cancellation handover remains visible while private work and cleanup stay guarded."""
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from cancellation import Cancellations
from secure_worker import Workspace
from diagnostics import action_code
from disc_backup import Burner
from test_build19 import cancel

class CancellationVisibility(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.core=Mock();self.core.call.return_value={'result':[]}
  self.original={'kind':'wallet_setup','name':'Pending vault'};self.original_id=digest(self.original)
  with self.store.edit() as s:s['pending'][self.original_id]={'proposal':self.original,'state':'pending'}
  self.setup=SimpleNamespace(sessions={self.original_id:{'proposal':self.original,'phase':'contributed','installed_wallets':{},'core':None}},disc_sessions={},reviews={},own_identity=lambda:{},burner=Burner(self.root/'jobs',lambda *a:None))
  self.ops=SimpleNamespace(prepared={});self.c=Cancellations(self.core,self.store,self.setup,self.ops)
  self.w=Workspace.__new__(Workspace);self.w.store=self.store;self.w.setup=self.setup;self.w.ops=self.ops;self.w.archives=SimpleNamespace(reading=False,loaded={},staged={},state=lambda:{});self.w.transfer=SimpleNamespace(state=lambda:{});self.w.node_status={'color':'green'}
 def test_received_cancellation_exposes_exact_replacement_and_setup_link_without_cleanup(self):
  key=self.c.receive(cancel('wallet',[self.original_id],[self.original_id]))
  with patch('secure_worker.enforce',return_value={}):status=self.w.state()
  self.assertEqual([p['id'] for p in status['pending']],[key]);self.assertEqual(status['pending'][0]['replaces'],[self.original_id]);self.assertEqual(status['setups'][0]['cancellation_id'],key)
  self.assertTrue(status['busy']);self.assertIn(self.original_id,self.setup.sessions);self.core.call.assert_not_called()
  with self.assertRaisesRegex(ValueError,'Finish active wallet'):self.w.begin_close()
  with self.assertRaisesRegex(ValueError,'Delete and Cancel'):self.store.deny(key)
  self.c.review(key);self.c.confirm(key,'delete')
  with patch('secure_worker.enforce',return_value={}):status=self.w.state()
  self.assertEqual(status['pending'],[]);self.assertEqual(status['setups'],[]);self.assertFalse(status['busy'])
  with self.assertRaisesRegex(ValueError,'Wallet Server deliveries'):self.w.begin_close()
  with self.store.edit() as s:s['outbox'].clear() # Model Wallet Server acknowledgement of delivery receipt.
  self.w.begin_close()
 def test_unrelated_pending_request_is_not_labelled_cancelled(self):
  unrelated={'kind':'wallet_setup','name':'Another vault'};ident=digest(unrelated)
  with self.store.edit() as s:s['pending'][ident]={'proposal':unrelated,'state':'pending'}
  key=self.c.receive(cancel('wallet',[self.original_id],[self.original_id]))
  with patch('secure_worker.enforce',return_value={}):status=self.w.state()
  rows={p['id']:p for p in status['pending']};self.assertEqual(rows[key]['replaces'],[self.original_id]);self.assertEqual(rows[ident]['replaces'],[])
 def test_separate_cancellations_keep_their_own_review_targets(self):
  first=self.c.receive(cancel('wallet',[self.original_id],[self.original_id]))
  other={'kind':'wallet_setup','name':'Second build'};other_id=digest(other)
  with self.store.edit() as s:s['pending'][other_id]={'proposal':other,'state':'pending'}
  request=cancel('wallet',[other_id],[other_id]);request['cancellation_id']='c'*32;request['request_id']=digest({k:v for k,v in request.items() if k!='request_id'})
  second=self.c.receive(request)
  with patch('secure_worker.enforce',return_value={}):rows={p['id']:p for p in self.w.state()['pending']}
  self.assertEqual(rows[first]['replaces'],[self.original_id]);self.assertEqual(rows[second]['replaces'],[other_id])
 def test_diagnostic_categories_do_not_echo_sensitive_exception_text(self):
  for message,code in [('Wallet Server requested cancellation. secret material','builder_cancellation_pending'),('Choose Delete and Cancel or Backup and Cancel locally.','builder_cancellation_choice_required'),('This build is cancelled. secret material','builder_cancellation_pending')]:self.assertEqual(action_code(ValueError(message)),code)
  self.assertEqual(action_code(ValueError('arbitrary secret')),'local_action_refused')
