"""Automatic QR discovery changes no role or secret-operation authority."""
import copy,json
from unittest.mock import Mock
from test_build66 import Pairing
from peer_protocol import endpoint
from protected_viewer import camera_permission_allowed

class AutomaticPairing(Pairing):
 def auto_pair(self,issuer,reader):
  invitation=issuer.create_invitation('auto',self.route);self.assertEqual(invitation['message']['version'],2);reader.import_invitation(invitation)
  self.move(reader,issuer);self.move(issuer,reader);self.move(reader,issuer)
  self.assertFalse(issuer.channels[reader.identity['endpoint_id']].local_grant);self.assertNotIn(reader.identity['endpoint_id'],issuer.persistence.read()['pairs'])
  issuer.approve(reader.identity['endpoint_id']);self.move(issuer,reader);self.move(reader,issuer);self.move(issuer,reader)
  self.assertTrue(issuer.channel(reader.identity['identity_key'],reader.identity['role']).ready)
  self.assertTrue(reader.channel(issuer.identity['identity_key'],issuer.identity['role']).ready)
  return invitation
 def test_one_automatic_agent_qr_accepts_agent_and_keeps_names(self):
  self.a.device_name='Treasury Australia';self.b.device_name='wallet-laptop';self.auto_pair(self.a,self.b)
  self.assertEqual(self.a.status()['pairs'][0]['name'],'wallet-laptop');self.assertEqual(self.b.status()['pairs'][0]['name'],'Treasury Australia')
 def test_same_automatic_agent_qr_format_detects_mobile_but_cannot_promote_it(self):
  phone=self.peer('phone','mobile');phone.device_name='Dad phone';self.auto_pair(self.a,phone)
  self.assertEqual(self.a.status()['pairs'][0]['role'],'mobile');self.assertEqual(self.a.status()['pairs'][0]['name'],'Dad phone')
  with self.assertRaises(ValueError):self.a.channel(phone.identity['identity_key'],'agent')
  phone.channel(self.a.identity['identity_key']).send('policy_agreement','a'*64,{'scope':'policy','digest':'b'*64})
  with self.assertRaisesRegex(ValueError,'Mobile'):self.move(phone,self.a)
 def test_agent_can_scan_mobile_generated_qr_without_mobile_to_mobile_authority(self):
  phone=self.peer('phone','mobile');self.auto_pair(phone,self.a)
  self.assertEqual(self.a.status()['pairs'][0]['role'],'mobile');self.assertEqual(phone.status()['pairs'][0]['role'],'agent')
  second=self.peer('second-phone','mobile');invitation=phone.create_invitation('auto',self.route)
  with self.assertRaises(ValueError):second.import_invitation(invitation)
 def test_tampering_role_name_version_and_expiry_never_adds_peer(self):
  invitation=self.a.create_invitation('auto',self.route)
  for field,value in [('issuer_role','mobile'),('issuer_name','Forged name'),('version',1),('expires_at',1),('issuer_name','invalid\nname')]:
   bad=copy.deepcopy(invitation);bad['message'][field]=value
   with self.assertRaises(ValueError):self.b.import_invitation(bad)
   self.assertFalse(self.b.channels);self.assertFalse(self.b.persistence.read()['pairs'])
 def test_mislabelled_directory_cannot_upgrade_a_mobile_identity(self):
  phone=self.peer('phone','mobile');invitation=self.a.create_invitation('auto',self.route);phone.import_invitation(invitation)
  forged={**phone.identity,'role':'agent','endpoint_id':endpoint('agent',phone.identity['identity_key'])}
  frame=next(iter(phone.outgoing.values()))
  with self.assertRaises(ValueError):self.a.accept(frame,[forged])
  self.assertFalse(self.a.persistence.read()['pairs'])
 def test_deleting_saved_connection_closes_channel_and_requires_new_qr(self):
  self.auto_pair(self.a,self.b);ident=self.b.identity['endpoint_id'];self.a.revoke(ident);self.assertFalse(self.a.status()['pairs']);self.assertNotIn(ident,self.a.channels)
 def test_camera_gate_refuses_audio_screen_and_other_origins(self):
  origin='http://[::1]:12345'
  self.assertTrue(camera_permission_allowed(origin,origin+'/',2,2))
  for request,kind in [('http://evil.test',2),('http://[::1]:12346',2),(origin,1),(origin,3),(origin,4)]:self.assertFalse(camera_permission_allowed(origin,request,kind,2))
