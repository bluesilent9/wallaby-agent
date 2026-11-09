"""A live direct connection cannot override a receiver's absent/denied offer."""
import copy
from unittest.mock import patch,Mock
from test_build71 import Table
from sync_offers import apply
from sync_queue import rows,apply_snapshot
from sync_table import state,choose,observe
from approval_store import digest
from batch_transfer import BatchTransfer

class ReceiverPermissions(Table):
 def outgoing(self):
  p=copy.deepcopy(self.p);p['direction']='send';apply_snapshot(self.store,1,[p]);o=copy.deepcopy(self.offer);o['direction']='send';o['status']='ready';snap=copy.deepcopy(self.snapshot);snap['offers']=[o];apply(self.store,snap,'session');return p,snap
 def test_withdrawn_receiver_removes_only_its_sender_option_and_count_and_reenable_returns(self):
  p,snap=self.outgoing();observe(self.store,'listwallets',None,['Local wallet']);observe(self.store,'listdescriptors','Local wallet',p['public_wallet'])
  with patch('sync_table.direct_ready',return_value=True):
   self.assertEqual(state(self.store,rows(self.store))['pending_count'],1);choose(self.store,digest(p),True,False)
   withdrawn=copy.deepcopy(snap);withdrawn.update(revision=2,offers=[]);apply(self.store,withdrawn,'session');r=state(self.store,rows(self.store));self.assertEqual(r['pending_count'],0);self.assertFalse(r['wallets']);self.assertFalse(self.store.read()['sync_choices'][digest(p)]['selected'])
   with self.assertRaisesRegex(ValueError,'receiver'):choose(self.store,digest(p),True,False)
   target=Mock();target.store=self.store
   with self.assertRaisesRegex(ValueError,'receiver'):BatchTransfer.validate_batch(target,[digest(p)],'send')
   snap['revision']=3;apply(self.store,snap,'session');self.assertEqual(state(self.store,rows(self.store))['pending_count'],1);choose(self.store,digest(p),False,True)
  self.assertIn(digest(p),self.store.read()['pending']);self.assertNotIn('sync_batch',self.store.read())
 def test_disabled_or_stale_permissions_never_become_sender_choices(self):
  p,snap=self.outgoing()
  for revision,status in enumerate(('disabled','permissions_pending'),2):
   snap['revision']=revision;snap['offers'][0]['status']=status;apply(self.store,snap,'session')
   with patch('sync_table.direct_ready',return_value=True):r=state(self.store,rows(self.store))
   self.assertEqual(r['pending_count'],0);self.assertFalse(r['wallets'])
 def test_unrelated_receiver_offer_cannot_restore_a_withdrawn_target(self):
  p,snap=self.outgoing();snap['revision']=2;snap['offers'][0]['peer']['node_id']='other';apply(self.store,snap,'session')
  with patch('sync_table.direct_ready',return_value=True):
   self.assertFalse(any(w['send'] for w in state(self.store,rows(self.store))['wallets']))
   with self.assertRaisesRegex(ValueError,'receiver'):choose(self.store,digest(p),True,False)
 def test_permission_reply_is_flushed_once_without_repeating_wallet_operations(self):
  from agent_exchange import Exchange
  ex=Exchange(1,'test',self.store)
  proposals=[{'kind':'wallet_sync_preferences','version':1,'challenge':'f'*64,'previous':None}]
  replies=[{'version':1,'accepted':[],'proposals':proposals},{'version':1,'accepted':[],'proposals':proposals}]
  with patch('sync_preferences.exchange'),patch('agent_exchange.http_json',side_effect=replies) as http,patch('agent_exchange.local_ipv6',return_value=None):ex.once(previews=False)
  self.assertEqual(http.call_count,2)
 def test_wallet_services_card_uses_wallet_brand_asset(self):
  from pathlib import Path
  root=Path(__file__).resolve().parents[1];html=(root/'web/index.html').read_text();card=html.split('data-service="dashboard"',1)[1].split('data-service="node"',1)[0]
  self.assertIn('<h3>Wallaby Wallet</h3>',card);self.assertIn('Open Wallaby Wallet securely from this computer. Bitcoin Core is not required.',card);self.assertIn('/wallaby-wallet.svg',card);self.assertNotIn('Wallaby Wallet Server',card);self.assertIn('<title>Wallaby Wallet</title>',(root/'web/wallaby-wallet.svg').read_text())
