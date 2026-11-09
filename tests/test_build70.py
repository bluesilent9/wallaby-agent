"""Public offers remain visible without pairing and never grant transfer authority."""
import copy,tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store,digest
from sync_offers import validate,apply,rows
from sync_preferences import change,enable,policy_id
from denial_storage import FileStore
from test_build8 import paired

class Offers(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);disk=self.root/'disk';disk.mkdir(mode=0o700);self.backend=FileStore(disk);self.store=Store(self.root/'ram',persistence=self.backend)
  self.p=paired('Other family wallet');self.offer={'id':'1'*64,'transfer_id':self.p['transfer_id'],'direction':'receive','peer':{k:self.p['peer'][k] for k in ('node_id','hostname')},'public_wallet':self.p['public_wallet'],'status':'secure_pairing_required'};self.snapshot={'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[self.offer]}
 def test_unpaired_offer_has_no_pending_approval_selection_or_transfer_authority(self):
  apply(self.store,self.snapshot,'session');shown=rows(self.store);saved=self.store.read()
  self.assertEqual(len(shown),1);self.assertIsNone(shown[0]['request_id']);self.assertFalse(saved['pending']);self.assertNotIn('active_transfer',saved);self.assertNotIn('sync_batch',saved);self.assertFalse(saved['outbox'])
  with self.assertRaisesRegex(ValueError,'not authorisation'):self.store.receive(self.snapshot)
  from peer_compatibility import require_current
  require_current(self.store,self.snapshot)
 def test_exchange_applies_offer_without_receive_or_core_pairing_actions(self):
  from agent_exchange import Exchange
  response={'version':1,'accepted':[],'proposals':[{'kind':'wallet_sync_queue','revision':1,'requests':[]},self.snapshot]}
  with patch('agent_exchange.http_json',return_value=response),patch('agent_exchange.local_ipv6',return_value=None),patch.object(self.store,'receive') as receive:Exchange(1,'fixture',self.store).once()
  receive.assert_not_called();self.assertEqual(len(rows(self.store)),1);self.assertFalse(self.store.read()['pending'])
 def test_deny_before_pairing_survives_new_workspace_and_other_source(self):
  apply(self.store,self.snapshot,'session');change(self.store,self.offer['id'],True);ident=policy_id(self.offer)
  self.assertFalse(rows(self.store));saved=self.backend.read();self.assertIn(ident,saved['wallets']);self.assertNotIn('descriptors',json.dumps(saved))
  second=Store(self.root/'second-ram',persistence=self.backend);new=copy.deepcopy(self.snapshot);new['offers'][0]['id']='2'*64;new['offers'][0]['peer']['hostname']='Another source';apply(second,new,'new-session')
  self.assertFalse(rows(second));self.assertIn(ident,second.read()['sync_exclusions']);enable(second,ident);self.assertEqual(len(rows(second)),1);self.assertFalse(second.read()['pending'])
 def test_send_offer_cannot_create_incoming_denial(self):
  p=copy.deepcopy(self.snapshot);p['offers'][0]['direction']='send';apply(self.store,p,'session')
  with self.assertRaises(ValueError):change(self.store,self.offer['id'],True)
  self.assertFalse(self.backend.read()['wallets'])
 def test_offer_links_only_exact_existing_request_without_creating_one(self):
  from sync_queue import apply_snapshot
  apply(self.store,self.snapshot,'session');apply_snapshot(self.store,1,[self.p]);self.assertEqual(rows(self.store)[0]['request_id'],digest(self.p))
  p=copy.deepcopy(self.snapshot);p['revision']=2;p['offers'][0]['peer']['node_id']='another';apply(self.store,p,'session');self.assertIsNone(rows(self.store)[0]['request_id']);self.assertEqual(len(self.store.read()['pending']),1)
 def test_stale_conflicting_retired_sessions_private_keys_and_duplicate_ids_refused(self):
  apply(self.store,self.snapshot,'one');bad=copy.deepcopy(self.snapshot);bad['offers'][0]['status']='ready'
  with self.assertRaises(ValueError):apply(self.store,bad,'one')
  apply(self.store,self.snapshot,'two')
  with self.assertRaises(ValueError):apply(self.store,self.snapshot,'one')
  for field,value in [('revision',True),('offers',[self.offer,self.offer])]:
   bad=copy.deepcopy(self.snapshot);bad[field]=value
   with self.assertRaises(ValueError):validate(bad)
  bad=copy.deepcopy(self.snapshot);bad['offers'][0]['public_wallet']['descriptors'][0]['desc']='wpkh(private-key-no-checksum)'
  with self.assertRaises(ValueError):validate(bad)
 def test_existing_attempted_transfer_cannot_be_erased_by_denying_its_offer(self):
  from sync_queue import apply_snapshot
  apply(self.store,self.snapshot,'session');apply_snapshot(self.store,1,[self.p])
  with self.store.edit() as s:s['pending'][digest(self.p)]['state']='attempted'
  before=self.store.read()
  with self.assertRaises(ValueError):change(self.store,self.offer['id'],True)
  self.assertEqual(before,self.store.read())

class Compatibility(Offers):
 def test_only_optional_offer_capability_falls_back_once_on_exact_legacy_refusal(self):
  from agent_exchange import Exchange
  from node_client import HTTPFailure
  response={'version':1,'accepted':[],'proposals':[]};calls=[]
  def http(port,path,body,*args,**kwargs):
   calls.append(copy.deepcopy(body))
   if len(calls)==1:raise HTTPFailure(400,'capabilities')
   return response
  with patch('agent_exchange.http_json',side_effect=http),patch('agent_exchange.local_ipv6',return_value=None):
   client=Exchange(1,'fixture',self.store);client.once();client.once()
  self.assertIn('wallet_sync_offers_v1',calls[0]['capabilities']);self.assertNotIn('wallet_sync_offers_v1',calls[1]['capabilities']);self.assertEqual(calls[1]['capabilities'],calls[2]['capabilities']);self.assertEqual(set(calls[0]['capabilities'])-set(calls[1]['capabilities']),{'wallet_sync_offers_v1'});self.assertIs(self.store.read()['sync_offer_server_support'],False);self.assertFalse(self.store.read()['pending'])
 def test_other_errors_are_not_treated_as_permission_to_remove_capabilities(self):
  from agent_exchange import Exchange
  from node_client import HTTPFailure
  with patch('agent_exchange.http_json',side_effect=HTTPFailure(400,'identity_conflict')) as http,patch('agent_exchange.local_ipv6',return_value=None),self.assertRaises(HTTPFailure):Exchange(1,'fixture',self.store).once()
  self.assertEqual(http.call_count,1)
