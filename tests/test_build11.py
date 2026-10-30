"""Build 11: one persistent wallet-sync denial list; Bitcoin work stays volatile."""
import copy,json,os,shutil,socket,struct,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from approval_store import Store,digest
from denial_storage import FileStore,Client,Server,initial,validate,project
from sync_preferences import change,enable,policy_id,exchange
from sync_queue import apply_snapshot,rows
from test_build8 import paired

class PersistentDenials(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.disk=self.root/'persistent';self.disk.mkdir(mode=0o700);self.backend=FileStore(self.disk);self.ram=self.root/'ram';self.store=Store(self.ram,persistence=self.backend);self.p=paired('Family savings','receive');self.ident=policy_id(self.p)
 def reboot(self):
    shutil.rmtree(self.ram);self.store=Store(self.ram,persistence=FileStore(self.disk));return self.store
 def disable(self):
    self.store.receive(self.p);change(self.store,digest(self.p),True)
 def test_disabled_wallet_survives_ram_loss_without_retaining_bitcoin_payloads(self):
    self.disable()
    with self.store.edit() as s:
        s['pending']['a'*64]={'proposal':{'kind':'sign_psbt_partial','psbt':'PSBT-FIXTURE-NEVER-PERSIST','wallet':'Fixture'},'state':'pending'}
        s['outbox']['fixture']={'kind':'partial_sign_result','payload':{'psbt':'SIGNED-FIXTURE-NEVER-PERSIST'}}
        s['denied']['b'*64]={'proposal':{'kind':'sign_psbt_partial'},'wallet_name':'Temporary declined request'}
        s['history_jobs']={'fixture':'NODE-HISTORY-NEVER-PERSIST'}
        s['vaults']={'fixture':'VAULT-POLICY-NEVER-PERSIST'}
    raw=(self.disk/'denials.json').read_text();self.assertEqual(set(json.loads(raw)),{'version','revision','wallets'});self.assertNotIn('PSBT',raw);self.assertNotIn('VAULT',raw);self.assertNotIn('Temporary',raw);self.assertNotIn('descriptors',raw)
    s=self.reboot().read();self.assertIn(self.ident,s['sync_exclusions']);self.assertEqual(s['pending'],{});self.assertEqual(s['outbox'],{});self.assertEqual(s['denied'],{});self.assertEqual(s['vaults'],{});self.assertNotIn('history_jobs',s)
    self.assertFalse(self.store.receive(self.p));apply_snapshot(self.store,1,[self.p]);self.assertEqual(rows(self.store),[])
    names={p.name for p in self.disk.iterdir()};self.assertEqual(names,{'denials.json','denials.lock'});self.assertEqual((self.disk/'denials.json').stat().st_mode&0o777,0o600)
 def test_reenable_is_persistent_and_current_queue_or_later_offer_can_run(self):
    self.disable();self.reboot();apply_snapshot(self.store,1,[self.p]);enable(self.store,self.ident);self.assertEqual(len(rows(self.store)),1);self.reboot();self.assertNotIn(self.ident,self.store.read()['sync_exclusions']);self.assertTrue(self.store.receive(self.p))
 def test_one_off_decline_is_not_persistent_and_does_not_change_denial_revision(self):
    self.disable();revision=self.backend.read()['revision']
    p={'kind':'sign_psbt_partial','wallet':'One-off fixture','psbt':'DONT-PERSIST'};key=digest(p)
    with self.store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
    self.store.deny(key);self.assertIn(key,self.store.read()['denied']);self.assertEqual(self.backend.read()['revision'],revision);self.assertNotIn(key,self.reboot().read()['denied'])
 def test_schema_refuses_psbts_descriptors_private_files_commands_and_extra_records(self):
    self.disable();before=(self.disk/'denials.json').read_bytes()
    for field in ('psbt','descriptors','private_key','wallet_file','command','denied','pending','outbox'):
        bad=self.backend.read();bad[field]='NEVER-WRITE';bad['revision']+=1
        with self.assertRaises(ValueError):self.backend.commit(bad['revision']-1,bad)
        self.assertEqual((self.disk/'denials.json').read_bytes(),before)
    bad=self.backend.read();bad['wallets'][self.ident]['psbt']='NEVER-WRITE';bad['revision']+=1
    with self.assertRaises(ValueError):self.backend.commit(bad['revision']-1,bad)
    self.assertEqual((self.disk/'denials.json').read_bytes(),before)
 def test_corruption_unavailable_storage_and_failed_commit_do_not_allow_requests(self):
    self.disable();(self.disk/'denials.json').write_text('{broken')
    with self.assertRaises(ValueError):self.store.receive(self.p)
    with self.assertRaises(ValueError):Client(self.root/'absent.sock').read()
    (self.disk/'denials.json').unlink();self.store=Store(self.ram,persistence=self.backend)
    before=self.store.path.read_bytes()
    with patch.object(self.backend,'commit',side_effect=OSError('fixture disk failure')):
        with self.assertRaises(OSError):self.disable()
    # The earlier receive may be committed, but a failed disable never claims success.
    self.assertEqual(self.backend.read()['wallets'],{});self.assertIn(digest(self.p),self.store.read()['pending'])
 def test_atomic_revision_conflicts_and_symlinks_are_refused(self):
    stale=self.backend.read();self.disable();stale['revision']=1
    with self.assertRaises(ValueError):self.backend.commit(0,stale)
    original=(self.disk/'denials.json').read_bytes();(self.disk/'denials.json').unlink();outside=self.root/'outside';outside.write_text('untouched');(self.disk/'denials.json').symlink_to(outside)
    with self.assertRaises(OSError):self.backend.read()
    self.assertEqual(outside.read_text(),'untouched')
    (self.disk/'denials.json').unlink();(self.disk/'denials.lock').unlink();(self.disk/'denials.lock').symlink_to(outside)
    with self.assertRaises(OSError):self.backend.read()
 def test_dashboard_old_signed_snapshot_cannot_restore_locally_cleared_wallet(self):
    from setup_messages import sign
    self.disable();sign(self.store,{'fixture':'identity'});exchange(self.store,{'challenge':'a'*64,'previous':None});old=next(x['payload']['snapshot'] for x in self.store.read()['outbox'].values() if x['kind']=='wallet_sync_preferences');enable(self.store,self.ident);self.reboot()
    # Identity is Services metadata; model its persistent external location.
    identity=self.root/'identity';identity.mkdir(mode=0o700);signer=Store(identity);sign(signer,{'fixture':'identity'});self.store.identity_root=identity
    # Re-sign an old preference under the same current Agent key to test replay authority.
    old=sign(self.store,old['message']|{'agent_key':sign(self.store,{'fixture':True})['public_key']},namespace='wallaby-sync-preferences-v1')
    exchange(self.store,{'challenge':'b'*64,'previous':old});self.assertNotIn(self.ident,self.store.read()['sync_exclusions']);self.assertEqual(self.backend.read()['wallets'],{})
 def test_disabled_wallet_is_not_unfinished_work_after_reboot(self):
    from secure_worker import Workspace
    from types import SimpleNamespace
    self.disable();self.reboot();apply_snapshot(self.store,1,[self.p]);w=Workspace.__new__(Workspace);w.store=self.store;w.node_status={'color':'green'};w.viewers=[];w.archives=SimpleNamespace(reading=False,loaded={},staged={});w.setup=SimpleNamespace(sessions={},burner=SimpleNamespace(state=lambda:{}),own_identity=lambda:{});w.transfer=SimpleNamespace(state=lambda:{'rows':rows(self.store),'recovery':{'status':'Synchronised'}})
    self.assertFalse(w.service_status()['has_approvals']);self.assertFalse(w.service_status()['needs_sync']);enable(self.store,self.ident);self.assertTrue(w.service_status()['has_approvals']);self.assertTrue(w.service_status()['needs_sync'])
 def test_socket_broker_only_exposes_denial_schema_and_restarts_with_same_file(self):
    path=self.root/'broker.sock';server=Server(path,self.backend);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();client=Client(path)
    try:
        record=client.read();record['wallets'][self.ident]={'policy_id':self.ident,'wallet_name':'Family savings'};record['revision']=1;client.commit(0,record)
        with self.assertRaises(ValueError):client.operation({'method':'wallet.sign','args':['secret']})
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(path));raw=b'{"method":"read","method":"commit"}';s.sendall(struct.pack('!I',len(raw))+raw);size=int.from_bytes(s.recv(4),'big');self.assertIn('error',json.loads(s.recv(size)))
        self.assertEqual(client.read()['wallets'],record['wallets'])
    finally:server.shutdown();server.server_close();thread.join()
    path.unlink();server=Server(path,FileStore(self.disk));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:self.assertIn(self.ident,Client(path).read()['wallets'])
    finally:server.shutdown();server.server_close();thread.join()
