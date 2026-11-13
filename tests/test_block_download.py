"""Direct public-block catch-up; every Core instance uses an isolated regtest directory."""
import threading,time,unittest,copy
from unittest.mock import patch,Mock
from fixture_history_transfer import ChainCatchup,ChainFailureGuards
from wallet_ops import rpc
from chain_sync import finish

class ProgressiveCore(ChainCatchup):
 def transfer(self,*args,**kwargs):
  from chain_sync import send as actual_send
  with patch('fixture_history_transfer.send',side_effect=lambda *a,**kw:actual_send(*a,**kw,progressive=True)):return super().transfer(*args,**kwargs)
 def test_sender_in_ibd_can_supply_validated_blocks_without_claiming_network_completion(self):
  from chain_sync import rpc as actual
  def downloading(core,method,*args,**kw):
   value=actual(core,method,*args,**kw)
   return {**value,'initialblockdownload':True,'headers':150} if core is self.source.core and method=='getblockchaininfo' else value
  with patch('chain_sync.rpc',side_effect=downloading):self.transfer()
  self.assertEqual(rpc(self.receiver.core,'getblockcount'),15)
 def test_source_behind_ahead_receiver_never_shortens_or_invalidates_receiver_chain(self):
  self.transfer();before=rpc(self.receiver.core,'getbestblockhash')
  rpc(self.source.core,'invalidateblock',[rpc(self.source.core,'getblockhash',[6])]);self.assertEqual(rpc(self.source.core,'getblockcount'),5)
  self.transfer();self.assertEqual(rpc(self.receiver.core,'getbestblockhash'),before);self.assertEqual(self.store.read()['chain_sync']['current_height'],15)
 def test_genesis_only_source_leaves_receiver_blocks_and_wallets_intact(self):
  self.transfer();before=rpc(self.receiver.core,'getbestblockhash')
  rpc(self.source.core,'invalidateblock',[rpc(self.source.core,'getblockhash',[1])]);self.transfer()
  self.assertEqual(rpc(self.receiver.core,'getbestblockhash'),before);self.assertEqual(self.store.read()['chain_sync']['source_height'],0)
 def test_ssh_only_success_cannot_resume_internet_automatically(self):
  with self.store.edit() as s:s['chain_sync']={'mode':'ssh_only'}
  self.transfer();finish(self.receiver.core,self.store)
  self.assertFalse(rpc(self.receiver.core,'getnetworkinfo')['networkactive']);self.assertEqual(self.store.read()['chain_sync']['state'],'waiting_source')

from fixture_direct_peers import DirectPeers
from fixture_public_policy import Regtest
from block_download import Blocks
from relay_stream import Bridge

