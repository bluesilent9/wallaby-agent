import os,sys,subprocess,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from secure_worker import Workspace

class HelperEntry(unittest.TestCase):
 def test_actual_isolated_python_launch_can_import_local_helper_modules(self):
  source=Path(__file__).resolve().parents[1]/'src/peer_storage.py'
  r=subprocess.run(['/usr/bin/python3','-I','-B','-c','import runpy; runpy.run_path('+repr(str(source))+',run_name="isolated_entry_test")'],capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stderr)
 def test_isolated_denial_helper_can_validate_original_signer_bindings(self):
  from approval_store import digest
  import json
  root=Path(__file__).resolve().parents[1]/'src';binding={'policy_id':'a'*64,'wallet_name':'fixture','private_key_ids':['b'*64],'had_private':True,'restored':False};binding['binding_id']=digest({k:v for k,v in binding.items() if k!='restored'})
  record={'version':1,'revision':1,'wallets':{},'retirements':{'a'*64:{'policy_id':'a'*64,'address_ids':['c'*64],'wallet_names':['fixture'],'request_hash':'d'*64,'operation_id':'e'*64,'state':'complete','wallet_bindings':[binding]}}}
  script='import runpy,json; m=runpy.run_path('+repr(str(root/'denial_storage.py'))+',run_name="isolated_test"); m["validate"](json.loads('+repr(json.dumps(record))+'))'
  r=subprocess.run(['/usr/bin/python3','-I','-B','-c',script],capture_output=True,text=True,timeout=15);self.assertEqual(r.returncode,0,r.stderr)
 def test_peer_helper_is_optional_in_packaged_worker_unit(self):
  root=Path(__file__).resolve().parents[1]
  r=subprocess.run([sys.executable,str(root/'packaging/build.py')],capture_output=True,text=True,timeout=30);self.assertEqual(r.returncode,0,r.stderr)
  text=(root/'build/package/usr/lib/systemd/system/wallaby-agent-secure@.service').read_text();requires=next(l for l in text.splitlines() if l.startswith('Requires='))
  self.assertNotIn('wallaby-agent-peers',requires);self.assertIn('Wants=wallaby-agent-peers@%i.service',text)

class OptionalPeers(unittest.TestCase):
 def worker(self):
  w=Workspace.__new__(Workspace);w.lock=threading.RLock();w.peer_start_lock=threading.Lock();w.closing=False;w.store=Mock();w.setup=Mock();w.setup.own_identity.return_value={'public_key':'local fixture'};return w
 def finish(self,w):
  until=time.monotonic()+2
  while w.peer_starting and time.monotonic()<until:time.sleep(.01)
  self.assertFalse(w.peer_starting)
 def test_trust_failure_blocks_peers_without_blocking_basic_status_or_resetting_keys(self):
  w=self.worker()
  with patch('peer_channels.Peers',side_effect=ValueError('corrupt persistent trust')) as create:
   w.start_peer_support();self.finish(w);status=w.peer_action('status',{})
   self.assertIn('Node access and local wallet work remain available',status['error']);self.assertEqual(status['pairs'],[])
   with self.assertRaises(ValueError):w.peer_action('invite',{'role':'agent'})
   self.assertEqual(create.call_count,1)
  w.store.edit.assert_not_called()
 def test_blocked_peer_initialisation_cannot_block_worker_status_and_only_starts_once(self):
  w=self.worker();gate=threading.Event();started=threading.Event();w.configure=lambda env:w.start_peer_support();w.service_status=Mock(return_value={'worker_version':'current','connected':True})
  def delayed(*args):started.set();gate.wait(3);raise ValueError('fixture unavailable')
  with patch('peer_channels.Peers',side_effect=delayed) as create,patch('secure_worker.enforce'):
   try:
    w.start_peer_support();self.assertTrue(started.wait(1));before=time.monotonic();self.assertTrue(w.dispatch('service_status',[],{})['connected']);self.assertLess(time.monotonic()-before,.3);w.start_peer_support();self.assertEqual(create.call_count,1)
   finally:gate.set();self.finish(w)

