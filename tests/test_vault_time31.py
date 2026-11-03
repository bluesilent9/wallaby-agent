import unittest
from unittest.mock import patch
from vault_time import estimates,for_review

class VaultTime(unittest.TestCase):
 def call(self,core,method,params=None):
  if method=='getblockchaininfo':return self.chain
  if method=='getblockhash':return params[0]
  if method=='getblockheader':return {'time':self.now-(self.chain['blocks']-params[0])*self.interval}
  raise AssertionError(method)
 def setUp(self):self.now=1800000000;self.interval=590;self.chain={'blocks':1000000,'headers':1000000,'initialblockdownload':False,'pruned':True,'pruneheight':999900}
 def run_estimate(self,heights):
  with patch('vault_time.rpc',side_effect=self.call):return estimates(None,heights,self.now)
 def test_pruned_headers_three_year_average_and_cltv_boundary(self):
  r=self.run_estimate([1000144])[0]
  self.assertEqual(r['seconds_per_block'],590);self.assertEqual(r['sample_blocks'],157788);self.assertEqual(r['first_spend_block'],1000145)
  from datetime import datetime
  self.assertLess(abs(datetime.fromisoformat(r['utc']).timestamp()-(self.now+145*590)),60)
  self.assertEqual(datetime.fromisoformat(r['utc']),datetime.fromisoformat(r['local']));self.assertIn('Rough estimate',r['notice']);self.assertNotIn('99%',str(r))
 def test_short_chain_and_invalid_history_fallback(self):
  self.chain['blocks']=100;self.chain['headers']=100
  self.assertEqual(self.run_estimate([200])[0]['seconds_per_block'],600)
  self.chain['blocks']=1000000;self.interval=1
  self.assertEqual(self.run_estimate([1000100])[0]['sample_blocks'],0)
 def test_unavailable_header_is_not_a_promise(self):
  with patch('vault_time.rpc',side_effect=ValueError):r=estimates(None,[200],self.now)
  self.assertEqual(r[0]['status'],'unavailable');self.assertNotIn('utc',r[0])
 def test_reached_height_and_stale_tip(self):
  self.chain['initialblockdownload']=True
  r=self.run_estimate([1000000,999999]);self.assertTrue(all(x['status']=='height_reached' for x in r));self.assertIn('catching up',r[0]['notice'])
 def test_distinct_verified_input_output_and_legacy_heights_only(self):
  review={'outputs':[{'vault_policy':{'height':20}}],'inputs':[{'vault_policies':[{'height':30}]}],'locktime':999}
  with patch('vault_time.estimates',return_value=[]) as e:for_review(None,review,{'vault_intents':[{'vault':{'height':40}}]})
  self.assertEqual(e.call_args.args[1],[20,30,40]);self.assertNotIn(999,e.call_args.args[1])
 def test_extreme_height_is_unavailable_instead_of_crashing_review(self):
  self.interval=3600
  self.assertEqual(self.run_estimate([499999999])[0]['status'],'unavailable')
