"""In-flight previews must not override a user's local synchronisation denial."""
import copy,tempfile,unittest
from unittest.mock import patch
from approval_store import Store,digest
from sync_queue import apply_snapshot,rows
from sync_preferences import change,enable,policy_id
from wallet_preview import receive
from agent_exchange import Exchange
from test_build8 import paired,signed
from vendor.embit.descriptor.checksum import checksum

class PreviewDenialRace(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.requests=[]
  for i in range(11):
   p=paired('Wallet '+str(i));body=p['public_wallet']['descriptors'][0]['desc'].split('#')[0].replace('/0/*','/'+str(i)+'/*');p['public_wallet']['descriptors'][0]['desc']=body+'#'+checksum(body);self.requests.append(p)
  apply_snapshot(self.store,1,self.requests)
 def preview(self,p):return signed(self.store,p,{'public_wallet':p['public_wallet'],'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]})
 def test_eleven_rows_then_one_locally_enabled_then_eleven_again(self):
  self.assertEqual(len(rows(self.store)),11)
  for p in self.requests[:-1]:change(self.store,digest(p),True)
  for p in self.requests[:-1]:
   result=receive(self.store,self.preview(p));self.assertEqual(result['ignored'],'locally_disabled')
  self.assertEqual(len(rows(self.store)),1);self.assertFalse(self.store.read().get('transfer_previews'))
  for p in self.requests[:-1]:enable(self.store,policy_id(p))
  self.assertEqual(len(rows(self.store)),11)
  for p in self.requests:receive(self.store,self.preview(p))
  self.assertEqual(len(self.store.read()['transfer_previews']),11)
 def test_disabled_preview_does_not_block_other_preview_or_outbox_acknowledgement(self):
  p,other=self.requests[:2];payload=self.preview(p);change(self.store,digest(p),True);ack=self.store.queue('node_identity',{'ipv6':'2001:db8::1'});response={'version':1,'accepted':[ack],'proposals':[{'kind':'wallet_sync_queue','revision':2,'requests':self.requests},{'kind':'wallet_transfer_preview',**payload},{'kind':'wallet_transfer_preview',**self.preview(other)}]}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value=response):Exchange(1,'test-token',self.store).once()
  state=self.store.read();self.assertNotIn(ack,state['outbox']);self.assertNotIn(digest(p),state['pending']);self.assertNotIn(digest(p),state['transfer_previews']);self.assertIn(digest(other),state['transfer_previews']);self.assertTrue(state['last_exchange'])
 def test_disabled_previews_still_require_signature_exact_policy_and_peer_binding(self):
  p=self.requests[0];change(self.store,digest(p),True);payload=self.preview(p);bad=copy.deepcopy(payload);bad['preview']['receiver_ipv6']='2001:db8::99'
  with self.assertRaises(ValueError):receive(self.store,bad)
  altered=copy.deepcopy(p);altered['preview_challenge']='f'*64
  with self.assertRaisesRegex(ValueError,'does not match'):receive(self.store,self.preview(altered))
  unknown=paired('Unknown')
  with self.assertRaisesRegex(ValueError,'No unique'):receive(self.store,self.preview(unknown))
  self.assertNotIn(digest(p),self.store.read()['pending']);self.assertFalse(self.store.read().get('transfer_previews'))
 def test_without_authoritative_snapshot_unpaired_preview_is_still_refused(self):
  p=self.requests[0];payload=self.preview(p)
  with self.store.edit() as s:s.pop('sync_snapshot_requests');s['pending'].pop(digest(p));s['sync_exclusions']={policy_id(p):{'policy_id':policy_id(p),'wallet_name':'Excluded'}}
  with self.assertRaisesRegex(ValueError,'No unique'):receive(self.store,payload)