class ViewerResume(unittest.TestCase):
 def test_old_busy_worker_gets_new_presentation_without_worker_stop_or_close(self):
  import viewer_recovery
  calls=[];worker={'pid':123,'start':'456'}
  def rpc(method,*args,**kw):
   calls.append(method)
   if 'peer' in kw:kw['peer'].update(worker)
   return {'busy':True,'viewer_open':len(calls)>=4,'worker_version':'2.0.0~dev62'} if method=='service_status' else {'message':'Opened'}
  with patch('viewer_recovery.call',side_effect=rpc),patch('viewer_recovery.tracked_viewers',return_value=[]),patch('viewer_recovery.signal.pidfd_send_signal') as signal:
   self.assertIn('RAM were retained',viewer_recovery.resume()['message']);signal.assert_not_called()
  self.assertEqual(calls,['service_status','service_status','ui.arm','ui.open','service_status'])
 def test_only_identified_viewer_is_signalled_and_worker_change_aborts(self):
  import viewer_recovery
  n=[0]
  def rpc(method,*args,**kw):
   n[0]+=1
   if 'peer' in kw:kw['peer'].update({'pid':123 if n[0]==1 else 124,'start':'456'})
   return {'viewer_open':True}
  with patch('viewer_recovery.call',side_effect=rpc),patch('viewer_recovery.tracked_viewers',return_value=[(8,{'pid':321,'start':'11'})]),patch('viewer_recovery.signal.pidfd_send_signal') as signal,patch('viewer_recovery.os.close'),self.assertRaisesRegex(ValueError,'changed'):viewer_recovery.resume()
  signal.assert_not_called()
 def test_missing_viewer_identity_cannot_claim_success(self):
  import viewer_recovery
  with patch('viewer_recovery.call',return_value={'viewer_open':True}),patch('viewer_recovery.tracked_viewers',return_value=[]),self.assertRaisesRegex(ValueError,'identified safely'):viewer_recovery.resume()

class Sidebar(unittest.TestCase):
 def test_sidebar_is_alphabetical(self):
  import re
  html=(Path(__file__).resolve().parents[1]/'web/index.html').read_text();nav=re.search(r'<nav aria-label="Workspace">(.*?)</nav>',html)[1]
  names=[re.sub('<[^>]+>','',v).strip() for v in re.findall(r'<button\b.*?</button>',nav)]
  self.assertEqual(names,sorted(names,key=str.lower))
 def test_peer_navigation_is_styled_and_disabled_before_any_javascript(self):
  from html.parser import HTMLParser
  rows=[]
  class Parser(HTMLParser):
   def handle_starttag(self,tag,attrs):
    a=dict(attrs)
    if tag=='button' and a.get('data-page')=='peers':rows.append(a)
  root=Path(__file__).resolve().parents[1];Parser().feed((root/'web/index.html').read_text());self.assertEqual(len(rows),1);self.assertIn('nav-item',rows[0]['class'].split());self.assertIn('disabled',rows[0]);self.assertNotIn('dev38',(root/'web/workspace.js').read_text())

