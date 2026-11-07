"""Persistent, independent lifecycle denials; cancellation never creates one."""
import copy,tempfile,unittest
from pathlib import Path
from approval_store import Store,digest
from denial_storage import FileStore
from lifecycle_preferences import deny,cancel,enable,blocked
from local_extinction import prepare,complete
from test_build30 import proposal,public
from test_build8 import paired
from sync_queue import apply_snapshot

class Preferences(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);disk=self.root/'disk';disk.mkdir(mode=0o700);self.disk=FileStore(disk);self.store=Store(self.root/'ram',persistence=self.disk)
  from vendor.embit.descriptor import Descriptor
  from vendor.embit.networks import NETWORKS
  address=Descriptor.from_string(public('Old')['descriptors'][0]['desc'].split('#')[0]).derive(0).script_pubkey().address(NETWORKS['regtest'])
  self.p=proposal(public('Old'),{'addresses':[{'address':address,'label':'Old'}],'transactions':[{'txid':'a'*64,'blockhash':'b'*64}]},'preserve','Wallaby Extinct')
 def test_extinction_denial_survives_restart_and_changed_operation_but_not_other_policy(self):
  key=digest(self.p);self.store.receive(self.p);deny(self.store,key);reopened=Store(self.root/'next',persistence=self.disk)
  changed=copy.deepcopy(self.p);changed['operation_id']='e'*64;changed['request_id']=digest({k:v for k,v in changed.items() if k!='request_id'})
  self.assertFalse(reopened.receive(changed));self.assertFalse(reopened.read()['pending']);self.assertEqual(len(reopened.read()['request_denials']),1)
  ident=next(iter(reopened.read()['request_denials']));enable(reopened,ident);self.assertTrue(reopened.receive(changed))
 def test_cancel_dismisses_without_deny_and_same_request_can_return(self):
  key=digest(self.p);self.store.receive(self.p);cancel(self.store,key);self.assertFalse(self.store.read()['request_denials']);self.assertTrue(self.store.receive(self.p))
 def test_restore_denial_is_separate_from_extinction_and_ordinary_sync(self):
  ident=prepare(self.store,self.p,['Old']);complete(self.store,ident)
  transfer=paired('Old');transfer['public_wallet']=self.p['public_wallet'];self.store.receive(transfer);key=digest(transfer);deny(self.store,key)
  self.assertTrue(blocked(self.store.read(),transfer));self.assertFalse(blocked(self.store.read(),self.p))
  other=paired('Different');other['public_wallet']['descriptors'][0]['desc']=other['public_wallet']['descriptors'][0]['desc'].split('#')[0].replace('/0/*','/1/*');from vendor.embit.descriptor.checksum import checksum;other['public_wallet']['descriptors'][0]['desc']+='#'+checksum(other['public_wallet']['descriptors'][0]['desc']);self.assertFalse(blocked(self.store.read(),other));apply_snapshot(self.store,1,[transfer,other]);self.assertNotIn(key,self.store.read()['pending']);self.assertIn(digest(other),self.store.read()['pending'])
 def test_attempted_request_cannot_be_denied_or_cancelled(self):
  key=digest(self.p);self.store.receive(self.p)
  with self.store.edit() as s:s['pending'][key]['state']='attempted'
  for action in (deny,cancel):
   with self.assertRaises(ValueError):action(self.store,key)
  self.assertFalse(self.store.read()['request_denials']);self.assertEqual(self.store.read()['pending'][key]['state'],'attempted')
 def test_private_or_unknown_fields_cannot_be_persisted(self):
  value=self.disk.read();value['request_denials']={'a'*64:{'policy_id':'a'*64,'purpose':'restoration','wallet_name':'Old','psbt':'forbidden'}};value['revision']+=1
  with self.assertRaises(ValueError):self.disk.commit(0,value)
