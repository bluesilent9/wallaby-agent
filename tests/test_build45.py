"""Actual pruned-node installation and fail-closed partial-wallet cancellation."""
import time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
import test_build41
from test_build41 import PASSWORD
from regtest_support import Regtest
from wallet_ops import rpc,WalletOps
from cancellation import Cancellations
from test_build19 import cancel
from approval_store import digest
from build8_policy import descriptors
from vendor.embit import ec,script
from vendor.embit.networks import NETWORKS

class PrunedInstallation(unittest.TestCase):
 def test_three_agents_install_original_keys_and_full_policy_without_restore(self):
  fixture=test_build41.CombinedCluster();self.addCleanup(fixture.doCleanups);heights=[]
  def pruned():
   n=Regtest(('-txindex=0','-prune=1','-fastprune=1'))
   try:
    address=script.p2wpkh(ec.PrivateKey(b'\x01'*32).get_public_key()).address(NETWORKS['regtest'])
    rpc(n.core,'setmocktime',[int(time.time())-7*86400]);rpc(n.core,'generatetoaddress',[900,address],timeout=120)
    rpc(n.core,'setmocktime',[int(time.time())]);rpc(n.core,'generatetoaddress',[100,address],timeout=120)
    rpc(n.core,'pruneblockchain',[600]);height=rpc(n.core,'getblockchaininfo')['pruneheight'];self.assertGreater(height,0);heights.append(height)
    return n
   except Exception:n.close();raise
  from combined_wallet import role_wallet
  def install(*args,**kwargs):
   destination=kwargs.get('destination')
   if destination:
    original=destination.call
    def forbid_restore(*a,**k):
     self.assertNotEqual(a[1],'restorewallet');return original(*a,**k)
    with patch.object(destination,'call',side_effect=forbid_restore):return role_wallet(*args,**kwargs)
   return role_wallet(*args,**kwargs)
  with patch('test_build41.Regtest',side_effect=pruned),patch('combined_wallet.role_wallet',side_effect=install):fixture.setUp()
  for i,(a,n) in enumerate(zip(fixture.agents,fixture.nodes)):
   record=next(iter(a.store.read()['approved_wallets'].values()));name=next(iter(record['signing_wallets'].values()))
   self.assertEqual(rpc(n.core,'listwallets'),[name]);self.assertEqual(rpc(n.core,'getwalletinfo',[],name)['unlocked_until'],0)
   self.assertEqual(descriptors(rpc(n.core,'listdescriptors',[False],name)),descriptors({'wallet_name':name,'descriptors':[{'desc':d} for d in fixture.descs]}))
   self.assertEqual(rpc(n.core,'getblockchaininfo')['pruneheight'],heights[i])
   # The old offline-backup path fails on this same real pruned chain,
   # Its offline 'now' timestamp resolves to the genesis tip's time.
   if i==1:
    session=a.sessions[fixture.h];role=next(r for r in fixture.p['cosigners'] if r['storage']=='node' and r['agent_key']==a.own_identity()['public_key'])
    with patch('wallet_setup.secret_dialog',return_value=PASSWORD):offline_name=role_wallet(a,{**session,'created_at':1296688602},role,session['review'])
    backup=Path(fixture.tmp.name)/'old-offline.dat';rpc(session['core'].core,'backupwallet',[str(backup)],offline_name)
    with self.assertRaisesRegex(ValueError,'predates the retained pruned history'):rpc(n.core,'restorewallet',{'wallet_name':'old restore','backup_file':str(backup)})
  self.assertEqual(len(fixture.agents[1].disc_sessions),2)
  self.assertEqual(fixture.agents[1].sessions[fixture.h]['phase'],'awaiting_disc')

class FailedInstallation(unittest.TestCase):
 def test_blank_created_wallet_is_reviewable_but_unknown_policy_is_not(self):
  fixture=test_build41.CombinedCluster();self.addCleanup(fixture.doCleanups)
  def fail(setup,session,role,facts,destination=None,target=None):
   self.assertIsNotNone(destination)
   rpc(destination,'createwallet',{'wallet_name':target,'blank':True,'descriptors':True,'passphrase':PASSWORD})
   session.setdefault('created_wallets',[]).append(target)
   raise ValueError('fixture import failure')
  with patch('combined_wallet.role_wallet',side_effect=fail),self.assertRaisesRegex(ValueError,'fixture import failure'):fixture.setUp()
  a=fixture.agents[0];session=a.sessions[fixture.h];name=session['created_wallets'][0]
  self.assertEqual(session['phase'],'installation_failed');self.assertIsNone(session['core'].process.poll())
  self.assertEqual(a.store.read()['pending'][digest(fixture.final)]['state'],'attempted')
  c=Cancellations(a.core,a.store,a,WalletOps(a.core,a.store));key=c.receive(cancel('wallet',[fixture.h],[fixture.h]));review=c.review(key)
  self.assertTrue(any(w['wallet']==name for w in review['cancellation']['wallets']))
  # An unacknowledged creation cannot use the partial-policy exception.
  session['created_wallets']=[]
  with self.assertRaisesRegex(ValueError,'no longer matches'):c.review(key)
  session['created_wallets']=[name]
  # Nor can an unrelated descriptor smuggled into the newly created wallet.
  address=script.p2wpkh(ec.PrivateKey(b'\x03'*32).get_public_key()).address(NETWORKS['regtest'])
  from vendor.embit.descriptor.checksum import checksum
  body='wpkh('+ec.PrivateKey(b'\x03'*32).wif(NETWORKS['regtest'])+')';rpc(a.core,'walletpassphrase',[PASSWORD,60],name)
  result=rpc(a.core,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':int(time.time())}]],name);self.assertTrue(all(r.get('success') for r in result),result);rpc(a.core,'walletlock',[],name)
  with self.assertRaisesRegex(ValueError,'no longer matches'):c.review(key)

class Diagnostics(unittest.TestCase):
 def test_prune_reason_is_fixed_and_raw_exception_never_exported(self):
  core=Mock();core.call.return_value={'error':{'code':-4,'message':'Wallet loading failed. Prune: last synchronisation secret-do-not-log'}}
  with self.assertRaises(ValueError) as error:rpc(core,'restorewallet',{})
  self.assertIn('predates',str(error.exception));self.assertNotIn('secret-do-not-log',str(error.exception))
