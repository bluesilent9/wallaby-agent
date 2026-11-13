import copy,threading,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from approval_store import Store,digest
from fixture_public_policy import paired
from wallet_preview import prepare

class PreviewConcurrency(unittest.TestCase):
 def test_concurrent_reviews_keep_one_frozen_signed_snapshot(self):
  with tempfile.TemporaryDirectory() as folder:
   store=Store(Path(folder));p=paired();key=digest(p)
   with store.edit() as s:s['pending'][key]={'proposal':p,'state':'pending'}
   barrier=threading.Barrier(2);sequence=iter(['first signature','second signature'])
   def sign(store,preview):
    payload={'preview':preview,'signature':next(sequence),'public_key':'fixture'};barrier.wait(timeout=5);return payload
   with patch('wallet_traits.source_storage',return_value='node'),patch('peer_wallet.wallet_details',return_value={'public_wallet':p['public_wallet']}),patch('peer_wallet.local_ipv6',return_value=p['node_ipv6']),patch('wallet_ops.rpc',return_value={'blocks':100,'headers':100,'bestblockhash':'a'*64}),patch('wallet_preview.sign',side_effect=sign),patch('wallet_preview.verify'):
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:prepare(None,store,key,p),range(2)))
   self.assertEqual(results[0],results[1]);self.assertEqual(len(store.read()['outbox']),1);self.assertEqual(store.read()['transfer_previews'][key],results[0])
