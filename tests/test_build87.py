"""Automatic direct Agent identities and deletion without hash transcription."""
import copy,time,unittest
from unittest.mock import Mock,patch
import test_build66 as pairing_fixture
import test_build81 as deletion_fixture

class DirectIdentity(unittest.TestCase):
 setUp=pairing_fixture.Pairing.setUp
 peer=pairing_fixture.Pairing.peer
 move=pairing_fixture.Pairing.move
 pair=pairing_fixture.Pairing.pair
 def test_paired_identity_requires_live_direct_and_cannot_be_supplied_manually(self):
  from direct_identity import require,require_fingerprint
  from wallet_preview import fingerprint
  self.pair();key=self.b.identity['identity_key']
  with self.assertRaises(ValueError):require(self.a.store,key)
  direct=Mock();self.a.direct=direct
  self.assertEqual(require(self.a.store,key),key);direct.require.assert_called_once_with(self.a.channel(key))
  self.assertEqual(require_fingerprint(self.a.store,fingerprint(key)),key)
  foreign=self.peer('server-substitute').identity['identity_key']
  with self.assertRaises(ValueError):require(self.a.store,foreign)
  with self.assertRaises(ValueError):require_fingerprint(self.a.store,fingerprint(foreign))
  direct.require.side_effect=ValueError('Direct connection unavailable')
  with self.assertRaisesRegex(ValueError,'unavailable'):require(self.a.store,key)
  self.a.revoke(self.b.identity['endpoint_id'])
  with self.assertRaises(ValueError):require(self.a.store,key)
 def test_local_identity_needs_no_remote_peer_and_mobile_cannot_confirm_agent(self):
  from direct_identity import require
  self.assertEqual(require(self.a.store,self.a.identity['identity_key']),self.a.identity['identity_key'])
  mobile=self.peer('mobile-only','mobile');invite=self.a.create_invitation('mobile',self.route);mobile.import_invitation(invite);self.move(mobile,self.a);self.move(self.a,mobile);self.move(mobile,self.a);self.a.approve(mobile.identity['endpoint_id']);self.move(self.a,mobile);self.a.direct=Mock()
  with self.assertRaises(ValueError):require(self.a.store,mobile.identity['identity_key'])
 def test_policy_confirmation_cannot_be_queued_on_server_relay(self):
  self.pair();channel=self.a.channel(self.b.identity['identity_key']);before=len(self.a.outgoing)
  with self.assertRaises(ValueError):channel.send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64})
  self.assertEqual(len(self.a.outgoing),before)
 def test_disc_cleanup_uses_direct_identity_and_still_requires_local_disc_read(self):
  from archive_cancel import Cancellations
  from approval_store import digest
  from wallet_preview import fingerprint
  from types import SimpleNamespace
  self.pair();cleanup=Cancellations(SimpleNamespace(store=self.a.store,archives=SimpleNamespace(catalogs={})))
  p={'archive_request':{'fixture':'exact-archive'}};cleanup.foreign_authors[digest(p['archive_request'])]={fingerprint(self.b.identity['identity_key'])};facts={'disc_created':False}
  with self.assertRaises(ValueError):cleanup.authorise(p,facts,fingerprint(self.b.identity['identity_key']))
  self.a.direct=Mock();cleanup.authorise(p,facts,None)
  facts.update(disc_created=True,archive_id='a'*64,members=[])
  with self.assertRaisesRegex(ValueError,'Read the original'):cleanup.authorise(p,facts,None)
 def test_manual_setup_values_cannot_bypass_direct_trust_before_key_generation(self):
  from wallet_setup import WalletSetup
  owner=WalletSetup.__new__(WalletSetup);owner.enforce=Mock();owner.core=object();owner.store=Mock();owner.own_identity=Mock(return_value={'public_key':self.a.identity['identity_key']})
  proposal={'kind':'wallet_setup','chain':'regtest'};owner.store.read.return_value={'pending':{'request':{'proposal':proposal,'state':'pending'}}}
  with patch('wallet_setup.proposal',return_value=proposal),patch('wallet_setup.rpc',return_value={'chain':'regtest'}),patch('peer_mesh.observe'),patch('peer_mesh.pins',side_effect=ValueError('Direct Agent is unavailable')) as trust,patch('wallet_setup.MemoryCore') as generate:
   with self.assertRaisesRegex(ValueError,'unavailable'):owner.approve_proposal('request',{'SHA256:server-value':'SHA256:server-value'})
   trust.assert_called_once();generate.assert_not_called()

class DeleteWithoutFingerprint(deletion_fixture.DeletionEvidence):
 def test_verified_empty_wallet_deletes_without_fingerprint_and_preserves_archive(self):
  from wallet_ops import rpc
  from wallet_deletion import remove
  from pathlib import Path
  owner,p,key=self.prepare();facts=owner.review(key)['retirement']
  self.assertTrue(facts['history_comparison']['verified']);self.assertNotIn('preservation_fingerprint',facts)
  before=rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount']
  with patch('wallet_deletion.delete',side_effect=lambda record:remove(record,[Path(record['path']).parent])):
   owner.approve(key)
  self.assertNotIn('Old',[w['name'] for w in rpc(self.core,'listwalletdir')['wallets']]);self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],before)
 def test_invalid_preservation_signature_still_blocks_before_deletion(self):
  from wallet_ops import rpc
  owner,p,key=self.prepare();bad=copy.deepcopy(p);bad['preservation']['receipt']['signature']='AAAA'
  with patch('retirement_phases.validate',return_value=bad),patch('wallet_deletion.delete') as delete:
   from retirement_phases import review
   with self.assertRaises(ValueError):review(self.core,self.store,bad)
   delete.assert_not_called()
  self.assertIn('Old',rpc(self.core,'listwallets'))

class FingerprintFreeAPI(unittest.TestCase):
 def setUp(self):
  from test_build31 import ProtectedCancellationAPI
  ProtectedCancellationAPI.setUp(self)
 def test_actions_accept_only_review_and_confirmation_fields(self):
  routes=[('retire',{'id':'exact-review'},'retirement.approve'),('participate',{'id':'exact-review'},'setup.participate'),('retire-disc',{'id':'exact-review','confirmed':True},'archive.retire_stage'),('destroy-retired-disc',{'id':'exact-review','confirmed':True},'archive.retire_destroyed'),('destroy-disc',{'id':'exact-review','confirmed':True},'archive.destroyed'),('cancel-archive-stage',{'id':'exact-review','confirmed':True},'archive.cancel_stage')]
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   for route,body,method in routes:
    with self.subTest(route=route):
     code,value=self.fixture.call('/api/authorise/'+route,body);self.assertEqual(code,200,value);self.assertEqual(call.call_args.args,(method,*body.values()))
     before=call.call_count;code,value=self.fixture.call('/api/authorise/'+route,{**body,'fingerprint':'SHA256:server-value'});self.assertEqual(code,400);self.assertEqual(call.call_count,before)
 def test_receive_approval_needs_no_identity_input(self):
  with patch('protected_memory.required',return_value=True),patch('protected_memory.inside',return_value=True),patch('secure_bridge.call',return_value={'ok':True}) as call:
   code,value=self.fixture.call('/api/synchronisation/authorise-batch',{});self.assertEqual(code,200,value);self.assertEqual(call.call_args.args,('transfer.authorise_batch',))
