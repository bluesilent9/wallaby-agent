"""Long-lived request-bound public reviews; live facts still gate every transfer."""
import copy,tempfile,time,unittest
from unittest.mock import patch,Mock
from approval_store import Store,digest
from test_build8 import paired,signed
from wallet_preview import verify,verify_bound,receive,sign
from sync_queue import apply_snapshot,choose
from batch_transfer import BatchTransfer
from agent_exchange import Exchange
from peer_wallet import Transfer

class ReviewLifetime(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.p=paired('Persistent review');apply_snapshot(self.store,1,[self.p]);self.facts={'public_wallet':self.p['public_wallet'],'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]};self.payload=signed(self.store,self.p,self.facts)
  v=copy.deepcopy(self.payload['preview']);v['generated_at']=int(time.time())-86400;self.payload=sign(self.store,v)
 def test_old_unbound_preview_refused_but_exact_active_bound_review_remains_usable(self):
  with self.assertRaisesRegex(ValueError,'expired'):verify(self.store,self.payload)
  receive(self.store,self.payload);choose(self.store,digest(self.p),True,True);BatchTransfer(Mock(),self.store).validate_batch([digest(self.p)],'receive');self.assertTrue(verify_bound(self.store,self.payload,self.p)['preview_hash'])
 def test_exchange_accepts_old_review_only_after_validating_current_queue_pair(self):
  response={'version':1,'accepted':[],'proposals':[{'kind':'wallet_sync_queue','revision':2,'requests':[self.p]},{'kind':'wallet_transfer_preview',**self.payload}]}
  with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value=response):Exchange(1,'fixture',self.store).once()
  self.assertEqual(self.store.read()['transfer_previews'][digest(self.p)],self.payload)
 def test_old_preview_is_not_a_new_authority_for_changed_request_signature_or_future_time(self):
  altered=copy.deepcopy(self.p);altered['preview_challenge']='f'*64
  with self.assertRaisesRegex(ValueError,'does not match'):verify_bound(self.store,self.payload,altered)
  bad=copy.deepcopy(self.payload);bad['preview']['funded_outputs']=[{'spoofed':True}]
  with self.assertRaises(ValueError):receive(self.store,bad)
  future=copy.deepcopy(self.payload['preview']);future['generated_at']=int(time.time())+10000
  with self.assertRaises(ValueError):verify_bound(self.store,sign(self.store,future),self.p)
  apply_snapshot(self.store,2,[])
  with self.assertRaises(ValueError):receive(self.store,self.payload)
 def test_signed_review_stays_immutable_even_when_old(self):
  receive(self.store,self.payload);v=copy.deepcopy(self.payload['preview']);v['generated_at']-=1
  with self.assertRaisesRegex(ValueError,'cannot be replaced'):receive(self.store,sign(self.store,v))
 def test_multi_recipient_batch_checks_each_transfer_identity(self):
  other=copy.deepcopy(self.p);other['direction']='send';other['peer']['node_id']='other';other['peer']['ipv6']='2001:db8::9';other['transfer_id']='e'*64;other['preview_challenge']='d'*64;apply_snapshot(self.store,2,[self.p,other])
  with self.store.edit() as s:s.setdefault('transfer_previews',{})[digest(other)]=self.payload
  with self.assertRaisesRegex(ValueError,'does not match'):BatchTransfer(Mock(),self.store).validate_batch([digest(other)],'send')
 def test_changed_live_facts_stop_sender_before_ssh_or_wallet_backup(self):
  p=copy.deepcopy(self.p);p['direction']='send';apply_snapshot(self.store,2,[p]);v=copy.deepcopy(self.payload['preview']);v['sender_ipv6']=p['node_ipv6'];v['receiver_ipv6']=p['peer']['ipv6'];payload=sign(self.store,v);key=digest(p)
  with self.store.edit() as s:s['active_transfer']=key;s.setdefault('transfer_previews',{})[key]=payload
  t=Transfer(Mock(),self.store);changed=copy.deepcopy(self.facts);changed['address_labels']=[{'changed':'test'}]
  import subprocess
  original=subprocess.Popen;ssh_calls=[]
  def transport(args,*a,**kw):
   if args[0]=='/usr/bin/ssh':ssh_calls.append(args);raise AssertionError('SSH must not start')
   return original(args,*a,**kw)
  with patch('peer_wallet.local_ipv6',return_value=p['node_ipv6']),patch('peer_wallet.wallet_details',return_value=changed),patch('peer_wallet.subprocess.Popen',side_effect=transport):
   with self.assertRaisesRegex(ValueError,'Wallet history changed'):t.send(key,'fixture','fixture','SHA256:'+'A'*43)
  self.assertFalse(ssh_calls);self.assertEqual(self.store.read()['pending'][key]['state'],'pending')

class IdentityStartup(unittest.TestCase):
 def test_exchange_initialises_identity_without_opening_any_workspace_page(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);response={'version':1,'accepted':[],'proposals':[{'kind':'wallet_setup_identity','version':1,'challenge':'c'*64}]}
   with patch('agent_exchange.local_ipv6',return_value=None),patch('agent_exchange.http_json',return_value=response):Exchange(1,'fixture',store).once()
   from setup_messages import verify as verify_setup
   saved=store.read();item=next(i for i in saved['outbox'].values() if i['kind']=='wallet_setup_identity');envelope=item['payload'];message=verify_setup(store,envelope,envelope['public_key']);self.assertEqual(message['challenge'],'c'*64);self.assertTrue((store.root/'preview_identity.pub').exists())

class SenderReviewReconnect(unittest.TestCase):
 def test_temporary_withdrawal_reoffers_exact_review_without_changing_comparison_code(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);p=paired('Reconnecting recipient','send');apply_snapshot(store,1,[p]);facts={'public_wallet':p['public_wallet'],'chain':'regtest','funded_outputs':[],'vaults':[],'address_labels':[]};v={'version':2,'transfer_id':p['transfer_id'],'challenge':p['preview_challenge'],'sender_ipv6':p['node_ipv6'],'receiver_ipv6':p['peer']['ipv6'],**facts,'node_tip':{'height':1,'hash':'1'*64},'generated_at':int(time.time())};payload=sign(store,v);key=digest(p)
   with store.edit() as state:state['transfer_previews']={key:payload}
   apply_snapshot(store,2,[]);self.assertNotIn(key,store.read()['pending']);self.assertNotIn(key,store.read()['transfer_previews']);apply_snapshot(store,3,[p]);self.assertEqual(store.read()['transfer_previews'][key],payload);self.assertNotIn(key,store.read()['sync_review_cache'])
 def test_changed_challenge_never_reuses_cached_review(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);p=paired('Changed recipient','send');apply_snapshot(store,1,[p]);payload={'untrusted':'not a signed review'}
   with store.edit() as state:state['sync_review_cache']={digest(p):payload}
   altered=copy.deepcopy(p);altered['preview_challenge']='d'*64;apply_snapshot(store,2,[altered]);self.assertNotIn(digest(altered),store.read().get('transfer_previews',{}))
