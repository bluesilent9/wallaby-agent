from pathlib import Path
import copy,time,threading,unittest,json,io,base64
from unittest.mock import patch
from fixture_encrypted_peers import Pairing,RelayCore
from direct_peers import Direct
from direct_protocol import validate,make,address
from direct_ssh import Restricted,key,public
import paramiko

class DirectPeers(Pairing):
 def network(self,mobile=False,actual_server=False):
  if mobile:
   self.b=self.peer('phone','mobile');invite=self.a.create_invitation('mobile',self.route);self.b.import_invitation(invite);self.move(self.b,self.a);self.move(self.a,self.b);self.move(self.b,self.a);(self.a.approve(self.b.identity['endpoint_id']) if self.b.identity['endpoint_id'] in self.a.pending else None);self.move(self.a,self.b)
  else:self.pair()
  self.failures=[];self.relay=[];self.done=threading.Event()
  for p in (self.a,self.b):Direct(p,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(p.close)
  if actual_server:
   import subprocess,sys,os
   source=Path(os.environ['WALLABY_SERVER_SOURCE'])
   proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server_fixture.py')),str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.addCleanup(proc.kill)
   def dispatch(peer,body):
    proc.stdin.write(json.dumps({'identity':peer.identity,'body':body})+'\n');proc.stdin.flush();reply=json.loads(proc.stdout.readline())
    if 'error' in reply:raise ValueError(reply['error'])
    if body['action']=='send':self.relay.append(copy.deepcopy(body['frame']))
    return reply['result']
   for peer in (self.a,self.b):
    peer.rpc=lambda body,peer=peer:dispatch(peer,body)
    peer.control('register',{'noise_public_key':peer.identity['noise_public_key'],'cipher_suite':__import__('peer_protocol').CIPHER});peer.registered=True
  def pump():
   while not self.done.wait(.25 if actual_server else .002):
    try:
     if actual_server:
      self.a.tick();self.b.tick();continue
     for a,b in ((self.a,self.b),(self.b,self.a)):
      with a.lock:rows=[v for v in a.outgoing.values() if v['id'] not in a.bulk_frames and not a.direct.holds(v)]
      for v in rows:
       b.accept(v,[a.identity]);self.relay.append(copy.deepcopy(v))
       with a.lock:a.outgoing.pop(v['id'],None)
    except Exception as e:self.failures.append(repr(e));break
  threading.Thread(target=pump,daemon=True).start();self.addCleanup(self.done.set)
  self.until(lambda:all(p.direct.ready(q.identity['endpoint_id']) for p,q in ((self.a,self.b),(self.b,self.a))))
 def until(self,condition,seconds=35):
  deadline=time.monotonic()+seconds
  while not condition() and time.monotonic()<deadline:
   if self.failures:self.fail(str(self.failures))
   time.sleep(.02)
  self.assertTrue(condition(),str([(p.direct.messages,{i:(e.id,e.remote_id,list(e.sessions),e.selected,e.closed,e.settled,[(s.dead,getattr(s,'failure',None),s.remote_selected,s.remote_active) for s in e.sessions.values()]) for i,e in p.direct.states.items()}) for p in (self.a,self.b)]))

class Restrictions(unittest.TestCase):
 pass

class QRImages(Pairing):
 pass

class DirectCore(RelayCore):
 def setup_peers(self):
  super().setup_peers();self.stopped.set();self.pump.join(timeout=3)
  self.stopped=threading.Event();self.addCleanup(self.stopped.set);self.pump_error=[]
  for p in (self.a,self.b):Direct(p,addresses=lambda:['127.0.0.1'],loopback=True).start();self.addCleanup(p.close)
  def pump():
   while not self.stopped.wait(.002):
    try:
     for a,b in ((self.a,self.b),(self.b,self.a)):
      with a.lock:rows=[v for v in a.outgoing.values() if v['id'] not in a.bulk_frames and not a.direct.holds(v)]
      for v in rows:
       b.accept(v,[a.identity])
       with a.lock:a.outgoing.pop(v['id'],None)
    except Exception as error:self.pump_error.append(repr(error));break
  self.pump=threading.Thread(target=pump,daemon=True);self.pump.start();deadline=time.monotonic()+35
  while not all(p.direct.ready(q.identity['endpoint_id']) for p,q in ((self.a,self.b),(self.b,self.a))):
   if self.pump_error or time.monotonic()>deadline:self.fail(str(self.pump_error)+' Direct connection timeout')
   time.sleep(.02)
