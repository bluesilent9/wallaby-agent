"""Core-native history, LOST labels, local eligibility and offline block catch-up."""
import copy,hashlib,json,os,socket,struct,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from regtest_support import Regtest
from wallet_ops import rpc
from approval_store import Store,digest
from fixture_history_recovery import ExtinctionRecovery
from core_history import collect,install,merge_backup,validate_rows
from archive_swap import exchange
from wallet_deletion import remove
from retirement_phases import imports,readback,review
from wallet_recovery import staging_timestamp
from chain_sync import send,receive,finish
from peer_wallet import frame_read,frame_write,read_exact

class NativeHistory(ExtinctionRecovery):
 def helpers(self):
  allowed=[Path(self.core.config['cookie']).parent/'wallets']
  return [patch('archive_swap.swap',side_effect=lambda a,b:exchange(a,b,allowed)),patch('wallet_deletion.delete',side_effect=lambda r,**kw:remove(r,allowed,allow_extinct=True))]
 def rows(self):
  with tempfile.TemporaryDirectory() as d:return collect(self.core,['Old'],[r['txid'] for r in self.p['manifest']['transactions']],d)

class ChainCatchup(unittest.TestCase):
 def setUp(self):
  self.source=Regtest();self.receiver=Regtest();self.addCleanup(self.source.close);self.addCleanup(self.receiver.close)
  rpc(self.source.core,'createwallet',{'wallet_name':'Miner'});a=rpc(self.source.core,'getnewaddress',[],'Miner');rpc(self.source.core,'generatetoaddress',[15,a])
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name)
 def transfer(self,source=None,receiver=None,store=None):
  source=source or self.source.core;receiver=receiver or self.receiver.core;store=store or self.store
  a,b=socket.socketpair();a.settimeout(20);b.settimeout(20);errors=[]
  def receive_thread():
   try:
    with b,b.makefile('rwb',buffering=0) as stream:receive(receiver,store,stream,frame_read(stream),frame_read,frame_write,read_exact)
   except Exception as e:errors.append(e)
  t=threading.Thread(target=receive_thread);t.start()
  try:
   with a,a.makefile('rwb',buffering=0) as stream:receipt=send(source,stream,frame_read,frame_write)
  finally:t.join(20)
  if errors:raise errors[0]
  self.assertFalse(t.is_alive());return receipt

class LocalEligibility(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from fixture_retirement import public
  self.p={'public_wallet':public('Old'),'manifest':{'addresses':[{'address':'fixture-address','label':'Old | LOST:01/01/2020 00:00:00 UTC'}]},'operation_id':'a'*64}
  self.raw={'descriptors':[{'desc':'addr(fixture-address)#ignored'}]}

class PrunedNativeHistory(unittest.TestCase):
 pass

class NativeGuards(NativeHistory):
 pass

class ChainFailureGuards(ChainCatchup):
 pass
