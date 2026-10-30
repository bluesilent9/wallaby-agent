"""Boundaries that must hold even when the privileged desktop service is unavailable."""
import array,ctypes,importlib.util,json,os,resource,socket,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
import test_live_settings as live_fixture
from approval_store import Store,digest
from wallet_setup_signing import restricted
from setup_policy import policy
from vendor.embit import bip32
from vendor.embit.networks import NETWORKS
from regtest_support import Regtest
from wallet_ops import rpc

class BoundaryAPI(unittest.TestCase):
 setUp=live_fixture.LiveSettings.setUp
 tearDown=live_fixture.LiveSettings.tearDown
 call=live_fixture.LiveSettings.call
 def test_normal_browser_never_receives_wallet_reviews_or_lists(self):
    headers={'Authorization':'Bearer test-token'}
    with patch.dict(os.environ,{'WALLABY_REQUIRE_PROTECTION':'1','WALLABY_PROTECTED_WORKER':'0'}),patch('secure_bridge.call') as bridge:
        summary={'connected':False,'pending':[],'denied':[],'transfer':{},'burn':{},'sync':'Protected workspace','outbox_count':0,'protected':{'running':True,'viewer':False},'busy':False};bridge.return_value=summary
        status,body=self.call('/api/state',headers);self.assertEqual(status,200);self.assertEqual(body['workspace'],summary);bridge.assert_called_once_with('service_status');bridge.reset_mock()
        for endpoint,fields in [('authorise/review',{'id':'a'*64}),('authorise/sign',{'id':'a'*64,'action':'partial','password':'not-accepted'}),('synchronisation/review',{'id':'a'*64}),('disc/burn',{'device':'/dev/sr0','confirmed':True})]:
            self.assertEqual(self.call('/api/'+endpoint,headers,fields)[0],400)
        self.assertEqual(self.call('/api/wallets',headers)[0],404);bridge.assert_not_called()

class ProtectedRuntime(unittest.TestCase):
 def test_private_rpc_readiness_is_not_routed_through_a_busy_public_request(self):
    from node_client import Core
    with patch.dict(os.environ,{'WALLABY_REQUIRE_PROTECTION':'1','WALLABY_PROTECTED_WORKER':'0'}),patch('secure_bridge.call',return_value={'ok':True}) as proxy:
        Core({'cookie':'/must-not-read','rpc_port':1}).ready();proxy.assert_called_once_with('core.health')
 def test_environment_flags_cannot_claim_a_protected_service(self):
    from protected_memory import enforce
    with patch.dict(os.environ,{'WALLABY_PROTECTED_WORKER':'1'}),patch('protected_memory.noswap_path',return_value=True),self.assertRaisesRegex(ValueError,'dedicated protected service'):enforce('/ram')
 def test_snap_mount_target_fds_reject_symlinks_and_pin_renamed_directory(self):
    path=Path(__file__).resolve().parents[1]/'packaging/secure_snap_ram.py'
    spec=importlib.util.spec_from_file_location('snap_ram_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        parent=Path(tmp);(parent/'target').mkdir();(parent/'link').symlink_to(parent/'target',target_is_directory=True)
        fd=os.open(parent,os.O_PATH|os.O_DIRECTORY)
        try:
            with self.assertRaises(OSError):module.open_directory(fd,'link')
            target=module.open_directory(fd,'target')
            try:
                inode=os.fstat(target).st_ino;(parent/'target').rename(parent/'original');(parent/'target').symlink_to('/tmp',target_is_directory=True)
                self.assertEqual(os.fstat(target).st_ino,inode);self.assertEqual(os.stat('/proc/self/fd/'+str(target)).st_ino,(parent/'original').stat().st_ino)
                with self.assertRaises(OSError):module.open_directory(fd,'target')
            finally:os.close(target)
        finally:os.close(fd)
 def test_native_exec_constructor_disables_dumps_and_core_limits(self):
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        lib=Path(tmp)/'guard.so';subprocess.run(['gcc','-shared','-fPIC','-o',str(lib),str(root/'packaging/no_dump.c')],check=True,capture_output=True)
        result=subprocess.run([sys.executable,'-c','import ctypes,resource; print(ctypes.CDLL(None).prctl(3,0,0,0,0),resource.getrlimit(resource.RLIMIT_CORE))'],capture_output=True,text=True,env={**os.environ,'LD_PRELOAD':str(lib)},check=True)
        self.assertEqual(result.stdout.strip(),'0 (0, 0)')
 def test_unprivileged_broker_cannot_run_without_protection(self):
    from secure_worker import Workspace
    fake=Workspace.__new__(Workspace);fake.lock=threading.RLock();fake.configure=Mock()
    with patch('secure_worker.enforce',side_effect=ValueError('No protected cgroup')),self.assertRaises(ValueError):fake.dispatch('wallet.sign',['id','partial'],{})
    fake.configure.assert_not_called()
 def test_peer_pipe_handoff_and_regular_file_rejection(self):
    import protected_peer
    with tempfile.TemporaryDirectory() as tmp,patch('protected_peer.root',return_value=Path(tmp)):
        server=protected_peer.start()
        try:
            inp,writer=os.pipe();reader,out=os.pipe();payload=b'fixture wallet bytes remain in the receiving worker'
            def receive(i,o,source):self.assertIn('2001:db8::2',source);o.write(i.read(len(payload)))
            with patch('peer_wallet.peer_receive',side_effect=receive) as forwarded:
                with socket.socket(socket.AF_UNIX) as s:
                    s.settimeout(3);s.connect(str(Path(tmp)/'peer-helper.sock'));fds=array.array('i',[inp,out]);s.sendmsg([b'2001:db8::2 50000 2001:db8::1 22'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,fds)]);os.write(writer,payload);self.assertEqual(s.recv(16),b'COMPLETE');self.assertEqual(os.read(reader,len(payload)),payload)
                self.assertEqual(forwarded.call_count,1)
                with open(Path(tmp)/'ordinary-disk-file','w+b') as regular,socket.socket(socket.AF_UNIX) as s:
                    s.settimeout(3);s.connect(str(Path(tmp)/'peer-helper.sock'));fds=array.array('i',[inp,regular.fileno()]);s.sendmsg([b'2001:db8::2 50000 2001:db8::1 22'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,fds)]);self.assertEqual(s.recv(16),b'STOPPED')
                self.assertEqual(forwarded.call_count,1)
            for fd in (inp,writer,reader,out):os.close(fd)
        finally:server.shutdown();server.server_close()

