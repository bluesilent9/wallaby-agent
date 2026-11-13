"""Build 82: cold-clone disk invariants, actual Core reopen, direct-only roles,
first-time complete Extinct imports, and pruned/full compatibility boundaries.
All files, Core processes and SSH sessions are isolated test fixtures.
"""
import copy,hashlib,io,json,os,shutil,socket,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from chain_clone_files import *
from chain_clone import compatible,copy_snapshot
from peer_wallet import frame_read,frame_write
from chain_clone_service import SocketStream,receive_snapshot
from wallet_ops import rpc

class CloneGuards(unittest.TestCase):
 def test_full_pruned_matrix_and_ahead_receiver(self):
  r={'core_version':310000,'chain':'regtest','blocks':100,'pruned':True};s={'core_version':310000,'chain':'regtest','height':120,'hash':'a'*64,'pruned':True,'pruneheight':90}
  self.assertTrue(compatible(r,s));self.assertTrue(compatible(r,{**s,'pruned':False,'pruneheight':0}));self.assertTrue(compatible({**r,'pruned':False},{**s,'pruned':False,'pruneheight':0}))
  for rr,ss in [({**r,'pruned':False},s),(r,{**s,'height':99}),(r,{**s,'pruneheight':110}),(r,{**s,'chain':'main'}),(r,{**s,'height':True}),(r,{**s,'core_version':310100})]:
   with self.assertRaises(ValueError):compatible(rr,ss)
 def test_file_grammar_excludes_every_wallet_config_and_traversal(self):
  for name in ('wallets/a/wallet.dat','bitcoin.conf','.cookie','blocks/../wallets/a','chainstate/../../wallet.dat','blocks/link','blocks/index/OPTIONS-00001','chainstate_snapshot/CURRENT','/blocks/blk00000.dat'):
   self.assertFalse(allowed(name),name)
  for name in ('blocks/blk00000.dat','blocks/rev00002.dat','blocks/xor.dat','blocks/index/CURRENT','chainstate/000001.ldb','chainstate/LOCK'):self.assertTrue(allowed(name))
 def test_duplicate_incomplete_and_oversized_manifests(self):
  good=[{'path':'blocks/blk00000.dat','bytes':80},{'path':'blocks/index/CURRENT','bytes':10},{'path':'chainstate/CURRENT','bytes':10}]
  self.assertEqual(validate(good),good)
  for rows in (good+[good[0]],good[:-1],[{**good[0],'bytes':MAX_TOTAL+1}]+good[1:]):
   with self.assertRaises(ValueError):validate(rows)
 def test_swap_failure_rolls_back_both_original_directories_without_touching_wallets(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);stage=root/('.wallaby-chain-'+'a'*32);(stage/'incoming').mkdir(parents=True)
   for name in ROOTS:
    (root/name).mkdir();(root/name/'proof').write_text('original '+name);(stage/'incoming'/name).mkdir();(stage/'incoming'/name/'proof').write_text('clone '+name)
   (root/'wallets').mkdir();(root/'wallets/wallet.dat').write_bytes(b'PRIVATE FIXTURE NEVER COPIED');before=(root/'wallets/wallet.dat').read_bytes();original=os.rename
   def fail(a,b):
    if Path(a)==stage/'incoming/chainstate':raise OSError('Injected swap failure')
    return original(a,b)
   with patch('chain_clone_files.os.rename',side_effect=fail),self.assertRaises(OSError):install(root,stage)
   for name in ROOTS:self.assertEqual((root/name/'proof').read_text(),'original '+name)
   self.assertEqual((root/'wallets/wallet.dat').read_bytes(),before);self.assertEqual(json.loads((stage/'state.json').read_text())['phase'],'rolled_back')
 def test_inventory_rejects_symlink_or_hardlinked_blocks(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'blocks/index').mkdir(parents=True);(root/'chainstate').mkdir()
   for p in ('blocks/index/CURRENT','chainstate/CURRENT','blocks/blk00000.dat'):(root/p).write_bytes(b'x')
   self.assertTrue(inventory(root));(root/'blocks/blk00000.dat').unlink();(root/'blocks/blk00000.dat').symlink_to(root/'chainstate/CURRENT')
   with self.assertRaises(ValueError):inventory(root)
   (root/'blocks/blk00000.dat').unlink();os.link(root/'chainstate/CURRENT',root/'blocks/blk00000.dat')
   with self.assertRaises(ValueError):inventory(root)
 def test_no_disk_space_refuses_before_staging_or_approval(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);hello={'operation':'clone_snapshot','core_version':310000,'chain':'regtest','height':1,'hash':'a'*64,'pruned':False,'pruneheight':0,'files':3,'bytes':100}
   with patch('chain_clone_service.shutil.disk_usage',return_value=shutil._ntuple_diskusage(100,100,0)),self.assertRaisesRegex(ValueError,'space'):receive_snapshot(root,io.BytesIO(),hello)
   self.assertEqual(list(root.iterdir()),[])
 def test_stream_corruption_never_produces_a_committable_snapshot(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);a,b=socket.socketpair();a.settimeout(3);b.settimeout(3);self.addCleanup(a.close);self.addCleanup(b.close);errors=[]
   hello={'operation':'clone_snapshot','core_version':310000,'chain':'regtest','height':1,'hash':'a'*64,'pruned':False,'pruneheight':0,'files':3,'bytes':3}
   def incoming():
    try:receive_snapshot(root,SocketStream(b),hello)
    except Exception as e:errors.append(e)
   t=threading.Thread(target=incoming);t.start();s=SocketStream(a);self.assertEqual(frame_read(s),{'status':'clone_space_ready'});frame_write(s,{'path':'blocks/blk00000.dat','bytes':1});s.write(b'x');frame_write(s,{'sha256':'0'*64});t.join(5)
   self.assertFalse(t.is_alive());self.assertTrue(errors);self.assertEqual(list(root.iterdir()),[])

