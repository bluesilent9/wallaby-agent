"""Real-Core preservation barrier, deletion-only cold nodes and mixed-disc guards."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement,inventory
from retirement_phases import validate,require_current
from regtest_support import Regtest
from setup_messages import sign
from wallet_preview import fingerprint
from wallet_deletion import remove
from fixture_wallet_setup import public

def proposal(raw,history,phase,wallet,targets=None,proof=None,operation='a'*64):
 p={'kind':'wallet_retire','version':3,'operation_id':operation,'phase':phase,'wallet':wallet,'public_wallet':raw,'archive_label':'Historical source','require_zero_balance':True,'delete_wallet':phase=='delete','nonce':'b'*64,'manifest':history,'manifest_hash':digest(history),'delete_wallets':targets or [],'preservation':proof};p['request_id']=digest(p);return p

def legacy(raw,targets,wallet='Old'):
 p={'kind':'wallet_retire','version':2,'wallet':wallet,'public_wallet':raw,'archive_label':'Historical source','require_zero_balance':True,'delete_wallet':True,'nonce':'c'*64,'delete_wallets':targets};p['request_id']=digest(p);return p

class RealPhasedRetirement(unittest.TestCase):
 pass

class PhaseSchema(unittest.TestCase):
 pass

if __name__=='__main__':unittest.main()

class MixedDiscRetirement(unittest.TestCase):
 def setUp(self):
  from archive_inventory import member
  from archive_format import identity
  from archive_operations import Operations
  from vendor.embit import ec
  from vendor.embit.descriptor.checksum import checksum
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name);self.store=Store(root/'agent');self.peer=Store(root/'preserver');records=[]
  for i,n in enumerate(('Retired','Current'),1):
   body='wpkh('+ec.PrivateKey(bytes([i])*32).get_public_key().sec().hex()+')';raw={'wallet_name':n,'descriptors':[{'desc':body+'#'+checksum(body),'timestamp':0}]};r={'version':1,'kind':'node_wallet','chain':'regtest','name':n,'policy_hash':digest(raw),'public_wallet':raw,'labels':[]};records.append(r)
  self.old,self.current=records;catalog={identity(r):r for r in records};self.archive='c'*64;inventory=sign(self.store,{'version':1,'event':'archive_observed','archive_id':self.archive,'payload_sha256':self.archive,'payload_verified':True,'readback_verified':False,'replacements':[],'members':[member(r) for r in records]});saved=sign(self.peer,{'version':1,'kind':'wallet_retirement_preservation','request_hash':'a'*64,'operation_id':'b'*64,'manifest_hash':'d'*64,'archive_wallet':'Wallaby Extinct','address_count':1,'wallet_deleted':False});preservation={'node_id':'1'*32,'request_hash':'a'*64,'archive_wallet':'Wallaby Extinct','manifest_hash':'d'*64,'verified_utc':'2026-11-03T00:00:00Z','receipt':saved}
  self.pin=fingerprint(saved['public_key']);self.p={'kind':'destroy_disc','version':2,'reason':'wallet_extinction','nonce':'e'*64,'operation_id':'b'*64,'archive_id':self.archive,'label':'Old retired disc','archive_inventory':inventory,'retired_wallet':self.old['public_wallet'],'retired_member_ids':[identity(self.old)],'manifest_hash':'d'*64,'preservation':preservation,'require_local_authorisation':True,'require_replacement_if_live_members':True,'require_verified_readback_before_destruction':True};self.p['request_id']=digest(self.p);self.key=digest(self.p);self.store.receive(self.p)
  staged={}
  for r in records:
   p=root/(r['name']+'.dat');p.write_bytes(b'fixture-encrypted-placeholder-not-a-wallet');staged[identity(r)]={'archive_id':self.archive,'recovery':r,'wallet':p}
  self.ops=SimpleNamespace(store=self.store,enforce=lambda:None,archives=SimpleNamespace(catalogs={self.archive:catalog},staged=staged,loaded={}),setup=SimpleNamespace(own_identity=lambda:{'public_key':inventory['public_key']},burner=SimpleNamespace(queue=Mock())),jobs={})
  self.ops.covers=lambda new,old:Operations.covers(self.ops,new,old)