class LegacyHistory(unittest.TestCase):
 def test_closing_legacy_worker_is_rearmed_before_protected_inspection_and_normal_close(self):
  import tempfile,json
  import legacy_startup_recovery as recovery
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);calls=[];worker={'pid':123,'start':'456'};armed=False
   def rpc(method,*args,**kwargs):
    nonlocal armed
    calls.append(method)
    if 'peer' in kwargs:kwargs['peer'].update(worker)
    if method=='service_status':return {'worker_version':'2.0.0~dev62','viewer_open':False,'connected':False}
    if method=='ui.arm':armed=True;return {'ok':True}
    if method=='ui.open':
     self.assertTrue(armed);request=json.loads((root/recovery.REQUEST).read_text());(root/recovery.RESULT).write_text(json.dumps({'nonce':request['nonce'],'worker':worker,'ok':True}));return {}
    raise AssertionError(method)
   with patch('legacy_startup_recovery.root',return_value=root),patch('legacy_startup_recovery.call',side_effect=rpc),patch('secure_bridge.stop',return_value={'message':'Safely closed'}) as stop:
    self.assertEqual(recovery.request_close('1'*64),{'message':'Safely closed'});stop.assert_called_once_with()
   self.assertEqual(calls,['service_status','ui.arm','service_status','ui.open','service_status']);self.assertFalse((root/recovery.REQUEST).exists())
 def fixture(self):
  from approval_store import Store,digest
  import tempfile
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);store=Store(Path(self.tmp.name)/'state');key='1'*64;job=digest({'local_retirement_history':key})
  public={'descriptors':[{'desc':'wpkh(fixture/0/*)#fixture','active':True,'internal':False}]}
  with store.edit() as s:
   s['pending'][key]={'state':'pending','proposal':{'kind':'wallet_retire'}};s['history_jobs']={job:{'wallet':'Original','state':'pending','local_only':True,'staged':None,'expected_private_keys':True,'details':{'public_wallet':public}}};s['recovery']={'state':'error'}
  status={'setups':[],'burn':{},'archives':{},'transfer':{'sending':False,'ready':False,'recovery':{'running':False,'job':{'state':'error'}}}}
  def rpc(core,method,*args):
   if method=='listwallets':return ['Original']
   if method=='getwalletinfo':return {'scanning':False,'private_keys_enabled':True}
   if method=='listdescriptors':self.assertEqual(args[0],[False]);return public
   raise AssertionError('Unexpected Core mutation: '+method)
  return store,key,job,status,rpc
 def test_only_pending_unstaged_local_history_is_dismissed_and_no_core_mutation(self):
  from legacy_startup_recovery import dismiss
  store,key,job,status,rpc=self.fixture()
  with patch('wallet_ops.rpc',side_effect=rpc),patch('build8_policy.descriptors',side_effect=lambda p:p['descriptors']):self.assertTrue(dismiss(store,object(),key,status))
  s=store.read();self.assertFalse(s['pending']);self.assertNotIn('history_jobs',s);self.assertNotIn('recovery',s);self.assertFalse(s['outbox']);self.assertNotIn(key,s['completed'])
 def test_staged_keys_attempted_jobs_running_recovery_and_unrelated_work_refuse(self):
  from legacy_startup_recovery import dismiss
  for change in ('staged','attempted','running','unrelated','expired'):
   with self.subTest(change=change):
    store,key,job,status,rpc=self.fixture()
    with store.edit() as s:
     if change=='staged':s['history_jobs'][job]['staged']='retained-private-backup.dat'
     if change=='attempted':s['history_jobs'][job]['state']='attempted'
     if change=='unrelated':s['pending']['2'*64]={'state':'pending','proposal':{'kind':'sign_psbt_partial'}}
    if change=='running':status['transfer']['recovery']['running']=True
    before=store.read()
    with patch('wallet_ops.rpc',side_effect=rpc),patch('build8_policy.descriptors',side_effect=lambda p:p['descriptors']),self.assertRaises(ValueError):dismiss(store,object(),key,status,time.monotonic()-1 if change=='expired' else None)
    self.assertEqual(before,store.read())

from test_build65 import OriginalRoles
class WorkerCore(OriginalRoles):
 def test_real_worker_configures_and_serves_core_with_failed_peer_trust(self):
  from configuration import Config
  from secure_worker import Workspace
  config=Config(self.root/'configuration');config.root.mkdir(parents=True,exist_ok=True,mode=0o700);config.values.update(self.core.config)
  with patch('secure_worker.root',return_value=self.root/'protected'),patch('secure_worker.Config',return_value=config),patch('secure_worker.enforce',return_value={}),patch('peer_channels.Peers',side_effect=ValueError('fixture trust unavailable')):
   w=Workspace();self.addCleanup(lambda:setattr(__import__('node_client'),'LOCAL_ROUTER',None));self.addCleanup(lambda:setattr(__import__('node_client'),'LOCAL_PUBLIC_RPC',None))
   result=w.dispatch('service_status',[],{});self.assertEqual(result['worker_version'],__import__('worker_upgrade').VERSION)
   deadline=time.monotonic()+2
   while w.peer_starting and time.monotonic()<deadline:time.sleep(.01)
   self.assertFalse(getattr(w,'peers',None));self.assertIn('unavailable',w.peer_error)
   response=w.dispatch('core.public',['worker-peer-fault-check','getblockcount',[],None,10],{})
   self.assertEqual(response,{'result':1})
