import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from sidebar_counts import counts,save,load
from wallet_ops import rpc
from regtest_support import Regtest

class Counts(unittest.TestCase):
 def test_counts_and_persistence_contain_only_aggregate_attention(self):
  view={'pending':[{}],'setups':[{}],'transfer':{'pending_count':3,'recovery':{'status':'Requires Blockchain Download','can_refresh':True}},'archives':{'staged':[{}],'loaded':[{}]},'burn':{'id':'opaque','phase':'uncertain'}}
  value=counts(view,2);self.assertEqual([value[k] for k in ('authorise','synchronisation','burn','peers')],[2,4,3,2])
  with tempfile.TemporaryDirectory() as folder,patch('sidebar_counts.location',return_value=Path(folder)/'counts.json'):
   save({**value,'wallet_name':'secret','message':True,'services':-5});stored=load();self.assertEqual(stored['authorise'],2);self.assertEqual(stored['services'],0);self.assertEqual(stored['message'],0);self.assertNotIn('secret',(Path(folder)/'counts.json').read_text())

class VaultFunds(unittest.TestCase):
 def test_local_core_uses_each_funded_policy_and_counts_locked_coins(self):
  from vault_history import status
  node=Regtest();self.addCleanup(node.close);core=node.core
  rpc(core,'createwallet',{'wallet_name':'Funding'});mine=rpc(core,'getnewaddress',[],'Funding');pub=rpc(core,'getaddressinfo',[mine],'Funding')['pubkey'];rpc(core,'generatetoaddress',[101,mine])
  rpc(core,'createwallet',{'wallet_name':'Vault','disable_private_keys':True,'blank':True})
  def policy(height):return rpc(core,'getdescriptorinfo',[f'wsh(and_v(v:after({height}),pk({pub})))'])['descriptor']
  def install(height):
   desc=policy(height);self.assertTrue(rpc(core,'importdescriptors',[[{'desc':desc,'timestamp':'now'}]],'Vault')[0]['success']);return rpc(core,'deriveaddresses',[desc])[0]
  address=install(200)
  def state():return status(core,'Vault',rpc(core,'listdescriptors',[False],'Vault'))
  self.assertEqual(state(),{'state':'unfunded'})
  tx=rpc(core,'sendtoaddress',[address,'1'],'Funding');rpc(core,'generatetoaddress',[1,mine]);self.assertEqual(state()['state'],'locked')
  coin=rpc(core,'listunspent',[0],'Vault')[0];rpc(core,'lockunspent',[False,[{'txid':coin['txid'],'vout':coin['vout']}]],'Vault');self.assertEqual(state()['state'],'locked')
  rpc(core,'generatetoaddress',[98,mine]);self.assertEqual(state(),{'state':'unlocked'})
  newer=install(400);rpc(core,'sendtoaddress',[newer,'1'],'Funding');rpc(core,'generatetoaddress',[1,mine]);self.assertEqual(state(),{'state':'mixed'})
 def test_unrecognised_vault_and_node_failure_never_claim_unlocked(self):
  from vault_history import status
  self.assertIsNone(status(None,'Plain',{'descriptors':[{'desc':'wpkh(dummy)'}]}))
  self.assertEqual(status(None,'Vault',{'descriptors':[{'desc':'wsh(after(999))'}]}),{'state':'error'})

class SourceStorage(unittest.TestCase):
 def test_offer_origin_is_optional_and_closed_enum(self):
  from sync_offers import validate
  from fixture_public_policy import paired
  # Discovery never grants transfer authority; origin is only a presentation hint.
  offer={'id':'a'*64,'transfer_id':'b'*64,'direction':'receive','peer':{'node_id':'source','hostname':'Laptop'},'public_wallet':paired()['public_wallet'],'status':'ready','source_storage':'disc'}
  self.assertEqual(validate({'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[offer]})['offers'][0]['source_storage'],'disc')
  offer['source_storage']='server'
  with self.assertRaises(ValueError):validate({'kind':'wallet_sync_offers','version':1,'revision':1,'offers':[offer]})

class CleanupOverlay(unittest.TestCase):
 def test_worker_closing_then_cleanup_markers_never_report_unlocked(self):
  from app import workspace
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with patch('app.runtime_dir',return_value=root),patch('protected_memory.inside',return_value=False),patch('protected_memory.required',return_value=True),patch('app.read_status',return_value={'color':'green'}),patch('secure_bridge.call',return_value={'closing':True,'viewer_open':False,'worker_version':'2.0.0~dev93','worker_protocol':1}):
    self.assertTrue(workspace(SimpleNamespace())['cleanup_pending'])
   with patch('app.runtime_dir',return_value=root),patch('protected_memory.inside',return_value=False),patch('protected_memory.required',return_value=True),patch('secure_bridge.call',side_effect=ValueError('Worker stopped')),patch('sidebar_counts.load',return_value={'authorise':2}):
    marker=root/'workspace-closing';marker.touch();self.assertTrue(workspace(None)['cleanup_pending']);marker.unlink()
    marker=root/'worker-upgrading';marker.touch();self.assertTrue(workspace(None)['cleanup_pending']);marker.unlink()
    result=workspace(None);self.assertFalse(result['cleanup_pending']);self.assertEqual(result['sidebar_counts'],{'authorise':2})
