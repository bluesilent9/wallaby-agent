"""Three independent Agents must not replicate each other's generated signers."""
import copy,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from approval_store import Store,digest
from wallet_ops import rpc
from managed_accounts import classify,blocked,guard
from sync_queue import apply_snapshot
from test_build8 import paired

class ThreeAgentAccounts(unittest.TestCase):
 def test_three_of_five_accounts_never_enter_each_others_transfer_queue(self):
  from regtest_support import Regtest
  from wallet_setup import WalletSetup
  from setup_policy import policy
  with tempfile.TemporaryDirectory() as d:
   nodes=[];agents=[]
   try:
    for i in range(3):
     node=Regtest();nodes.append(node);agent=WalletSetup(node.core,Store(Path(d)/str(i)),binary=os.environ['WALLABY_TEST_BITCOIND']);agents.append(agent);node.core.managed_store=agent.store
    identities=[a.own_identity() for a in agents];roles=[{'id':'role-'+str(i),'name':['Disc A','Disc B','Primary','Australia','Russia'][i],'agent_key':identities[owner]['public_key'],'storage':'disc' if i<2 else 'node'} for i,owner in enumerate([0,0,0,1,2])]
    p={'kind':'wallet_setup','version':1,'session_id':'d'*64,'chain':'regtest','name':'Treasury fixture','threshold':3,'height':100,'expires_at':int(time.time())+3600,'cosigners':roles};binding=digest(p)
    for a in agents:
     a.store.receive(p)
     with patch('wallet_setup.secret_dialog',return_value='fixture-encrypted-passphrase'):a.approve_proposal(binding,{r['fingerprint']:r['fingerprint'] for r in identities})
    contributions=[e for a in agents for e in a.sessions[binding]['contributions']];descs=policy(p,[e['message'] for e in contributions]);final={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]}
    for a in agents:a.store.receive(final);a.review(digest(final));a.approve_policy(digest(final))
    records=[next(iter(a.store.read()['approved_wallets'].values())) for a in agents];signers=[next(iter(r['signing_wallets'].values())) for r in records];raw=[rpc(n.core,'listdescriptors',[False],name) for n,name in zip(nodes,signers)]
    for i,a in enumerate(agents):
     state=a.store.read();self.assertEqual(classify(state,records[i]['monitor_wallet'],rpc(nodes[i].core,'listdescriptors',[False],records[i]['monitor_wallet']))['display_name'],'Treasury fixture')
     meta=classify(state,signers[i],raw[i]);self.assertEqual(meta['role_name'],roles[i+2]['name']);self.assertEqual(meta['kind'],'signer');requests=[]
     for j in range(3):
      if j==i:continue
      for sender,receiver,direction in [(i,j,'send'),(j,i,'receive')]:
       request=paired('fixture',direction);request.update(transfer_id=digest({'sender':sender,'receiver':receiver}),public_wallet=raw[sender],source_has_private_keys=True);requests.append(request)
     self.assertEqual(len(requests),4)
     renamed=copy.deepcopy(requests[-1]);renamed['public_wallet']['wallet_name']='Ordinary looking name';self.assertTrue(blocked(state,renamed))
     apply_snapshot(a.store,1,requests);after=a.store.read();self.assertFalse(any(r['proposal']['kind']=='wallet_transfer' for r in after['pending'].values()));self.assertEqual(len(after['sync_guarded']),4)
     self.assertEqual(sum(r['kind']=='wallet_transfer_result' and r['payload']['status']=='error' for r in after['outbox'].values()),4)
     for request in requests:
      with self.assertRaisesRegex(ValueError,'Managed signing accounts'):guard(nodes[i].core,request,a.store)
     self.assertEqual(set(rpc(nodes[i].core,'listwallets')),{signers[i],records[i]['monitor_wallet']})
    self.assertEqual(len(agents[0].disc_sessions),2);self.assertIsNone(agents[0].sessions[binding]['core'].process.poll())
    fresh=Store(Path(d)/'fresh');renamed=paired('incoming');renamed.update(public_wallet=copy.deepcopy(raw[1]),source_has_private_keys=True);renamed['public_wallet']['wallet_name']='Renamed account'
    with self.assertRaisesRegex(ValueError,'Managed signing accounts'):guard(nodes[0].core,renamed,fresh)
    rpc(nodes[0].core,'createwallet',{'wallet_name':'Ordinary','passphrase':'fixture-ordinary-passphrase'});request=paired('Ordinary','send');request.update(public_wallet=rpc(nodes[0].core,'listdescriptors',[False],'Ordinary'),source_has_private_keys=True);guard(nodes[0].core,request,agents[0].store)
    apply_snapshot(agents[0].store,2,[request]);self.assertIn(digest(request),agents[0].store.read()['pending'])
   finally:
    for a in agents:
     for session in a.sessions.values():
      if session.get('core'):session['core'].close()
    for n in nodes:n.close()

