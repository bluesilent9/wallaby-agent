"""Queue authority, watch-only privacy and local history recovery against Core 31."""
import copy,hashlib,os,socket,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from sync_queue import apply_snapshot,choose,rows,freeze,release
from peer_wallet import active,frame_read,frame_write,socket_path,wallet_details,source_wallet
from batch_transfer import BatchTransfer
from wallet_preview import sign,receive,fingerprint,verify
from wallet_ops import rpc
from wallet_recovery import Recovery,history_missing,require,process_launch
from regtest_support import Regtest
from test_build7 import proposal,public
from vendor.embit.descriptor.checksum import checksum


def paired(name='Wallet',direction='receive'):
    p=proposal(direction,name);p.update(transfer_version=2,node_ipv6='2001:db8::1',preview_challenge=digest(name+'challenge'));return p


def signed(store,p,facts):
    return sign(store,{'version':2,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':p['peer']['ipv6'],'receiver_ipv6':p['node_ipv6'],**facts,'node_tip':{'height':105,'hash':'1'*64},'generated_at':int(time.time())})


class QueuePolicy(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
 def test_multiple_snapshots_withdrawals_and_local_choices(self):
    a=paired('Alpha');b=paired('Beta');apply_snapshot(self.store,1,[b,a]);self.assertEqual(len(rows(self.store)),2)
    key=digest(a);choose(self.store,key,True,True);apply_snapshot(self.store,2,[a]);self.assertEqual(len(rows(self.store)),1);self.assertTrue(rows(self.store)[0]['watch_only'])
    apply_snapshot(self.store,3,[]);self.assertEqual(rows(self.store),[])
    with self.assertRaises(ValueError):apply_snapshot(self.store,2,[a])
    with self.assertRaises(ValueError):apply_snapshot(self.store,3,[a])
 def test_only_dashboard_removes_and_batch_options_are_frozen(self):
    p=paired();key=digest(p);apply_snapshot(self.store,1,[p]);choose(self.store,key,True,False)
    with self.assertRaises(ValueError):self.store.deny(key)
    freeze(self.store,[key],'receive')
    with self.assertRaises(ValueError):choose(self.store,key,False,True)
    with self.store.edit() as state:state['active_transfer']=key;state['pending'][key]['state']='attempted'
    apply_snapshot(self.store,2,[]);self.assertEqual(rows(self.store),[]);self.assertIn(key,self.store.read()['pending'])
    release(self.store);self.assertIn(key,self.store.read()['pending'])
 def test_watch_source_cannot_be_full_and_unknown_fields_rejected(self):
    p=paired();p['source_has_private_keys']=False;self.store.receive(p);choose(self.store,digest(p),True,False)
    self.assertTrue(rows(self.store)[0]['watch_only']);self.assertTrue(rows(self.store)[0]['watch_only_locked'])
    bad=copy.deepcopy(p);bad['command']='stop'
    with self.assertRaises(ValueError):apply_snapshot(self.store,1,[bad])
 def test_snapshot_validation_is_atomic(self):
    a=paired('A');b=paired('B');b['peer']['ipv6']='127.0.0.1'
    with self.assertRaises(ValueError):apply_snapshot(self.store,1,[a,b])
    self.assertEqual(rows(self.store),[])
 def test_forged_labels_and_vault_metadata_break_signed_preview(self):
    p=paired();self.store.receive(p);facts={'public_wallet':p['public_wallet'],'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]};payload=signed(self.store,p,facts);verify(self.store,payload)
    bad=copy.deepcopy(payload);bad['preview']['address_labels']=[{'address':'not-an-address','label':'changed','is_change':False}]
    with self.assertRaises(ValueError):verify(self.store,bad)
 def test_old_build7_display_lock_cannot_block_upgrade(self):
    p=paired();self.store.receive(p)
    with self.store.edit() as state:state['active_transfer']=digest(p)
    t=BatchTransfer(Mock(),self.store)
    self.assertFalse(self.store.read().get('active_transfer'));choose(self.store,digest(p),True,True)
    self.assertTrue(self.store.receive(paired('Another')))
 def test_dashboard_withdrawal_removes_selected_row_and_details(self):
    p=paired();key=digest(p);apply_snapshot(self.store,1,[p])
    with self.store.edit() as state:state['viewed_transfer']=key
    apply_snapshot(self.store,2,[]);self.assertEqual(active(self.store),(None,None));self.assertEqual(rows(self.store),[])
 def test_synchronisation_never_opens_browser(self):
    import runtime
    self.store.receive(paired())
    with patch('approval_store.Store',return_value=self.store),patch('runtime.subprocess.Popen') as launch:runtime.notify_approvals()
    launch.assert_not_called()


class KeyPrivacy(unittest.TestCase):
 def test_valid_private_keys_are_rejected_but_random_psbt_text_is_not_a_key(self):
    from agent_rpc import clean_json
    from vendor.embit import ec,bip32
    for key in (ec.PrivateKey(b'\x01'*32).wif(),bip32.HDKey.from_seed(b'\x02'*32).to_base58()):
        with self.assertRaises(ValueError):clean_json({'unexpected':key},10000)
    value={'psbt':'cHNidP8/K'+'A'*51+'/'};self.assertEqual(clean_json(value,10000)[0],value)


class RecoveryPolicy(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.core=Mock(config={'cookie':str(Path(self.tmp.name)/'.cookie')});self.manager=Recovery(self.core,self.store)
 def test_pruned_boundary_includes_two_hour_descriptor_margin(self):
    def call(core,method,*args,**kwargs):return {'pruned':True,'pruneheight':100} if method=='getblockchaininfo' else 'hash' if method=='getblockhash' else {'time':10000}
    with patch('wallet_recovery.rpc',side_effect=call):self.assertTrue(history_missing(self.core,11000));self.assertFalse(history_missing(self.core,18000))
 def test_remote_input_cannot_start_recovery_without_fresh_local_plan(self):
    with self.assertRaises(ValueError):self.manager.start('a'*64)
    self.core.call.assert_not_called()
 def test_interrupted_operation_is_not_replayed(self):
    with self.store.edit() as s:s['recovery']={'state':'rescanning','plan':{}}
    self.manager.resume_monitor();self.assertEqual(self.store.read()['recovery']['state'],'interrupted');self.core.call.assert_not_called()
 def test_plan_change_after_local_review_requires_new_authorisation(self):
    with self.store.edit() as s:s['recovery_plan']={'id':'test','plan':{'created':time.time(),'requirements':digest({})}};s['history_jobs']={'new':{}}
    with self.assertRaisesRegex(ValueError,'changed or expired'):self.manager.start('test')
 def test_recovery_refuses_any_pruning_override_before_contacting_core(self):
    for option in ('-prune=0','-prune=1000','--prune=550'):
        with self.assertRaisesRegex(ValueError,'cannot override pruning'):self.manager.restart({},[option])
    self.core.call.assert_not_called()
 def test_missing_rpc_is_not_claimed_synchronised(self):
    with patch('wallet_recovery.rpc',side_effect=OSError()):self.assertFalse(self.manager.state()['available']);self.assertFalse(self.manager.state()['can_refresh']);self.assertNotEqual(self.manager.state()['status'],'Synchronised')


class CoreBatch(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.sender=Regtest();cls.receiver=Regtest();cls.core=cls.sender.core
    rpc(cls.core,'createwallet',{'wallet_name':'miner8'});cls.miner=rpc(cls.core,'getnewaddress',[],'miner8');rpc(cls.core,'generatetoaddress',[105,cls.miner])
    for h in range(1,106):rpc(cls.receiver.core,'submitblock',[rpc(cls.core,'getblock',[rpc(cls.core,'getblockhash',[h]),0])])
 @classmethod
 def tearDownClass(cls):cls.receiver.close();cls.sender.close()
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
 def test_watch_only_two_wallet_batch_preserves_labels_and_never_private_keys(self):
    incoming=[];facts={};proofs={}
    for name in ('Batch Alpha','Batch Beta'):
        rpc(self.core,'createwallet',{'wallet_name':name})
        address=rpc(self.core,'getnewaddress',['Family label '+name],name)
        rpc(self.core,'sendtoaddress',[address,'0.1'],'miner8');rpc(self.core,'generatetoaddress',[1,self.miner])
        for h in range(rpc(self.receiver.core,'getblockcount')+1,rpc(self.core,'getblockcount')+1):rpc(self.receiver.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[h]),0])])
        p=paired(name);p['public_wallet']=rpc(self.core,'listdescriptors',[False],name)
        facts[digest(p)]=wallet_details(self.core,{**p,'direction':'send'},self.store);incoming.append(p)
    apply_snapshot(self.store,1,incoming)
    for p in incoming:
        key=digest(p);choose(self.store,key,True,True);payload=signed(self.store,p,facts[key]);receive(self.store,payload);proofs[key]=fingerprint(payload['public_key'])
    t=BatchTransfer(self.receiver.core,self.store)
    with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch(proofs)
    self.addCleanup(t.close)
    # Reverse incoming order: the receiver resolves only rows in its frozen authorisation.
    for p in reversed(incoming):
        key=digest(p)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(30);sock.connect(str(socket_path(self.store)));stream=sock.makefile('rwb',buffering=0)
            frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':facts[key],'watch_only':False})
            self.assertEqual(frame_read(stream)['status'],'review_required');self.assertEqual(frame_read(stream),{'status':'ready','watch_only':True})
            frame_write(stream,{'operation':'public_wallet'});result=frame_read(stream);self.assertEqual(result['status'],'loaded',result);frame_write(stream,{'status':'confirmed'})
    t.thread.join(5);self.assertFalse(t.listener);self.assertFalse(self.store.read().get('sync_batch'));self.assertEqual(len(self.store.read()['completed']),2)
    for p in incoming:
        name='Wallaby Watch '+p['transfer_id'][:24];self.assertFalse(rpc(self.receiver.core,'getwalletinfo',[],name)['private_keys_enabled'])
        for row in facts[digest(p)]['address_labels']:self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[row['address']],name)['labels'],[row['label']])
 def test_fixed_address_extinct_subsets_and_loss_labels_from_own_core(self):
    name='Extinct archive8';rpc(self.core,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True})
    requests=[]
    for group in ('Old One','Old Two'):
        address=rpc(self.core,'getnewaddress',[],'miner8');body='addr('+address+')';requests.append({'desc':body+'#'+checksum(body),'timestamp':0,'label':group+' | LOST:02/01/2020 00:00:00 UTC'})
    self.assertTrue(all(r['success'] for r in rpc(self.core,'importdescriptors',{'requests':requests},name)))
    p=paired('Spoofed Dashboard name','send');p['source_has_private_keys']=False;p['public_wallet']={'wallet_name':'Dashboard name','descriptors':[{'desc':requests[0]['desc'],'timestamp':0,'active':False,'internal':False}]}
    self.assertEqual(source_wallet(self.core,p),name);details=wallet_details(self.core,p,self.store)
    self.assertEqual(details['public_wallet']['wallet_name'],'Old One');self.assertEqual(len(details['public_wallet']['descriptors']),1);self.assertEqual(details['address_labels'][0]['label'],requests[0]['label']);self.assertEqual(len(details['address_labels']),1)
    from build8_policy import descriptors
    self.assertTrue(descriptors(details['public_wallet']))
 def transfer_public(self,p,details):
    apply_snapshot(self.store,1,[p]);key=digest(p);choose(self.store,key,True,True);payload=signed(self.store,p,details);receive(self.store,payload)
    t=BatchTransfer(self.receiver.core,self.store);self.addCleanup(t.close)
    with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(payload['public_key'])})
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(30);sock.connect(str(socket_path(self.store)));stream=sock.makefile('rwb',buffering=0)
            frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':details,'watch_only':True});self.assertEqual(frame_read(stream)['status'],'review_required');self.assertTrue(frame_read(stream)['watch_only'])
            frame_write(stream,{'operation':'public_wallet'});reply=frame_read(stream);self.assertEqual(reply['status'],'loaded',reply);frame_write(stream,{'status':'confirmed'})
    finally:t.thread.join(5)
    return 'Wallaby Watch '+p['transfer_id'][:24]
 def test_extinct_addresses_and_loss_labels_are_imported(self):
    name='Historical transfer8';rpc(self.core,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True});address=rpc(self.core,'getnewaddress',[],'miner8');body='addr('+address+')';label='Earlier wallet | LOST:02/01/2020 00:00:00 UTC'
    rpc(self.core,'importdescriptors',{'requests':[{'desc':body+'#'+checksum(body),'timestamp':0,'label':label}]},name)
    p=paired('Extinct receive');p['source_has_private_keys']=False;p['public_wallet']=rpc(self.core,'listdescriptors',[False],name);details=wallet_details(self.core,{**p,'direction':'send'},self.store)
    restored=self.transfer_public(p,details);self.assertFalse(rpc(self.receiver.core,'getwalletinfo',[],restored)['private_keys_enabled']);self.assertEqual(rpc(self.receiver.core,'getaddressinfo',[address],restored)['labels'],[label])
 def test_vault_records_are_verified_and_installed_with_watch_transfer(self):
    from vendor.embit.descriptor import Descriptor
    from vendor.embit.networks import NETWORKS
    from wallet_ops import install_vault
    name='Vault public8';rpc(self.core,'createwallet',{'wallet_name':name});raw=rpc(self.core,'listdescriptors',[False],name);source=raw['descriptors'][0]['desc'];key=Descriptor.from_string(source.split('#')[0]).derive(0).key.get_public_key().sec().hex();body='wsh(and_v(v:pk('+key+'),after(500)))';descriptor=body+'#'+checksum(body)
    vault={'version':1,'chain':'regtest','descriptor':descriptor,'address':Descriptor.from_string(body).script_pubkey().address(NETWORKS['regtest']),'height':500,'source':{'descriptor':source,'index':0},'timestamp':0};install_vault(self.core,vault,self.store,owner=name)
    p=paired('Vault watch transfer');p['public_wallet']=raw;details=wallet_details(self.core,{**p,'direction':'send'},self.store);self.assertEqual(details['vaults'],[vault]);self.transfer_public(p,details)
    saved=self.store.read()['vaults'][digest(vault)];info=rpc(self.receiver.core,'getaddressinfo',[vault['address']],saved['monitor_wallet']);self.assertTrue(info.get('ismine') or info.get('iswatchonly'))
 def test_z_clean_shutdown_reindex_restart_and_restore_with_real_core(self):
    import subprocess
    name='Recovery encrypted8';rpc(self.core,'createwallet',{'wallet_name':name,'passphrase':'fixture-only'});raw=rpc(self.core,'listdescriptors',[False],name);stage=Path(self.tmp.name)/'received-encrypted.dat';rpc(self.core,'backupwallet',[str(stage)],name)
    details={'public_wallet':raw,'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]};require(self.store,'b'*64,'Recovered boot8',details,stage);manager=Recovery(self.core,self.store);original_run=subprocess.run;launched=[]
    def launch(command,*args,**kwargs):
        if command[:3]==['/usr/bin/systemctl','--user','show-environment']:return Mock(returncode=0)
        if command[0]=='/usr/bin/systemd-run':
            self.sender.process.wait(timeout=10);core_args=command[command.index('--')+1:];launched.append(core_args)
            self.sender.process=subprocess.Popen(core_args,stdout=self.sender.log,stderr=subprocess.STDOUT);return Mock(returncode=0)
        return original_run(command,*args,**kwargs)
    with patch('wallet_recovery.subprocess.run',side_effect=launch):
        with patch('wallet_recovery.history_missing',return_value=True):plan=manager.plan()
        self.assertEqual(plan['mode'],'download');manager.start(plan['id']);manager.thread.join(60)
    self.assertFalse(manager.thread.is_alive());self.assertEqual(self.store.read()['recovery']['state'],'complete',self.store.read()['recovery']);self.assertEqual(len(launched),1);self.assertIn('-reindex=1',launched[0]);self.assertIn('-networkactive=0',launched[0]);self.assertFalse(any(arg.startswith('-prune') for arg in launched[0]));self.assertFalse(stage.exists());self.assertEqual(rpc(self.core,'getwalletinfo',[],'Recovered boot8')['unlocked_until'],0)
 def test_process_identification_and_rescan_are_local_and_do_not_backup(self):
    launch=process_launch(self.core);self.assertEqual(launch['pid'],self.sender.process.pid);self.assertEqual(launch['netdir'],str(Path(self.core.config['cookie']).parent))
    # A pending history job makes the already-current node require an explicit rescan.
    raw=rpc(self.core,'listdescriptors',[False],'miner8');details={'public_wallet':raw,'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]};require(self.store,'a'*64,'miner8',details)
    with self.store.edit() as state:state['history_jobs']['a'*64]['expected_private_keys']=True
    manager=Recovery(self.core,self.store);self.assertEqual(manager.state()['status'],'Requires Rescan');plan=manager.plan();self.assertEqual(plan['mode'],'rescan');manager.start(plan['id']);manager.thread.join(30)
    self.assertFalse(manager.thread.is_alive());self.assertEqual(self.store.read()['recovery']['state'],'complete',self.store.read()['recovery']);self.assertFalse(self.store.read()['history_jobs'])

if __name__=='__main__':unittest.main()
