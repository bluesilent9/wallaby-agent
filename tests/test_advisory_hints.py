"""Untrusted live-source hints affect presentation and denial, never direct authority."""
import copy,tempfile,time,unittest
from unittest.mock import patch
from approval_store import Store,digest
from fixture_public_policy import paired
from sync_preferences import policy_id,change,enable
from sync_offers import apply
from sync_table import state,choose
from direct_wallet_catalogue import activate

class Hints(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);activate(self.store)
  self.raw=paired()['public_wallet'];self.ident=policy_id({'public_wallet':self.raw})
  self.offer={'id':'a'*64,'transfer_id':'b'*64,'direction':'receive','peer':{'node_id':'source','hostname':'wallet-laptop'},'public_wallet':self.raw,'status':'ready','source_online':True}
 def apply(self,offers,revision=1):apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':revision,'offers':offers},'session')
 def rows(self):return state(self.store,[])['wallets']
 def test_live_hint_is_grey_and_cannot_create_a_request_or_be_selected(self):
  self.apply([self.offer]);w=self.rows()[0];self.assertEqual(w['availability'],'advisory');self.assertTrue(w['server_hint']);self.assertEqual(w['receive'],[]);self.assertEqual(self.store.read()['pending'],{})
  with self.assertRaises(ValueError):choose(self.store,self.offer['id'],True,False)
 def test_denial_persists_red_after_source_disconnect_then_reenable_removes_row(self):
  self.apply([self.offer]);change(self.store,self.offer['id'],True);self.assertEqual(self.rows()[0]['availability'],'denied')
  self.apply([],2);self.assertEqual(self.rows()[0]['availability'],'denied');enable(self.store,self.ident);self.assertEqual(self.rows(),[])
 def test_offline_absent_presence_and_expired_hints_disappear(self):
  for field,value in [('source_online',False),('status','peer_offline')]:
   with self.subTest(field=field):self.offer[field]=value;self.apply([self.offer]);self.assertFalse(self.rows());self.offer[field]=True if field=='source_online' else 'ready'
   with self.store.edit() as s:s.pop('sync_offer_revision',None);s.pop('sync_offer_snapshot_hash',None)
  self.offer.pop('source_online');self.apply([self.offer]);self.assertFalse(self.rows())
  with self.store.edit() as s:s.pop('sync_offer_revision',None);s.pop('sync_offer_snapshot_hash',None)
  self.offer['source_online']=True;self.apply([self.offer]);self.assertTrue(self.rows())
  with self.store.edit() as s:s['sync_offer_observed_at']=time.monotonic()-46
  self.assertFalse(self.rows())
 def test_direct_route_wins_and_server_withdrawal_cannot_remove_it(self):
  self.apply([self.offer]);p=paired();p['direction']='receive';key=digest(p)
  with self.store.edit() as s:
   s['pending'][key]={'proposal':p,'state':'pending'};s['direct_sync_keys']={key:{'enabled':True}};s['direct_sync_offers']={key:{**self.offer,'id':key,'source_online':True}}
  request={'id':key,'wallet_name':self.raw['wallet_name'],'direction':'receive','state':'pending','sender':'wallet-laptop','receiver':'self'}
  with patch('sync_table.direct_ready',return_value=True):w=state(self.store,[request])['wallets'][0]
  self.assertEqual(w['availability'],'ready');self.assertFalse(w.get('server_hint'));self.apply([],2)
  with patch('sync_table.direct_ready',return_value=True):self.assertEqual(state(self.store,[request])['wallets'][0]['availability'],'ready')
 def test_hint_cannot_launder_a_server_request_into_direct_authority(self):
  self.apply([self.offer]);p=paired();p['direction']='receive';key=digest(p)
  with self.store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
  with self.assertRaises(ValueError):choose(self.store,key,True,False)
 def test_same_revision_refreshes_presence_lease_without_mutating_pending(self):
  self.apply([self.offer]);before=self.store.read()['pending']
  with self.store.edit() as s:s['sync_offer_observed_at']=time.monotonic()-46
  self.apply([self.offer]);self.assertTrue(self.rows());self.assertEqual(before,self.store.read()['pending'])
