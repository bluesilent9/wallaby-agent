"""Build 12 local fee decisions and explicit multi-disc operations; no physical drives."""
import tempfile,unittest,sys,time,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).parent)]
from disc_backup import Burner,parse_speeds,speed_value
from wallet_ops import assess_fee,WalletOps
from approval_store import Store

class Fees(unittest.TestCase):
 def test_change_is_excluded_only_for_input_owners(self):
    inputs=[{'wallets':['Sender']}]
    out=[{'sats':'1000','change':False,'wallets':[]},{'sats':'8000','change':True,'wallets':['Sender']}]
    r=assess_fee(inputs,out,100,200);self.assertTrue(r['requires_ack']);self.assertEqual(r['basis_sats'],'1000')
    out[1]['wallets']=['Other'];r=assess_fee(inputs,out,100,200);self.assertFalse(r['requires_ack']);self.assertEqual(r['basis_sats'],'9000')
 def test_fee_thresholds_no_remote_rate_and_zero_payment(self):
    out=[{'sats':'10000000','change':False,'wallets':[]}]
    self.assertFalse(assess_fee([],out,9999,100)['requires_ack']);self.assertTrue(assess_fee([],out,10000,100)['high_rate'])
    self.assertTrue(assess_fee([],[],1,100)['high_share'])
    for v in (None,0,-1,True):
     with self.assertRaises(ValueError):assess_fee([],out,100,v)
 def test_missing_fee_ack_preserves_review_without_marking_attempted_or_unlocking(self):
    with tempfile.TemporaryDirectory() as tmp:
     ops=WalletOps(None,Store(tmp));review={'inputs':[{'txid':'f'*64,'vout':0}],'fee_review':{'requires_ack':True}}
     ops.prepared['key']={'kind':'sign_psbt_partial','created':time.time(),'psbt':'fixture','wallet':'Local','chain':'regtest','review':review}
     with patch.object(ops,'review',return_value=review),patch('wallet_ops.rpc',return_value={}) as call:
      with self.assertRaisesRegex(ValueError,'acknowledge'):ops.sign('key','unused','partial')
      self.assertEqual(call.call_args.args[1],'gettxout');self.assertEqual(call.call_count,1)
     self.assertIn('key',ops.prepared)
     for value in ('true',1,None):
      with self.assertRaises(ValueError):ops.sign('key','unused','partial',value)
 def test_retired_local_builder_is_unavailable(self):
    self.assertFalse(hasattr(WalletOps,'build'));self.assertFalse(hasattr(WalletOps,'list_wallets'))

