"""Only useful sync work is listed; local inventory alone is never a sync row."""
import copy
from unittest.mock import patch
from test_build70 import Offers
from sync_table import observe,state
from sync_queue import apply_snapshot,rows
from sync_offers import apply
from sync_preferences import change,enable,policy_id
from approval_store import digest

class Visibility(Offers):
 def local(self):
  observe(self.store,'listwallets',None,['Other family wallet','Unrelated local']);observe(self.store,'listdescriptors','Other family wallet',self.p['public_wallet'])
 def outgoing(self):
  p=copy.deepcopy(self.p);p['direction']='send';apply_snapshot(self.store,1,[p]);snap=copy.deepcopy(self.snapshot);snap['offers'][0]['direction']='send';snap['offers'][0]['status']='ready';apply(self.store,snap,'session');return p,snap
 def test_local_wallets_with_no_other_agents_produce_no_rows_or_badge(self):
  self.local();self.assertEqual(state(self.store,[]),{'wallets':[],'pending_count':0})
 def test_sender_needs_live_recipient_not_just_cached_offer_or_local_wallet(self):
  self.local();p,snap=self.outgoing();before=self.store.read()
  with patch('sync_table.direct_ready',return_value=False):self.assertEqual(state(self.store,rows(self.store)),{'wallets':[],'pending_count':0})
  with patch('sync_table.direct_ready',return_value=True):
   result=state(self.store,rows(self.store));self.assertEqual(len(result['wallets']),1);self.assertEqual(result['pending_count'],1)
  with patch('sync_table.direct_ready',return_value=False):self.assertFalse(state(self.store,rows(self.store))['wallets'])
  self.assertEqual(before,self.store.read())
 def test_incoming_discovery_stays_visible_without_online_sender(self):
  snap=copy.deepcopy(self.snapshot);snap['offers'][0]['status']='peer_offline';apply(self.store,snap,'session')
  result=state(self.store,[]);self.assertEqual(len(result['wallets']),1);self.assertFalse(result['wallets'][0]['denied']);self.assertEqual(result['pending_count'],1)
 def test_deny_stays_visible_even_after_sender_and_offer_disappear(self):
  apply(self.store,self.snapshot,'session');change(self.store,self.offer['id'],True)
  empty={**self.snapshot,'revision':2,'offers':[]};apply(self.store,empty,'session');self.local()
  result=state(self.store,[]);self.assertEqual(len(result['wallets']),1);self.assertTrue(result['wallets'][0]['denied']);self.assertEqual(result['pending_count'],0)
 def test_reenabled_receive_discovery_returns_without_a_connected_sender(self):
  apply(self.store,self.snapshot,'session');change(self.store,self.offer['id'],True);enable(self.store,policy_id(self.p));result=state(self.store,[])
  self.assertEqual(len(result['wallets']),1);self.assertFalse(result['wallets'][0]['denied']);self.assertEqual(result['pending_count'],1)
 def test_only_live_recipient_is_in_wallet_row_and_disabled_receiver_removes_row(self):
  p,snap=self.outgoing();second=copy.deepcopy(p);second['transfer_id']='2'*64;second['peer']['node_id']='other';apply_snapshot(self.store,2,[p,second]);o=copy.deepcopy(snap['offers'][0]);o.update(id='3'*64,transfer_id=second['transfer_id']);o['peer']['node_id']='other';snap.update(revision=2,offers=[snap['offers'][0],o]);apply(self.store,snap,'session')
  with patch('sync_table.direct_ready',side_effect=lambda s,q:q['peer']['node_id']=='other'):
   r=state(self.store,rows(self.store));self.assertEqual(len(r['wallets']),1);self.assertEqual([x['peer_id'] for x in r['wallets'][0]['send']],['other']);self.assertEqual(r['pending_count'],1)
  snap.update(revision=3,offers=[]);apply(self.store,snap,'session')
  with patch('sync_table.direct_ready',return_value=True):self.assertFalse(state(self.store,rows(self.store))['wallets'])
 def test_attempted_disconnected_work_is_preserved_for_inspection(self):
  p,snap=self.outgoing()
  with self.store.edit() as s:s['pending'][digest(p)]['state']='attempted'
  with patch('sync_table.direct_ready',return_value=False):r=state(self.store,rows(self.store))
  self.assertEqual(r['wallets'][0]['send'][0]['state'],'attempted');self.assertEqual(r['pending_count'],0)
