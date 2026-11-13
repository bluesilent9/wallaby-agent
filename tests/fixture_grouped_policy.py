"""One grouped consent, signed delivery receipt, exact local batch boundaries."""
import copy,time,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from approval_store import Store,digest
from policy_refresh import Refresh
from policy_refresh_group import received
from vendor.embit.descriptor.checksum import checksum
from wallet_ops import rpc

class Receipt(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
  from fixture_policy_refresh import RecoveryValidation
  f=RecoveryValidation();f.setUp();pairs=[]
  for height in (100,200):
   pair=[]
   for field in ('receive_key','change_key'):
    body='wsh(and_v(v:after('+str(height)+'),pk('+f.contribution[field]+')))';pair.append(body+'#'+checksum(body))
   pairs.append(pair)
  f.policies=pairs;self.p={'kind':'wallet_policy_refresh','version':1,'request_id':'8'*64,'chain':'regtest','wallet':'primary','previous_descriptors':f.policies[0],'receive_descriptor':f.policies[1][0],'change_descriptor':f.policies[1][1],'timestamp':0,'expires_at':int(time.time())+3600};self.key=digest(self.p)

class BatchIsolation(unittest.TestCase):
 def setUp(self):
  f=Receipt();f.setUp();self.addCleanup(f.doCleanups);self.store=f.store;self.p=f.p;self.key=f.key;self.store.receive(self.p)
  self.ops=Refresh(object(),self.store,SimpleNamespace(loaded={}));self.facts={'funded_outputs':[],'height':200,'policy_hash':digest(__import__('policy_refresh').transition(self.p))};self.targets=[{'wallet':n,'storage':'node','private':False,'archive':None,'history':None,'public':'same','already_installed':False} for n in ('one','two')];self.ops.reviews[self.key]=(self.p,self.facts,time.monotonic(),self.targets);self.imports=[]
 def call(self,core,method,params=None,wallet=None,**kwargs):
  if method=='getblockchaininfo':return {'chain':'regtest','blocks':100}
  if method=='importdescriptors':
   self.imports.append(wallet)
   if wallet=='two':raise ValueError('fixture failed second import')
   return [{'success':True},{'success':True}]
  if method=='listdescriptors':return {'wallet_name':wallet,'descriptors':[{'desc':d} for d in self.p['previous_descriptors']+[self.p['receive_descriptor'],self.p['change_descriptor']]]}
  if method=='deriveaddresses':return ['fixture address']
  if method=='setlabel':return None
  raise AssertionError(method)

class RealBatch(unittest.TestCase):
 def setUp(self):
  from fixture_combined_wallets import CombinedCluster
  CombinedCluster.setUp(self)

class FundingAndDiscs(unittest.TestCase):
 setUp=Receipt.setUp

class BackupHandoff(unittest.TestCase):
 setUp=Receipt.setUp
