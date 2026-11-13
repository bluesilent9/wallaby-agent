"""Build 8 interoperability and local-only peer wallet transfer regression."""
import base64,copy,hashlib,io,json,os,socket,struct,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from vault_policy import validate_proposal
from public_policy import descriptors
from peer_wallet import Transfer,active,frame_read,frame_write,firewall_verdict,validate_details,source_wallet,wallet_details
from agent_exchange import Exchange
from wallet_ops import WalletOps,rpc
from regtest_support import Regtest
from vendor.embit import bip32
from vendor.embit.descriptor.checksum import checksum

def public(name='Example'):
    key=bip32.HDKey.from_seed(b'\x01'*32).to_public().to_base58();d='wpkh('+key+'/0/*)'
    return {'wallet_name':name,'descriptors':[{'desc':d+'#'+checksum(d),'active':True,'internal':False,'timestamp':0,'range':[0,10],'next_index':0}]}

def proposal(direction='receive',name='Example'):
    return {'kind':'wallet_transfer','direction':direction,'transfer_id':digest(name),'peer':{'node_id':'peer','hostname':'example','ipv6':'2001:db8::2'},'public_wallet':public(name),'source_has_private_keys':True,'earliest_timestamp':0,'requires_blockchain_redownload':False}

class PublicProtocol(unittest.TestCase):
 pass

class RouteDisplay(unittest.TestCase):
 pass

class PreviewSecurity(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.p=proposal();self.p.update(preview_challenge='c'*64,node_ipv6='2001:db8::1');self.store.receive(self.p);self.key=active(self.store)[0]
    from wallet_preview import sign
    self.payload=sign(self.store,{'version':1,'transfer_id':self.p['transfer_id'],'challenge':self.p['preview_challenge'],'sender_ipv6':self.p['peer']['ipv6'],'receiver_ipv6':self.p['node_ipv6'],'public_wallet':self.p['public_wallet'],'chain':'regtest','funded_outputs':[],'node_tip':{'height':0,'hash':'0'*64},'generated_at':int(time.time())})

@unittest.skipUnless(Path(os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind')).exists(),'Core 31 required')
class CoreBuild7(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.node=Regtest();cls.core=cls.node.core;rpc(cls.core,'createwallet',{'wallet_name':'miner7'});cls.miner=rpc(cls.core,'getnewaddress',[],'miner7');rpc(cls.core,'generatetoaddress',[105,cls.miner]);cls.counter=0
 @classmethod
 def tearDownClass(cls):cls.node.close()
 def setUp(self):
    type(self).counter+=1;self.source='build7source'+str(self.counter);self.dest='build7dest'+str(self.counter)
    for name in (self.source,self.dest):rpc(self.core,'createwallet',{'wallet_name':name,'passphrase':'test-password'})
    rpc(self.core,'sendtoaddress',[rpc(self.core,'getnewaddress',[],self.source),'1'],'miner7');rpc(self.core,'generatetoaddress',[1,self.miner]);self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.ops=WalletOps(self.core,self.store)
 def build(self):
    from vault_fixture import proposal
    return proposal(self.ops,self.source,self.dest)

