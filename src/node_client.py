"""Dashboard V155 protocol: separate heartbeat, poll and RPC execution loops."""
import base64, concurrent.futures, http.client, json, os, re, socket, threading, time, uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from agent_rpc import METHODS,clean_json,request,MAX_RESULT_BYTES

LIMIT=16*1024*1024+4096

def decode(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('Duplicate JSON key.')
            d[k]=v
        return d
    return json.loads(raw,parse_float=Decimal,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Invalid number.')))

class HTTPFailure(Exception):
    def __init__(self,status):self.status=status;super().__init__('HTTP request failed (%d).'%status)

def http_json(port,path,body=None,token=None,timeout=30,auth=None):
    headers={'Content-Type':'application/json','X-Wallaby-Agent':'1'}
    if token:headers['Authorization']='Bearer '+token
    if auth:headers['Authorization']='Basic '+base64.b64encode(auth.encode()).decode()
    raw=None if body is None else json.dumps(body,allow_nan=False,separators=(',',':')).encode()
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=timeout)
    try:
        conn.request('GET' if raw is None else 'POST',path,raw,headers)
        response=conn.getresponse();data=response.read(LIMIT+1)
        if len(data)>LIMIT:raise ValueError('Response exceeds size limit.')
        if response.status!=200:raise HTTPFailure(response.status)
        return decode(data)
    finally:conn.close()

def adapter_mac():
    candidates=[]
    for p in sorted(Path('/sys/class/net').glob('*')):
        try:
            if p.name=='lo' or (p/'type').read_text().strip()!='1':continue
            value=(p/'address').read_text().strip().lower()
            if re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',value) and int(value[:2],16)&1==0 and value!='00:00:00:00:00:00':
                candidates.append((not (p/'device').exists(),p.name,value))
        except OSError:continue
    if not candidates:raise ValueError('No stable network adapter MAC found.')
    return sorted(candidates)[0][2]

class Core:
    def __init__(self,config):self.config=config
    def call(self,ident,method,params,wallet=None,timeout=30):
        # Read the cookie again on every request: Core rotates it on restart.
        cookie=Path(self.config['cookie']).expanduser().read_text().strip()
        if ':' not in cookie or '\n' in cookie:raise ValueError('Invalid Core cookie.')
        path='/' if wallet is None else '/wallet/'+quote(wallet,safe='')+'/'
        response=http_json(self.config['rpc_port'],path,{'jsonrpc':'2.0','id':ident,'method':method,'params':params},timeout=timeout,auth=cookie)
        if not isinstance(response,dict) or response.get('id')!=ident:raise ValueError('Core response ID mismatch.')
        if response.get('error') is not None:return {'error':response['error']}
        if 'result' not in response:raise ValueError('Missing Core result.')
        value,_=clean_json(response['result'],MAX_RESULT_BYTES)
        return {'result':value}
    def ready(self):
        r=self.call('wallaby-health','getblockchaininfo',[],timeout=5)
        if 'error' in r:raise ValueError('Bitcoin Core RPC is not ready.')

class NodeClient:
    def __init__(self,config,port,stop,status):
        self.core=Core(config);self.port=port;self.stop=stop;self.status=status;self.token=None
        self.failed=threading.Event();self.seen=set();self.lock=threading.Lock()
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='core-rpc')
        self.pending=threading.BoundedSemaphore(2);self.threads=[]
    def post(self,path,body,timeout=30):
        return http_json(self.port,'/agent/v1/'+path,body,self.token,timeout)
    def consume(self,response):
        if not isinstance(response,dict):raise ValueError('Invalid Dashboard response.')
        commands=response.get('commands',[])
        if not isinstance(commands,list) or len(commands)>1:raise ValueError('Invalid command envelope.')
        for c in commands:
            if not isinstance(c,dict) or set(c)!={'id','kind','method','params','wallet','expires_in_seconds'}:raise ValueError('Invalid RPC envelope.')
            ident=c['id']
            if not isinstance(ident,str) or not 1<=len(ident)<=100:raise ValueError('Invalid request ID.')
            with self.lock:
                if ident in self.seen:continue
                if len(self.seen)>=10000:raise ValueError('Session request limit reached; reconnect required.')
                self.seen.add(ident)
            if not self.pending.acquire(blocking=False):raise ValueError('Too many concurrent Core commands.')
            self.pool.submit(self.execute,c,time.monotonic())
    def execute(self,c,received):
        try:
            ident=c['id'];expiry=c['expires_in_seconds']
            if not isinstance(expiry,(int,Decimal)) or expiry<=0 or expiry>3600:raise ValueError('Invalid or expired RPC deadline.')
            params,_=request(c['method'],c['params'],c['wallet'])
            if c['kind']!='rpc' or self.stop.is_set() or self.failed.is_set() or time.monotonic()-received>=expiry:return
            ack=self.post('ack',{'id':ident})
            if ack.get('execute') is not True:return
            # Never retry an acknowledged Core call; a lost response has unknown outcome.
            try:result=self.core.call(ident,c['method'],params,c['wallet'],timeout=max(1,float(expiry)-(time.monotonic()-received)))
            except Exception:result={'error':{'code':'local_rpc_failed','message':'Local Core request failed; execution outcome may be unknown. It was not replayed.'}}
            self.post('result',{'id':ident,**result})
        except Exception:self.failed.set()
        finally:self.pending.release()
    def heartbeat(self):
        while not self.stop.wait(15) and not self.failed.is_set():
            try:
                self.core.ready()
                if self.stop.is_set() or self.failed.is_set():return
                self.consume(self.post('heartbeat',{}));self.status('green','Tunnel, Bitcoin Core and Dashboard connected.')
            except Exception:self.failed.set();self.status('red','Bitcoin Core or Dashboard connection lost.')
    def run(self):
        self.core.ready()
        if self.stop.is_set():return
        r=self.post('register',{'mac':adapter_mac(),'hostname':socket.gethostname().split('.')[0],'rpc':{'version':1,'methods':sorted(METHODS)}})
        if self.stop.is_set():return
        if r.get('protocol')!='wallaby-agent' or r.get('version')!=1 or not isinstance(r.get('connection_token'),str) or not r['connection_token']:raise ValueError('Unsupported Dashboard protocol.')
        self.token=r['connection_token'];self.consume(r)
        self.status('green','Tunnel, Bitcoin Core and Dashboard connected.')
        thread=threading.Thread(target=self.heartbeat,daemon=True);self.threads.append(thread);thread.start()
        try:
            while not self.stop.is_set() and not self.failed.is_set():self.consume(self.post('poll',{'wait_seconds':20},timeout=25))
            if self.failed.is_set():raise ConnectionError('Node session failed.')
        finally:
            self.failed.set()
            try:self.post('disconnect',{},timeout=2)
            except Exception:pass
            self.pool.shutdown(wait=False,cancel_futures=True)
