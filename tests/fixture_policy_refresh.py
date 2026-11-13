"""Historical private policies retain exact branch, role and approved history."""
import copy,re,time,zipfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from combined_wallet import verify_private_role
from vendor.embit import bip32
from vendor.embit.descriptor.checksum import checksum
from wallet_ops import rpc
from approval_store import digest

class RecoveryValidation(unittest.TestCase):
 def setUp(self):
  self.key=bip32.HDKey.from_seed(b'57 role fixture'*3);self.other=bip32.HDKey.from_seed(b'57 unrelated key'*3)
  self.contribution={field:str(self.key.to_public())+'/'+str(branch)+'/*' for branch,field in enumerate(('receive_key','change_key'))}
  self.policies=[self.pair(height) for height in (100,200,300,400)]
  self.rows=[{'desc':self.private(desc),'active':generation==3,**({'internal':bool(branch)} if generation==3 else {})} for generation,pair in enumerate(self.policies) for branch,desc in enumerate(pair)]
 def pair(self,height):
  result=[]
  for branch in range(2):
   body='wsh(and_v(v:pk('+str(self.key.to_public())+'/'+str(branch)+'/*),after('+str(height)+')))';result.append(body+'#'+checksum(body))
  return result
 def private(self,desc):
  body=desc.split('#')[0].replace(str(self.key.to_public()),str(self.key));return body+'#'+checksum(body)
 def verify(self,rows=None,policies=None):
  return verify_private_role(SimpleNamespace(private_descriptors=lambda name:copy.deepcopy(self.rows if rows is None else rows)),'archive',self.contribution,self.policies if policies is None else policies)


class RealRepeatedRecovery(unittest.TestCase):
 def setUp(self):
  from fixture_combined_wallets import CombinedCluster
  CombinedCluster.setUp(self)
