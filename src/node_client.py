"""Dashboard V155 protocol: separate heartbeat, poll and RPC execution loops."""
import base64, concurrent.futures, http.client, json, os, re, socket, threading, time, uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from agent_rpc import METHODS,clean_json,request,MAX_RESULT_BYTES
from diagnostics import ConnectionFailure,describe

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

def http_json(port,path,body=None,token=None,timeout=30,auth=None,host='::1'):
    headers={'Content-Type':'application/json','X-Wallaby-Agent':'1','X-Wallaby-Agent-Version':'2.0.0~dev8'}
    if token:headers['Authorization']='Bearer '+token
    if auth:headers['Authorization']='Basic '+base64.b64encode(auth.encode()).decode()
    raw=None if body is None else json.dumps(body,allow_nan=False,separators=(',',':')).encode()
    conn=http.client.HTTPConnection(host,port,timeout=timeout)
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
        if not self.config['cookie']:raise ConnectionFailure('rpc','cookie_missing','Bitcoin Core RPC cookie was not found. Choose the local .cookie file in Connection settings and save.')
        try:cookie=Path(self.config['cookie']).expanduser().read_text().strip()
        except FileNotFoundError:raise ConnectionFailure('rpc','cookie_missing','The selected Bitcoin Core RPC cookie does not exist. Check the data directory, network and whether Core has restarted with RPC enabled.') from None
        except (PermissionError,IsADirectoryError):raise ConnectionFailure('rpc','cookie_access','The Bitcoin Core cookie cannot be read by this desktop user. Choose the correct .cookie file and check its permissions.') from None
        except UnicodeError:raise ConnectionFailure('rpc','cookie_invalid','The selected file is not a Bitcoin Core text cookie. Choose the correct .cookie file.') from None
        if ':' not in cookie or '\n' in cookie:raise ConnectionFailure('rpc','cookie_invalid','The selected file is not a valid Bitcoin Core RPC cookie. Choose the .cookie file; do not enter its contents.')
        path='/' if wallet is None else '/wallet/'+quote(wallet,safe='')
        try:response=http_json(self.config['rpc_port'],path,{'jsonrpc':'2.0','id':ident,'method':method,'params':params},timeout=timeout,auth=cookie,host='127.0.0.1')
        except Exception as error:raise describe('rpc',error) from None
        if not isinstance(response,dict) or response.get('id')!=ident:raise ConnectionFailure('rpc','response_id','Bitcoin Core returned an unexpected RPC response ID. Check the local RPC port and service.')
        if response.get('error') is not None:return {'error':response['error']}
        if 'result' not in response:raise ConnectionFailure('rpc','response','Bitcoin Core returned no RPC result. Check the local RPC service and version.')
        value,_=clean_json(response['result'],MAX_RESULT_BYTES)
        return {'result':value}
    def ready(self):
        r=self.call('wallaby-health','getblockchaininfo',[],timeout=5)
        if 'error' in r:
            code=r['error'].get('code') if isinstance(r['error'],dict) else None
            if code==-28:raise ConnectionFailure('rpc','warming_up','Bitcoin Core RPC is still starting or loading the blockchain. Wait for Core to finish; Agent will retry.')
            suffix=f' (RPC code {code})' if type(code) is int else ''
            raise ConnectionFailure('rpc','rpc_error',f'Bitcoin Core rejected its RPC readiness check{suffix}. Check Core’s local debug log.')