from test_build78 import HistoryUpdate
class FirstArchive(HistoryUpdate):
 # Inherit the comprehensive existing history/LOST tests as regression coverage.
 def test_first_time_verified_archive_needs_no_old_local_retirement_or_history_download(self):
  node,store,key,_=self.destination(allow=False);packet,_,_=self.packet()
  with patch('wallet_recovery.history_missing',side_effect=AssertionError('No blockchain replay needed for native complete history')):
   from extinct_history_sync import install_packet,summary
   install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(summary(node.core,'Wallaby Extinct'),summary(self.core,'Wallaby Extinct'));self.assertFalse(store.read().get('history_jobs'));self.assertFalse(store.read().get('local_retirements'))
 def test_first_time_archive_refuses_active_wallet_even_with_complete_peer_history(self):
  node,store,key,_=self.destination(allow=False);packet,_,_=self.packet()
  with tempfile.TemporaryDirectory() as d:
   backup=Path(d)/'active';rpc(self.core,'backupwallet',[str(backup)],'Old');rpc(node.core,'restorewallet',{'wallet_name':'Still active','backup_file':str(backup)})
  from extinct_history_sync import install_packet
  with self.assertRaisesRegex(ValueError,'active local wallet'):install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertNotIn('Wallaby Extinct',rpc(node.core,'listwallets'))
 def test_named_existing_archive_is_updated_in_place_with_lost_labels(self):
  node,store,key,_=self.destination(stale=True)
  rpc(node.core,'unloadwallet',{'wallet_name':'Wallaby Extinct','load_on_startup':False})
  base=Path(node.core.config['cookie']).parent/'wallets';os.rename(base/'Wallaby Extinct',base/'extinct_watch');rpc(node.core,'loadwallet',{'filename':'extinct_watch','load_on_startup':True})
  from extinct_history_sync import install_packet,summary
  packet,_,_=self.packet();name=install_packet(node.core,store,key,self.transfer,self.facts,packet)
  self.assertEqual(name,'extinct_watch');self.assertNotIn('Wallaby Extinct',rpc(node.core,'listwallets'));self.assertEqual(summary(node.core,name),summary(self.core,'Wallaby Extinct'))

