"""Reserved staging and monitor accounts are never ordinary sync wallets."""
import copy,tempfile,unittest
from approval_store import Store
from fixture_public_policy import paired
from direct_wallet_catalogue import activate
from sync_offers import apply
from sync_table import state
from wallet_visibility import internal

class Visibility(unittest.TestCase):
 def test_only_reserved_generated_names_are_classified(self):
  for name in ('.wallaby-history-'+'a'*24,'Wallaby policy '+'a'*20,'Wallaby key '+'b'*12+' '+'c'*8):self.assertTrue(internal(name))
  for name in ('History','Wallaby History','Wallaby policy notes','Treasury','.wallaby-history-not-a-generated-id','Wallaby Extinct','extinct_watch'):self.assertFalse(internal(name))
 def test_internal_hints_local_rows_and_stale_direct_offers_do_not_become_sync_rows(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);activate(store);raw=paired()['public_wallet'];offers=[]
   for i,name in enumerate(('.wallaby-history-'+'a'*24,'Wallaby policy '+'a'*20)):
    wallet={**raw,'wallet_name':name};offers.append({'id':str(i+1)*64,'transfer_id':str(i+2)*64,'direction':'receive','peer':{'node_id':'source','hostname':'wallet-laptop'},'public_wallet':wallet,'status':'ready','source_online':True})
   apply(store,{'kind':'wallet_sync_offers','version':1,'revision':1,'offers':offers},'session')
   with store.edit() as s:
    s['sync_local_wallets']={o['public_wallet']['wallet_name']:{'policy_id':o['id']} for o in offers};s['direct_sync_offers']={o['id']:o for o in offers}
   self.assertEqual(state(store,[])['wallets'],[])
