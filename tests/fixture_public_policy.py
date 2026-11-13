"""Queue authority, watch-only privacy and local history recovery against Core 31."""
import copy,hashlib,os,socket,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from approval_store import Store,digest
from sync_queue import apply_snapshot,choose,rows,freeze,release
from peer_wallet import active,frame_read,frame_write,socket_path,wallet_details,source_wallet
from batch_transfer import BatchTransfer
from wallet_preview import sign,receive,fingerprint,verify
from wallet_ops import rpc
from wallet_recovery import Recovery,history_missing,require,process_launch
from regtest_support import Regtest
from fixture_wallet_setup import proposal,public
from vendor.embit.descriptor.checksum import checksum


def paired(name='Wallet',direction='receive'):
    p=proposal(direction,name);p.update(transfer_version=2,node_ipv6='2001:db8::1',preview_challenge=digest(name+'challenge'));return p


def signed(store,p,facts):
    return sign(store,{'version':2,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':p['peer']['ipv6'],'receiver_ipv6':p['node_ipv6'],**facts,'node_tip':{'height':105,'hash':'1'*64},'generated_at':int(time.time())})


class QueuePolicy(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)


class KeyPrivacy(unittest.TestCase):
 pass


class RecoveryPolicy(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.core=Mock(config={'cookie':str(Path(self.tmp.name)/'.cookie')});self.manager=Recovery(self.core,self.store)


class CoreBatch(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.sender=Regtest();cls.receiver=Regtest();cls.core=cls.sender.core
    rpc(cls.core,'createwallet',{'wallet_name':'miner8'});cls.miner=rpc(cls.core,'getnewaddress',[],'miner8');rpc(cls.core,'generatetoaddress',[105,cls.miner])
    for h in range(1,106):rpc(cls.receiver.core,'submitblock',[rpc(cls.core,'getblock',[rpc(cls.core,'getblockhash',[h]),0])])
 @classmethod
 def tearDownClass(cls):cls.receiver.close();cls.sender.close()
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
 def transfer_public(self,p,details):
    apply_snapshot(self.store,1,[p]);key=digest(p);choose(self.store,key,True,True);payload=signed(self.store,p,details);receive(self.store,payload)
    t=BatchTransfer(self.receiver.core,self.store);self.addCleanup(t.close)
    with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(payload['public_key'])})
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(30);sock.connect(str(socket_path(self.store)));stream=sock.makefile('rwb',buffering=0)
            frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':details,'watch_only':True});self.assertEqual(frame_read(stream)['status'],'review_required');self.assertTrue(frame_read(stream)['watch_only'])
            frame_write(stream,{'operation':'public_wallet'});reply=frame_read(stream);self.assertEqual(reply['status'],'loaded',reply);frame_write(stream,{'status':'confirmed'})
    finally:t.thread.join(5)
    return details['public_wallet']['wallet_name']+'_watch'

if __name__=='__main__':unittest.main()