# Real Core process replacement. Only the desktop service launcher is substituted
# because CI has no user systemd manager. Snapshot I/O, checksums, locks, swap,
# actual Core startup, direct SSH encryption and wallet readback are production code.
from test_build67 import DirectPeers
from regtest_support import Regtest
from block_download import Blocks
from relay_stream import Bridge
class DirectClone(DirectPeers):
 def test_real_ssh_cold_clone_keeps_receiver_keys_wallets_and_history(self):self.exercise()
 def test_actual_pruned_clone_then_first_extinct_import_needs_no_replay(self):self.exercise(pruned=True)
 def test_disconnect_restarts_source_and_leaves_receiver_chain_and_wallet_unchanged(self):self.exercise(disconnect=True)
 def exercise(self,pruned=False,disconnect=False):
  beforetime=int(time.time())-3*86400
  options=['-txindex=0']+(['-prune=550','-fastprune=1','-mocktime='+str(beforetime)] if pruned else [])
  self.network();source=Regtest(options);receiver=Regtest(options);self.addCleanup(source.close);self.addCleanup(receiver.close)
  for p,n in ((self.a,source),(self.b,receiver)):p.wallet_bridge=Bridge(p,p.store);p.blocks=Blocks(p,p.store,n.core)
  rpc(source.core,'createwallet',{'wallet_name':'Source only'});rpc(receiver.core,'createwallet',{'wallet_name':'Keep private','load_on_startup':True});address=rpc(receiver.core,'getnewaddress',[],'Keep private');rpc(source.core,'generatetoaddress',[15,address])
  for h in range(1,6):rpc(receiver.core,'submitblock',[rpc(source.core,'getblock',[rpc(source.core,'getblockhash',[h]),0])])
  if pruned:
   # Build a complete fixed-address archive BEFORE genuinely deleting its blocks.
   from vendor.embit.descriptor.checksum import checksum
   from extinct_upgrade import certify
   old=rpc(source.core,'getnewaddress',[],'Source only');rpc(source.core,'generatetoaddress',[1,old]);rpc(source.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True,'load_on_startup':True});body='addr('+old+')'
   rpc(source.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':0,'label':'Old Treasury | LOST:02/01/2020 00:00:00 UTC'}]],'Wallaby Extinct');certify(source.core,self.a.store,'Wallaby Extinct',[old])
   from test_pruned_recovery import padding_block
   rpc(source.core,'setmocktime',[int(time.time())]);rpc(receiver.core,'setmocktime',[int(time.time())]);padding_block(source.core,beforetime+600);rpc(source.core,'generatetoaddress',[310,address])
   total=rpc(source.core,'getblockcount')
   for h in range(6,total-4):rpc(receiver.core,'submitblock',[rpc(source.core,'getblock',[rpc(source.core,'getblockhash',[h]),0])])
   floor=rpc(source.core,'pruneblockchain',[total-288]);self.assertGreater(floor,16)
   with self.assertRaises(ValueError):rpc(source.core,'getblock',[rpc(source.core,'getblockhash',[16]),0])
  before=rpc(receiver.core,'getwalletinfo',[],'Keep private');nodes={Path(n.core.config['cookie']).parent:n for n in (source,receiver)};events=[]
  class ColdFixture:
   def __init__(self,core,root):self.node=nodes[root];self.core=core;self.root=root;self.args=list(self.node.process.args)+(['-mocktime='+str(int(time.time()))] if pruned else []);self.stopped=False;self.chain='regtest'
   def stop(self):rpc(self.core,'stop');self.node.process.wait(timeout=30);self.stopped=True;events.append(('stop',self.root))
   def start(self):
    if not self.stopped:return
    self.stopped=False;self.node.process=subprocess.Popen(self.args+['-networkactive=0'],stdout=self.node.log,stderr=subprocess.STDOUT)
    for _ in range(300):
     try:return rpc(self.core,'getblockchaininfo')
     except Exception:time.sleep(.1)
    raise AssertionError('Isolated cloned Core failed to restart')
  threads=[];failures=[]
  def local(manager,mode,tip):
   from chain_clone_service import export,receive_clone
   a,b=socket.socketpair();a.settimeout(120);b.settimeout(120);root=Path(manager.core.config['cookie']).parent
   def serve():
    try:(export if mode=='export' else receive_clone)(root,manager.core,SocketStream(b),{'hash':tip})
    except Exception as e:failures.append(repr(e))
    finally:b.close()
   t=threading.Thread(target=serve);threads.append(t);t.start();return a,SocketStream(a)
  self.a.blocks.clones.local_socket=lambda mode,tip:local(self.a.blocks.clones,mode,tip);self.b.blocks.clones.local_socket=lambda mode,tip:local(self.b.blocks.clones,mode,tip)
  original_tip=rpc(receiver.core,'getbestblockhash')
  if disconnect:
   progress=self.b.blocks.clones.progress
   def interrupt(n,total):
    progress(n,total)
    if n>65536:raise ConnectionError('Injected direct-stream interruption')
   self.b.blocks.clones.progress=interrupt
  with patch('chain_clone_service.ColdNode',ColdFixture):
   plan=self.b.blocks.clones.review(self.a.identity['endpoint_id']);self.b.blocks.clones.start(plan['review']['id'],True)
   deadline=time.monotonic()+180
   while self.b.blocks.clones.running and time.monotonic()<deadline:time.sleep(.1)
   for t in threads:t.join(20)
  if disconnect:
   self.assertEqual(self.b.blocks.clones.stage,'error');self.assertEqual(rpc(receiver.core,'getbestblockhash'),original_tip);self.assertEqual(rpc(receiver.core,'getwalletinfo',[],'Keep private')['txcount'],before['txcount']);self.assertTrue(rpc(source.core,'getblockcount')>0);self.assertFalse(list(Path(receiver.core.config['cookie']).parent.glob('.wallaby-chain-*')));return
  self.assertFalse(failures,failures);self.assertEqual(self.b.blocks.clones.stage,'complete',self.b.blocks.clones.message);self.assertEqual(rpc(source.core,'getbestblockhash'),rpc(receiver.core,'getbestblockhash'))
  after=rpc(receiver.core,'getwalletinfo',[],'Keep private');self.assertTrue(after['private_keys_enabled']);self.assertGreaterEqual(after['txcount'],before['txcount']);self.assertNotIn('Source only',rpc(receiver.core,'listwallets'));self.assertFalse(rpc(receiver.core,'getnetworkinfo')['networkactive']);self.assertNotIn('stream_data',str(self.relay));self.assertEqual(len(events),2);self.until(lambda:not self.a.blocks.clones.running);self.assertTrue(rpc(source.core,'getnetworkinfo')['networkactive'])

  if pruned:
   from test_build8 import paired
   from peer_wallet import wallet_details
   from history_wire import export as export_history
   from extinct_history_sync import install_packet,summary
   from sync_queue import apply_snapshot,choose
   from approval_store import Store,digest
   archive_store=Store(Path(receiver.root.name)/'archive-approval');p=paired('Wallaby Extinct');p['source_has_private_keys']=False;p['public_wallet']=rpc(source.core,'listdescriptors',[False],'Wallaby Extinct');details=wallet_details(source.core,p,self.a.store)
   with tempfile.TemporaryDirectory() as d:
    file,header=export_history(source.core,self.a.store,p,details,d,version=2);packet=json.loads(file.read_text())
   key=digest(p);apply_snapshot(archive_store,1,[p]);choose(archive_store,key,True,True)
   with patch('wallet_recovery.history_missing',side_effect=AssertionError('No history replay after a complete direct native import')):install_packet(receiver.core,archive_store,key,p,details,packet)
   self.assertEqual(summary(receiver.core,'Wallaby Extinct'),summary(source.core,'Wallaby Extinct'));self.assertFalse(archive_store.read().get('history_jobs'));self.assertTrue(rpc(receiver.core,'getblockchaininfo')['pruned'])
   self.assertEqual(rpc(receiver.core,'getaddressinfo',[old],'Wallaby Extinct')['labels'],['Old Treasury | LOST:02/01/2020 00:00:00 UTC'])
   with self.assertRaises(ValueError):rpc(receiver.core,'getblock',[rpc(receiver.core,'getblockhash',[16]),0])

class RestartAndRoles(unittest.TestCase):
 def test_mobile_cannot_open_clone_stream_and_saved_flags_cannot_extend_restart_grace(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  from relay_stream import Bridge
  from chain_clone import Clones
  peers=SimpleNamespace(listeners=[],direct=SimpleNamespace(require=Mock()),stop=threading.Event())
  bridge=Bridge(peers,None)
  with self.assertRaisesRegex(ValueError,'Agent permission'):bridge.open_clone(SimpleNamespace(peer={'role':'mobile'}))
  self.assertFalse(bridge.streams)
  manager=Clones(SimpleNamespace(peers=peers,store=None,core=None));manager.running=True;manager.deadline=time.monotonic()+3600;self.assertFalse(manager.active())
 def test_independent_launcher_preflight_failure_never_stops_core(self):
  from chain_clone_service import ColdNode
  from unittest.mock import Mock
  launch={'pid':123,'started':'fixture','netdir':'/tmp/fixture-clone','cwd':'/tmp','argv':['/usr/bin/bitcoind','-prune=550'],'env':{},'executable':'/usr/bin/bitcoind'}
  with patch('wallet_recovery.process_launch',return_value=launch),patch('chain_clone_service.subprocess.run',return_value=Mock(returncode=1)),patch('chain_clone_service.rpc') as rpc_mock,self.assertRaisesRegex(ValueError,'preflight'):ColdNode(Mock(),Path('/tmp/fixture-clone'))
  rpc_mock.assert_not_called()
 def test_unconfirmed_shutdown_never_launches_a_second_core(self):
  from chain_clone_service import ColdNode
  node=ColdNode.__new__(ColdNode);node.stopped=True;node.locked=False;node.lock=None
  with patch('chain_clone_service.subprocess.run') as launch,self.assertRaisesRegex(ValueError,'No duplicate'):node.start()
  launch.assert_not_called()
 def test_service_requires_protected_helper_and_has_scoped_core_paths(self):
  import runpy
  root=Path(__file__).resolve().parents[1];source=(root/'packaging/build.py').read_text();self.assertIn('wallaby-agent-chain@%i.service',source);self.assertIn('RuntimeDirectory=wallaby-agent-chain/%i',source);self.assertIn('TimeoutStopSec=330',source)
  helpers=runpy.run_path(str(root/'packaging/secure_start.py'))
  with tempfile.TemporaryDirectory() as d:
   unit=Path(d)/'units';fn=helpers['wallet_paths']
   with patch.dict(fn.__globals__,runtime_parent=lambda p:p.mkdir(parents=True,exist_ok=True)):fn(1000,Path(d)/'home',unit,'chain')
   config=(unit/'wallaby-agent-chain@1000.service.d/30-wallet-paths.conf').read_text();self.assertIn('/snap/bitcoin-core/common/.bitcoin',config);self.assertIn('/.bitcoin/regtest',config);self.assertNotIn('ReadWritePaths=-/home\n',config)
