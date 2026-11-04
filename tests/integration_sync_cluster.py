"""Three independent Agents, Dashboard HTTP/RPC broker and three real Core nodes.

Test-only adapters: Dashboard network constants/health accept regtest, fixture MAC/IPv6
identities, receiver SSH readiness, and SSH pipes replaced by a local relay.
Production pairing, permissions, signatures, snapshots, batches, import/backup,
framing, Core verification and completion receipts remain real. No live coins,
services, SSH credentials, firewall changes or production configurations used.
"""
import sys,os,json,time,threading,subprocess,tempfile,select,traceback,shutil,hashlib,base64
from pathlib import Path

def reply(v):print(json.dumps(v),flush=True)
def commands(handler):
 for line in sys.stdin:
  try:reply({'ok':True,'result':handler(json.loads(line))})
  except Exception as e:traceback.print_exc(file=sys.stderr);reply({'ok':False,'error':type(e).__name__+': '+str(e)})

def dashboard(source,root,port="0"):
 sys.path.insert(0,source)
 from nodes import NodeRegistry,create_agent_server
 import node_health,wallet_preview as dashboard_preview,ast,inspect
 # Keep real validation/signature bodies; translate only the test network guard.
 tree=ast.parse(inspect.getsource(dashboard_preview.validate))
 class RegtestNetwork(ast.NodeTransformer):
  def visit_Constant(self,node):
   return ast.copy_location(ast.Constant('regtest'),node) if node.value=='main' else node
 exec(compile(ast.fix_missing_locations(RegtestNetwork().visit(tree)),'regtest-only-preview-network','exec'),dashboard_preview.__dict__)
 clock={'offset':0};real_time=time.time;time.time=lambda:real_time()+clock['offset']
 from vendor.embit.networks import NETWORKS
 NETWORKS['main']=dict(NETWORKS['regtest']) # Test network only; keep exact real descriptors/scripts.
 original=node_health.classify
 node_health.classify=lambda info:original(dict(info,chain='main')) # Test coins only.
 Path(root).mkdir(parents=True,exist_ok=True);registry=NodeRegistry(Path(root)/'config.cfg');server=create_agent_server(registry,port=int(port),ipv4=False);server.start()
 original_exchange=registry.hub.exchange
 def measured_exchange(*args,**kwargs):
  started=time.monotonic()
  try:return original_exchange(*args,**kwargs)
  finally:
   elapsed=time.monotonic()-started
   if elapsed>1:print('FIXTURE exchange elapsed_seconds='+str(round(elapsed,3)),file=sys.stderr,flush=True)
 registry.hub.exchange=measured_exchange
 def poll_nodes():
  while True:
   try:
    registry.ready_for_builders() # Production health refresh through the RPC broker.
    (Path(root)/'poll-evidence.json').write_text(json.dumps({'connections':len(registry.connections),'health':len(registry.health.values),'pending':len(registry.health.pending)}))
   except Exception:traceback.print_exc(file=sys.stderr)
   time.sleep(.5)
 threading.Thread(target=poll_nodes,daemon=True).start();reply({'port':server.server_port,'polling':'production-health'})
 def control(c):
  if c['op']=='discover_identity':return registry.hub.wallet_builder.discover(foreground=True)
  if c['op']=='identity_status':
   data=registry.hub.wallet_builder.read()
   return {'eligible':len(registry.hub.wallet_builder.available()),'identities':len(data['identities']),'challenges':len(data['challenges']),'connections':len(registry.connections),'sessions':sorted(hashlib.sha256(t.encode()).hexdigest() for t in registry.connections)}
  if c['op']=='advance':clock['offset']=c['seconds'];return True
  if c['op']=='clear_profile':
   from profile_archive import ProfileArchive
   with registry.lock:
    ProfileArchive(registry.config).replace();registry.reset()
   return {'cleared':True}
  if c['op']=='status':
   state=registry.hub.read();result={}
   for token,row in list(registry.connections.items()):
    node=row['node_id'];entry=state['nodes'].get(node,{});summary=registry.hub.node_summary(node)
    result[row['hostname']]={'id':node,'permissions':summary['sync_permissions'],'inventory':summary['inventory_ready'],'inventory_error':summary['inventory_error'],'wallets':len(registry.hub.inventories.get(node,{}).get('wallets',[])),'queue':len(entry.get('sync_snapshot',[])),'health':registry.health.status(row)}
   return {'nodes':result,'requests':len(state['requests']),'log':registry.log_text()[-6000:]}
  if c['op']=='stop':server.close();return True
  raise ValueError('Unknown fixture command')
 commands(control)