class NodeClient:
    def __init__(self,config,port,stop,status):
        self.core=Core(config);self.port=port;self.stop=stop;self.status=status;self.token=None
        self.failed=threading.Event();self.seen=set();self.lock=threading.Lock();self.error=None
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='core-rpc')
        self.pending=threading.BoundedSemaphore(2);self.threads=[]
    def check_core(self):
        try:self.core.ready()
        except Exception as error:raise describe('rpc',error) from None
    def post(self,path,body,timeout=30):
        try:return http_json(self.port,'/agent/v1/'+path,body,self.token,timeout)
        except Exception as error:raise describe('dashboard',error) from None
    def fail(self,error):
        with self.lock:
            if self.error is not None:return
            self.error=describe('dashboard',error);self.failed.set()
        self.status('red',str(self.error))
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
            received=time.monotonic()
            while not self.pending.acquire(timeout=.1):
                if self.stop.is_set() or self.failed.is_set():return
                if time.monotonic()-received>=float(c['expires_in_seconds']):raise ValueError('RPC deadline expired while waiting for a Core worker.')
            if self.stop.is_set() or self.failed.is_set():self.pending.release();return
            self.pool.submit(self.execute,c,received)
    def execute(self,c,received):
        try:
            ident=c['id'];expiry=c['expires_in_seconds']
            if not isinstance(expiry,(int,Decimal)) or expiry<=0 or expiry>3600:raise ValueError('Invalid or expired RPC deadline.')
            params,_=request(c['method'],c['params'],c['wallet'])
            if c['kind']!='rpc' or self.stop.is_set() or self.failed.is_set() or time.monotonic()-received>=expiry:return
            ack=self.post('ack',{'id':ident})
            if ack.get('execute') is not True:return
            # Never retry an acknowledged Core call; a lost response has unknown outcome.
            try:
                from approval_store import Store
                if Store().read().get('active_transfer') or Store().read().get('sync_batch') or Store().read().get('recovery',{}).get('state') in ('starting','stopping','downloading','rescanning'):result={'error':{'code':'synchronisation_busy','message':'Local wallet synchronisation is active. Dashboard requests are temporarily refused.'}}
                else:result=self.core.call(ident,c['method'],params,c['wallet'],timeout=max(1,float(expiry)-(time.monotonic()-received)))
            except Exception:result={'error':{'code':'local_rpc_failed','message':'Local Core request failed; execution outcome may be unknown. It was not replayed.'}}
            self.post('result',{'id':ident,**result})
        except Exception as error:self.fail(error)
        finally:self.pending.release()
    def heartbeat(self):
        while not self.stop.wait(15) and not self.failed.is_set():
            try:
                self.check_core()
                if self.stop.is_set() or self.failed.is_set():return
                self.consume(self.post('heartbeat',{}));self.status('green','Tunnel, Bitcoin Core and Dashboard connected.')
            except Exception as error:self.fail(error)
    def run(self):
        try:
            self.check_core()
            if self.stop.is_set():return
            self.status('amber','Local Bitcoin Core RPC connected. Registering with Wallaby Dashboard…')
            try:mac=adapter_mac()
            except Exception:raise ConnectionFailure('node_identity','adapter','No usable local network adapter identity was found. Check the network interface before registering this node.') from None
            r=self.post('register',{'mac':mac,'hostname':socket.gethostname().split('.')[0],'rpc':{'version':1,'methods':sorted(METHODS)}})
            if self.stop.is_set():return
            if not isinstance(r,dict) or r.get('protocol')!='wallaby-agent' or r.get('version')!=1 or not isinstance(r.get('connection_token'),str) or not r['connection_token']:
                raise ConnectionFailure('dashboard','protocol','Dashboard registration returned an incompatible Agent protocol or no session token. Check the Dashboard Agent service/version on port 56443.')
            self.token=r['connection_token'];self.consume(r)
            from agent_exchange import Exchange
            exchange=Exchange(self.port,self.token)
            exchange_thread=threading.Thread(target=exchange.run,args=(self.failed,),daemon=True);self.threads.append(exchange_thread);exchange_thread.start()
            self.status('green','Tunnel, Bitcoin Core and Dashboard connected.')
            thread=threading.Thread(target=self.heartbeat,daemon=True);self.threads.append(thread);thread.start()
            while not self.stop.is_set() and not self.failed.is_set():self.consume(self.post('poll',{'wait_seconds':20},timeout=25))
            if self.failed.is_set():raise self.error or ConnectionFailure('dashboard','session','Dashboard node session ended unexpectedly. Check the Dashboard Agent service.')
        except Exception as error:
            raise self.error or describe('dashboard',error) from None
        finally:
            self.failed.set()
            if self.token:
                try:self.post('disconnect',{},timeout=2)
                except Exception:pass
            self.pool.shutdown(wait=False,cancel_futures=True)
