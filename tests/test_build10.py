"""Build 10 optical salvage, archive signing, BIP-322 and preference boundaries."""
import copy,hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from approval_store import Store,digest
from wallet_ops import rpc,WalletOps
from regtest_support import Regtest
from disc_archive import plan,chunks,recover,decode_header,HEADER,ALIGN
from disc_backup import pack,image,write_stream,readback
from wallet_setup import WalletSetup
from setup_policy import policy
from setup_completion import apply
from disc_restore import Archives
from message_signing import Messages,maps,challenge
from wallet_preview import fingerprint
from test_build8 import paired
BINARY='/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind'

class Redundancy(unittest.TestCase):
 def test_streamed_copies_recover_after_bad_header_and_bad_payload_without_capacity_allocation(self):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);iso=p/'small.iso';iso.write_bytes(b'ISO fixture'*500);package=p/'recovery';payload=b'encrypted package fixture'*10000;package.write_bytes(payload)
        layout=plan(iso,package,12*ALIGN);self.assertGreater(layout['copies'],5);parts=list(chunks(iso,package,layout));self.assertLessEqual(max(map(len,parts)),ALIGN);raw=bytearray(b''.join(parts));self.assertEqual(len(raw),layout['total_bytes'])
        raw[layout['start']:layout['start']+HEADER]=bytes(HEADER);raw[layout['start']+layout['stride']+HEADER+123]^=1
        target=p/'restored';found=recover(0,len(raw),target,read=lambda offset,count:bytes(raw[offset:offset+count]));self.assertEqual(found['index'],2);self.assertEqual(target.read_bytes(),payload)
        header=bytearray(parts[2] if len(parts[2])==HEADER else bytes(HEADER));self.assertIsNone(decode_header(bytes(header),0,len(raw)))
        huge=plan(iso,package,100*1000**3);iterator=chunks(iso,package,huge);self.assertLessEqual(len(next(iterator)),ALIGN);iterator.close()
 def test_actual_xorriso_stream_and_direct_readback_and_salvage(self):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);disc=p/'files';disc.mkdir();payload=disc/'recovery.wallaby';payload.write_bytes(b'ciphertext fixture'*10000);iso=p/'base.iso';image(disc,iso);layout=plan(iso,payload,12*ALIGN);out=p/'optical-track'
        sha=write_stream('stdio:'+str(out),chunks(iso,payload,layout),layout['total_bytes'],lambda n:None);readback(str(out),layout['total_bytes'],sha)
        fd=os.open(out,os.O_RDONLY|os.O_DIRECT)
        try:found=recover(fd,layout['total_bytes'],p/'recovered',start_hint=layout['start']);self.assertEqual(found['index'],0);self.assertEqual((p/'recovered').read_bytes(),payload.read_bytes())
        finally:os.close(fd)
 def test_all_damaged_copies_fail_without_leaving_an_output(self):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);(p/'iso').write_bytes(b'iso');(p/'pkg').write_bytes(b'ciphertext'*100);layout=plan(p/'iso',p/'pkg',5*ALIGN);raw=bytearray(b''.join(chunks(p/'iso',p/'pkg',layout)))
        for i in range(layout['copies']):raw[layout['start']+i*layout['stride']+HEADER+2]^=1
        with self.assertRaisesRegex(ValueError,'No intact'):recover(0,len(raw),p/'out',read=lambda off,n:bytes(raw[off:off+n]))
        self.assertFalse((p/'out').exists())