def role_env(c):
 os.environ['XDG_CONFIG_HOME']=str(Path(c['root'])/'config');os.environ['XDG_RUNTIME_DIR']=str(Path(c['root'])/'runtime');Path(os.environ['XDG_RUNTIME_DIR']).mkdir(exist_ok=True,mode=0o700)
 os.environ.pop('WALLABY_REQUIRE_PROTECTION',None);os.environ.pop('WALLABY_PROTECTED_WORKER',None)

def relay(source,config,own):
 c=json.loads(Path(config).read_text());role_env(c);sys.path.insert(0,source)
 from peer_wallet import peer_receive
 peer_receive(ssh_connection=own+' 12345 '+c['ipv6']+' 22')

def agent(source,config):
 c=json.loads(Path(config).read_text());role_env(c);sys.path.insert(0,source)
 clock={'offset':0};real_time=time.time;time.time=lambda:real_time()+clock['offset']
 from configuration import Config
 cfg=Config();v=cfg.values;v.update(cookie=c['core']['cookie'],rpc_port=c['core']['rpc_port'],hostname='fixture.invalid');cfg.save(v)
 import node_client,peer_wallet,agent_exchange,batch_transfer
 from approval_store import Store
 from wallet_ops import rpc
 from wallet_preview import fingerprint
 from sync_queue import rows,choose
 from batch_transfer import BatchTransfer
 from sync_preferences import change,enable,policy_id
 node_client.adapter_mac=lambda:c['mac'];node_client.socket.gethostname=lambda:c['name'];peer_wallet.local_ipv6=lambda *a:c['ipv6'];agent_exchange.local_ipv6=peer_wallet.local_ipv6
 peer_wallet.readiness=lambda p:{'listening':True};batch_transfer.readiness=peer_wallet.readiness
 store=Store();core=node_client.Core(c['core']);transfer=BatchTransfer(core,store);stop=threading.Event();errors=[];threads=[]
 original_popen=subprocess.Popen;original_run=subprocess.run
 def popen(args,*a,**kw):
  if isinstance(args,list) and args[0]=='/usr/bin/ssh':
   peer=args[-2].split('@')[-1];target=c['peers'][peer];args=[sys.executable,'-B',__file__,'relay',source,target,c['ipv6']]
  return original_popen(args,*a,**kw)
 def run(args,*a,**kw):
  if isinstance(args,list) and args[0]=='/usr/bin/ssh-keyscan':return subprocess.CompletedProcess(args,0,args[-1]+' '+c['hostkey']+'\n','')
  return original_run(args,*a,**kw)
 subprocess.Popen=popen;subprocess.run=run
 def connect():
  while not stop.is_set():
   client=node_client.NodeClient(c['core'],c['port'],stop,lambda *a:None)
   try:client.run()
   except Exception as e:errors.append(type(e).__name__+': '+str(e));errors[:]=errors[-3:]
   if stop.wait(.25):break
 thread=threading.Thread(target=connect,daemon=True);thread.start();reply({'started':c['name']})
 def control(x):
  if x['op']=='advance':clock['offset']=x['seconds'];return True
  if x['op']=='rotate_ipv6':
   c['ipv6']=x['ipv6'];Path(config).write_text(json.dumps(c));return True
  if x['op']=='status':
   state=store.read();listing=rows(store)
   return {'rows':len(listing),'send':sum(r['direction']=='send' for r in listing),'receive':sum(r['direction']=='receive' for r in listing),'previews':len(state.get('transfer_previews',{})),'peers':len({r['peer_id'] for r in listing}),'excluded':len(state.get('sync_exclusions',{})),'completed':len(state['completed']),'outbox':len(state['outbox']),'error':state.get('exchange_error'),'thread_errors':errors,'transfer_error':transfer.error,'wallets':rpc(core,'listwallets')}
  if x['op']=='codes':
   state=store.read();return {row['proposal']['transfer_id']:hashlib.sha256(json.dumps(state['transfer_previews'][key]['preview'],sort_keys=True,separators=(',',':')).encode()).hexdigest() for key,row in state['pending'].items() if key in state.get('transfer_previews',{}) and not row.get('withdrawn')}
  if x['op']=='disable_one':
   key=next(r['id'] for r in rows(store) if r['direction']=='receive' and not r['extinct_group']);p=store.read()['pending'][key]['proposal'];change(store,key,True);return policy_id(p)
  if x['op']=='enable':return enable(store,x['id'])
  if x['op']=='authorise':
   state=store.read();proofs={}
   for row in rows(store):
    if row['direction']=='receive':
     key=row['id'];p=state['pending'][key]['proposal'];choose(store,key,True,p['public_wallet']['wallet_name']!='hot01');proofs[key]=fingerprint(state['transfer_previews'][key]['public_key'])
   return transfer.authorise_batch(proofs)
  if x['op']=='send':
   state=store.read();credentials={}
   for row in rows(store):
    if row['direction']=='send':
     p=state['pending'][row['id']]['proposal'];choose(store,row['id'],True,p['public_wallet']['wallet_name']!='hot01');credentials[p['peer']['node_id']]={'username':'fixture','password':'fixture-not-a-real-password','fingerprint':c['host_fingerprint']}
   transfer.send_batch(credentials);state=store.read();return {'completed':len(state['completed']),'credentials_cleared':all(d['password'] is None for d in credentials.values()),'remaining':[{'wallet':r['proposal']['public_wallet']['wallet_name'],'direction':r['proposal'].get('direction'),'peer':r['proposal'].get('peer',{}).get('hostname'),'state':r['state'],'withdrawn':r.get('withdrawn',False)} for r in state['pending'].values()],'transfer_error':transfer.error}
  if x['op']=='stop':stop.set();transfer.close();thread.join(8);return {'stopped':not thread.is_alive()}
  raise ValueError('Unknown fixture command')
 commands(control)

