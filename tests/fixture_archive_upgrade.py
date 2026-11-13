"""Whole-archive migration, not just the current extinction manifest."""
import copy,os,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from wallet_ops import rpc
from wallet_retirement import Retirement
from retirement_phases import prepare_history,readback
from extinct_upgrade import status,snapshot,upgrade,certify
from wallet_recovery import Recovery,staging_timestamp
from wallet_labels import fixed_address
from fixture_history_recovery import ExtinctionRecovery
from fixture_retirement import proposal
from vendor.embit.descriptor.checksum import checksum

class WholeArchive(ExtinctionRecovery):
 def legacy(self):
  rpc(self.core,'createwallet',{'wallet_name':'Long Gone'})
  address=rpc(self.core,'getnewaddress',[],'Long Gone');miner=rpc(self.core,'getnewaddress',[],'Miner')
  rpc(self.core,'generatetoaddress',[1,address]);rpc(self.core,'generatetoaddress',[101,miner]);rpc(self.core,'sendall',{'recipients':[miner]},'Long Gone');rpc(self.core,'generatetoaddress',[1,miner])
  txids={r['txid'] for r in rpc(self.core,'listtransactions',['*',100,0,True],'Long Gone')}
  rpc(self.core,'setmocktime',[int(time.time())+3*86400]);rpc(self.core,'generatetoaddress',[1,miner])
  label='Long Gone | LOST:02/01/2020 03:04:05 UTC';body='addr('+address+')';desc=body+'#'+checksum(body)
  rpc(self.core,'importdescriptors',[[{'desc':desc,'timestamp':staging_timestamp(self.core),'label':label}]],'Wallaby Extinct')
  from wallet_deletion import target,remove
  old=target(self.core,'Long Gone');rpc(self.core,'unloadwallet',['Long Gone']);remove(old,[Path(self.core.config['cookie']).parent/'wallets'])
  self.assertEqual(rpc(self.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],0)
  return address,label,txids

class PrunedMigration(unittest.TestCase):
 pass

class RecoveryReload(unittest.TestCase):
 pass

class CompletionGuards(unittest.TestCase):
 pass
