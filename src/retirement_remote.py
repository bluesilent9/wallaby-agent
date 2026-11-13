"""Optional read-only Extinct comparison over authenticated direct Agent streams.

Its absence, timeout or an older peer never blocks local wallet deletion.
"""
import hashlib,threading,time,secrets
from approval_store import digest
from wallet_ops import rpc
from peer_wallet import frame_read,frame_write
from retirement_evidence import samples
FEATURE='extinct_compare_v1'

def raw_hash(value):return hashlib.sha256(bytes.fromhex(value)).hexdigest()

class Comparisons:
    def __init__(self,peers,core,lock,guard):self.peers=peers;self.core=core;self.lock=lock;self.guard=guard;self.gate=threading.BoundedSemaphore(1)
    def accept(self,stream):
        if not self.gate.acquire(False):return False
        def serve():
            acquired=False
            try:
                deadline=time.monotonic()+60;stream.timeout=30;acquired=self.lock.acquire(False)
                if not acquired or self.guard():raise ValueError('Source is busy')
                request=frame_read(stream)
                if set(request)!={'kind','addresses','transactions'} or request['kind']!=FEATURE or type(request['addresses']) is not int or type(request['transactions']) is not int or not 0<=request['addresses']<=10000 or not 0<=request['transactions']<=100000:raise ValueError('Invalid comparison limits')
                from retirement_phases import local_archives
                candidates=local_archives(self.core);address_rows=[];tx_rows=[]
                frame_write(stream,{'ready':bool(candidates)})
                if not candidates:return
                for _ in range(request['addresses']):
                    if time.monotonic()>deadline:raise ValueError('Comparison time limit reached')
                    row=frame_read(stream)
                    if set(row)!={'address','label'} or not isinstance(row['address'],str) or not isinstance(row['label'],str) or len(row['address'])>128 or len(row['label'])>256:raise ValueError('Invalid address comparison')
                    valid=[]
                    for name in candidates:
                        info=rpc(self.core,'getaddressinfo',[row['address']],name,timeout=3)
                        if (info.get('ismine') or info.get('iswatchonly')) and info.get('labels')==[row['label']]:valid.append(name)
                    candidates=valid;address_rows.append({**row,'matched':True})
                for _ in range(request['transactions']):
                    if time.monotonic()>deadline:raise ValueError('Comparison time limit reached')
                    row=frame_read(stream)
                    if set(row)!={'txid','blockhash','raw_hash'} or any(not __import__('re').fullmatch('[0-9a-f]{64}',str(v)) for v in row.values()):raise ValueError('Invalid transaction comparison')
                    valid=[]
                    for name in candidates:
                        try:value=rpc(self.core,'gettransaction',[row['txid'],True],name,timeout=3)
                        except ValueError:continue
                        if value.get('confirmations',0)>0 and value.get('blockhash')==row['blockhash'] and raw_hash(value['hex'])==row['raw_hash']:valid.append(name)
                    candidates=valid;header=rpc(self.core,'getblockheader',[row['blockhash']],timeout=3)
                    if header.get('confirmations',0)<=0:candidates=[]
                    tx_rows.append({'txid':row['txid'],'blockhash':row['blockhash'],'height':header['height'],'time':header['time'],'matched':True})
                frame_write(stream,{'verified':bool(candidates),'archive':candidates[0] if candidates else None,'address_count':len(address_rows),'transaction_count':len(tx_rows),'address_samples':samples(address_rows),'transaction_samples':samples(tx_rows)})
                # Let the requesting peer consume and acknowledge the final bytes.
                frame_read(stream)
            except Exception as error:
                from activity_log import event
                event('extinction.compare','Optional source comparison unavailable · exception='+type(error).__name__)
                try:frame_write(stream,{'verified':False})
                except Exception:pass
            finally:
                if acquired:self.lock.release()
                self.peers.wallet_bridge.abort(stream);self.gate.release()
        threading.Thread(target=serve,daemon=True,name='optional-extinct-comparison').start();return True


