import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from approval_store import Store,digest
from sync_queue import apply_snapshot,choose
from sync_approvals import groups,binding
from fixture_public_policy import paired
from batch_transfer import BatchTransfer

class ReceiveApprovals(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name));self.a=paired('Alpha');self.b=copy.deepcopy(self.a);self.b['transfer_id']='b'*64;self.b['public_wallet']['wallet_name']='Beta'
  self.ka=digest(self.a);self.kb=digest(self.b)
  with self.store.edit() as saved:saved['pending']={digest(p):{'proposal':p,'state':'pending'} for p in (self.a,self.b)}
 def test_selection_combines_by_source_and_deselection_removes(self):
  self.assertEqual(groups(self.store),[]);choose(self.store,self.ka,True,False);first=groups(self.store)[0];self.assertEqual(first['keys'],[self.ka]);choose(self.store,self.kb,True,True);g=groups(self.store);self.assertEqual(len(g),1);self.assertEqual(set(g[0]['keys']),{self.ka,self.kb});self.assertNotEqual(first['id'],g[0]['id']);choose(self.store,self.ka,False,False);choose(self.store,self.kb,False,True);self.assertEqual(groups(self.store),[])
 def test_different_sources_never_share_approval(self):
  self.b['peer']['node_id']='c'*64
  with self.store.edit() as saved:saved['pending']={digest(p):{'proposal':p,'state':'pending'} for p in (self.a,self.b)}
  choose(self.store,self.ka,True,False);choose(self.store,digest(self.b),True,False);self.assertEqual(len(groups(self.store)),2)
 def test_changed_choice_or_preview_invalidates_review_without_starting(self):
  choose(self.store,self.ka,True,False);g=groups(self.store)[0];t=BatchTransfer.__new__(BatchTransfer);t.store=self.store;t.authorise_batch=Mock();token=binding(self.store,g);t.receive_reviews={g['id']:(token,time.monotonic())}
  with self.store.edit() as s:s['transfer_previews']={self.ka:{'different':'preview'}}
  with self.assertRaisesRegex(ValueError,'changed or expired'):t.authorise_receive(g['id'],token)
  choose(self.store,self.ka,True,True)
  with self.assertRaisesRegex(ValueError,'choices changed'):t.authorise_receive(g['id'],token)
  t.authorise_batch.assert_not_called()
 def test_approval_only_starts_the_reviewed_source_group(self):
  choose(self.store,self.ka,True,False);g=groups(self.store)[0];t=BatchTransfer.__new__(BatchTransfer);t.store=self.store;t.authorise_batch=Mock(return_value={'ready':True});token=binding(self.store,g);t.receive_reviews={g['id']:(token,time.monotonic())};t.authorise_receive(g['id'],token);t.authorise_batch.assert_called_once_with(keys=[self.ka])
  with self.assertRaisesRegex(ValueError,'expired'):t.authorise_receive(g['id'],token)

 def test_cancel_clears_only_local_selection_without_permanent_denial(self):
  choose(self.store,self.ka,True,False);g=groups(self.store)[0];t=BatchTransfer.__new__(BatchTransfer);t.store=self.store;t.receive_reviews={g['id']:('review',time.monotonic())};t.cancel_receive(g['id']);self.assertEqual(groups(self.store),[]);self.assertIn(self.ka,self.store.read()['pending']);self.assertFalse(self.store.read().get('sync_exclusions'));self.assertFalse(t.receive_reviews)
