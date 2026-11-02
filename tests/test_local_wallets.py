"""Destructive local controls tested only against isolated regtest wallets."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from local_wallets import LocalWallets
from wallet_ops import rpc
from wallet_deletion import remove
from regtest_support import Regtest

class LocalDeletion(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;self.base=Path(self.core.config['cookie']).parent/'wallets';self.manager=LocalWallets(self.core,lambda:None);self.allowed=patch('wallet_deletion.bases',return_value=[self.base]);self.allowed.start();self.addCleanup(self.allowed.stop)
 def restart(self):
  import subprocess,time
  args=self.node.process.args;rpc(self.core,'stop');self.node.process.wait(timeout=20);self.node.process=subprocess.Popen(args,stdout=self.node.log,stderr=subprocess.STDOUT)
  for _ in range(100):
   try:self.core.ready();return
   except Exception:time.sleep(.1)
  self.fail('Isolated Core restart failed')
 def deletion(self,source,manual=False):
  self.assertTrue(manual);return remove(source,[self.base],allow_extinct=True)
 def test_watch_copy_deletion_requires_explicit_fresh_local_confirmation(self):
  rpc(self.core,'createwallet',{'wallet_name':'Watch mistake','disable_private_keys':True});rows=self.manager.listing()['wallets'];row=next(r for r in rows if r['wallet']=='Watch mistake');self.assertFalse(row['private_keys_enabled']);self.assertEqual(row['sats'],'0');self.assertTrue(row['deletable']);review=self.manager.review('Watch mistake');self.assertTrue((self.base/'Watch mistake/wallet.dat').exists())
  with patch('wallet_deletion.delete',side_effect=self.deletion) as helper:
   with self.assertRaises(ValueError):self.manager.delete(review['token'],False)
   helper.assert_not_called();self.assertIn('Watch mistake',rpc(self.core,'listwallets'))
   self.manager.delete(review['token'],True);self.assertEqual(helper.call_count,1)
   with self.assertRaises(ValueError):self.manager.delete(review['token'],True)
   self.assertEqual(helper.call_count,1)
  self.assertFalse((self.base/'Watch mistake').exists());self.assertNotIn('Watch mistake',rpc(self.core,'listwallets'))
 def test_private_wallet_balance_is_exact_and_only_chosen_wallet_is_deleted(self):
  rpc(self.core,'createwallet',{'wallet_name':'Signing account','passphrase':'test password','load_on_startup':True});rpc(self.core,'createwallet',{'wallet_name':'Other wallet','load_on_startup':True});address=rpc(self.core,'getnewaddress',[],'Signing account');mine=rpc(self.core,'getnewaddress',[],'Other wallet');rpc(self.core,'generatetoaddress',[101,mine]);rpc(self.core,'sendtoaddress',[address,'0.125'],'Other wallet');rpc(self.core,'generatetoaddress',[1,mine]);row=next(r for r in self.manager.listing()['wallets'] if r['wallet']=='Signing account');self.assertEqual(row['sats'],'12500000');self.assertTrue(row['private_keys_enabled']);review=self.manager.review('Signing account')
  with patch('wallet_deletion.delete',side_effect=self.deletion):self.manager.delete(review['token'],True)
  self.assertFalse((self.base/'Signing account').exists());self.assertTrue((self.base/'Other wallet/wallet.dat').exists());self.restart();self.assertNotIn('Signing account',rpc(self.core,'listwallets'));self.assertIn('Other wallet',rpc(self.core,'listwallets'))
 def test_changed_wallet_and_expired_review_never_reach_delete(self):
  rpc(self.core,'createwallet',{'wallet_name':'Changed'});r=self.manager.review('Changed');rpc(self.core,'getnewaddress',[],'Changed')
  with patch('wallet_deletion.delete') as helper:
   with self.assertRaisesRegex(ValueError,'changed'):self.manager.delete(r['token'],True)
   helper.assert_not_called();r=self.manager.review('Changed')
   with patch('local_wallets.time.monotonic',return_value=self.manager.reviews[r['token']][2]+121):
    with self.assertRaisesRegex(ValueError,'expired'):self.manager.delete(r['token'],True)
   helper.assert_not_called()
 def test_unavailable_or_uncertain_delete_is_not_replayed_and_guards_run(self):
  rpc(self.core,'createwallet',{'wallet_name':'Uncertain'});r=self.manager.review('Uncertain')
  with patch('wallet_deletion.delete',side_effect=ValueError('injected uncertain helper')) as helper:
   with self.assertRaisesRegex(ValueError,'not confirmed'):self.manager.delete(r['token'],True)
   with self.assertRaises(ValueError):self.manager.delete(r['token'],True)
   self.assertEqual(helper.call_count,1)
  self.assertTrue((self.base/'Uncertain/wallet.dat').exists());rpc(self.core,'loadwallet',['Uncertain']);self.manager.guard=lambda:(_ for _ in ()).throw(ValueError('Active work'))
  with self.assertRaisesRegex(ValueError,'Active work'):self.manager.review('Uncertain')
 def test_custom_directories_are_disabled_and_retirement_reserved_guard_is_unchanged(self):
  rpc(self.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True});r=self.manager.review('Wallaby Extinct');source=self.manager.reviews[r['token']][1]
  with self.assertRaises(ValueError):remove(source,[self.base])
  with patch('wallet_deletion.bases',return_value=[]):
   row=self.manager.listing()['wallets'][0];self.assertFalse(row['deletable'])
   with self.assertRaises(ValueError):self.manager.review('Wallaby Extinct')
  with patch('wallet_deletion.delete',side_effect=self.deletion):self.manager.delete(r['token'],True)

class RemoteBoundary(unittest.TestCase):
 def test_dashboard_rpc_and_proposals_cannot_request_manual_deletion(self):
  from agent_rpc import request
  from vault_policy import validate_proposal
  for method in ('local_wallets.list','local_wallets.review','local_wallets.delete'):
   with self.subTest(method=method),self.assertRaises(ValueError):request(method,[],None)
  with self.assertRaises(ValueError):validate_proposal({'kind':'local_wallets.delete','wallet':'Victim'})
