"""Build 8 interoperability and local-only peer wallet transfer regression."""
import base64,copy,hashlib,io,json,os,socket,struct,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from vault_policy import validate_proposal
from build8_policy import descriptors
from peer_wallet import Transfer,active,frame_read,frame_write,firewall_verdict,validate_details,source_wallet,wallet_details
from agent_exchange import Exchange
from wallet_ops import WalletOps,rpc
from regtest_support import Regtest
from vendor.embit import bip32
from vendor.embit.descriptor.checksum import checksum

def public(name='Example'):
    key=bip32.HDKey.from_seed(b'\x01'*32).to_public().to_base58();d='wpkh('+key+'/0/*)'
    return {'wallet_name':name,'descriptors':[{'desc':d+'#'+checksum(d),'active':True,'internal':False,'timestamp':0,'range':[0,10],'next_index':0}]}

def proposal(direction='receive',name='Example'):
    return {'kind':'wallet_transfer','direction':direction,'transfer_id':digest(name),'peer':{'node_id':'peer','hostname':'example','ipv6':'2001:db8::2'},'public_wallet':public(name),'source_has_private_keys':True,'earliest_timestamp':0,'requires_blockchain_redownload':False}

class PublicProtocol(unittest.TestCase):
 def test_strict_transfer_rejects_private_descriptor_invalid_peer_and_extra_commands(self):
    p=proposal();self.assertEqual(validate_proposal(p),p)
    for ip in ['127.0.0.1','::1','fe80::1','2001:db8::1%eth0','::ffff:192.0.2.1']:
        bad=copy.deepcopy(p);bad['peer']['ipv6']=ip
        with self.assertRaises(ValueError):validate_proposal(bad)
    bad=copy.deepcopy(p);bad['command']='backupwallet'
    with self.assertRaises(ValueError):validate_proposal(bad)
    bad=copy.deepcopy(p);bad['public_wallet']['descriptors'][0]['desc']='wpkh(xprvFAIL)'
    with self.assertRaises(ValueError):validate_proposal(bad)
 def test_frozen_batch_alphabetical_and_new_requests_rejected(self):
    with tempfile.TemporaryDirectory() as root:
        store=Store(root);e=Exchange(1,'test',store)
        with patch('agent_exchange.local_ipv6',return_value='2001:db8::1'),patch('agent_exchange.http_json',return_value={'version':1,'accepted':[],'proposals':[proposal(name='Zulu'),proposal(name='Alpha')]}) as post:e.once()
        self.assertEqual(active(store)[1]['proposal']['public_wallet']['wallet_name'],'Alpha');self.assertEqual(len(store.read()['pending']),2)
        self.assertIn('wallet_transfer',post.call_args.args[2]['capabilities']);self.assertEqual(post.call_args.args[2]['node_info']['ipv6'],'2001:db8::1')
        self.assertFalse(store.receive(proposal(name='Another')))
        self.assertFalse(store.receive({'kind':'node_identity'}))
 def test_changed_wallet_name_does_not_change_descriptor_identity(self):
    self.assertEqual(descriptors(public('One')),descriptors(public('Two')))
 def test_conservative_firewall_diagnostics(self):
    peer='2001:db8::2'
    self.assertEqual(firewall_verdict('Status: inactive',peer)['state'],'allowed')
    self.assertEqual(firewall_verdict('Status: active\n22/tcp (v6) ALLOW IN 2001:db8::2',peer)['state'],'allowed')
    self.assertEqual(firewall_verdict('Status: active\n22/tcp (v6) DENY IN Anywhere (v6)\n22/tcp (v6) ALLOW IN 2001:db8::2',peer)['state'],'blocked')
    self.assertEqual(firewall_verdict('unfamiliar localized status',peer)['state'],'unknown')
 def test_bounded_frames_reject_incomplete_and_oversized_data(self):
    stream=io.BytesIO();frame_write(stream,{'ok':True});stream.seek(0);self.assertEqual(frame_read(stream),{'ok':True})
    for raw in [b'\0\0\0\x10{}',struct.pack('!I',2*1024*1024)]:
        with self.assertRaises(ValueError):frame_read(io.BytesIO(raw))
 def test_remote_legacy_signing_and_private_direct_rpc_are_rejected(self):
    with self.assertRaises(ValueError):validate_proposal({'kind':'sign_psbt','wallet':'x','chain':'main','psbt':'cHNidP8='})
 def test_forged_public_history_rejected(self):
    d={'public_wallet':public(),'chain':'main','funded_outputs':[{'address':'a','txid':'1'*64,'vout':0,'amount_sats':'-1','time_received':0,'blockheight':1,'confirmations':1}]}
    with self.assertRaises(ValueError):validate_details(d)
 def test_receiving_requires_ipv6_listener_and_explicit_local_click(self):
    with tempfile.TemporaryDirectory() as root:
        store=Store(root);p=proposal();p.update(preview_challenge='a'*64,node_ipv6='2001:db8::1');store.receive(p);key=active(store)[0];t=Transfer(None,store)
        from wallet_preview import sign,receive,fingerprint
        payload=sign(store,{'version':1,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':p['peer']['ipv6'],'receiver_ipv6':p['node_ipv6'],'public_wallet':p['public_wallet'],'chain':'regtest','funded_outputs':[],'node_tip':{'height':0,'hash':'0'*64},'generated_at':int(time.time())});receive(store,payload);fp=fingerprint(payload['public_key'])
        with patch('peer_wallet.readiness',return_value={'listening':False}):
            with self.assertRaisesRegex(ValueError,'Start the receiving'):t.authorise(key,fp)
        self.assertFalse(t.listener);self.assertEqual(store.read()['pending'][key]['state'],'pending')
 def test_sender_fingerprint_precedes_password_and_backup(self):
    with tempfile.TemporaryDirectory() as root:
        store=Store(root);p=proposal('send');store.receive(p);key=active(store)[0];t=Transfer(Mock(),store)
        with self.assertRaisesRegex(ValueError,'fingerprint'):t.send(key,'dave','secret','')
        t.core.call.assert_not_called()

class RouteDisplay(unittest.TestCase):
 def test_physical_on_link_is_lan_and_gateway_or_virtual_is_not_assumed_lan(self):
    from peer_wallet import route_info
    with patch('peer_wallet.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps([{'dev':'wlan0'}]))),patch('peer_wallet.Path.exists',return_value=True):self.assertTrue(route_info('2001:db8::2')['direct_lan'])
    with patch('peer_wallet.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps([{'dev':'wlan0','gateway':'fe80::1'}]))),patch('peer_wallet.Path.exists',return_value=True):self.assertFalse(route_info('2001:db8::2')['direct_lan'])
    with patch('peer_wallet.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps([{'dev':'wg0'}]))),patch('peer_wallet.Path.exists',return_value=False):self.assertFalse(route_info('2001:db8::2')['direct_lan'])

class PreviewSecurity(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.p=proposal();self.p.update(preview_challenge='c'*64,node_ipv6='2001:db8::1');self.store.receive(self.p);self.key=active(self.store)[0]
    from wallet_preview import sign
    self.payload=sign(self.store,{'version':1,'transfer_id':self.p['transfer_id'],'challenge':self.p['preview_challenge'],'sender_ipv6':self.p['peer']['ipv6'],'receiver_ipv6':self.p['node_ipv6'],'public_wallet':self.p['public_wallet'],'chain':'regtest','funded_outputs':[],'node_tip':{'height':0,'hash':'0'*64},'generated_at':int(time.time())})
 def test_signature_binds_amounts_descriptors_addresses_peers_and_challenge(self):
    from wallet_preview import receive,verify
    verify(self.store,self.payload)
    for field,value in [('challenge','d'*64),('sender_ipv6','2001:db8::9'),('receiver_ipv6','2001:db8::8'),('transfer_id','e'*64),('public_wallet',public('Forged wallet name'))]:
        bad=copy.deepcopy(self.payload);bad['preview'][field]=value
        with self.assertRaises(ValueError):receive(self.store,bad)
    self.assertNotIn(self.key,self.store.read().get('transfer_previews',{}))
 def test_sender_fingerprint_must_be_pinned_outside_dashboard(self):
    from wallet_preview import receive
    receive(self.store,self.payload);t=Transfer(None,self.store)
    with self.assertRaisesRegex(ValueError,'fingerprint'):t.authorise(self.key,'SHA256:'+'A'*43)
    self.assertFalse(t.listener)
 def test_signed_preview_cannot_be_replaced_or_replayed_for_another_request(self):
    from wallet_preview import receive,sign
    receive(self.store,self.payload);changed=copy.deepcopy(self.payload['preview']);changed['generated_at']+=1;other=sign(self.store,changed)
    with self.assertRaisesRegex(ValueError,'cannot be replaced'):receive(self.store,other)
    changed['challenge']='e'*64
    with self.assertRaisesRegex(ValueError,'does not match'):receive(self.store,sign(self.store,changed))
 def test_build8_without_preview_stays_disabled(self):
    with tempfile.TemporaryDirectory() as root:
        store=Store(root);store.receive(proposal());key=active(store)[0]
        with self.assertRaisesRegex(ValueError,'Build 8 needs'):Transfer(None,store).authorise(key,'unused')

@unittest.skipUnless(Path(os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind')).exists(),'Core 31 required')
class CoreBuild7(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.node=Regtest();cls.core=cls.node.core;rpc(cls.core,'createwallet',{'wallet_name':'miner7'});cls.miner=rpc(cls.core,'getnewaddress',[],'miner7');rpc(cls.core,'generatetoaddress',[105,cls.miner]);cls.counter=0
 @classmethod
 def tearDownClass(cls):cls.node.close()
 def setUp(self):
    type(self).counter+=1;self.source='build7source'+str(self.counter);self.dest='build7dest'+str(self.counter)
    for name in (self.source,self.dest):rpc(self.core,'createwallet',{'wallet_name':name,'passphrase':'test-password'})
    rpc(self.core,'sendtoaddress',[rpc(self.core,'getnewaddress',[],self.source),'1'],'miner7');rpc(self.core,'generatetoaddress',[1,self.miner]);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.ops=WalletOps(self.core,self.store)
 def build(self):
    from datetime import datetime,timedelta
    return self.ops.build(self.source,self.dest,'2',(datetime.now()+timedelta(days=30)).date().isoformat(),'UTC')
 def test_unsigned_export_sign_partial_and_separate_broadcast(self):
    r=self.build();self.ops.sign(r['id'],'not-used','transaction_builder');item=next(i['payload'] for i in self.store.read()['outbox'].values() if i['kind']=='transaction_builder_psbt')
    p={'kind':'sign_psbt_partial','request_id':'1'*64,'chain':'regtest','wallet':self.source,'psbt':item['psbt'],'vault_intents':[{'vault':r['vault'],'proposal_psbt':item['psbt']}]};self.store.receive(p);key=digest(p);self.ops.prepare_request(key)
    with self.assertRaisesRegex(ValueError,'return signatures only'):self.ops.sign(key,'test-password','broadcast')
    self.ops.prepare_request(key);before=rpc(self.core,'getrawmempool');self.ops.sign(key,'test-password','partial');self.assertEqual(rpc(self.core,'getrawmempool'),before)
    signed=next(i['payload']['psbt'] for i in self.store.read()['outbox'].values() if i['kind']=='partial_sign_result');final=rpc(self.core,'finalizepsbt',[signed]);self.assertTrue(final['complete']);txid=rpc(self.core,'decoderawtransaction',[final['hex']])['txid']
    b={'kind':'broadcast_transaction','request_id':'2'*64,'chain':'regtest','psbt':signed,'txid':txid};self.store.receive(b);key=digest(b);self.ops.prepare_request(key);self.ops.sign(key,'','broadcast');self.assertIn(txid,rpc(self.core,'getrawmempool'))
    old={**item,'psbt':signed};old_id=self.store.queue('transaction_builder_psbt',old);e=Exchange(1,'test',self.store)
    with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value={'version':1,'accepted':[],'proposals':[]}):e.once()
    self.assertIn(old_id,self.store.read()['legacy_exports']);self.assertNotIn(old_id,self.store.read()['outbox'])
 def test_omitted_local_vault_intent_cannot_be_signed(self):
    r=self.build();self.ops.sign(r['id'],'','transaction_builder');p={'kind':'sign_psbt_partial','request_id':'3'*64,'chain':'regtest','wallet':self.source,'psbt':r['psbt']};self.store.receive(p)
    with self.assertRaisesRegex(ValueError,'omitted or changed'):self.ops.prepare_request(digest(p))
 def test_wallet_file_is_encrypted_and_restore_checks_descriptors(self):
    raw=rpc(self.core,'listdescriptors',[False],self.source);p=proposal('send');p['public_wallet']=raw
    self.assertEqual(source_wallet(self.core,p),self.source);detail=wallet_details(self.core,p);validate_details(detail);self.assertEqual(len(detail['funded_outputs']),1)
    # Exercise the real receiving protocol on a second isolated Core; no production SSH listener.
    receiver=Regtest();self.addCleanup(receiver.close)
    for height in range(1,rpc(self.core,'getblockcount')+1):rpc(receiver.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
    with tempfile.TemporaryDirectory() as root:
        rs=Store(root);incoming={**p,'direction':'receive','preview_challenge':'b'*64,'node_ipv6':'2001:db8::1'};rs.receive(incoming);key=active(rs)[0];t=Transfer(receiver.core,rs)
        from wallet_preview import sign,receive,fingerprint
        tip=rpc(self.core,'getblockchaininfo');payload=sign(self.store,{'version':1,'transfer_id':p['transfer_id'],'challenge':incoming['preview_challenge'],'sender_ipv6':p['peer']['ipv6'],'receiver_ipv6':incoming['node_ipv6'],**detail,'node_tip':{'height':tip['blocks'],'hash':tip['bestblockhash']},'generated_at':int(time.time())});receive(rs,payload)
        with patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise(key,fingerprint(payload['public_key']))
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(30);s.connect(str(__import__('peer_wallet').socket_path(rs)));stream=s.makefile('rwb',buffering=0)
            frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':detail});self.assertEqual(frame_read(stream)['status'],'review_required');self.assertEqual(frame_read(stream)['status'],'ready')
            backup=Path(self.tmp.name)/'encrypted.dat';rpc(self.core,'backupwallet',[str(backup)],self.source);data=backup.read_bytes();frame_write(stream,{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()});stream.write(data);stream.flush();reply=frame_read(stream);self.assertEqual(reply['status'],'loaded',reply);frame_write(stream,{'status':'confirmed'})
        t.thread.join(3);self.assertFalse(t.listener);self.assertFalse(rs.read()['pending']);self.assertGreater(t.success_until,time.time());name=rpc(receiver.core,'listwallets')[0];self.assertEqual(descriptors(rpc(receiver.core,'listdescriptors',[False],name)),descriptors(raw));self.assertEqual(rpc(receiver.core,'getwalletinfo',[],name)['unlocked_until'],0)
        self.assertTrue(all(i['kind']=='wallet_transfer_result' for i in rs.read()['outbox'].values()))
 def test_composition_accepts_extra_payments_and_rejects_changed_vault(self):
    r=self.build();self.ops.sign(r['id'],'','transaction_builder');export=next(i['payload'] for i in self.store.read()['outbox'].values() if i['kind']=='transaction_builder_psbt');original=rpc(self.core,'decodepsbt',[export['psbt']])['tx'];extra=rpc(self.core,'listunspent',[1], 'miner7')[0]
    inputs=[{'txid':v['txid'],'vout':v['vout'],'sequence':v['sequence']} for v in original['vin']]+[{'txid':extra['txid'],'vout':extra['vout'],'sequence':4294967294}]
    address=rpc(self.core,'getnewaddress',[],self.dest)
    from decimal import Decimal
    outputs=[{r['vault']['address']:original['vout'][0]['value']},{address:str(Decimal(extra['amount'])-Decimal('0.00001000'))}]
    def check(ins,outs):
        psbt=rpc(self.core,'createpsbt',[ins,outs,original['locktime'],False]);p={'kind':'sign_psbt_partial','request_id':digest({'in':ins,'out':outs}),'chain':'regtest','wallet':self.source,'psbt':psbt,'vault_intents':[{'vault':r['vault'],'proposal_psbt':export['psbt']}]};self.store.receive(p);return self.ops.prepare_request(digest(p))
    self.assertEqual(len(check(inputs,outputs)['review']['outputs']),2)
    bad=copy.deepcopy(outputs);bad[0][r['vault']['address']]=str(Decimal(bad[0][r['vault']['address']])-Decimal('0.00000001'))
    with self.assertRaisesRegex(ValueError,'fixed vault output'):check(inputs,bad)
    bad=copy.deepcopy(inputs);bad[0]['sequence']=4294967293
    with self.assertRaisesRegex(ValueError,'fixed vault input'):check(bad,outputs)