def request(owner,key):
    state=owner.store.read();row=state['pending'].get(key);review=owner.reviews.get(key)
    if not row or row['proposal'].get('phase')!='delete' or row['state']!='pending' or not review or time.time()-review[1]>600:raise ValueError('Open the current deletion review before comparing optional remote history.')
    facts=review[0]
    if facts.get('history_comparison',{}).get('verified'):return {'state':'complete','evidence':facts['history_comparison']}
    jobs=getattr(owner,'remote_comparisons',None)
    if jobs is None:jobs={};owner.remote_comparisons=jobs
    binding=digest({'request':row['proposal'],'local_wallets':facts['local_wallets']})
    if key in jobs and jobs[key]['binding']==binding and (jobs[key]['result']['state']=='checking' or time.monotonic()-jobs[key]['created']<15):return jobs[key]['result']
    result={'state':'checking','message':'Checking connected Agents for optional Extinct history evidence. Deletion does not depend on this check.'};job={'binding':binding,'result':result,'created':time.monotonic()};jobs[key]=job
    peers=getattr(owner.store,'peers',None)
    channels=[]
    if peers and getattr(peers,'direct',None):
        for c in list(peers.channels.values()):
            try:
                if c.peer['role']!='agent' or FEATURE not in getattr(c,'features',set()):continue
                if peers.channel(c.peer['identity_key']) is not c:continue
                peers.direct.require(c);channels.append(c)
            except ValueError:continue
    if not channels:
        job['result']={'state':'unavailable','message':'No connected Agent offers an Extinct history comparison. Before deleting, this history should already have been preserved in another node’s Extinct wallet.'};return job['result']
    def run():
        deadline=time.monotonic()+90
        for channel in channels[:3]:
            stream=None
            try:
                p=row['proposal'];stream=peers.wallet_bridge.open_comparison(channel);stream.timeout=30
                frame_write(stream,{'kind':FEATURE,'addresses':len(p['manifest']['addresses']),'transactions':len(p['manifest']['transactions'])})
                if frame_read(stream)!={'ready':True}:continue
                for address in p['manifest']['addresses']:
                    if time.monotonic()>deadline:raise ValueError('Comparison time limit reached')
                    frame_write(stream,address)
                for tx in p['manifest']['transactions']:
                    if time.monotonic()>deadline:raise ValueError('Comparison time limit reached')
                    original=None
                    for name in facts['local_wallets']:
                        try:value=rpc(owner.core,'gettransaction',[tx['txid'],True],name,timeout=3)
                        except ValueError:continue
                        if value.get('blockhash')==tx['blockhash'] and value.get('confirmations',0)>0:original=value;break
                    if original is None:raise ValueError('Original record unavailable')
                    frame_write(stream,{**tx,'raw_hash':raw_hash(original['hex'])})
                evidence=frame_read(stream);frame_write(stream,{'received':True})
                if evidence.get('verified') is not True:continue
                if evidence.get('address_count')!=len(p['manifest']['addresses']) or evidence.get('transaction_count')!=len(p['manifest']['transactions']):raise ValueError('Comparison counts differ')
                if not isinstance(evidence.get('archive'),str) or not 1<=len(evidence['archive'])<=200:raise ValueError('Invalid archive result')
                address_set={(a['address'],a['label']) for a in p['manifest']['addresses']};tx_set={(t['txid'],t['blockhash']) for t in p['manifest']['transactions']}
                if len(evidence.get('address_samples',[]))>5 or len(evidence.get('transaction_samples',[]))>5:raise ValueError('Invalid comparison samples')
                if any((a.get('address'),a.get('label')) not in address_set for a in evidence['address_samples']) or any((t.get('txid'),t.get('blockhash')) not in tx_set for t in evidence['transaction_samples']):raise ValueError('Comparison samples differ')
                if any(type(t.get('height')) is not int or t['height']<0 or type(t.get('time')) is not int or t['time']<0 for t in evidence['transaction_samples']):raise ValueError('Invalid comparison block samples')
                evidence.update(remote=True)
                job['result']={'state':'complete','evidence':evidence,'message':'Original history matches the Extinct wallet on a directly paired Agent.'};return
            except Exception as error:
                from activity_log import event
                event('extinction.compare','Optional receiving comparison unavailable · exception='+type(error).__name__)
            finally:
                if stream:peers.wallet_bridge.abort(stream)
        job['result']={'state':'unavailable','message':'No connected Extinct wallet confirmed every original record. Before deleting, this history should already have been preserved elsewhere.'}
    threading.Thread(target=run,daemon=True,name='optional-retirement-evidence').start();return result