class Preferences(unittest.TestCase):
 def test_exact_receive_policy_disable_cancel_and_authenticated_relay(self):
    from sync_preferences import change,enable,policy_id,exchange
    from setup_messages import sign
    from sync_queue import apply_snapshot
    with tempfile.TemporaryDirectory() as tmp:
        store=Store(Path(tmp)/'state');p=paired('Family','receive');apply_snapshot(store,1,[p]);key=digest(p)
        from secure_worker import Workspace
        from types import SimpleNamespace
        from sync_queue import rows
        worker=Workspace.__new__(Workspace);worker.store=store;worker.node_status={'color':'green'};worker.viewers=[];worker.archives=SimpleNamespace(reading=False,loaded={},staged={});worker.setup=SimpleNamespace(sessions={},burner=SimpleNamespace(state=lambda:{}),own_identity=lambda:{});worker.transfer=SimpleNamespace(state=lambda:{'rows':rows(store),'recovery':{'status':'Synchronised'}})
        self.assertTrue(worker.service_status()['has_approvals']);self.assertTrue(worker.service_status()['needs_sync'])
        change(store,key,True);self.assertNotIn(key,store.read()['pending']);self.assertFalse(worker.service_status()['has_approvals']);self.assertFalse(worker.service_status()['needs_sync']);self.assertFalse(store.receive(p));apply_snapshot(store,2,[p]);self.assertFalse(worker.service_status()['has_approvals']);self.assertFalse(worker.service_status()['needs_sync']);self.assertNotIn(key,store.read()['pending']);enable(store,policy_id(p));self.assertIn(key,store.read()['pending'])
        change(store,key,True);sign(store,{'identity':'initialise'})
        exchange(store,{'challenge':'a'*64,'previous':None});snapshot=next(x['payload']['snapshot'] for x in store.read()['outbox'].values() if x['kind']=='wallet_sync_preferences')
        with store.edit() as s:s.pop('sync_exclusions');s.pop('sync_preferences_changed',None)
        exchange(store,{'challenge':'b'*64,'previous':snapshot});self.assertNotIn(policy_id(p),store.read().get('sync_exclusions',{}))
        forged=copy.deepcopy(snapshot);forged['message']['policies']=[]
        with self.assertRaises(ValueError):exchange(store,{'challenge':'b'*64,'previous':forged})
        bad={'kind':'sign_psbt_partial','request_id':'c'*64,'chain':'main','wallet':'x','psbt':'bad'}
        with store.edit() as s:s['pending']['sign']={'proposal':bad,'state':'pending'}
        with self.assertRaises(ValueError):change(store,'sign',True)
 def test_new_approval_requests_queue_while_other_work_is_active(self):
    from test_build7 import public
    with tempfile.TemporaryDirectory() as tmp:
        store=Store(tmp)
        with store.edit() as s:s['active_transfer']='unrelated'
        self.assertTrue(store.receive(paired('Concurrent','receive')))

