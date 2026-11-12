"""History differences with identical addresses; direct authenticated updates only."""
import copy,io,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from regtest_support import Regtest
import test_build62 as retirement_fixture
from test_build8 import paired,signed
from retirement_phases import imports
from wallet_recovery import staging_timestamp
from core_history import collect,install,database,TX_KEY,HISTORY_KEY
from extinct_upgrade import certify,status,snapshot
from extinct_history_sync import summary,preflight,install_packet
from history_wire import export,receive
from peer_wallet import wallet_details,read_exact,frame_read,frame_write,socket_path
from wallet_preview import receive as receive_preview,fingerprint
from local_extinction import prepare,complete
from sync_queue import apply_snapshot,choose
from batch_transfer import BatchTransfer
from vendor.embit.descriptor.checksum import checksum


class HistoryUpdate(unittest.TestCase):
 def setUp(self):
  retirement_fixture.ExtinctionRecovery.setUp(self)
  with tempfile.TemporaryDirectory() as d:self.records=collect(self.core,['Old'],[r['txid'] for r in self.p['manifest']['transactions']],d)
  imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  install(self.core,self.store,'Wallaby Extinct',self.records,self.p['manifest'])
  certify(self.core,self.store,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']])
  self.transfer=paired('Wallaby Extinct');self.transfer['source_has_private_keys']=False;self.transfer['public_wallet']=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct')
  self.facts=wallet_details(self.core,self.transfer,self.store)
 def packet(self):
  with tempfile.TemporaryDirectory() as d:
   file,header=export(self.core,self.store,self.transfer,self.facts,d,version=2)
   return json.loads(file.read_text()),header,file.read_bytes()
 def destination(self,*,stale=False,allow=True):
  node=Regtest();self.addCleanup(node.close);store=Store(self.store.root/'destination')
  for height in range(1,rpc(self.core,'getblockcount')+1):rpc(node.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
  if stale:
   with tempfile.TemporaryDirectory() as d:
    file=Path(d)/'stale.dat';rpc(self.core,'backupwallet',[str(file)],'Wallaby Extinct')
    # Deliberately model damaged/older public transaction inventory with exactly
    # the same descriptors and labels. Neither production wallet is touched.
    missing=self.records[-1]['txid']
    with database(file,True) as db:
     db.execute('delete from main where key=?',(TX_KEY+bytes.fromhex(missing)[::-1],))
     marker=json.loads(db.execute('select value from main where key=?',(HISTORY_KEY,)).fetchone()[0]);marker['txids'].remove(missing);marker.pop('checksum');marker['checksum']=digest(marker)
     db.execute('update main set value=? where key=?',(json.dumps(marker).encode(),HISTORY_KEY));db.commit()
    rpc(node.core,'restorewallet',{'wallet_name':'Wallaby Extinct','backup_file':str(file),'load_on_startup':False})
   self.assertEqual(rpc(node.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],len(self.records)-1)
  if allow:
   ident=prepare(store,{**self.p,'public_wallet':self.transfer['public_wallet'],'manifest':{'addresses':[{k:r[k] for k in ('address','label')} for r in self.facts['address_labels']]}},['Old']);complete(store,ident)
  key=digest(self.transfer);apply_snapshot(store,1,[self.transfer]);choose(store,key,True,True)
  proof=signed(self.store,self.transfer,self.facts);receive_preview(store,proof)
  return node,store,key,proof
 def test_summary_detects_missing_spent_history_with_identical_addresses_and_no_retirement_request(self):
  node,store,key,_=self.destination(stale=True)
  before=summary(node.core,'Wallaby Extinct');source=summary(self.core,'Wallaby Extinct')
  self.assertEqual(before['address_hash'],source['address_hash']);self.assertEqual(before['label_hash'],source['label_hash']);self.assertNotEqual(before['transaction_hash'],source['transaction_hash'])
  self.assertTrue(before['history_complete']);self.assertTrue(source['history_complete'])
  self.assertEqual({r['proposal']['kind'] for r in store.read()['pending'].values()},{'wallet_transfer'})
  packet,_,_=self.packet();install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),source);self.assertFalse(status(node.core,'Wallaby Extinct')['required'])
  install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),source)
 def test_actual_authorised_socket_updates_existing_wallet_and_records_completion(self):
  node,store,key,proof=self.destination(stale=True);transfer=BatchTransfer(node.core,store);self.addCleanup(transfer.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):transfer.authorise_batch({key:fingerprint(proof['public_key'])})
  packet,header,raw=self.packet()
  with socket.socket(socket.AF_UNIX) as sock:
   sock.settimeout(60);sock.connect(str(socket_path(store)));stream=sock.makefile('rwb',buffering=0)
   frame_write(stream,{'operation':'manifest','transfer_id':self.transfer['transfer_id'],'peer_ipv6':self.transfer['peer']['ipv6'],'details':self.facts,'watch_only':True})
   self.assertEqual(frame_read(stream)['status'],'review_required');self.assertIn('core_history_v2',frame_read(stream)['features'])
   from chain_sync import send
   send(self.core,stream,frame_read,frame_write);frame_write(stream,header);stream.write(raw);stream.flush();result=frame_read(stream);frame_write(stream,{'status':'confirmed'})
  transfer.thread.join(10);self.assertFalse(transfer.thread.is_alive(),transfer.error);self.assertEqual(result['status'],'loaded',transfer.error)
  self.assertIn(key,store.read()['completed']);self.assertEqual(summary(node.core,'Wallaby Extinct'),summary(self.core,'Wallaby Extinct'));self.assertTrue(rpc(node.core,'getnetworkinfo')['networkactive'])
 def test_preserves_receiver_only_address_history_and_lost_label_without_permanent_backup(self):
  node,store,key,_=self.destination(stale=True)
  extra=rpc(self.core,'getnewaddress',[],'Miner');label='Another old wallet | LOST:02/01/2020 03:04:05 UTC';body='addr('+extra+')'
  rpc(node.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':0,'label':label}]],'Wallaby Extinct')
  certify(node.core,store,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']]+[extra])
  before=set(snapshot(node.core,'Wallaby Extinct')['txids']);packet,_,_=self.packet();install_packet(node.core,store,key,self.transfer,self.facts,packet)
  after=snapshot(node.core,'Wallaby Extinct');self.assertTrue(before<=set(after['txids']));self.assertIn(extra,after['addresses']);self.assertFalse(status(node.core,'Wallaby Extinct')['required'])
  self.assertEqual(rpc(node.core,'getaddressinfo',[extra],'Wallaby Extinct')['labels'],[label]);self.assertEqual([r['name'] for r in rpc(node.core,'listwalletdir')['wallets']],['Wallaby Extinct'])
 def test_unknown_extinction_or_active_owner_cannot_be_bypassed_by_server_offer(self):
  node,store,key,_=self.destination(allow=False);packet,_,_=self.packet()
  with self.assertRaises(ValueError):preflight(node.core,store,self.transfer,{**packet,'coverage':{}})
  self.assertNotIn('Wallaby Extinct',rpc(node.core,'listwallets'))
  self.assertTrue(preflight(node.core,store,self.transfer,packet)) # Explicit direct coverage supports first-time history; a bare Server offer does not.
  ident=prepare(self.store,{**self.p,'public_wallet':self.transfer['public_wallet']},['Old']);complete(self.store,ident)
  with self.assertRaisesRegex(ValueError,'exists again'):preflight(self.core,self.store,self.transfer,packet)
 def test_conflicting_lost_labels_stop_before_import_or_history_replacement(self):
  node,store,key,_=self.destination(stale=True);address=self.p['manifest']['addresses'][0]['address'];label='Old | LOST:03/01/2020 03:04:05 UTC'
  rpc(node.core,'setlabel',[address,label],'Wallaby Extinct');before=summary(node.core,'Wallaby Extinct');packet,_,_=self.packet()
  with self.assertRaisesRegex(ValueError,'label conflicts'):install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),before)
 def test_uncovered_receiver_only_legacy_entry_requires_its_own_upgrade(self):
  node,store,key,_=self.destination(stale=True);extra=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+extra+')'
  rpc(node.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':staging_timestamp(node.core),'label':'Legacy'}]],'Wallaby Extinct')
  packet,_,_=self.packet()
  with self.assertRaisesRegex(ValueError,'additional legacy'):preflight(node.core,store,self.transfer,packet)
 def test_signed_packet_integrity_scope_chain_and_coverage_cannot_be_substituted(self):
  node,store,_,_=self.destination();packet,header,raw=self.packet()
  with tempfile.TemporaryDirectory() as d:
   got=receive(node.core,store,self.transfer,self.facts,header,io.BytesIO(raw),read_exact,d);self.assertEqual(got,packet)
   with self.assertRaisesRegex(ValueError,'checksum'):receive(node.core,store,self.transfer,self.facts,header,io.BytesIO(raw[:-1]+b'!'),read_exact,d)
  from extinct_history_sync import validate_coverage
  for field,value in [('addresses',[]),('txids',[]),('chain','main'),('tip','f'*64)]:
   bad=copy.deepcopy(packet['coverage']);bad[field]=value;bad.pop('checksum');bad['checksum']=digest(bad)
   with self.assertRaises(ValueError):validate_coverage(node.core,bad,packet['coverage']['addresses'],packet['coverage']['txids'])
 def test_summary_is_bounded_public_rpc_and_stable_when_only_confirmations_change(self):
  value=rpc(self.core,'wallaby_extinct_summary',[],'Wallaby Extinct');self.assertEqual(value,summary(self.core,'Wallaby Extinct'))
  raw=json.dumps(value);self.assertLess(len(raw),1024);self.assertNotIn('record',raw);self.assertNotIn(self.p['manifest']['addresses'][0]['address'],raw)
  miner=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[1,miner]);self.assertEqual(value,summary(self.core,'Wallaby Extinct'))
  from agent_rpc import request
  for params,name in [([1],'Wallaby Extinct'),([], 'Old')]:
   with self.assertRaises(ValueError):request('wallaby_extinct_summary',params,name)
 def test_complete_coverage_accepts_unused_address_and_empty_label(self):
  extra=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+extra+')';rpc(self.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':0}]],'Wallaby Extinct')
  certify(self.core,self.store,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']]+[extra]);self.transfer['public_wallet']=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct');self.facts=wallet_details(self.core,self.transfer,self.store)
  node,store,key,_=self.destination();packet,_,_=self.packet();install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),summary(self.core,'Wallaby Extinct'))

 def test_unused_address_only_packet_has_no_transaction_records(self):
  extra=rpc(self.core,'getnewaddress',[],'Miner');body='addr('+extra+')';desc=body+'#'+checksum(body)
  rpc(self.core,'importdescriptors',[[{'desc':desc,'timestamp':0}]],'Wallaby Extinct')
  certify(self.core,self.store,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']]+[extra])
  allrows=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct')['descriptors'];self.transfer['public_wallet']={'wallet_name':'Wallaby Extinct','descriptors':[r for r in allrows if r['desc']==desc]}
  self.facts=wallet_details(self.core,self.transfer,self.store);node,store,key,_=self.destination()
  # Explicit local approval for the unused fixed address as well.
  ident=prepare(store,{**self.p,'public_wallet':self.transfer['public_wallet'],'manifest':{'addresses':[{'address':extra,'label':''}]}},['Unused original']);complete(store,ident)
  packet,_,_=self.packet();self.assertEqual(packet['records'],[]);self.assertEqual(packet['manifest']['transactions'],[])
  install_packet(node.core,store,key,self.transfer,self.facts,packet);self.assertEqual(summary(node.core,'Wallaby Extinct')['transactions'],0);self.assertTrue(summary(node.core,'Wallaby Extinct')['history_complete'])
 def test_missing_source_coverage_cannot_claim_complete_direct_history(self):
  from extinct_history_sync import coverage
  with patch('extinct_history_sync.valid',return_value=False),self.assertRaisesRegex(ValueError,'Upgrade and verify'):coverage(self.core,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']],set())

 def test_upgraded_legacy_entries_are_local_evidence_without_old_request_records(self):
  node,store,key,_=self.destination(stale=True)
  with store.edit() as state:state.pop('local_retirements',None)
  packet,_,_=self.packet();install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),summary(self.core,'Wallaby Extinct'))
  # A restored decision overrides historical membership even when it still exists.
  ident=prepare(store,{**self.p,'public_wallet':self.transfer['public_wallet']},['Old'])
  with store.edit() as state:state['local_retirements'][ident]['state']='restored'
  with self.assertRaisesRegex(ValueError,'restoration|unfinished retirement'):preflight(node.core,store,self.transfer,packet)
