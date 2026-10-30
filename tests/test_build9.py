"""Build 9 public policy, local retirement, encrypted disc and real-Core multisig checks."""
import copy,hashlib,json,os,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from approval_store import Store,digest
from setup_policy import policy,proposal
from setup_messages import sign,verify
from wallet_setup import WalletSetup
from wallet_retirement import Retirement
from wallet_ops import WalletOps,rpc
from wallet_preview import fingerprint
from protected_memory import enforce,noswap_path
from disc_backup import pack,decrypt_file,media,image,readback
from regtest_support import Regtest

BINARY='/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind'

class PublicAndDisc(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=Store(self.root/'state')
 def test_non_swapping_mount_evidence_and_fail_closed_gate(self):
    mount='1 0 0:1 / / rw - ext4 /dev/root rw\n2 1 0:2 / /ram rw,nosuid - tmpfs tmpfs rw,noswap\n3 2 0:3 / /ram/nested rw - ext4 /dev/disk rw\n'
    self.assertTrue(noswap_path('/ram/a',mount));self.assertFalse(noswap_path('/ram/nested/a',mount));self.assertFalse(noswap_path('/tmp/a',mount))
    with patch.dict(os.environ,{'WALLABY_PROTECTED_WORKER':'0'}),self.assertRaises(ValueError):enforce(self.root)
 def test_domain_signature_rejects_substitution_and_changed_payload(self):
    message={'session_id':'a'*64,'cosigner_id':'A'};e=sign(self.store,message);self.assertEqual(verify(self.store,e,e['public_key']),message)
    e['message']['cosigner_id']='attacker'
    with self.assertRaises(ValueError):verify(self.store,e,e['public_key'])
 def test_encrypted_package_contains_complete_policy_and_wallet_and_authenticates(self):
    wallet=self.root/'private.dat';wallet.write_bytes(b'fixture encrypted Core wallet');recovery={'policy_hash':'b'*64,'receive_descriptor':'fixture public receive','change_descriptor':'fixture public change','threshold':2,'cosigners':['A','B','C']}
    disc=pack(self.root/'bundle' if False else self.root,{'keyA':wallet},recovery,'long-fixture-backup-passphrase');out=self.root/'authenticated.zip';decrypt_file(disc/'recovery.wallaby',out,'long-fixture-backup-passphrase')
    with zipfile.ZipFile(out) as z:self.assertEqual(z.read('wallets/keyA.dat'),wallet.read_bytes());self.assertEqual(json.loads(z.read('policy.json')),recovery)
    with self.assertRaises(ValueError):decrypt_file(disc/'recovery.wallaby',self.root/'bad.zip','incorrect-password')
    self.assertFalse((self.root/'bad.zip').exists());self.assertFalse((self.root/'recovery.zip').exists());self.assertNotIn(wallet.read_bytes(),(disc/'recovery.wallaby').read_bytes())
    iso=self.root/'test.iso';sha=image(disc,iso);self.assertEqual(sha,hashlib.sha256(iso.read_bytes()).hexdigest());readback(str(iso),iso.stat().st_size,sha)
    with self.assertRaises(ValueError):readback(str(iso),iso.stat().st_size,'0'*64)
 def test_writer_accepts_only_blank_write_once_optical_devices(self):
    fake=Mock(st_mode=0o060660,st_rdev=os.makedev(11,0))
    with patch('disc_backup.os.stat',return_value=fake),patch('disc_backup.subprocess.run',return_value=Mock(returncode=0,stdout=b'Media current: BD-R sequential recording\nMedia status : is blank\n',stderr=b'')):
        self.assertTrue(media('/dev/sr0')['blank'])
        with self.assertRaises(ValueError):media('/dev/sda')
    with patch('disc_backup.os.stat',return_value=fake),patch('disc_backup.subprocess.run',return_value=Mock(returncode=0,stdout=b'Media current: BD-RE\nMedia status : is blank\n',stderr=b'')),self.assertRaises(ValueError):media('/dev/sr0')
 def test_retirement_wire_rejects_deletion_and_changed_identity(self):
    from test_build7 import public
    p={'kind':'wallet_retire','version':1,'wallet':'name','public_wallet':public('name'),'archive_label':'Earlier wallet','require_zero_balance':True,'delete_wallet':False};p['request_id']=digest(p);self.assertEqual(proposal(p),p)
    p['delete_wallet']=True
    with self.assertRaises(ValueError):proposal(p)
 def test_no_browser_secret_fields_or_local_vault_builder(self):
    root=Path(__file__).resolve().parents[1];html=(root/'web/index.html').read_text();js=(root/'web/workspace.js').read_text()
    self.assertNotIn('Vault Builder',html);self.assertNotIn('type="password"',html);self.assertIn('Disc Operations',html);self.assertIn('authorise/sign',js);self.assertNotIn('wallet-password',js)

class RealCoreBuild9(unittest.TestCase):
 def setUp(self):
    self.node=Regtest();self.addCleanup(self.node.close);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'state');self.core=self.node.core
 def test_two_of_three_vault_setup_distinct_signatures_and_disc_role(self):
    setup=WalletSetup(self.core,self.store,binary=BINARY);own=setup.own_identity();p={'kind':'wallet_setup','version':1,'session_id':'a'*64,'chain':'regtest','name':'Family threshold vault','threshold':2,'height':50,'expires_at':int(time.time())+3600,'cosigners':[{'id':str(i),'name':'Role '+str(i),'agent_key':own['public_key'],'storage':'disc' if i==2 else 'node'} for i in range(3)]};self.store.receive(p);key=digest(p)
    def cleanup():
        for session in setup.sessions.values():
            if session.get('core'):session['core'].close()
    self.addCleanup(cleanup)
    with patch('wallet_setup.secret_dialog',return_value='fixture-only-Core-passphrase') as prompts:
        with self.assertRaises(ValueError):setup.approve_proposal(key,{own['fingerprint']:'SHA256:wrong'})
        self.assertEqual(prompts.call_count,0)
        setup.approve_proposal(key,{own['fingerprint']:own['fingerprint']})
    self.assertEqual(prompts.call_count,3)
    for call in prompts.call_args_list:self.assertIn('Create encrypted Bitcoin Core signing wallet key_',call.args[0])
    session=setup.sessions[digest(p)];contributions=session['contributions'];descs=policy(p,[e['message'] for e in contributions]);self.assertEqual(len(set(e['message']['receive_key'] for e in contributions)),3)
    complete={'kind':'wallet_setup_policy','version':1,'proposal':p,'contributions':contributions,'receive_descriptor':descs[0],'change_descriptor':descs[1]};self.store.receive(complete);key=digest(complete);review=setup.review(key);self.assertEqual(len(review['setup']['samples']),6)
    changed=copy.deepcopy(complete);changed['receive_descriptor']=descs[1];self.store.receive(changed)
    with self.assertRaises(ValueError):setup.review(digest(changed))
    setup.approve_policy(key);self.assertTrue(setup.burner.state()['id']);record=next(iter(self.store.read()['approved_wallets'].values()));self.assertEqual(len(record['signing_wallets']),2);self.assertEqual(session['phase'],'awaiting_disc')
    # The physical-only share has never been installed in the persistent node.
    self.assertEqual(len([n for n in rpc(self.core,'listwallets') if n.startswith('Wallaby key ')]),2)
    rpc(self.core,'createwallet',{'wallet_name':'Miner'});dest=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[102,dest]);monitor=record['monitor_wallet'];address=rpc(self.core,'getnewaddress',[],monitor);rpc(self.core,'sendtoaddress',[address,'2'],'Miner');rpc(self.core,'generatetoaddress',[1,dest]);coin=rpc(self.core,'listunspent',[1],monitor)[0]
    psbt=rpc(self.core,'createpsbt',[[{'txid':coin['txid'],'vout':coin['vout'],'sequence':4294967294}],{dest:'1.9999'},50]);psbt=rpc(self.core,'walletprocesspsbt',{'psbt':psbt,'sign':False,'bip32derivs':True,'finalize':False},monitor)['psbt'];ops=WalletOps(self.core,self.store)
    # Global readiness is cryptographic evidence, never a Dashboard green flag.
    from setup_completion import apply as complete_setup
    policy_ack=[item['payload'] for item in self.store.read()['outbox'].values() if item['kind']=='wallet_setup_ack' and item['payload']['message'].get('status')=='policy_approved']
    proof={'kind':'wallet_setup_complete','version':1,'proposal_hash':digest(p),'policy_hash':record['policy_hash'],'acknowledgements':policy_ack}
    with self.assertRaises(ValueError):complete_setup(self.core,self.store,proof)
    # Simulate the verified optical callback only; real optical hardware is not
    # available in this fixture. The encryption/ISO/direct-read path is tested above.
    setup.burn_complete(setup.burner.state()['id'],'e'*64)
    proof['acknowledgements']=[item['payload'] for item in self.store.read()['outbox'].values() if item['kind']=='wallet_setup_ack' and item['payload']['message'].get('status') in ('policy_approved','backup_verified')]
    self.assertTrue(complete_setup(self.core,self.store,proof))
    # Signing-role recognition survives loss of Agent RAM metadata: Core's own
    # persisted public policies and encrypted account wallets establish ownership.
    with self.store.edit() as saved:saved['approved_wallets']={};saved.pop('setup_active',None)
    for i,wallet in enumerate(record['signing_wallets'].values()):
        req={'kind':'sign_psbt_partial','request_id':str(i+1)*64,'chain':'regtest','wallet':wallet,'psbt':psbt};self.store.receive(req);k=digest(req);ops.prepare_request(k);ops.sign(k,'fixture-only-Core-passphrase','partial',fee_ack=True);psbt=[x['payload']['psbt'] for x in self.store.read()['outbox'].values() if x['kind']=='partial_sign_result'][-1];self.assertEqual(len(rpc(self.core,'decodepsbt',[psbt])['inputs'][0].get('partial_signatures',{})),i+1)
    final=rpc(self.core,'finalizepsbt',[psbt]);self.assertTrue(final['complete']);self.assertTrue(rpc(self.core,'testmempoolaccept',[[final['hex']]])[0]['allowed']);self.assertFalse(rpc(self.core,'getrawmempool'))
    # Dashboard request validation never allows changing a mandatory height path.
    wrong=rpc(self.core,'createpsbt',[[{'txid':coin['txid'],'vout':coin['vout'],'sequence':4294967295}],{dest:'1.9999'},0]);req={'kind':'sign_psbt_partial','request_id':'f'*64,'chain':'regtest','wallet':next(iter(record['signing_wallets'].values())),'psbt':wrong};self.store.receive(req)
    with self.assertRaises(ValueError):ops.prepare_request(digest(req))
 def test_empty_private_wallet_archives_used_change_and_keeps_keys(self):
    rpc(self.core,'createwallet',{'wallet_name':'Old'});rpc(self.core,'createwallet',{'wallet_name':'Destination'});old=rpc(self.core,'getnewaddress',['A source label'],'Old');dest=rpc(self.core,'getnewaddress',[],'Destination');rpc(self.core,'generatetoaddress',[1,old]);rpc(self.core,'generatetoaddress',[101,dest]);rpc(self.core,'sendtoaddress',[dest,'49.9999','','',True],'Old');rpc(self.core,'generatetoaddress',[1,dest])
    # Sweep all remaining coins, if Core generated change from the first spend.
    rpc(self.core,'sendall',{'recipients':[dest]},'Old');rpc(self.core,'generatetoaddress',[1,dest]);raw=rpc(self.core,'listdescriptors',[False],'Old')
    p={'kind':'wallet_retire','version':1,'wallet':'Old','public_wallet':raw,'archive_label':'Earlier wallet','require_zero_balance':True,'delete_wallet':False};p['request_id']=digest(p);self.store.receive(p);k=digest(p);ret=Retirement(self.core,self.store);review=ret.review(k);self.assertGreaterEqual(len(review['retirement']['addresses']),2);ret.approve(k);self.assertTrue(rpc(self.core,'getwalletinfo',[],'Old')['private_keys_enabled']);self.assertIn('Old',rpc(self.core,'listwallets'));self.assertFalse(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['private_keys_enabled']);self.assertEqual(rpc(self.core,'getaddressinfo',[old],'Wallaby Extinct')['labels'],['Earlier wallet'])

if __name__=='__main__':unittest.main()