class ReservedAccounts(unittest.TestCase):
 def test_legacy_reserved_key_blocks_without_authorising_any_cleanup(self):
  p=paired('Wallaby key '+'a'*12+' '+'b'*8);self.assertTrue(blocked({},p));p['public_wallet']['wallet_name']='Ordinary';self.assertFalse(blocked({},p))
  with self.assertRaisesRegex(ValueError,'Managed signing accounts'):guard(Mock(),p,actual_name='Wallaby key '+'a'*12+' '+'b'*8)

class AccountMetadata(unittest.TestCase):
 def setUp(self):
  from vendor.embit import bip32
  from managed_accounts import raw_keys
  from vendor.embit.descriptor.checksum import checksum
  key=bip32.HDKey.from_seed(b'\x01'*32).to_public().to_base58();receive=key+'/0/*';change=key+'/1/*'
  self.raw={'wallet_name':'Renamed signing account','descriptors':[{'desc':s+'#'+checksum(s)} for s in ['wpkh('+receive+')','wpkh('+change+')']]}
  receive_desc='wsh(sortedmulti(1,'+receive+'))';change_desc='wsh(sortedmulti(1,'+change+'))'
  self.record={'proposal':{'name':'Treasury fixture','threshold':1,'cosigners':[{'id':'a','name':'Primary'}]},'policy_hash':'a'*64,'receive_descriptor':receive_desc+'#'+checksum(receive_desc),'change_descriptor':change_desc+'#'+checksum(change_desc),'contributions':[{'message':{'cosigner_id':'a','receive_key':receive,'change_key':change}}],'signing_wallets':{'a':'Renamed signing account'},'monitor_wallet':'Policy'}
  self.state={'approved_wallets':{'policy':self.record}}
 def test_metadata_binds_descriptors_not_remote_names(self):
  metadata=classify(self.state,'Any name',self.raw);self.assertEqual(metadata['kind'],'signer');self.assertEqual(metadata['display_name'],'Treasury fixture · Primary (signer)')
  from test_build7 import public
  other=public('Ordinary');other['descriptors'][0]['desc']=other['descriptors'][0]['desc'].replace('/0/*','/9/*').split('#')[0]
  from vendor.embit.descriptor.checksum import checksum
  other['descriptors'][0]['desc']+='#'+checksum(other['descriptors'][0]['desc']);self.assertIsNone(classify(self.state,'Ordinary',other))
 def test_snapshot_refuses_managed_transfer_and_keeps_unrelated_request(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d)
   with store.edit() as state:state.update(self.state)
   p=paired('Managed');p['public_wallet']=self.raw;ordinary=paired('Ordinary');ordinary['source_has_private_keys']=False
   apply_snapshot(store,1,[p,ordinary]);saved=store.read();self.assertNotIn(digest(p),saved['pending']);self.assertIn(digest(ordinary),saved['pending']);self.assertEqual(len(saved['sync_guarded']),1)
   self.assertTrue(any(row['payload'].get('status')=='error' for row in saved['outbox'].values()))
 def test_attempted_transfer_is_retained_for_reconciliation(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);p=paired('Managed');p['public_wallet']=self.raw;key=digest(p)
   with store.edit() as state:state.update(self.state);state['pending'][key]={'proposal':p,'state':'attempted'}
   apply_snapshot(store,1,[p]);self.assertEqual(store.read()['pending'][key]['state'],'attempted')

class ReceiverBoundary(unittest.TestCase):
 def test_guard_rejects_signer_before_any_wallet_bytes_or_import(self):
  import io,struct
  from peer_wallet import Transfer
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);p=paired('Wallaby key '+'a'*12+' '+'b'*8);conn=Mock();conn.getsockopt.return_value=struct.pack('3i',123,os.getuid(),os.getgid());conn.makefile.return_value=io.BytesIO();listener=Mock();listener.accept.return_value=(conn,None);transfer=Transfer(Mock(),store);transfer.listener=listener;transfer.deadline=time.monotonic()+60
   with patch('peer_wallet.frame_read',return_value={}),patch('peer_wallet.frame_write') as reply,patch('peer_wallet.work_dir') as folder,patch('peer_wallet.rpc') as core_call:transfer.receive('fixture',p)
   self.assertIn('Managed signing accounts',transfer.error);folder.assert_not_called();core_call.assert_not_called();self.assertEqual(reply.call_args.args[1]['status'],'error')
