"""Actual missing-block recovery with -prune=550 unchanged from start to finish.

All nodes/data are isolated regtest fixtures. Core’s official -fastprune test
option uses small block files so real block deletion can be tested cheaply. RPC block delivery substitutes for
Internet peers and systemd-run is substituted only by the test child launcher.
"""
import hashlib,os,struct,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from regtest_support import Regtest
from wallet_ops import rpc,install_vault,sats
from wallet_recovery import Recovery,require,pruning_identity,staging_timestamp
from peer_wallet import wallet_details
from approval_store import Store,digest
from test_build8 import paired
from vendor.embit.transaction import Transaction,TransactionInput,TransactionOutput
from vendor.embit.script import Script,address_to_scriptpubkey,p2wpkh
from vendor.embit import ec
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from vendor.embit.networks import NETWORKS



def padding_block(core,when):
    # One 60 KiB block rolls Core's official fastprune fixture into a new file.
    height=rpc(core,'getblockcount')+1;number=height.to_bytes((height.bit_length()+7)//8,'little')
    if number[-1]&128:number+=b'\x00'
    tx=Transaction(vin=[TransactionInput(b'\x00'*32,0xffffffff,Script(bytes([len(number)])+number+b'\x00'))],vout=[TransactionOutput((50*100000000)>>(height//150),Script(b'\x51')),TransactionOutput(0,Script(b'\x6a'+b'\x00'*60000))])
    prefix=struct.pack('<I',4)+bytes.fromhex(rpc(core,'getbestblockhash'))[::-1]+tx.hash()+struct.pack('<II',when,0x207fffff);nonce=0;target=0x7fffff << (8*(0x20-3))
    while True:
        header=prefix+struct.pack('<I',nonce)
        if int.from_bytes(hashlib.sha256(hashlib.sha256(header).digest()).digest(),'little')<=target:break
        nonce+=1
    result=rpc(core,'submitblock',[(header+b'\x01'+tx.serialize()).hex()])
    if result is not None:raise AssertionError('Fixture block rejected: '+str(result))


class PrunedRecovery(unittest.TestCase):
 def test_full_and_watch_wallets_vaults_labels_and_change_survive_pruned_replay(self):
    before=int(time.time())-3*86400;after=before+2*86400
    source=Regtest(['-mocktime='+str(before)]);receiver=Regtest(['-prune=550','-txindex=0','-fastprune=1','-mocktime='+str(before)]);self.addCleanup(source.close);self.addCleanup(receiver.close)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);sender_store=Store(root/'sender');store=Store(root/'receiver');c=source.core;r=receiver.core
        rpc(c,'createwallet',{'wallet_name':'Original cold','passphrase':'fixture-only'});rpc(c,'createwallet',{'wallet_name':'Miner'})
        old_address=rpc(c,'getnewaddress',['Cold income'],'Original cold');miner=rpc(c,'getnewaddress',[],'Miner');rpc(c,'generatetoaddress',[1,old_address]);rpc(c,'generatetoaddress',[104,miner])
        raw=rpc(c,'listdescriptors',[False],'Original cold');src=raw['descriptors'][0]['desc'];pub=Descriptor.from_string(src.split('#')[0]).derive(0).key.get_public_key().sec().hex();body='wsh(and_v(v:pk('+pub+'),after(2000)))';vault={'version':1,'chain':'regtest','descriptor':body+'#'+checksum(body),'address':Descriptor.from_string(body).script_pubkey().address(NETWORKS['regtest']),'height':2000,'source':{'descriptor':src,'index':0},'timestamp':0};install_vault(c,vault,sender_store,owner='Original cold')
        rpc(c,'walletpassphrase',['fixture-only',60],'Original cold');rpc(c,'sendtoaddress',[vault['address'],'1'],'Original cold');rpc(c,'walletlock',[],'Original cold');rpc(c,'generatetoaddress',[1,miner])
        # Fund a labelled address-only historical wallet before the blocks disappear.
        archived=p2wpkh(ec.PrivateKey(b'\x03'*32).get_public_key()).address(NETWORKS['regtest']);fixed='addr('+archived+')';label='Extinct example | LOST:02/01/2020 00:00:00 UTC'
        rpc(c,'createwallet',{'wallet_name':'Old address archive','disable_private_keys':True,'blank':True,'descriptors':True});rpc(c,'importdescriptors',{'requests':[{'desc':fixed+'#'+checksum(fixed),'timestamp':0,'label':label}]},'Old address archive');rpc(c,'sendtoaddress',[archived,'0.5'],'Miner');rpc(c,'generatetoaddress',[1,miner])
        change=rpc(c,'listunspent',[1], 'Original cold')[0];rpc(c,'lockunspent',[False,[{'txid':change['txid'],'vout':change['vout']}]],'Original cold')
        raw=rpc(c,'listdescriptors',[False],'Original cold');p=paired('Pruned private','send');p['public_wallet']=raw;full=wallet_details(c,p,sender_store)
        self.assertEqual(len(full['funded_outputs']),2) # Locked change AND locked-height vault.
        p=paired('Pruned archive','send');p['source_has_private_keys']=False;p['public_wallet']=rpc(c,'listdescriptors',[False],'Old address archive');watch=wallet_details(c,p,sender_store)
        stage=root/'received-wallet.dat';rpc(c,'backupwallet',[str(stage)],'Original cold')
        rpc(c,'setmocktime',[after]);rpc(r,'setmocktime',[after]);padding_block(c,before+600);rpc(c,'generatetoaddress',[310,miner],timeout=120);height=rpc(c,'getblockcount')
        for h in range(1,height+1):rpc(r,'submitblock',[rpc(c,'getblock',[rpc(c,'getblockhash',[h]),0])])
        original=pruning_identity(rpc(r,'getblockchaininfo'));self.assertTrue(original['pruned']);self.assertEqual(original['prune_target_size'],550*1024*1024)
        boundary=rpc(r,'pruneblockchain',[height-288]);self.assertGreaterEqual(boundary,107)
        # Missing historical blocks really have been deleted, not just mocked.
        with self.assertRaises(ValueError):rpc(r,'getblock',[rpc(r,'getblockhash',[106]),0])
        rpc(r,'createwallet',{'wallet_name':'Received address archive','disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
        imported=rpc(r,'importdescriptors',{'requests':[{'desc':fixed+'#'+checksum(fixed),'timestamp':staging_timestamp(r),'label':label}]},'Received address archive');self.assertTrue(imported[0]['success'],imported)
        require(store,'a'*64,'Received cold',full,stage);require(store,'b'*64,'Received address archive',watch)
        manager=Recovery(r,store);self.assertEqual(manager.state()['status'],'Requires Blockchain Download');real_run=subprocess.run;launched=[];replayed=[]
        def deliver():
            try:
                # Wait for persisted proof that BOTH wallets and vault monitors were
                # installed before delivering any historical blocks.
                while time.monotonic()<deadline:
                    if store.read().get('recovery',{}).get('replay_ready'):break
                    time.sleep(.05)
                else:raise AssertionError('Wallet preparation did not finish.')
                self.assertEqual(pruning_identity(rpc(r,'getblockchaininfo')),original)
                for h in range(1,height+1):rpc(r,'submitblock',[rpc(c,'getblock',[rpc(c,'getblockhash',[h]),0])])
                replayed.append(True)
            except Exception as error:replayed.append(error)
        def launch(command,*args,**kwargs):
            if command[:3]==['/usr/bin/systemctl','--user','show-environment']:return Mock(returncode=0)
            if command[0]=='/usr/bin/systemd-run':
                receiver.process.wait(timeout=10);arguments=command[command.index('--')+1:];launched.append(arguments)
                # The fixture uses a historical clock to make a genuine >2-hour
                # pruning gap. Advancing that test clock is not a recovery option.
                receiver.process=subprocess.Popen(arguments+['-mocktime='+str(after)],stdout=receiver.log,stderr=subprocess.STDOUT)
                import threading
                threading.Thread(target=deliver,daemon=True).start();return Mock(returncode=0)
            return real_run(command,*args,**kwargs)
        deadline=time.monotonic()+240
        with patch('wallet_recovery.subprocess.run',side_effect=launch):
            plan=manager.plan();self.assertEqual(plan['mode'],'download');self.assertNotIn('required_free',plan);manager.start(plan['id']);manager.thread.join(240)
        if store.read()['recovery']['state']!='complete':
            print('FIXTURE WATCH ORIGINAL',watch['public_wallet'],flush=True)
            print('FIXTURE WATCH RECEIVED',rpc(r,'listdescriptors',[False],'Received address archive'),rpc(r,'getwalletinfo',[],'Received address archive'),flush=True)
        self.assertFalse(manager.thread.is_alive(),store.read().get('recovery'));self.assertEqual(store.read()['recovery']['state'],'complete',store.read()['recovery']);self.assertEqual(replayed,[True]);self.assertEqual(len(launched),1)
        self.assertEqual([a for a in launched[0] if a.startswith('-prune')],['-prune=550']);self.assertEqual(pruning_identity(rpc(r,'getblockchaininfo')),original)
        self.assertGreater(rpc(r,'getwalletinfo',[],'Received cold')['txcount'],0);self.assertEqual(rpc(r,'getaddressinfo',[old_address],'Received cold')['labels'],['Cold income']);self.assertEqual(rpc(r,'getaddressinfo',[archived],'Received address archive')['labels'],[label]);self.assertFalse(rpc(r,'getwalletinfo',[],'Received address archive')['private_keys_enabled'])
        monitor=store.read()['vaults'][digest(vault)]['monitor_wallet'];self.assertEqual(sats(rpc(r,'getbalances',[],monitor)['mine']['trusted']),100000000)
        # Prune the recovered old block file again: wallet history/balances remain.
        rpc(r,'pruneblockchain',[height-288]);self.assertEqual(pruning_identity(rpc(r,'getblockchaininfo')),original)
        self.assertEqual(sats(rpc(r,'getbalances',[],'Received address archive')['mine']['trusted']),50000000);self.assertGreater(rpc(r,'getwalletinfo',[],'Received cold')['txcount'],0)
        self.assertLessEqual(rpc(r,'getwalletinfo',[],'Received address archive')['birthtime'],before)
        self.assertFalse(store.read()['history_jobs']);self.assertFalse(stage.exists())

if __name__=='__main__':unittest.main()
