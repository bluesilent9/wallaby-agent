"""Preparation must not rescan before queuing recovery or duplicate archive history."""
import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement,inventory,MissingHistory
from retirement_phases import prepare_history,imports,readback,review
from regtest_support import Regtest
from fixture_retirement import proposal,legacy

class ExtinctionRecovery(unittest.TestCase):
 def setUp(self):
  self.node=Regtest();self.addCleanup(self.node.close);self.core=self.node.core;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.store=Store(Path(tmp.name))
  for name in ('Old','Miner'):rpc(self.core,'createwallet',{'wallet_name':name})
  a=rpc(self.core,'getnewaddress',[],'Old');miner=rpc(self.core,'getnewaddress',[],'Miner');rpc(self.core,'generatetoaddress',[1,a]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'sendall',{'recipients':[miner]},'Old');rpc(self.core,'generatetoaddress',[1,miner])
  self.raw=rpc(self.core,'listdescriptors',[False],'Old');targets=[{'wallet':'Old','public_wallet':self.raw,'private_keys_enabled':True}];facts=inventory(self.core,self.store,legacy(self.raw,targets))
  manifest={'addresses':[{k:r[k] for k in ('address','label')} for r in facts['addresses']],'transactions':facts['transaction_records']};self.p=proposal(self.raw,manifest,'preserve','Wallaby Extinct');self.key=digest(self.p);self.store.receive(self.p)
  rpc(self.core,'createwallet',{'wallet_name':'Wallaby Extinct','disable_private_keys':True,'blank':True})

class PrunedPreservationBarrier(unittest.TestCase):
 def setUp(self):
  self.p={'phase':'preserve','wallet':'Extinct','public_wallet':{'wallet_name':'Old'},'manifest':{'addresses':[],'transactions':[]},'manifest_hash':'hash'}
