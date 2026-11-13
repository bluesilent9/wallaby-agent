"""A discovery notice is not an executable direct wallet transfer."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from fixture_public_policy import paired
from sync_preferences import policy_id,enable
from sync_offers import apply
from sync_table import state,choose

class DiscoveryRoutes(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'state');self.raw=paired()['public_wallet'];self.ident=policy_id({'public_wallet':self.raw})
  self.offer={'id':'a'*64,'transfer_id':'b'*64,'direction':'receive','peer':{'node_id':'node-source','hostname':'wallet-laptop'},'public_wallet':self.raw,'status':'peer_changed'}
  with self.store.edit() as saved:saved['sync_exclusions']={self.ident:{'policy_id':self.ident,'wallet_name':'Extinct'}}
 def test_enabling_discovery_only_entry_preserves_source_and_reason_without_inventing_request(self):
  apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[self.offer]},'session')
  enable(self.store,self.ident);view=state(self.store,[]);self.assertEqual(len(view['wallets']),1);wallet=view['wallets'][0];self.assertFalse(wallet['denied']);self.assertEqual(wallet['receive'],[]);self.assertEqual(wallet['offers'][0]['peer']['hostname'],'wallet-laptop');self.assertEqual(wallet['offers'][0]['status'],'peer_changed');self.assertTrue(wallet['pending']);self.assertEqual(self.store.read()['pending'],{})
  with self.assertRaises(ValueError):choose(self.store,self.offer['id'],True,True)
 def test_offline_discovery_never_becomes_selectable_and_deny_survives_offer_withdrawal(self):
  self.offer['status']='peer_offline';apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[self.offer]},'session');view=state(self.store,[]);self.assertTrue(view['wallets'][0]['denied']);self.assertFalse(view['wallets'][0]['pending'])
  apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':2,'offers':[]},'session');view=state(self.store,[]);self.assertTrue(view['wallets'][0]['denied']);self.assertEqual(view['wallets'][0]['receive'],[])
 def test_current_discovery_diagnostics_include_blocker_counts_without_wallet_contents(self):
  with patch('activity_log.event') as event:
   apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[self.offer]},'session')
   args=event.call_args.args;self.assertIn('peer_changed:1',args[1]);self.assertNotIn(self.raw['wallet_name'],args[1]);self.assertNotIn('wallet-laptop',args[1])

 def test_denial_does_not_hide_advertised_source_or_enable_transfer(self):
  from sync_offers import rows
  self.offer['status']='disabled';apply(self.store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[self.offer]},'session');self.assertEqual(rows(self.store)[0]['peer']['hostname'],'wallet-laptop');view=state(self.store,[]);wallet=view['wallets'][0];self.assertTrue(wallet['denied']);self.assertEqual(wallet['offers'][0]['peer']['hostname'],'wallet-laptop');self.assertFalse(wallet['pending']);self.assertEqual(wallet['receive'],[])

 def test_changed_server_preview_cannot_proceed_as_a_ready_receive(self):
  from sync_offers import receive_blocker
  p={'transfer_id':self.offer['transfer_id'],'peer':self.offer['peer']}
  self.offer['status']='preview_changed';self.assertIn('renew',receive_blocker({'sync_offers':{'offer':self.offer}},p))
  self.offer['status']='ready';self.assertIsNone(receive_blocker({'sync_offers':{'offer':self.offer}},p))
