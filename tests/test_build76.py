"""Production worker startup must reach its asynchronously initialised peers."""
import os,json,select,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from contextlib import ExitStack
from regtest_support import Regtest

class Process:
 def __init__(self,case,root,*args):
  self.log=(root/(str(args[0])+str(time.monotonic_ns())+'.log')).open('w');self.p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('worker_peer_startup_fixture.py')),*map(str,args)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True);case.addCleanup(self.close);self.initial=self.read()
 def read(self,seconds=35):
  if not select.select([self.p.stdout],[],[],seconds)[0]:raise TimeoutError('Startup fixture timeout; inspect isolated stderr log')
  line=self.p.stdout.readline()
  if not line:raise RuntimeError('Startup fixture exited; inspect isolated stderr log')
  return json.loads(line)
 def call(self,**body):
  self.p.stdin.write(json.dumps(body)+'\n');self.p.stdin.flush();r=self.read()
  if not r.get('ok'):raise AssertionError(r.get('error'))
  return r['result']
 def close(self):
  if self.p.poll() is None:
   try:self.call(op='stop')
   except Exception:pass
   self.p.terminate()
   try:self.p.wait(10)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
  self.log.close()

class Startup(unittest.TestCase):
 def test_actual_protected_worker_node_registration_exchange_and_qr_direct_pairing(self):
  with tempfile.TemporaryDirectory(prefix='startup-peer-76-') as tmp, ExitStack() as fixtures:
   fixtures.addCleanup=fixtures.callback
   root=Path(tmp);source=Path(os.environ.get('WALLABY_STARTUP_AGENT_SOURCE',str(Path(__file__).resolve().parents[1]/'src')));server_source=os.environ['WALLABY_SERVER_SOURCE']
   server=Process(fixtures,root,'server',server_source,root/'server')
   # Real HTTP listener, using normal registration and signed-identity discovery.
   port=server.initial['port']
   nodes=[];agents=[]
   for i,name in enumerate(('wallet-laptop','treasury-australia')):
    core=Regtest();fixtures.callback(core.close);nodes.append(core)
    from wallet_ops import rpc
    from vendor.embit import ec,script
    from vendor.embit.networks import NETWORKS
    address=script.p2wpkh(ec.PrivateKey(b'\x01'*32).get_public_key()).address(NETWORKS['regtest'])
    rpc(core.core,'generatetoaddress',[1,address])
    p=Process(fixtures,root,'agent',source,root/name,core.core.config['cookie'],core.core.config['rpc_port'],port,name,'02:76:00:00:00:0'+str(i+1));agents.append(p)
   def until(check,seconds=35):
    seconds=min(seconds,float(os.environ.get('WALLABY_STARTUP_TIMEOUT','35')))
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
     result=check()
     if result:return result
     time.sleep(.2)
    states=[a.call(op='status') for a in agents]
    raise AssertionError('Normal startup did not attach/pair peers: '+json.dumps(states))
   until(lambda:all(a.call(op='status')['rpc_attached'] for a in agents))
   until(lambda:all(a.call(op='status')['node']['color']=='green' for a in agents))
   until(lambda:server.call(op='identity_status')['eligible']==2)
   server.call(op='discover_identity') # Ordinary Server signed-identity challenge; no trust injection.
   until(lambda:all(a.call(op='status')['peer']['registered'] for a in agents))
   invite=agents[0].call(op='invite');agents[1].call(op='scan',envelope=invite['envelope'])
   def direct_ready():
    states=[a.call(op='status') for a in agents]
    return all(s['node']['color']=='green' and s['peer']['pairs'] and s['peer']['pairs'][0]['direct']['state']=='ready' for s in states)
   until(direct_ready)
   for a in agents:
    status=a.call(op='status');self.assertTrue(status['relay_thread']);self.assertFalse(status['peer']['pending']);self.assertEqual(status['peer']['pairs'][0]['role'],'agent')
   keys=[a.call(op='status')['peer']['identity']['identity_key'] for a in agents]
   self.assertTrue(agents[0].call(op='check_identity',key=keys[1])['verified'])
   self.assertTrue(agents[1].call(op='check_identity',key=keys[0])['verified'])
   agents[0].call(op='policy_agreement',key=keys[1],policy='exact-policy')
   until(lambda:agents[1].call(op='policy_agreement',key=keys[0],policy='exact-policy')['verified'])
   until(lambda:agents[0].call(op='policy_agreement',key=keys[1],policy='exact-policy')['verified'])
   self.assertFalse(agents[0].call(op='policy_agreement',key=keys[1],policy='server-substitution')['verified'])
   agents[1].call(op='listen');agents[0].call(op='send');until(lambda:agents[1].call(op='status')['received']==1,10)
   ident=agents[0].call(op='status')['peer']['pairs'][0]['id']
   agents[0].call(op='disconnect_direct',ident=ident)
   self.assertFalse(agents[0].call(op='check_identity',key=keys[1])['verified'])
   # Close in dependency order while their isolated Core nodes still exist.
   for a in reversed(agents):a.close()
   server.close()

class Wiring(unittest.TestCase):
 def test_exchange_keeps_same_store_identity_for_late_peer_initialisation(self):
  from agent_exchange import Exchange
  from approval_store import Store
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(tmp);exchange=Exchange(1,'fixture',store);self.assertIs(exchange.store,store)
   marker=object();store.peers=marker;self.assertIs(exchange.store.peers,marker)
