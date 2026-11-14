"""Temporary ownership inspection must restore only Agent-loaded wallets."""
import unittest
from unittest.mock import patch
from wallet_loading import ownership_wallets

class Loading(unittest.TestCase):
 def setUp(self):self.loaded={'Already open'};self.calls=[];self.fail_load=None;self.fail_unload=None
 def rpc(self,core,method,args=None,**kw):
  self.calls.append((method,args))
  if method=='listwallets':return sorted(self.loaded)
  if method=='listwalletdir':return {'wallets':[{'name':n} for n in ['Already open','A','B']]}
  if method=='loadwallet':
   self.assertEqual(set(args),{'filename'})
   if args['filename']==self.fail_load:raise ValueError('load failed')
   self.loaded.add(args['filename']);return {}
  if method=='unloadwallet':
   self.assertEqual(set(args),{'wallet_name'})
   if args['wallet_name']==self.fail_unload:raise ValueError('unload failed')
   self.loaded.remove(args['wallet_name']);return {}
  self.fail(method)
 def test_success_restores_state_without_changing_startup_preferences(self):
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with ownership_wallets(object()):self.assertEqual(self.loaded,{'Already open','A','B'})
  self.assertEqual(self.loaded,{'Already open'})
 def test_operation_failure_still_restores_temporarily_loaded_wallets(self):
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with self.assertRaisesRegex(ValueError,'conflicting owner'):
    with ownership_wallets(object()):raise ValueError('conflicting owner')
  self.assertEqual(self.loaded,{'Already open'})
 def test_partial_load_failure_restores_earlier_wallets(self):
  self.fail_load='B'
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with self.assertRaisesRegex(ValueError,'could not load'):
    with ownership_wallets(object()):self.fail('Operation must not run')
  self.assertEqual(self.loaded,{'Already open'})
 def test_cleanup_failure_does_not_claim_success(self):
  self.fail_unload='B'
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with self.assertRaisesRegex(ValueError,'could not restore'):
    with ownership_wallets(object()):pass
  self.assertEqual(self.loaded,{'Already open','B'})
 def test_source_candidate_scope_does_not_load_other_wallets(self):
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with ownership_wallets(object(),names={'A'}):self.assertEqual(self.loaded,{'Already open','A'})
  self.assertEqual(self.loaded,{'Already open'})
 def test_nested_checks_do_not_unload_outer_scopes_wallets(self):
  core=object()
  with patch('wallet_loading.rpc',side_effect=self.rpc),patch('wallet_loading.event'):
   with ownership_wallets(core):
    with ownership_wallets(core):self.assertEqual(self.loaded,{'Already open','A','B'})
    self.assertEqual(self.loaded,{'Already open','A','B'})
  self.assertEqual(self.loaded,{'Already open'})