class FourPolicies(unittest.TestCase):
 def test_all_four_policy_shapes_are_accepted_by_real_core_and_have_no_bypass(self):
    node=Regtest();self.addCleanup(node.close)
    from wallet_preview import sign
    with tempfile.TemporaryDirectory() as tmp:
        key=sign(Store(tmp),{'fixture':True})['public_key']
        for count,height in ((1,None),(3,None),(1,50),(3,50)):
            p={'kind':'wallet_setup','version':1,'session_id':'a'*64,'chain':'regtest','name':'Fixture','threshold':1 if count==1 else 2,'height':height,'expires_at':int(time.time())+3600,'cosigners':[{'id':str(i),'name':'Role','agent_key':key,'storage':'node'} for i in range(count)]};contributions=[]
            for i in range(count):
                master=bip32.HDKey.from_seed(bytes([i+1])*32,version=NETWORKS['regtest']['xprv']);account=master.derive('m/84h/1h/0h').to_public().to_base58();prefix='['+master.my_fingerprint.hex()+'/84h/1h/0h]'+account
                contributions.append({'session_id':p['session_id'],'proposal_hash':digest(p),'cosigner_id':str(i),'receive_key':prefix+'/0/*','change_key':prefix+'/1/*'})
            descs=policy(p,contributions)
            for d in descs:
                self.assertTrue(rpc(node.core,'getdescriptorinfo',[d])['isrange']);parsed=restricted(d);self.assertEqual(parsed['height'],height);self.assertEqual(parsed['threshold'],p['threshold'])
            if count>1:
                forged=[dict(c) for c in contributions];forged[1]['receive_key']=forged[0]['receive_key'];forged[1]['change_key']=forged[0]['change_key']
                with self.assertRaises(ValueError):policy(p,forged)
        self.assertIsNone(restricted('wsh(or_i(pk(02'+ '11'*32+'),after(50)))'))

if __name__=='__main__':unittest.main()