class Discs(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.calls=[]
    self.burner=Burner(self.root,lambda *args:self.calls.append(args));self.burner.authorise('job',{}, {'policy_hash':'f'*64})
    self.details={'speeds':['2','4'],'capacity_bytes':12*1024*1024}
 def test_default_one_disc_and_slowest_speed(self):
    state=self.burner.state();self.assertEqual(state['disc_count'],1);self.assertEqual(state['speed'],'slowest');self.assertEqual(speed_value('slowest'),'-1')
 def test_reported_speeds_sorted_and_bad_values_rejected(self):
    self.assertEqual(parse_speeds('Write speed  0 :  8990k , 2.0xBD\nWrite speed  1 : 17980k , 4.0xBD\nWrite speed 2 : 8990k , 2.0xBD','BD'),['2','4'])
    self.assertEqual(parse_speeds('Write speed 0 : 2770k , 2.0xDVD','DVD'),['2'])
    for value in ('max','0','-1','0.5.5','65','2;reboot',1,None):
     with self.assertRaises(ValueError):speed_value(value)
 def test_count_confirmation_and_numeric_speed_validation_before_writing(self):
    with patch('disc_backup.media',return_value=self.details):
     for count in (0,100,True,'2'):
      with self.assertRaises(ValueError):self.burner.validate_options('/dev/sr0',True,count)
     with self.assertRaises(ValueError):self.burner.validate_options('/dev/sr0',False)
     with self.assertRaises(ValueError):self.burner.validate_options('/dev/sr0',True,1,'1')
     self.burner.validate_options('/dev/sr0',True,1,'2')
 def fake_pack(self,root,wallets,recovery,password):
    disc=root/'disc';disc.mkdir(exist_ok=True);(disc/'recovery.wallaby').write_bytes(b'encrypted fixture'*100);return disc
 def fake_write(self,device,source,total,progress,speed):
    data=b''.join(source);self.assertEqual(len(data),total);self.assertEqual(speed,'slowest');progress(total);return hashlib.sha256(data).hexdigest()
 def test_each_disc_requires_confirmation_reuses_package_and_completes_once(self):
    with patch('disc_backup.media',return_value=self.details),patch('disc_backup.pack',side_effect=self.fake_pack) as pack,patch('disc_backup.image',side_effect=lambda disc,iso:iso.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=self.fake_write) as write,patch('disc_backup.readback') as read:
     self.burner.start('/dev/sr0',True,'password',2);self.burner.thread.join(10)
     self.assertEqual(self.burner.state()['phase'],'awaiting_disc');self.assertEqual(self.calls,[]);self.assertEqual(write.call_count,1)
     with self.assertRaises(ValueError):self.burner.start('/dev/sr0',True,None,1)
     with self.assertRaises(ValueError):self.burner.start('/dev/sr0',False,None,2)
     self.burner.start('/dev/sr0',True,None,2);self.burner.thread.join(10)
     self.assertEqual(self.burner.state()['phase'],'complete');self.assertEqual(self.burner.state()['discs_verified'],2);self.assertEqual(pack.call_count,1);self.assertEqual(read.call_count,2);self.assertEqual(len(self.calls),1);self.assertFalse((self.root/'job').exists())
     with self.assertRaises(ValueError):self.burner.start('/dev/sr0',True,None,2)
 def test_failed_verification_never_counts_disc_or_repeats_write(self):
    with patch('disc_backup.media',return_value=self.details),patch('disc_backup.pack',side_effect=self.fake_pack),patch('disc_backup.image',side_effect=lambda disc,iso:iso.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=self.fake_write) as write,patch('disc_backup.readback',side_effect=ValueError('Bad readback')):
     self.burner.start('/dev/sr0',True,'password');self.burner.thread.join(10)
     self.assertEqual(self.burner.state()['phase'],'uncertain');self.assertEqual(self.burner.state()['discs_verified'],0);self.assertEqual(write.call_count,1);self.assertEqual(self.calls,[])
 def test_completion_failure_requires_reconciliation_without_reburn(self):
    self.burner.on_complete=lambda *args:(_ for _ in ()).throw(ValueError('Offline completion'))
    with patch('disc_backup.media',return_value=self.details),patch('disc_backup.pack',side_effect=self.fake_pack),patch('disc_backup.image',side_effect=lambda disc,iso:iso.write_bytes(b'iso')),patch('disc_backup.write_stream',side_effect=self.fake_write),patch('disc_backup.readback'):
     self.burner.start('/dev/sr0',True,'password');self.burner.thread.join(10)
     self.assertEqual(self.burner.state()['phase'],'completion_uncertain');self.assertEqual(self.burner.state()['discs_verified'],1)
     with self.assertRaises(ValueError):self.burner.start('/dev/sr0',True,'password')

class NativePrompt(unittest.TestCase):
 def test_prompt_uses_routed_core_wallet_and_no_remote_display_name(self):
    from secure_worker import Workspace
    from types import SimpleNamespace
    from unittest.mock import Mock
    import threading
    with tempfile.TemporaryDirectory() as tmp:
     worker=Workspace.__new__(Workspace);worker.lock=threading.RLock();worker.store=Store(tmp);worker.configure=lambda env:None;worker.environment={};worker.archives=None
     worker.ops=SimpleNamespace(core=object(),prepared={'key':{'wallet':'local-route','display_name':'Untrusted Dashboard name','fee_review':{},'review':{'fee_review':{'requires_ack':False}}}},sign=Mock(return_value={'queued':True}))
     with patch('secure_worker.enforce'),patch('wallet_ops.rpc',return_value={'walletname':'Exact Core wallet','unlocked_until':0}),patch('secure_worker.secret_dialog',return_value='fixture-password') as prompt:
      worker.dispatch('wallet.sign',['key','partial',False],{})
      text=prompt.call_args.args[0];self.assertIn('Exact Core wallet',text);self.assertIn('local-route',text);self.assertIn('sign the reviewed transaction',text);self.assertNotIn('Untrusted Dashboard name',text)
     worker.ops.sign.assert_called_once_with('key','fixture-password','partial',False)
