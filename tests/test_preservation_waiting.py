"""Missing archive history is a receiving workflow, not automatic reindexing."""
from pathlib import Path
from unittest.mock import patch
from fixture_signer_restoration import OriginalRoles
from wallet_retirement import Retirement,MissingHistory
from wallet_ops import rpc
from approval_store import digest

class Waiting(OriginalRoles):
 def request(self):
  p={'kind':'wallet_retire','phase':'preserve','wallet':'Wallaby Extinct'};key='a'*64
  with self.store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
  return key,Retirement(self.receiver.core,self.store)
 def test_deleted_archive_returns_receive_guidance_without_creating_recovery(self):
  key,r=self.request();f=r.review(key)['retirement']
  self.assertTrue(f['history_transfer_first']);self.assertFalse(f['archive_present']);self.assertEqual(f['existing_transactions'],0)
  self.assertFalse(self.store.read().get('history_jobs'));self.assertNotIn('Wallaby Extinct',rpc(self.receiver.core,'listwallets'))
 def test_partial_archive_returns_receive_guidance_and_keeps_unloaded_state(self):
  rpc(self.receiver.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True});rpc(self.receiver.core,'unloadwallet',{'wallet_name':'Wallaby Extinct'})
  key,r=self.request()
  with patch('retirement_phases.review',side_effect=MissingHistory('Incomplete local history')):f=r.review(key)['retirement']
  self.assertTrue(f['archive_present']);self.assertTrue(f['history_transfer_first']);self.assertNotIn('Wallaby Extinct',rpc(self.receiver.core,'listwallets'));self.assertFalse(self.store.read().get('history_jobs'))
 def test_already_authorised_recovery_still_uses_its_existing_path(self):
  key,r=self.request()
  with self.store.edit() as s:s['history_jobs']={digest({'local_retirement_history':key}):{'state':'pending'}}
  f=r.review(key)['retirement'];self.assertTrue(f['history_prepared']);self.assertFalse(f['history_transfer_first'])
 def test_received_history_is_rechecked_instead_of_reusing_missing_history_review(self):
  key,r=self.request();self.assertTrue(r.review(key)['retirement']['history_required'])
  rpc(self.receiver.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True})
  with patch('retirement_phases.review',return_value={'phase':'preserve','history_method':'existing'}):f=r.review(key)['retirement']
  self.assertNotIn('history_required',f);self.assertEqual(f['history_method'],'existing')
