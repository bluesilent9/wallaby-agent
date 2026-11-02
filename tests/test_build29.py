"""Profile reset and reauthentication must not strand the Agent's public queue."""
import copy,tempfile,unittest
from unittest.mock import patch,Mock
from approval_store import Store,digest
from agent_exchange import Exchange
from sync_queue import apply_snapshot,rows
from sync_preferences import cancel,change,enable,policy_id
from test_build8 import paired

class SessionQueues(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.p=paired('Receiving wallet');self.key=digest(self.p)
 def exchange(self,token,revision,requests):
  response={'version':1,'accepted':[],'proposals':[{'kind':'wallet_sync_queue','revision':revision,'requests':requests}]}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value=response):Exchange(1,token,self.store).once()
 def test_profile_clear_reauth_accepts_zero_then_new_requests(self):
  self.exchange('before reset',15,[]);self.exchange('after reset',0,[]);self.exchange('after reset',1,[self.p]);self.assertEqual(len(rows(self.store)),1);self.assertEqual(self.store.read()['sync_revision'],1)
 def test_same_session_rewind_and_same_revision_changes_still_rejected(self):
  self.exchange('current',15,[self.p])
  for revision,requests in ((0,[]),(15,[])):
   with self.assertRaises(ValueError):self.exchange('current',revision,requests)
  self.assertEqual(len(rows(self.store)),1)
 def test_late_old_exchange_cannot_reactivate_retired_session(self):
  self.exchange('old',15,[]);self.exchange('new',0,[self.p])
  with self.assertRaisesRegex(ValueError,'Retired'):self.exchange('old',16,[])
  self.assertEqual(len(rows(self.store)),1)
 def test_session_change_preserves_active_attempts_completed_denials_and_outbox(self):
  self.exchange('old',15,[self.p]);other=paired('Already done');self.store.queue('fixture',{'public':'result'})
  with self.store.edit() as s:
   s['pending'][self.key]['state']='receiving';s['active_transfer']=self.key;s['completed'][digest(other)]={'state':'complete'};s['sync_exclusions']={'local':{'policy_id':'local'}}
  self.exchange('new',0,[]);s=self.store.read();self.assertTrue(s['pending'][self.key]['withdrawn']);self.assertEqual(s['active_transfer'],self.key);self.assertEqual(s['pending'][self.key]['state'],'receiving');self.assertIn(digest(other),s['completed']);self.assertTrue(s['outbox']);self.assertIn('local',s['sync_exclusions'])
 def test_malformed_snapshot_does_not_rebase_session(self):
  self.exchange('old',15,[self.p]);invalid=copy.deepcopy(self.p);invalid['peer']['ipv6']='127.0.0.1'
  with self.assertRaises(ValueError):self.exchange('new',0,[invalid])
  self.assertEqual(self.store.read()['sync_revision'],15);self.exchange('old',16,[self.p])
 def test_repeated_snapshot_restores_dismissed_unattempted_offer(self):
  self.exchange('current',2,[self.p]);cancel(self.store,self.key);self.assertFalse(rows(self.store));self.exchange('current',2,[self.p]);self.assertEqual(len(rows(self.store)),1)
 def test_same_snapshot_never_replays_completed_or_attempted_operation(self):
  self.exchange('current',2,[self.p])
  with self.store.edit() as s:s['pending'][self.key]['state']='receiving';s['active_transfer']=self.key
  self.exchange('current',2,[self.p]);self.assertEqual(self.store.read()['pending'][self.key]['state'],'receiving')
  with self.store.edit() as s:s['pending'].pop(self.key);s['completed'][self.key]={'state':'complete'};s.pop('active_transfer')
  self.exchange('current',2,[self.p]);self.assertFalse(rows(self.store))
 def test_disable_is_local_and_reenable_restores_same_offered_revision(self):
  self.exchange('current',2,[self.p]);change(self.store,self.key,True);self.exchange('current',2,[self.p]);self.assertFalse(rows(self.store))
  with tempfile.TemporaryDirectory() as root:
   peer=Store(root);apply_snapshot(peer,2,[self.p]);self.assertEqual(len(rows(peer)),1)
  enable(self.store,policy_id(self.p));self.exchange('current',2,[self.p]);self.assertEqual(len(rows(self.store)),1)
 def test_token_never_written_to_ram_state_or_diagnostics(self):
  token='secret-session-fixture-do-not-export';self.exchange(token,0,[]);self.assertNotIn(token,self.store.path.read_text())

class BatchWithdrawal(unittest.TestCase):
 def test_received_wallet_waiting_for_history_is_not_misreported_as_withdrawn(self):
  from batch_transfer import BatchTransfer
  from peer_wallet import Transfer
  from sync_queue import choose
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);p=paired('Pruned wallet','send');key=digest(p);apply_snapshot(store,1,[p]);choose(store,key,True,True);manager=BatchTransfer(Mock(),store);credentials={p['peer']['node_id']:{'username':'fixture','password':'fixture','fingerprint':'fixture'}}
   with patch.object(manager,'validate_batch'),patch.object(Transfer,'send',side_effect=lambda *a,**kw:manager.pending_recovery(key)):manager.send_batch(credentials)
   self.assertEqual(store.read()['pending'][key]['state'],'recovery_required');self.assertFalse(manager.error);self.assertIsNone(next(iter(credentials.values()))['password'])
 def test_withdrawal_reports_partial_completion_and_clears_credentials_without_replaying(self):
  from batch_transfer import BatchTransfer
  from peer_wallet import Transfer
  from sync_queue import choose
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);a=paired('Alpha','send');b=paired('Beta','send');apply_snapshot(store,1,[a,b])
   for p in (a,b):choose(store,digest(p),True,True)
   manager=BatchTransfer(Mock(),store);credentials={p['peer']['node_id']:{'username':'fixture','password':'fixture','fingerprint':'fixture'} for p in (a,b)}
   def send(key,**kwargs):
    with store.edit() as s:s['pending'].pop(key);s['completed'][key]={'status':'complete'}
    apply_snapshot(store,2,[])
   with patch.object(manager,'validate_batch'),patch.object(Transfer,'send',side_effect=send) as called:
    with self.assertRaisesRegex(ValueError,'1 of 2'):manager.send_batch(credentials)
   self.assertEqual(called.call_count,1);self.assertFalse(store.read().get('sync_batch'));self.assertTrue(all(v['password'] is None for v in credentials.values()))

if __name__=='__main__':unittest.main()
