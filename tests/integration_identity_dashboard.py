import os,sys,tempfile,time,json
from pathlib import Path
base=Path.cwd()
if len(sys.argv)!=4:raise SystemExit('Usage: integration_identity_dashboard.py AGENT_SOURCE DASHBOARD_SOURCE OUTPUT_FOLDER')
source=Path(sys.argv[1]).resolve();dashboard_source=Path(sys.argv[2]).resolve()
os.environ.setdefault('WALLABY_TEST_BITCOIND',str(base/'work/core31-fixture/bitcoin-31.0/bin/bitcoind'))
sys.path[:0]=[str(source/'src'),str(source/'tests')]
from integration_sync_cluster import Process
from regtest_support import Regtest
from wallet_ops import rpc
from vendor.embit import ec,script
from vendor.embit.networks import NETWORKS
out=Path(sys.argv[3]).resolve();out.mkdir(exist_ok=True);nodes=[];processes=[]
with tempfile.TemporaryDirectory(prefix='identity-cluster-',dir='/tmp') as temporary:
 root=Path(temporary)
 try:
  server=Process(['dashboard',str(dashboard_source),str(root/'dashboard')],out/'dashboard.log');processes.append(server)
  address=script.p2wpkh(ec.PrivateKey(b'\x01'*32).get_public_key()).address(NETWORKS['regtest'])
  agents=[]
  for i,name in enumerate(('wallet-laptop','treasury-australia','treasury-russia')):
   n=Regtest();nodes.append(n);rpc(n.core,'generatetoaddress',[101,address]);folder=root/name;folder.mkdir()
   c={'root':str(folder),'name':name,'core':n.core.config,'ipv6':'2001:db8::'+str(i+1),'mac':'02:aa:00:00:00:0'+str(i+1),'port':server.initial['port'],'hostkey':'','peers':{}}
   path=folder/'role.json';path.write_text(json.dumps(c));agent=Process(['agent',str(source/'src'),str(path)],out/(name+'.log'));processes.append(agent);agents.append(agent)
  deadline=time.monotonic()+35
  while True:
   eligible=server.command({'op':'identity_status'},timeout=5)
   if eligible['eligible']==3:break
   if time.monotonic()>deadline:raise AssertionError('Not all fixture nodes became eligible: '+str(eligible))
   time.sleep(.5)
  discovered=server.command({'op':'discover_identity'},timeout=5)
  before=server.command({'op':'identity_status'});started=time.monotonic();deadline=started+15
  while True:
   state=server.command({'op':'identity_status'})
   if state['identities']==3 and state['challenges']==3:break
   if time.monotonic()>deadline:raise AssertionError('Three actual Dashboard identity replies did not arrive: '+str(state))
   time.sleep(.1)
  assert state['connections']==3 and before['sessions']==state['sessions'],'Session replacement during identity discovery'
  assert all(not a.command({'op':'status'})['thread_errors'] for a in agents)
  result={'passed':True,'agent_build':44,'dashboard_source':str(dashboard_source),'separate_agent_processes':3,'core_nodes':3,'signed_identities_accepted':3,'authenticated_sessions_unchanged':True,'seconds_after_discovery':round(time.monotonic()-started,3),'adapters':'Isolated regtest network/health, synthetic MAC/IPv6 identities. Production Agent NodeClient/exchange and current Dashboard HTTP/RPC/builder signature validation. No live wallets or OS services.'}
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
 finally:
  for p in reversed(processes):p.close()
  for n in reversed(nodes):n.close()
