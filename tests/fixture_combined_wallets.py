"""Real independent nodes: combined policies, signer isolation, idle archive queue."""
import copy,os,tempfile,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from setup_policy import policy
from wallet_setup import WalletSetup
from public_policy import descriptors
from managed_accounts import classify,guard
from combined_wallet import wallet_name
from regtest_support import Regtest

PASSWORD='fixture-combined-passphrase'
class CombinedCluster(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.nodes=[];self.agents=[]
  for i in range(3):
   n=Regtest();self.nodes.append(n);self.addCleanup(n.close)
   a=WalletSetup(n.core,Store(Path(self.tmp.name)/str(i)),binary=os.environ['WALLABY_TEST_BITCOIND']);self.agents.append(a)
   self.addCleanup(lambda a=a:[s['core'].close() for s in a.sessions.values() if s.get('core')])
  own=[a.own_identity() for a in self.agents]
  roles=[{'id':'r'+str(i),'name':['Disc A','Disc B','Node Live','Australia','Russia'][i],'agent_key':own[j]['public_key'],'storage':'disc' if i<2 else 'node'} for i,j in enumerate((1,1,0,1,2))]
  self.p={'kind':'wallet_setup','version':1,'session_id':'9'*64,'chain':'regtest','name':'Treasury','threshold':3,'height':100,'expires_at':int(time.time())+3600,'cosigners':roles};self.h=digest(self.p)
  for a in self.agents:
   a.store.receive(self.p)
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):a.approve_proposal(self.h,{o['fingerprint']:o['fingerprint'] for o in own})
  self.contributions=[e for a in self.agents for e in a.sessions[self.h]['contributions']];self.descs=policy(self.p,[e['message'] for e in self.contributions])
  self.final={'kind':'wallet_setup_policy','version':1,'proposal':self.p,'contributions':self.contributions,'receive_descriptor':self.descs[0],'change_descriptor':self.descs[1]}
  for a in self.agents:
   a.store.receive(self.final);a.review(digest(self.final))
   with patch('wallet_setup.secret_dialog',return_value=PASSWORD):a.approve_policy(digest(self.final))

class Names(unittest.TestCase):
 pass

class PublicAvailability(unittest.TestCase):
 pass