class CoreMessages(unittest.TestCase):
 def setUp(self):
    self.node=Regtest();self.addCleanup(self.node.close);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'state')
 def test_single_key_variants_and_real_transaction_psbt_rejected(self):
    rpc(self.node.core,'createwallet',{'wallet_name':'messages','passphrase':'fixture-message-password'})
    m=Messages(self.node.core,self.store,lambda prompt:'fixture-message-password')
    for typ in ('bech32','p2sh-segwit','bech32m'):
        with self.subTest(typ=typ):
            address=rpc(self.node.core,'getnewaddress',['',typ],'messages');r=m.prepare(['messages'],address,' Exact message\nUnicode ✓ ');result=m.sign(r['id']);self.assertTrue(result['complete']);self.assertTrue(result['signature'].startswith('ful' if typ=='p2sh-segwit' else 'smp'))
            _,_,psbt=challenge(address,'different');
            with self.assertRaises(ValueError):m.prepare(['messages'],address,'Exact message',psbt)
    self.assertEqual(rpc(self.node.core,'getrawmempool'),[]);self.assertEqual(rpc(self.node.core,'getwalletinfo',[],'messages')['unlocked_until'],0)
 def test_archive_restores_only_to_ram_routes_and_signs_shared_transaction_and_message(self):
    core=self.node.core;setup=WalletSetup(core,self.store,binary=BINARY);self.addCleanup(lambda:[v['node'].close() for v in setup.sessions.values() if v.get('node')]);own=setup.own_identity()['public_key'];p={'kind':'wallet_setup','version':1,'session_id':'d'*64,'chain':'regtest','name':'Archive policy','threshold':2,'cosigners':[{'id':'role-'+str(i),'name':'Share '+str(i),'agent_key':own,'storage':'disc' if i==2 else 'node'} for i in range(3)],'height':50,'expires_at':int(time.time())+3600}
    self.store.receive(p);key=digest(p);setup.review(key)
    with patch('wallet_setup.secret_dialog',return_value='fixture-core-passphrase'):setup.approve_proposal(key,{r['id']:fingerprint(own) for r in p['cosigners']})
    contributions=sorted([x['payload'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_setup_contribution'],key=lambda x:x['message']['cosigner_id']);descs=policy(p,[e['message'] for e in contributions]);proposal={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};self.store.receive(proposal);setup.review(digest(proposal));setup.approve_policy(digest(proposal));record=next(iter(self.store.read()['approved_wallets'].values()));job=setup.burner.job
    folder=Path(self.tmp.name)/'optical';disc=pack(folder,job['wallets'],job['recovery'],'fixture-backup-password');setup.burn_complete(job['id'],'e'*64)
    proof={'kind':'wallet_setup_complete','version':1,'proposal_hash':digest(p),'policy_hash':record['policy_hash'],'acknowledgements':[x['payload'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_setup_ack' and x['payload']['message'].get('status') in ('policy_approved','backup_verified')]};apply(core,self.store,proof)
    pool=Archives(core,self.store,BINARY,lambda:None);import node_client;node_client.LOCAL_ROUTER=pool
    self.addCleanup(lambda:setattr(node_client,'LOCAL_ROUTER',None))
    stage=Path(self.tmp.name)/'read';stage.mkdir();
    with patch('setup_policy.time.time',return_value=p['expires_at']+86400):review=pool.inspect_package(disc/'recovery.wallaby','fixture-backup-password',stage)
    self.assertEqual(review['threshold'],2)
    pool.load(review['id'],True);self.addCleanup(lambda:pool.unload(review['id']) if review['id'] in pool.loaded else None);archive=pool.state()['loaded'][0]['wallets'][0];self.assertIn(archive,rpc(core,'listwallets'))
    with self.assertRaises(ValueError):rpc(core,'backupwallet',[str(Path(self.tmp.name)/'forbidden-copy')],archive)
    account=next(iter(record['signing_wallets'].values()));address=rpc(core,'deriveaddresses',[descs[0],[0,0]])[0];m=Messages(core,self.store,lambda prompt:'fixture-core-passphrase')
    a=m.prepare([account],address,'Joint archived message');partial=m.sign(a['id']);self.assertFalse(partial['complete']);self.assertEqual(partial['signatures_present'],1)
    b=m.prepare([archive],address,'Joint archived message',partial['psbt']);full=m.sign(b['id']);self.assertTrue(full['complete']);self.assertTrue(full['signature'].startswith('ful'));self.assertEqual(full['height'],50)
    rpc(core,'createwallet',{'wallet_name':'Miner'});dest=rpc(core,'getnewaddress',[],'Miner');rpc(core,'generatetoaddress',[102,dest]);rpc(core,'sendtoaddress',[address,'2'],'Miner');rpc(core,'generatetoaddress',[1,dest]);coin=rpc(core,'listunspent',[1],record['monitor_wallet'])[0];psbt=rpc(core,'createpsbt',[[{'txid':coin['txid'],'vout':coin['vout'],'sequence':0xfffffffe}],{dest:'1.9999'},50]);ops=WalletOps(core,self.store);request={'kind':'sign_psbt_partial','request_id':'f'*64,'chain':'regtest','wallet':archive,'psbt':psbt};self.store.receive(request);k=digest(request);ops.prepare_request(k);ops.sign(k,'fixture-core-passphrase','partial',fee_ack=True);signed=[x['payload']['psbt'] for x in self.store.read()['outbox'].values() if x['kind']=='partial_sign_result'][-1];self.assertEqual(len(rpc(core,'decodepsbt',[signed])['inputs'][0]['partial_signatures']),1);self.assertEqual(rpc(core,'getrawmempool'),[])
    from wallet_recovery import Recovery
    history=Recovery(core,self.store);self.assertEqual(history.state()['status'],'Synchronised');from wallet_recovery import persistent_wallets;self.assertNotIn(archive,persistent_wallets(core))
    # The persistent node has only its original two private signing accounts.
    node_client.LOCAL_ROUTER=None;self.assertNotIn(archive,rpc(core,'listwallets'));self.assertEqual(len([n for n in rpc(core,'listwallets') if n.startswith('Wallaby key ')]),2);node_client.LOCAL_ROUTER=pool

 def test_two_distinct_archival_discs_sign_one_multisig_message(self):
    core=self.node.core;setup=WalletSetup(core,self.store,binary=BINARY);self.addCleanup(lambda:[v['node'].close() for v in setup.sessions.values() if v.get('node')]);own=setup.own_identity()['public_key'];p={'kind':'wallet_setup','version':1,'session_id':'d'*64,'chain':'regtest','name':'Archive policy','threshold':2,'cosigners':[{'id':'role-'+str(i),'name':'Share '+str(i),'agent_key':own,'storage':'disc' if i>=1 else 'node'} for i in range(3)],'height':50,'expires_at':int(time.time())+3600}
    self.store.receive(p);key=digest(p);setup.review(key)
    with patch('wallet_setup.secret_dialog',return_value='fixture-core-passphrase'):setup.approve_proposal(key,{r['id']:fingerprint(own) for r in p['cosigners']})
    contributions=sorted([x['payload'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_setup_contribution'],key=lambda x:x['message']['cosigner_id']);descs=policy(p,[e['message'] for e in contributions]);proposal={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};self.store.receive(proposal);setup.review(digest(proposal));setup.approve_policy(digest(proposal));record=next(iter(self.store.read()['approved_wallets'].values()));job=setup.burner.job
    jobs=[job]+[{'id':ident,'wallets':wallets,'recovery':recovery} for ident,wallets,recovery in setup.burner.pending];self.assertEqual(len(jobs),2);packages=[]
    for i,j in enumerate(jobs):packages.append(pack(Path(self.tmp.name)/('optical-'+str(i)),j['wallets'],j['recovery'],'fixture-backup-password')/'recovery.wallaby')
    for j in jobs:setup.burn_complete(j['id'],'e'*64)
    proof={'kind':'wallet_setup_complete','version':1,'proposal_hash':digest(p),'policy_hash':record['policy_hash'],'acknowledgements':[x['payload'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_setup_ack' and x['payload']['message'].get('status') in ('policy_approved','backup_verified')]};apply(core,self.store,proof)
    pool=Archives(core,self.store,BINARY,lambda:None);import node_client;node_client.LOCAL_ROUTER=pool
    self.addCleanup(lambda:setattr(node_client,'LOCAL_ROUTER',None))
    archives=[]
    for i,package in enumerate(packages):
        stage=Path(self.tmp.name)/('read-'+str(i));stage.mkdir();review=pool.inspect_package(package,'fixture-backup-password',stage);self.assertEqual(review['threshold'],2);pool.load(review['id'],True);self.addCleanup(lambda ident=review['id']:pool.unload(ident) if ident in pool.loaded else None);archives.append(pool.loaded[review['id']]['keys'][0])
    self.assertNotEqual(*archives)
    duplicate=Path(self.tmp.name)/'duplicate';duplicate.mkdir()
    repeated=pool.inspect_package(packages[0],'fixture-backup-password',duplicate)
    with self.assertRaisesRegex(ValueError,'already'):pool.load(repeated['id'],True)
    address=rpc(core,'deriveaddresses',[descs[0],[0,0]])[0];m=Messages(core,self.store,lambda prompt:'fixture-core-passphrase')
    first=m.sign(m.prepare([archives[0]],address,'Two archival discs, one message')['id']);self.assertFalse(first['complete']);self.assertEqual(first['signatures_present'],1)
    same=m.sign(m.prepare([archives[0]],address,'Two archival discs, one message',first['psbt'])['id']);self.assertFalse(same['complete']);self.assertEqual(same['signatures_present'],1)
    second=m.sign(m.prepare([archives[1]],address,'Two archival discs, one message',first['psbt'])['id']);self.assertTrue(second['complete']);self.assertEqual(second['height'],50)
    together=m.sign(m.prepare(archives,address,'Two archival discs, one message')['id']);self.assertTrue(together['complete']);self.assertEqual(rpc(core,'getrawmempool'),[])