class Process:
 def __init__(self,args,log):
  self.log=open(log,'w');self.process=subprocess.Popen([sys.executable,'-B',__file__,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1);self.initial=self.read(40)
 def read(self,timeout=120):
  if not select.select([self.process.stdout],[],[],timeout)[0]:raise TimeoutError('Fixture process response timed out')
  text=self.process.stdout.readline()
  if not text:raise RuntimeError('Fixture process exited; inspect its stderr log')
  return json.loads(text)
 def command(self,c,timeout=120):
  self.process.stdin.write(json.dumps(c)+'\n');self.process.stdin.flush();r=self.read(timeout)
  if not r.get('ok'):raise RuntimeError(r.get('error'))
  return r['result']
 def close(self):
  if self.process.poll() is None:
   try:self.command({'op':'stop'},30)
   except Exception:pass
   self.process.stdin.close()
   try:self.process.wait(timeout=10)
   except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(10)
  self.log.close()

def coordinator(agent_source,dashboard_source,out):
 sys.path.insert(0,str(Path(agent_source).parent/'tests'));sys.path.insert(0,agent_source)
 from regtest_support import Regtest
 from wallet_ops import rpc
 from vendor.embit.descriptor.checksum import checksum
 output=Path(out);output.mkdir(parents=True,exist_ok=True);root=tempfile.TemporaryDirectory(prefix='sync-cluster-',dir='/tmp');base=Path(root.name);nodes=[];processes=[]
 def stage(name,**extra):reply({'stage':name,**extra})
 try:
  for i in range(3):nodes.append(Regtest())
  source=nodes[0].core
  for name in ('treasury','david_smsf'):
   rpc(source,'createwallet',{'wallet_name':name,'passphrase':'fixture wallet password'});raw=rpc(source,'listdescriptors',[False],name)
   for node in nodes[1:]:
    directory=Path(node.core.config['cookie']).parent/'wallets'/name;directory.mkdir(parents=True);rpc(source,'backupwallet',[str(directory/'wallet.dat')],name);rpc(node.core,'loadwallet',[name])
   rpc(source,'unloadwallet',[name]);shutil.rmtree(Path(source.config['cookie']).parent/'wallets'/name)
   watch=name+'_watch';rpc(source,'createwallet',{'wallet_name':watch,'disable_private_keys':True,'blank':True});rpc(source,'importdescriptors',[[dict(d,timestamp='now') for d in raw['descriptors']]],watch)
  for i in range(10):rpc(source,'createwallet',{'wallet_name':'hot'+str(i).zfill(2),**({'passphrase':'fixture wallet password'} if i==1 else {})})
  mine=rpc(source,'getnewaddress',[],'hot00');rpc(source,'generatetoaddress',[101,mine])
  for i in range(1,10):address=rpc(source,'getnewaddress',['Owner label '+str(i)],'hot'+str(i).zfill(2));rpc(source,'sendtoaddress',[address,'0.01'],'hot00')
  rpc(source,'generatetoaddress',[1,mine]);address=rpc(source,'getnewaddress',[],'hot00');body='addr('+address+')';rpc(source,'createwallet',{'wallet_name':'extinct_watch','disable_private_keys':True,'blank':True});rpc(source,'importdescriptors',[[{'desc':body+'#'+checksum(body),'timestamp':0,'label':'Old fixture wallet'}]],'extinct_watch')
  for node in nodes[1:]:
   for h in range(1,103):rpc(node.core,'submitblock',[rpc(source,'getblock',[rpc(source,'getblockhash',[h]),0])])
  stage('cores_ready',wallet_counts=[len(rpc(n.core,'listwallets')) for n in nodes])
  key=base/'host';subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True);hostkey=' '.join(key.with_suffix('.pub').read_text().split()[:2]);fp='SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(hostkey.split()[1])).digest()).decode().rstrip('=')
  server=Process(['dashboard',dashboard_source,str(base/'dashboard')],output/'dashboard-stderr.log');processes.append(server);assert server.initial.get('polling')=='production-health';port=server.initial['port'];configs=[];roles=[]
  for i,name in enumerate(('wallet-laptop','treasury-australia','treasury-russia')):
   folder=base/name;folder.mkdir();config=folder/'role.json';configs.append(config);roles.append({'root':str(folder),'name':name,'core':nodes[i].core.config,'ipv6':'2001:db8::'+str(i+1),'mac':'02:aa:00:00:00:0'+str(i+1),'port':port,'hostkey':hostkey,'host_fingerprint':fp})
  peers={r['ipv6']:str(p) for r,p in zip(roles,configs)}
  peers['2001:db8::12']=str(configs[1]) # Alternate address for the same real receiver process.
  for config,r in zip(configs,roles):r['peers']=peers;config.write_text(json.dumps(r))
  agents={}
  for i in (1,2,0):agents[roles[i]['name']]=Process(['agent',agent_source,str(configs[i])],output/(roles[i]['name']+'-stderr.log'));processes.append(agents[roles[i]['name']])
  def states():return {name:a.command({'op':'status'}) for name,a in agents.items()}
  def wait_counts(expected,previews=True,timeout=150):
   deadline=time.monotonic()+timeout;last=None
   while time.monotonic()<deadline:
    current=states();signature={n:(s['rows'],s['previews'],s['excluded']) for n,s in current.items()}
    if signature!=last:stage('queue_progress',counts=signature);last=signature
    dashboard_state=server.command({'op':'status'});live=dashboard_state['nodes']
    if all(current[n]['rows']==count and current[n]['error'] is None and (not previews or current[n]['previews']>=count) and n in live and live[n]['permissions'] and live[n]['permissions']['ready'] and live[n]['inventory'] and live[n]['queue']==count for n,count in expected.items()):return current
    time.sleep(1)
   snapshot=server.command({'op':'status'});(output/'failure-dashboard.json').write_text(json.dumps(snapshot,indent=2));(output/'failure-agents.json').write_text(json.dumps(current,indent=2));raise AssertionError('Expected queues '+str(expected)+'; actual '+str(signature))
  expected={'wallet-laptop':22,'treasury-australia':11,'treasury-russia':11};initial=wait_counts(expected);assert initial['wallet-laptop']['peers']==2;stage('all_three_real_exchange_queues_verified',counts={n:s['rows'] for n,s in initial.items()})
  policy=agents['treasury-russia'].command({'op':'disable_one'});wait_counts({'wallet-laptop':21,'treasury-australia':11,'treasury-russia':10},previews=False);agents['treasury-russia'].command({'op':'enable','id':policy});wait_counts(expected);stage('local_denial_enable_isolated_to_one_recipient')
  agents['treasury-australia'].close();agents['treasury-australia']=Process(['agent',agent_source,str(configs[1])],output/'australia-reconnect-stderr.log');processes.append(agents['treasury-australia']);wait_counts(expected);stage('recipient_reconnect_verified')
  # Match the reported installed lifecycle: keep all Agent workspaces alive,
  # clear the Dashboard profile through its production storage operation, and
  # let real HTTP re-registration rebuild all lists without Ownership records.
  server.command({'op':'clear_profile'});reset=wait_counts(expected)
  assert not any(v['error'] for v in reset.values()),reset
  stage('profile_clear_live_agents_reauthenticated_and_queues_rediscovered_without_ownership')
  if os.environ.get('WALLABY_TEST_ROTATE_IPV6')=='1':
   before=agents['wallet-laptop'].command({'op':'codes'});agents['treasury-australia'].command({'op':'rotate_ipv6','ipv6':'2001:db8::12'})
   deadline=time.monotonic()+150
   while time.monotonic()<deadline:
    current=wait_counts(expected,timeout=150);after=agents['wallet-laptop'].command({'op':'codes'})
    if not set(before)==set(after):break
    time.sleep(1)
   else:raise AssertionError('IPv6 rotation did not replace stale transfer bindings')
   stage('same_receiver_new_ipv6_fresh_reviews_without_ownership')
  server.command({'op':'advance','seconds':1000})
  for a in agents.values():a.command({'op':'advance','seconds':1000})
  time.sleep(5);aged=wait_counts(expected);assert not any(v['error'] for v in aged.values());stage('reviews_survive_sixteen_minutes_without_reauthorising_transfers')
  server.close();server=Process(['dashboard',dashboard_source,str(base/'dashboard'),str(port)],output/'dashboard-restart-stderr.log');processes.append(server);server.command({'op':'advance','seconds':1000});wait_counts(expected);stage('dashboard_restart_three_authenticated_agents_verified')
  sender_codes=agents['wallet-laptop'].command({'op':'codes'})
  for name in ('treasury-australia','treasury-russia'):
   codes=agents[name].command({'op':'codes'});assert len(codes)==11;assert all(sender_codes[k]==v for k,v in codes.items()),'Independent review codes diverged on reconnect'
  stage('all_twenty_two_independent_review_codes_match_after_reconnects')
  for name in ('treasury-australia','treasury-russia'):agents[name].command({'op':'authorise'})
  sent=agents['wallet-laptop'].command({'op':'send'},timeout=240)
  if sent['completed']!=22 or not sent['credentials_cleared']:
   (output/'transfer-failure-agents.json').write_text(json.dumps(states(),indent=2));(output/'transfer-failure-dashboard.json').write_text(json.dumps(server.command({'op':'status'}),indent=2))
  assert sent['completed']==22 and sent['credentials_cleared'],sent;stage('twenty_two_direct_transfers_verified',**sent)
  deadline=time.monotonic()+40
  while time.monotonic()<deadline:
   final=states()
   if all(final[n]['completed']==11 for n in ('treasury-australia','treasury-russia')) and not any(v['rows'] for v in final.values()):break
   time.sleep(1)
  else:raise AssertionError('Completion did not converge: '+str(final))
  for node in nodes[1:]:
   wallets=rpc(node.core,'listwallets');assert len(wallets)==13,wallets
   private=[n for n in wallets if rpc(node.core,'getwalletinfo',[],n)['private_keys_enabled']];assert len(private)==3,private
   balances=[rpc(node.core,'getbalances',[],n)['mine']['trusted'] for n in wallets if n not in ('treasury','david_smsf')];assert sum(float(v) for v in balances)>0
  (output/'result.json').write_text(json.dumps({'passed':True,'initial':initial,'final':final,'transfers':22,'core_nodes':3,'dashboard_source':dashboard_source,'agent_source':agent_source,'adapters':__doc__},indent=2));stage('PASS',transfers=22,receivers=2)
 finally:
  for p in reversed(processes):p.close()
  for node in reversed(nodes):node.close()
  root.cleanup()

if __name__=='__main__':
 mode,*args=sys.argv[1:]
 {'dashboard':dashboard,'agent':agent,'relay':relay,'run':coordinator}[mode](*args)
