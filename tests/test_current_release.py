"""Regressions for the maintained release baseline."""
import unittest,time
from unittest.mock import patch
import fixture_encrypted_peers as pairing
from approval_store import digest

class Heartbeat(unittest.TestCase):
 setUp=pairing.Pairing.setUp
 peer=pairing.Pairing.peer
 pair=pairing.Pairing.pair
 move=pairing.Pairing.move
 def test_periodic_authenticated_heartbeat_retains_comparison_capability(self):
  self.pair();a=self.a.channel(self.b.identity['identity_key']);b=self.b.channel(self.a.identity['identity_key']);a.features=set();self.b.registered=True
  def rpc(body):
   if body['action']=='send':self.a.accept(body['frame'],[self.b.identity])
   return {'endpoints':[]} if body['action']=='directory' else {'frames':[]} if body['action']=='receive' else {}
  self.b.rpc=rpc
  b.pinged=0;self.b.tick();self.move(self.b,self.a);self.assertIn('extinct_compare_v1',a.features)
  b.send('ping',digest(b.prologue),{'nonce':'metadata','device_name':'Source'});self.move(self.b,self.a);self.assertIn('extinct_compare_v1',a.features)
  a.features=set();b.send('pong',digest(b.prologue),{'nonce':'fixture','device_name':'Source','features':['extinct_compare_v1']});self.move(self.b,self.a);self.assertEqual(a.features,set())
 def test_only_current_qr_workflow_is_accepted(self):
  from setup_messages import sign
  from peer_protocol import INVITATION
  invite=self.a.create_invitation('connect',self.route);self.assertEqual(invite['message']['version'],3)
  for version in (1,2):
   message=dict(invite['message'],version=version);message.pop('pairing_mode')
   if version==1:message.pop('issuer_name')
   with self.assertRaises(ValueError):self.b.import_invitation(sign(self.a.store,message,INVITATION))
 def test_obsolete_combined_retirement_protocol_is_rejected(self):
  from wallet_retirement import validate
  for version in (1,2):
   with self.assertRaises(ValueError):validate({'kind':'wallet_retire','version':version})

 def test_obsolete_wallet_transfer_protocol_is_rejected_even_when_queued(self):
  from fixture_public_policy import paired
  from public_policy import proposal
  from peer_compatibility import require_current
  p=paired();key=digest(p)
  with self.a.store.edit() as saved:saved['pending'][key]={'proposal':p,'state':'pending'}
  with self.assertRaisesRegex(ValueError,'current direct'):proposal(p)
  with self.assertRaisesRegex(ValueError,'current direct'):require_current(self.a.store,p)