class DirectBlocks(DirectPeers):
 def setup_blocks(self):
  self.network();self.cores=[Regtest(),Regtest()]
  for core in self.cores:self.addCleanup(core.close)
  for p,core in zip((self.a,self.b),self.cores):p.wallet_bridge=Bridge(p,p.store);p.blocks=Blocks(p,p.store,core.core);self.addCleanup(p.blocks.end)
 def catch(self,source,receiver,source_core,receiver_core):
  rpc(source_core,'createwallet',{'wallet_name':'Block source'});address=rpc(source_core,'getnewaddress',[],'Block source');rpc(source_core,'generatetoaddress',[15,address])
  receiver.blocks.prepare(source.identity['endpoint_id']);self.assertFalse(rpc(receiver_core,'getnetworkinfo')['networkactive'])
  receiver.blocks.start();self.until(lambda:rpc(receiver_core,'getblockcount')==15)
  self.assertFalse(rpc(receiver_core,'getnetworkinfo')['networkactive'])
  rpc(source_core,'generatetoaddress',[3,address]);self.until(lambda:rpc(receiver_core,'getblockcount')==18)
  self.assertEqual(rpc(source_core,'getbestblockhash'),rpc(receiver_core,'getbestblockhash'));receiver.blocks.end();self.until(lambda:not receiver.blocks.state().get('running'))
  self.assertNotIn('stream_data',str(self.relay));self.assertFalse(self.failures)
 def test_real_ssh_server_can_source_progressive_blocks(self):
  self.setup_blocks();state=self.a.direct.active[self.b.identity['endpoint_id']];client=state.sessions[state.selected].client
  source,receiver=(self.b,self.a) if client else (self.a,self.b);sc,rc=(self.cores[1],self.cores[0]) if client else self.cores
  self.catch(source,receiver,sc.core,rc.core)
 def test_real_ssh_client_can_source_progressive_blocks(self):
  self.setup_blocks();state=self.a.direct.active[self.b.identity['endpoint_id']];client=state.sessions[state.selected].client
  source,receiver=(self.a,self.b) if client else (self.b,self.a);sc,rc=self.cores if client else (self.cores[1],self.cores[0])
  self.catch(source,receiver,sc.core,rc.core)
 def test_source_automatic_and_disconnect_never_resume_internet_or_reset_chain(self):
  self.setup_blocks();self.b.blocks.prepare(self.a.identity['endpoint_id']);self.b.blocks.start();time.sleep(2)
  self.assertFalse(rpc(self.cores[1].core,'getnetworkinfo')['networkactive']);self.assertEqual(rpc(self.cores[1].core,'getblockcount'),0)
  self.b.blocks.end();self.until(lambda:not self.b.blocks.state().get('running'))
 def test_prepare_only_pauses_network_and_mobile_cannot_be_a_source(self):
  self.setup_blocks();before=rpc(self.cores[1].core,'getbestblockhash');self.b.blocks.prepare(self.a.identity['endpoint_id']);self.assertEqual(rpc(self.cores[1].core,'getbestblockhash'),before)
  with self.assertRaises(ValueError):self.b.blocks.prepare('0'*64)
 def test_real_ssh_waits_for_genesis_source_without_rewinding_ahead_receiver(self):
  self.setup_blocks();self.catch(self.a,self.b,self.cores[0].core,self.cores[1].core)
  first=rpc(self.cores[0].core,'getblockhash',[1]);before=rpc(self.cores[1].core,'getbestblockhash')
  rpc(self.cores[0].core,'invalidateblock',[first]);self.b.blocks.start()
  self.until(lambda:self.b.store.read().get('chain_sync',{}).get('source_height')==0)
  self.assertEqual(rpc(self.cores[1].core,'getbestblockhash'),before);self.assertEqual(rpc(self.cores[1].core,'getblockcount'),18)
  rpc(self.cores[0].core,'reconsiderblock',[first]);address=rpc(self.cores[0].core,'getnewaddress',[],'Block source');rpc(self.cores[0].core,'generatetoaddress',[3,address])
  self.until(lambda:rpc(self.cores[1].core,'getblockcount')==21);self.b.blocks.end();self.until(lambda:not self.b.blocks.state()['running'])
 def test_pruned_source_gap_is_reported_and_stops_without_internet_fallback(self):
  self.setup_blocks();rpc(self.cores[0].core,'createwallet',{'wallet_name':'Miner'});address=rpc(self.cores[0].core,'getnewaddress',[],'Miner');rpc(self.cores[0].core,'generatetoaddress',[15,address])
  self.b.blocks.prepare(self.a.identity['endpoint_id'])
  from chain_sync import rpc as actual
  def limited(core,method,*a,**kw):
   value=actual(core,method,*a,**kw)
   return {**value,'pruned':True,'pruneheight':10} if core is self.cores[0].core and method=='getblockchaininfo' else value
  with patch('chain_sync.rpc',side_effect=limited):
   self.b.blocks.start();self.until(lambda:not self.b.blocks.state().get('running'))
  self.assertEqual(self.b.blocks.state()['error'],'source_pruned');self.assertIn('pruned',self.b.blocks.state()['message']);self.assertFalse(rpc(self.cores[1].core,'getnetworkinfo')['networkactive']);self.assertEqual(rpc(self.cores[1].core,'getblockcount'),0)
 def test_block_reads_are_bounded_even_for_four_megabyte_frames(self):
  from peer_wallet import read_exact
  class Bounded:
   def read(self,n):
    if n>1024*1024:raise AssertionError('Unbounded direct read')
    return b'a'*n
  self.assertEqual(len(read_exact(Bounded(),4*1024*1024)),4*1024*1024)

