"""Unified wallet rows keep local policy identity and live direct authority separate."""
import copy
from unittest.mock import patch,Mock
from test_build70 import Offers
from approval_store import digest
from sync_offers import apply
from sync_queue import apply_snapshot,rows
from sync_preferences import change,enable,policy_id
from sync_table import state,observe,choose,direct_ready

class Table(Offers):
 def test_all_local_offered_and_denied_wallets_sort_together_and_count_once(self):
  observe(self.store,'listwallets',None,['Zebra local','alpha local'])
  apply(self.store,self.snapshot,'session')
  r=state(self.store,[]);self.assertEqual([x['wallet_name'] for x in r['wallets']],['alpha local','Other family wallet','Zebra local']);self.assertEqual(r['pending_count'],1)
  change(self.store,self.offer['id'],True);r=state(self.store,[]);self.assertEqual(len(r['wallets']),3);self.assertEqual(r['pending_count'],0);self.assertTrue(r['wallets'][1]['denied'])
  # Server can withdraw the offer after learning the denial; its row stays.
  with self.store.edit() as s:s['sync_offers']={}
  self.assertEqual(len(state(self.store,[])['wallets']),3)
  enable(self.store,policy_id(self.p));self.assertEqual(state(self.store,[])['pending_count'],0)
 def test_local_inventory_matches_exact_policy_and_unloads_stale_names(self):
  observe(self.store,'listwallets',None,['Local Wallet']);observe(self.store,'listdescriptors','Local Wallet',self.p['public_wallet']);observe(self.store,'getwalletinfo','Local Wallet',{'private_keys_enabled':True});apply(self.store,self.snapshot,'session')
  r=state(self.store,[]);self.assertEqual(len(r['wallets']),1);self.assertEqual(r['wallets'][0]['wallet_name'],'Local Wallet');self.assertTrue(r['wallets'][0]['local_private'])
  observe(self.store,'listwallets',None,[]);self.assertFalse(state(self.store,[])['wallets'][0]['local_wallets'])
 def requests(self):
  second=copy.deepcopy(self.p);second['transfer_id']='2'*64;second['peer']['node_id']='different';second['peer']['hostname']='Second Agent';apply_snapshot(self.store,1,[self.p,second]);return digest(self.p),digest(second)
 def test_peer_options_deduplicate_wallet_and_offline_route_never_creates_choice(self):
  first,second=self.requests();before=self.store.read();r=state(self.store,rows(self.store));self.assertEqual(len(r['wallets']),1);self.assertEqual(r['pending_count'],1);self.assertEqual(len(r['wallets'][0]['receive']),2);self.assertFalse(any(x['direct_ready'] for x in r['wallets'][0]['receive']))
  with self.assertRaisesRegex(ValueError,'No Agent Detected'):choose(self.store,first,True,False)
  self.assertEqual(before,self.store.read())
 def test_switch_peer_is_atomic_and_force_watch_only_sources(self):
  first,second=self.requests()
  with patch('sync_table.direct_ready',return_value=True):
   choose(self.store,first,True,False);choose(self.store,second,True,True)
  choices=self.store.read()['sync_choices'];self.assertFalse(choices[first]['selected']);self.assertTrue(choices[second]['selected']);self.assertTrue(choices[second]['watch_only'])
  with self.store.edit() as s:s['pending'][second]['proposal']['source_has_private_keys']=False
  with patch('sync_table.direct_ready',return_value=True):choose(self.store,second,True,False)
  self.assertTrue(self.store.read()['sync_choices'][second]['watch_only'])
 def test_direct_readiness_requires_exact_local_channel_and_direct_connection(self):
  p=copy.deepcopy(self.p);p['transfer_version']=3;peer=Mock();self.store.peers=peer
  peer.binding.return_value='exact-channel';self.assertTrue(direct_ready(self.store,p));peer.binding.assert_called_with(p);peer.direct.require.assert_called_with('exact-channel')
  peer.direct.require.side_effect=ValueError('Offline');self.assertFalse(direct_ready(self.store,p));self.assertFalse(direct_ready(self.store,self.p))
 def test_sending_does_not_get_hidden_by_receive_denial_and_attempts_not_counted(self):
  send=copy.deepcopy(self.snapshot);send['offers'][0]['direction']='send';apply(self.store,send,'session')
  with self.store.edit() as s:s['sync_exclusions']={policy_id(self.p):{'policy_id':policy_id(self.p),'wallet_name':'Other family wallet'}}
  self.assertEqual(state(self.store,[])['pending_count'],1)

 def test_multiple_multisig_accounts_are_one_wallet_with_separate_signer_labels(self):
  from vendor.embit import ec
  from vendor.embit.descriptor.checksum import checksum
  keys=[ec.PrivateKey(bytes([n])*32).get_public_key().sec().hex() for n in (1,2,3)]
  desc='wsh(sortedmulti(2,'+','.join(keys)+'))';raw={'wallet_name':'Treasury','descriptors':[{'desc':desc+'#'+checksum(desc)}]}
  observe(self.store,'listwallets',None,['Treasury Russia Signer','Treasury Australia Signer'])
  for name,label in [('Treasury Russia Signer','Russia'),('Treasury Australia Signer','Australia')]:
   observe(self.store,'listdescriptors',name,raw);observe(self.store,'getwalletinfo',name,{'private_keys_enabled':True,'wallaby_managed':{'logical_name':'Treasury','role_name':label}})
  r=state(self.store,[]);self.assertEqual(len(r['wallets']),1);self.assertEqual(r['wallets'][0]['wallet_name'],'Treasury');self.assertTrue(r['wallets'][0]['multisig']);self.assertEqual({s['label'] for s in r['wallets'][0]['signers']},{'Russia','Australia'});self.assertEqual(r['pending_count'],0)

 def test_legacy_multiple_peer_selection_cannot_silently_transfer_both(self):
  first,second=self.requests()
  from batch_transfer import BatchTransfer
  target=Mock();target.store=self.store
  with self.assertRaisesRegex(ValueError,'one peer'):
   BatchTransfer.validate_batch(target,[first,second],'receive')
