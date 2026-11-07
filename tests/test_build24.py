"""Reported exchange failures and one locally verified Extinct container."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from approval_store import Store,digest
from agent_exchange import Exchange
from node_client import HTTPFailure,exchange_http_reason
from wallet_ops import rpc
from regtest_support import Regtest
from wallet_labels import fixed_address
from extinct_sync import ARCHIVE,grouped,children,import_watch
from peer_wallet import wallet_details,source_wallet
from test_build8 import paired
from vendor.embit.descriptor.checksum import checksum

class ExchangeDiagnostics(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.exchange=Exchange(1,'never-log-this-token',self.store)
 def run_once(self,error=None):
  stop=Mock();stop.is_set.return_value=False;stop.wait.side_effect=lambda seconds:setattr(stop.is_set,'return_value',True)
  with patch.object(self.exchange,'once',side_effect=error),patch('activity_log.event') as log:self.exchange.run(stop)
  return stop,log
 def test_failure_waits_thirty_seconds_and_never_logs_raw_exception(self):
  self.exchange.phase='proposal_validation';self.exchange.proposal_kind='wallet_sync_queue';stop,log=self.run_once(ValueError('cookie=SECRET; xprv-SECRET wallet data'))
  stop.wait.assert_called_once_with(30);message=log.call_args.args[1];self.assertNotIn('SECRET',message);self.assertNotIn('never-log',message);self.assertIn('kind=wallet_sync_queue',message);self.assertIn('retry_s=30',message);self.assertEqual(self.store.read()['exchange_error']['code'],'exchange_invalid_data')
 def test_success_keeps_two_second_poll(self):
  stop,log=self.run_once();stop.wait.assert_called_once_with(2);log.assert_not_called()
 def test_exact_http_errors_get_useful_categories_but_arbitrary_text_does_not(self):
  for text,code in [('Unsupported Agent capabilities.','capabilities'),('Update Wallaby Agent to V2 Development Build 8 or later.','agent_version'),('Resolve the node identity conflict first.','identity_conflict'),('Connection expired. Register again.','session_expired')]:
   reason=exchange_http_reason(json.dumps({'error':text}).encode());self.assertEqual(reason,code);failure=self.exchange.failure(HTTPFailure(400,reason));self.assertEqual(failure.code,'exchange_'+code)
  for raw in (b'{"error":"cookie=SECRET"}',b'not JSON',b'{"error":{"secret":"hidden"}}'):self.assertIsNone(exchange_http_reason(raw))
 def test_invalid_queued_proposal_has_its_kind_without_losing_valid_ack(self):
  key=self.store.queue('node_identity',{'ipv6':'2001:db8::1'});p={'kind':'wallet_sync_queue','revision':1,'requests':[{'kind':'not_allowed'}]}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value={'version':1,'accepted':[key],'proposals':[p]}):
   with self.assertRaises(ValueError) as raised:self.exchange.once()
  failure=self.exchange.failure(raised.exception);self.assertIn('wallet_sync_queue',str(failure));self.assertEqual(self.exchange.phase,'proposal_validation');self.assertNotIn(key,self.store.read()['outbox']);self.assertFalse(self.store.read()['pending'])
 def test_success_clears_old_failure_and_true_is_not_a_protocol_version(self):
  with self.store.edit() as s:s['exchange_error']={'code':'old'}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value={'version':1,'accepted':[],'proposals':[]}):self.exchange.once()
  self.assertNotIn('exchange_error',self.store.read())
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value={'version':True,'accepted':[],'proposals':[]}):
   with self.assertRaises(ValueError):self.exchange.once()

class GroupedExtinct(unittest.TestCase):
 def setUp(self):
  self.sender=Regtest();self.addCleanup(self.sender.close);self.receiver=Regtest();self.addCleanup(self.receiver.close);self.core=self.sender.core
  rpc(self.core,'createwallet',{'wallet_name':'addresses24'})
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
 def fixture(self):
  rpc(self.core,'createwallet',{'wallet_name':ARCHIVE,'disable_private_keys':True,'blank':True})
  rows=[]
  for label in ('Old Treasury','Old SMSF'):
   address=rpc(self.core,'getnewaddress',[],'addresses24');body='addr('+address+')';rows.append({'desc':body+'#'+checksum(body),'timestamp':0,'label':label+' | LOST:02/01/2020 00:00:00 UTC'})
  rpc(self.core,'importdescriptors',{'requests':rows},ARCHIVE)
  p=paired(ARCHIVE);p['source_has_private_keys']=False;p['public_wallet']=rpc(self.core,'listdescriptors',[False],ARCHIVE)
  facts=wallet_details(self.core,{**p,'direction':'send'},self.store)
  from local_extinction import prepare,complete
  ident=prepare(self.store,{'public_wallet':p['public_wallet'],'manifest':{'addresses':facts['address_labels']},'operation_id':'a'*64},['Original locally extinct wallet']);complete(self.store,ident)
  return p,facts,rows
 def test_one_real_peer_transfer_creates_one_archive_with_two_children(self):
  p,facts,rows=self.fixture();self.assertTrue(grouped(p['public_wallet']));self.assertEqual([r['name'] for r in children(facts)],['Old SMSF','Old Treasury'])
  from test_build8 import CoreBatch
  CoreBatch.transfer_public(self,p,facts)
  loaded=rpc(self.receiver.core,'listwallets');self.assertEqual(loaded,[ARCHIVE]);self.assertFalse(rpc(self.receiver.core,'getwalletinfo',[],ARCHIVE)['private_keys_enabled'])
  for r in rows:self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[fixed_address(r['desc'])],ARCHIVE)['labels'],[r['label']])
 def test_merge_preserves_existing_addresses_labels_and_rejects_conflicts_before_mutation(self):
  p,facts,rows=self.fixture();rpc(self.receiver.core,'createwallet',{'wallet_name':ARCHIVE,'disable_private_keys':True,'blank':True})
  extra=rpc(self.core,'getnewaddress',[],'addresses24');body='addr('+extra+')';rpc(self.receiver.core,'importdescriptors',{'requests':[rows[0],{'desc':body+'#'+checksum(body),'timestamp':0,'label':'Retained local history'}]},ARCHIVE)
  self.store.receive(p);key=digest(p);name,missing,merged=import_watch(self.receiver.core,self.store,key,p,facts);self.assertEqual(name,ARCHIVE);self.assertFalse(missing);self.assertEqual(len(merged['public_wallet']['descriptors']),3)
  self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[extra],ARCHIVE)['labels'],['Retained local history'])
  before=rpc(self.receiver.core,'listdescriptors',[False],ARCHIVE);changed=copy.deepcopy(facts);changed['address_labels'][0]['label']='Untrusted replacement'
  with self.assertRaisesRegex(ValueError,'conflicts'):import_watch(self.receiver.core,self.store,key,p,changed)
  self.assertEqual(before,rpc(self.receiver.core,'listdescriptors',[False],ARCHIVE));self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[extra],ARCHIVE)['labels'],['Retained local history'])
 def test_sender_prefers_verified_canonical_archive_over_duplicate_subset(self):
  p,facts,rows=self.fixture();rpc(self.core,'createwallet',{'wallet_name':'old subset24','disable_private_keys':True,'blank':True});rpc(self.core,'importdescriptors',{'requests':[rows[0]]},'old subset24')
  p['public_wallet']['descriptors']=p['public_wallet']['descriptors'][:1];self.assertEqual(source_wallet(self.core,p),ARCHIVE);self.assertEqual(len(wallet_details(self.core,p,self.store)['public_wallet']['descriptors']),1)

 def test_fragmented_old_watch_imports_are_verified_and_combined_without_moving_keys(self):
  p,facts,rows=self.fixture();rpc(self.core,'unloadwallet',[ARCHIVE]);rpc(self.core,'createwallet',{'wallet_name':'Legacy child one','disable_private_keys':True,'blank':True});rpc(self.core,'createwallet',{'wallet_name':'Legacy child two','disable_private_keys':True,'blank':True})
  for name,row in zip(('Legacy child one','Legacy child two'),rows):rpc(self.core,'importdescriptors',{'requests':[row]},name)
  combined=wallet_details(self.core,p,self.store);self.assertEqual(len(combined['public_wallet']['descriptors']),2);self.assertEqual(len(children(combined)),2);self.assertEqual(combined['public_wallet']['wallet_name'],ARCHIVE)
  from build8_policy import descriptors
  self.assertEqual(descriptors(combined['public_wallet']),descriptors(p['public_wallet']))

class ObsoleteDenials(unittest.TestCase):
 def test_reboot_keeps_denials_then_one_local_cleanup_removes_only_verified_children(self):
  from extinct_sync import obsolete_denials,clear_obsolete_denials
  from denial_storage import FileStore
  from wallet_preview import sign
  from sync_queue import apply_snapshot
  from vendor.embit import ec
  from vendor.embit.script import p2wpkh
  from vendor.embit.networks import NETWORKS
  import time
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);disk=root/'preferences';disk.mkdir(mode=0o700);persist=FileStore(disk);old=Store(root/'old',persist);rows=[];labels=[]
   for i,name in enumerate(('Old Treasury','Old SMSF')):
    address=p2wpkh(ec.PrivateKey(bytes([i+1])*32).get_public_key()).address(NETWORKS['regtest']);body='addr('+address+')';rows.append({'desc':body+'#'+checksum(body),'timestamp':0});labels.append({'address':address,'label':name,'is_change':False})
   from build8_policy import descriptors
   ids=[digest(sorted(descriptors({'wallet_name':'old','descriptors':[row]}))) for row in rows]
   other='f'*64
   with old.edit() as state:state['sync_exclusions']={ids[0]:{'policy_id':ids[0],'wallet_name':'Old Treasury'},ids[1]:{'policy_id':ids[1],'wallet_name':'Old SMSF'},other:{'policy_id':other,'wallet_name':'Intentionally excluded wallet'}}
   fresh=Store(root/'fresh',persist);self.assertEqual(len(fresh.read()['sync_exclusions']),3);p=paired('Extinct');p['source_has_private_keys']=False;p['public_wallet']={'wallet_name':'Extinct','descriptors':rows};apply_snapshot(fresh,1,[p]);self.assertEqual(obsolete_denials(fresh),[])
   preview={'version':2,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':p['peer']['ipv6'],'receiver_ipv6':p['node_ipv6'],'public_wallet':p['public_wallet'],'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':labels,'node_tip':{'height':0,'hash':'1'*64},'generated_at':int(time.time())};payload=sign(fresh,preview)
   from wallet_preview import receive
   receive(fresh,payload);self.assertEqual({r['policy_id'] for r in obsolete_denials(fresh)},set(ids));clear_obsolete_denials(fresh);self.assertEqual(set(fresh.read()['sync_exclusions']),{other});again=Store(root/'again',persist);self.assertEqual(set(again.read()['sync_exclusions']),{other});self.assertIn(digest(p),fresh.read()['pending'])
 def test_single_child_identical_policy_can_be_reenabled_but_deliberate_container_denial_stays(self):
  from extinct_sync import obsolete_denials,clear_obsolete_denials
  from sync_queue import apply_snapshot
  from sync_preferences import policy_id
  from vendor.embit import ec
  from vendor.embit.script import p2wpkh
  from vendor.embit.networks import NETWORKS
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);address=p2wpkh(ec.PrivateKey(b'\x07'*32).get_public_key()).address(NETWORKS['regtest']);body='addr('+address+')';p=paired('Extinct');p['source_has_private_keys']=False;p['public_wallet']={'wallet_name':'Extinct','descriptors':[{'desc':body+'#'+checksum(body),'timestamp':0}]};ident=policy_id(p)
   with store.edit() as state:state['sync_exclusions']={ident:{'policy_id':ident,'wallet_name':'Old Treasury'}}
   apply_snapshot(store,1,[p]);self.assertFalse(store.read()['pending']);self.assertEqual(len(obsolete_denials(store)),1);clear_obsolete_denials(store);self.assertIn(digest(p),store.read()['pending'])
   with store.edit() as state:state['sync_exclusions']={ident:{'policy_id':ident,'wallet_name':'Extinct'}}
   self.assertEqual(obsolete_denials(store),[])