class SSHRecovery(unittest.TestCase):
 def setUp(self):
  import tempfile
  from approval_store import Store
  self.node=Regtest();self.addCleanup(self.node.close);self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name)
  from wallet_recovery import Recovery
  self.recovery=Recovery(self.node.core,self.store)
 def test_actual_core_wallet_registration_keeps_network_disabled_in_ssh_only_mode(self):
  from wallet_recovery import pruning_identity
  rpc(self.node.core,'createwallet',{'wallet_name':'Existing'});rpc(self.node.core,'setnetworkactive',[False])
  with self.store.edit() as s:s['recovery']={'state':'starting'};s['chain_sync']={'mode':'ssh_only'}
  plan={'pruning':pruning_identity(rpc(self.node.core,'getblockchaininfo')),'wallets':['Existing'],'ssh_only':True}
  self.recovery.prepare_replay(plan)
  self.assertTrue(self.store.read()['recovery']['replay_ready']);self.assertFalse(rpc(self.node.core,'getnetworkinfo')['networkactive']);self.assertIn('Existing',rpc(self.node.core,'listwallets'))
 def test_download_plan_binds_ssh_only_choice_and_never_enables_p2p(self):
  with self.store.edit() as s:s['history_jobs']={'1'*64:{'wallet':'Future','timestamp':0}};s['chain_sync']={'mode':'ssh_only'}
  from wallet_recovery import rpc as real
  calls=[]
  def track(core,name,*a,**kw):calls.append(name);return real(core,name,*a,**kw)
  with patch('wallet_recovery.rpc',side_effect=track),patch('wallet_recovery.history_missing',return_value=True),patch('wallet_recovery.process_launch',return_value={'fixture':'isolated'}),patch('wallet_recovery.subprocess.run',return_value=Mock(returncode=0)):
   self.recovery.plan()
  plan=self.store.read()['recovery_plan']['plan'];self.assertTrue(plan['ssh_only']);self.assertFalse(plan['resume_network']);self.assertFalse(plan['restore_network_after']);self.assertEqual(plan['mode'],'download');self.assertNotIn('setnetworkactive',calls)
 def test_mode_change_after_review_refuses_before_restarting_core(self):
  from approval_store import digest
  with self.store.edit() as s:s['recovery_plan']={'id':'1'*64,'plan':{'created':time.time(),'requirements':digest({}),'ssh_only':False}};s['chain_sync']={'mode':'ssh_only'}
  with patch.object(self.recovery,'restart') as restart,self.assertRaisesRegex(ValueError,'mode changed'):self.recovery.start('1'*64)
  restart.assert_not_called()
 def test_explicit_internet_resume_after_registration_requires_fresh_preparation(self):
  from chain_sync import resume_network
  rpc(self.node.core,'setnetworkactive',[False])
  with self.store.edit() as s:s['chain_sync']={'mode':'ssh_only','network_paused':True};s['block_download']={'prepared':True};s['recovery']={'state':'downloading','replay_ready':True,'plan':{'replay':True}}
  resume_network(self.node.core,self.store)
  self.assertTrue(rpc(self.node.core,'getnetworkinfo')['networkactive']);self.assertFalse(self.store.read()['block_download']['prepared']);self.assertEqual(self.store.read()['chain_sync']['mode'],'internet')
 def test_explicit_internet_resume_is_refused_before_replay_wallets_registered(self):
  from chain_sync import resume_network
  rpc(self.node.core,'setnetworkactive',[False])
  with self.store.edit() as s:s['recovery']={'state':'downloading','plan':{'replay':True}};s['chain_sync']={'mode':'ssh_only','network_paused':True}
  with self.assertRaisesRegex(ValueError,'registered'):resume_network(self.node.core,self.store)
  self.assertFalse(rpc(self.node.core,'getnetworkinfo')['networkactive'])

