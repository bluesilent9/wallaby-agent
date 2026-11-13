"""History differences with identical addresses; direct authenticated updates only."""
import copy,io,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from regtest_support import Regtest
import fixture_history_recovery as retirement_fixture
from fixture_public_policy import paired,signed
from retirement_phases import imports
from wallet_recovery import staging_timestamp
from core_history import collect,install,database,TX_KEY,HISTORY_KEY
from extinct_upgrade import certify,status,snapshot
from extinct_history_sync import summary,preflight,install_packet
from history_wire import export,receive
from peer_wallet import wallet_details,read_exact,frame_read,frame_write,socket_path
from wallet_preview import receive as receive_preview,fingerprint
from local_extinction import prepare,complete
from sync_queue import apply_snapshot,choose
from batch_transfer import BatchTransfer
from vendor.embit.descriptor.checksum import checksum


class HistoryUpdate(unittest.TestCase):
 def setUp(self):
  retirement_fixture.ExtinctionRecovery.setUp(self)
  with tempfile.TemporaryDirectory() as d:self.records=collect(self.core,['Old'],[r['txid'] for r in self.p['manifest']['transactions']],d)
  imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  install(self.core,self.store,'Wallaby Extinct',self.records,self.p['manifest'])
  certify(self.core,self.store,'Wallaby Extinct',[r['address'] for r in self.p['manifest']['addresses']])
  self.transfer=paired('Wallaby Extinct');self.transfer['source_has_private_keys']=False;self.transfer['public_wallet']=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct')
  self.facts=wallet_details(self.core,self.transfer,self.store)
 def packet(self):
  with tempfile.TemporaryDirectory() as d:
   file,header=export(self.core,self.store,self.transfer,self.facts,d,version=2)
   return json.loads(file.read_text()),header,file.read_bytes()
 def destination(self,*,stale=False,allow=True):
  node=Regtest();self.addCleanup(node.close);store=Store(self.store.root/'destination')
  for height in range(1,rpc(self.core,'getblockcount')+1):rpc(node.core,'submitblock',[rpc(self.core,'getblock',[rpc(self.core,'getblockhash',[height]),0])])
  if stale:
   with tempfile.TemporaryDirectory() as d:
    file=Path(d)/'stale.dat';rpc(self.core,'backupwallet',[str(file)],'Wallaby Extinct')
    # Deliberately model damaged/older public transaction inventory with exactly
    # the same descriptors and labels. Neither production wallet is touched.
    missing=self.records[-1]['txid']
    with database(file,True) as db:
     db.execute('delete from main where key=?',(TX_KEY+bytes.fromhex(missing)[::-1],))
     marker=json.loads(db.execute('select value from main where key=?',(HISTORY_KEY,)).fetchone()[0]);marker['txids'].remove(missing);marker.pop('checksum');marker['checksum']=digest(marker)
     db.execute('update main set value=? where key=?',(json.dumps(marker).encode(),HISTORY_KEY));db.commit()
    rpc(node.core,'restorewallet',{'wallet_name':'Wallaby Extinct','backup_file':str(file),'load_on_startup':False})
   self.assertEqual(rpc(node.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],len(self.records)-1)
  if allow:
   ident=prepare(store,{**self.p,'public_wallet':self.transfer['public_wallet'],'manifest':{'addresses':[{k:r[k] for k in ('address','label')} for r in self.facts['address_labels']]}},['Old']);complete(store,ident)
  key=digest(self.transfer);apply_snapshot(store,1,[self.transfer]);choose(store,key,True,True)
  proof=signed(self.store,self.transfer,self.facts);receive_preview(store,proof)
  return node,store,key,proof


