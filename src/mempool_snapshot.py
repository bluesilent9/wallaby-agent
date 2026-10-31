"""Read-only, paged fee-planning snapshot; never a generic larger RPC envelope.

The Core-local read alone may use 64 MiB. Remote replies retain the existing
16 MiB bound. One complete snapshot stays in protected process memory for 5 min.
"""
import copy,re,secrets,threading,time
from decimal import Decimal
from agent_rpc import PublicDataFailure
METHOD='wallaby_mempool_snapshot'
LOCAL_BYTES=64*1024*1024
MAX_ENTRIES=100000
PAGE=1000
TTL=300

def params(value):
    if value in ([],{}):return None
    if not isinstance(value,dict) or set(value)!={'snapshot','offset'} or not isinstance(value['snapshot'],str) or not re.fullmatch('[0-9a-f]{32}',value['snapshot']) or type(value['offset']) is not int or not 0<=value['offset']<=MAX_ENTRIES or value['offset']%PAGE:raise ValueError('Use empty parameters for a new snapshot, or its exact snapshot ID and 1000-entry page offset.')
    return value

class Snapshot:
    def __init__(self):self.lock=threading.Lock();self.ident=None;self.rows=[];self.until=0;self.created=0
    def call(self,value,fetch):
        query=params(value)
        # Refuse overlapping captures rather than filling the protected cgroup.
        if not self.lock.acquire(blocking=False):raise PublicDataFailure('mempool_busy','A mempool snapshot capture is already running. Retry this read-only request after it finishes.')
        try:
            if time.monotonic()>=self.until:self.ident=None;self.rows=[]
            if query is None:
                started=time.monotonic()
                self.ident=None;self.rows=[] # A failed replacement cannot masquerade as the requested new capture.
                raw=fetch()
                if not isinstance(raw,dict) or len(raw)>MAX_ENTRIES:raise PublicDataFailure('mempool_limit','The complete mempool exceeds this bounded snapshot capacity. No partial snapshot was returned.')
                rows=[]
                for txid,entry in raw.items():
                    if not isinstance(txid,str) or not re.fullmatch('[0-9a-f]{64}',txid) or not isinstance(entry,dict):raise PublicDataFailure('response_json','Core returned an invalid mempool entry.')
                    size=entry.get('vsize');parents=entry.get('depends');fee=entry.get('fees',{}).get('modified') if isinstance(entry.get('fees'),dict) else None
                    if type(size) is not int or not 1<=size<=4000000 or not isinstance(parents,list) or len(parents)>MAX_ENTRIES or any(not isinstance(p,str) or not re.fullmatch('[0-9a-f]{64}',p) for p in parents) or len(set(parents))!=len(parents):raise PublicDataFailure('response_json','Core returned invalid mempool size or dependency data.')
                    if isinstance(fee,bool) or not isinstance(fee,(Decimal,int,float,str)):raise PublicDataFailure('response_json','Core returned an invalid modified fee.')
                    try:amount=Decimal(str(fee))
                    except Exception:raise PublicDataFailure('response_json','Core returned an invalid modified fee.') from None
                    if not amount.is_finite() or abs(amount)>21000000 or amount*100000000!=(amount*100000000).to_integral_value():raise PublicDataFailure('response_json','Core returned an invalid modified fee.')
                    rows.append((txid,{'vsize':size,'fees':{'modified':format(amount,'f')},'depends':list(parents)}))
                known=set(raw)
                if any(parent not in known for _,entry in rows for parent in entry['depends']):raise PublicDataFailure('response_json','Core returned an incomplete mempool dependency graph. No partial snapshot was returned.')
                self.rows=sorted(rows);self.ident=secrets.token_hex(16);self.created=int(time.time());self.until=time.monotonic()+TTL
                from activity_log import event
                event('mempool.snapshot','Complete public capture prepared · transactions='+str(len(rows))+' · pages='+str(max(1,(len(rows)+PAGE-1)//PAGE))+' · capture_ms='+str(round((time.monotonic()-started)*1000))+' · local_limit_bytes='+str(LOCAL_BYTES))
            elif query['snapshot']!=self.ident:raise PublicDataFailure('mempool_expired','The requested mempool snapshot expired or was replaced. Discard incomplete pages and begin a new capture.')
            offset=0 if query is None else query['offset']
            if offset>=len(self.rows) and (offset!=0 or self.rows):raise PublicDataFailure('mempool_offset','The requested mempool page is outside this snapshot.')
            end=min(offset+PAGE,len(self.rows))
            return {'version':1,'snapshot':self.ident,'created_at':self.created,'expires_at':self.created+TTL,'total':len(self.rows),'offset':offset,'next_offset':end if end<len(self.rows) else None,'entries':copy.deepcopy(dict(self.rows[offset:end]))}
        finally:self.lock.release()