class DaisyChain(DirectPeers):
 def test_three_agents_can_pass_blocks_onward_while_middle_is_still_receiving(self):
  from direct_peers import Direct
  self.pair();self.c=self.peer('third');invite=self.b.create_invitation('agent',self.route);self.c.import_invitation(invite);self.move(self.c,self.b);self.move(self.b,self.c);self.move(self.c,self.b);self.b.approve(self.c.identity['endpoint_id']);self.move(self.b,self.c)
  peers=[self.a,self.b,self.c];self.failures=[];self.relay=[];self.done=threading.Event();self.addCleanup(self.done.set)
  lookup={p.identity['endpoint_id']:p for p in peers}
  for p in peers:Direct(p,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(p.close)
  def pump():
   while not self.done.wait(.002):
    try:
     for p in peers:
      with p.lock:frames=[f for f in p.outgoing.values() if f['id'] not in p.bulk_frames and not p.direct.holds(f)]
      for f in frames:
       lookup[f['to']].accept(f,[p.identity]);self.relay.append(copy.deepcopy(f))
       with p.lock:p.outgoing.pop(f['id'],None)
    except Exception as e:self.failures.append(repr(e));break
  threading.Thread(target=pump,daemon=True).start();self.until(lambda:self.a.direct.ready(self.b.identity['endpoint_id']) and self.b.direct.ready(self.c.identity['endpoint_id']))
  cores=[Regtest(),Regtest(),Regtest()]
  for core in cores:self.addCleanup(core.close)
  for p,c in zip(peers,cores):p.wallet_bridge=Bridge(p,p.store);p.blocks=Blocks(p,p.store,c.core);self.addCleanup(p.blocks.end)
  rpc(cores[0].core,'createwallet',{'wallet_name':'Miner'});address=rpc(cores[0].core,'getnewaddress',[],'Miner');rpc(cores[0].core,'generatetoaddress',[15,address])
  self.b.blocks.prepare(self.a.identity['endpoint_id']);self.b.blocks.start();self.c.blocks.prepare(self.b.identity['endpoint_id']);self.c.blocks.start()
  self.until(lambda:rpc(cores[2].core,'getblockcount')==15)
  rpc(cores[0].core,'generatetoaddress',[4,address]);self.until(lambda:rpc(cores[2].core,'getblockcount')==19)
  self.assertTrue(self.b.blocks.state()['running']);self.assertTrue(self.b.blocks.state()['allowed'])
  for c in cores[1:]:self.assertFalse(rpc(c.core,'getnetworkinfo')['networkactive']);self.assertEqual(rpc(c.core,'getbestblockhash'),rpc(cores[0].core,'getbestblockhash'))
  self.c.blocks.end();self.b.blocks.end();self.until(lambda:not self.c.blocks.state()['running'] and not self.b.blocks.state()['running']);self.assertFalse(self.failures)

class StreamRetirement(unittest.TestCase):
 def test_late_frames_for_exact_closed_stream_do_not_drop_connection_or_cross_bindings(self):
  from types import SimpleNamespace
  from relay_stream import Stream
  peers=SimpleNamespace(listeners=[],direct=Mock());bridge=Bridge(peers,Mock());channel=SimpleNamespace(peer={'role':'agent'})
  stream=Stream(bridge,channel,'1'*64,'2'*64);bridge.streams[stream.id]=stream;bridge.remove(stream)
  for kind in ('stream_ack','stream_ready','stream_close','stream_data'):
   self.assertTrue(bridge(channel,{'payload_type':kind,'operation_hash':'1'*64,'body':{'stream_id':'2'*64}}))
  with self.assertRaises(ValueError):bridge(channel,{'payload_type':'stream_ack','operation_hash':'3'*64,'body':{'stream_id':'2'*64}})
  other=SimpleNamespace(peer={'role':'agent'})
  with self.assertRaises(ValueError):bridge(other,{'payload_type':'stream_ack','operation_hash':'1'*64,'body':{'stream_id':'2'*64}})
  with self.assertRaises(ValueError):bridge(channel,{'payload_type':'stream_open','operation_hash':'1'*64,'body':{'stream_id':'2'*64,'block_request':'4'*64}})
