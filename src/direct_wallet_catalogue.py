"""Paired Agents own discovery, complete transfer scope and receiver permissions.

Public inventories use an Agent-only direct stream. No Server request, label,
subset, permission snapshot or completed-transfer ledger creates these offers.
"""
import copy,secrets,threading,time
from approval_store import digest,MAX_ITEMS
from public_policy import descriptors
from wallet_ops import rpc
from peer_wallet import frame_read,frame_write
FEATURE='wallet_catalogue_v1'
SERVER_KINDS={'wallet_sync_queue','wallet_transfer','wallet_transfer_preview','wallet_sync_offers'}

def write_inventory(stream,value):
    import json,struct
    raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>8*1024*1024:raise ValueError('Direct inventory exceeds the bounded public discovery size.')
    stream.write(struct.pack('!I',len(raw)))
    for offset in range(0,len(raw),65536):stream.write(raw[offset:offset+65536])

def read_inventory(stream):
    import struct
    from peer_wallet import read_exact
    from denial_storage import strict_json
    count=struct.unpack('!I',read_exact(stream,4))[0]
    if not 0<count<=8*1024*1024:raise ValueError('Invalid direct inventory size.')
    return validate(strict_json(read_exact(stream,count)))

def local_request(saved,p):return digest(p) in saved.get('direct_sync_keys',{})

def activate(store):
    with store.edit() as s:
        for ident,row in list(s.get('sync_exclusions',{}).items()):
            if row.get('wallet_name') in ('Extinct','Wallaby Extinct','extinct_watch'):
                stable=digest({'wallet_sync':'extinct_archive_v1'});s['sync_exclusions'].pop(ident);s['sync_exclusions'][stable]={**row,'policy_id':stable}
        s['direct_wallet_discovery']=True
        # Old unstarted Server jobs cannot compete with direct Agent inventory.
        for k,r in list(s['pending'].items()):
            if r['proposal'].get('kind')=='wallet_transfer' and k not in s.get('direct_sync_keys',{}) and r['state']=='pending' and k!=s.get('active_transfer'):
                s['pending'].pop(k);s.get('sync_choices',{}).pop(k,None);s.get('transfer_previews',{}).pop(k,None)
        s['sync_offers']={};s['sync_offers_received']=True

def reconcile_preservation(core,store):
    """Actual directory absence cancels stale preservation, never completes it."""
    saved=store.read()
    rows=[(k,r) for k,r in saved['pending'].items() if r['proposal'].get('kind')=='wallet_retire' and r['proposal'].get('phase')=='preserve' and r['state']=='pending']
    if not rows:return
    names={r['name'] for r in rpc(core,'listwalletdir')['wallets']}
    for key,row in rows:
        p=row['proposal']
        if p['wallet'] in names:continue # Unloaded is not deleted.
        if saved.get('retirement_continuations',{}).get(key) or digest({'local_retirement_history':key}) in saved.get('history_jobs',{}):continue
        from retirement_phases import result
        outcome=result(p,'cancelled',message='Preservation superseded: its local Extinct archive was deleted. No preservation or deletion was performed.')
        with store.edit() as s:
            if s['pending'].get(key)!=row:continue
            s['pending'].pop(key)
            s['completed'][key]={'kind':'wallet_retire','at':time.time(),'outcome':'cancelled_archive_absent','result':outcome}
        store.queue('wallet_retirement_result',outcome)
        from activity_log import event
        event('extinction.reconcile','Stale preservation cancelled · archive_absent=true · no_wallet_mutation=true · request='+key[:12])

def snapshot(core,store):
    from wallet_loading import ownership_wallets
    from wallet_labels import read_labels
    from extinct_sync import grouped,ARCHIVE
    reconcile_preservation(core,store)
    from wallet_visibility import internal
    entries=[];seen=set()
    names={r['name'] for r in rpc(core,'listwalletdir')['wallets'] if not internal(r['name'])}
    with ownership_wallets(core,names):
        for name in sorted(rpc(core,'listwallets')):
            if internal(name):continue
            info=rpc(core,'getwalletinfo',[],name);raw=rpc(core,'listdescriptors',[False],name)
            if not raw.get('descriptors'):continue
            raw={'wallet_name':name,'descriptors':copy.deepcopy(raw['descriptors'])};ident=digest(sorted(descriptors(raw)))
            # Router aliases are not additional signing wallets.
            if info.get('walletname')!=name or ident in seen:continue
            seen.add(ident)
            from managed_accounts import classify
            managed=classify(store.read(),name,raw)
            if managed and managed['kind']=='signer':continue # Assigned signer keys are not independent asset wallets.
            from wallet_setup_signing import restricted
            public_only=bool(managed and managed['kind']=='combined' or any((policy:=restricted(d['desc'])) and (policy['height'] is not None or policy['total']>1) for d in raw['descriptors']))
            archive=grouped(raw)
            if archive:raw['wallet_name']=ARCHIVE
            row={'public_wallet':raw,'private':bool(info.get('private_keys_enabled')) and not public_only,'storage':'disc' if info.get('wallaby_storage')=='disc' else 'node','archive':archive,'txids':[],'labels':[],'available':not bool(info.get('scanning'))}
            if archive:
                from extinct_upgrade import snapshot as archive_snapshot
                state=archive_snapshot(core,name);row['txids']=state['txids'];row['labels']=read_labels(core,name,raw,[])
            entries.append(row)
    if len(entries)>MAX_ITEMS:raise ValueError('Direct wallet inventory exceeds the supported wallet count.')
    return {'version':1,'name':__import__('socket').gethostname(),'wallets':entries,'denied':sorted(store.read().get('sync_exclusions',{}))}

def validate(value):
    from agent_rpc import PRIVATE
    import json,re
    if not isinstance(value,dict) or set(value)!={'version','name','wallets','denied'} or type(value['version']) is not int or value['version']!=1:raise ValueError('Invalid direct wallet catalogue.')
    if not isinstance(value['name'],str) or not 1<=len(value['name'])<=128 or any(ord(c)<32 for c in value['name']):raise ValueError('Invalid direct device name.')
    if not isinstance(value['wallets'],list) or len(value['wallets'])>MAX_ITEMS or not isinstance(value['denied'],list) or len(value['denied'])>MAX_ITEMS or any(not isinstance(k,str) or not re.fullmatch('[0-9a-f]{64}',k) for k in value['denied']):raise ValueError('Invalid direct inventory limits.')
    if PRIVATE.search(json.dumps(value)):raise ValueError('Private material in public wallet discovery.')
    seen=set()
    for row in value['wallets']:
        if not isinstance(row,dict) or set(row)!={'public_wallet','private','storage','archive','txids','labels','available'} or any(type(row[k]) is not bool for k in ('private','archive','available')) or row['storage'] not in ('node','disc'):raise ValueError('Invalid direct wallet metadata.')
        ident=digest(sorted(descriptors(row['public_wallet'])))
        if ident in seen:raise ValueError('Duplicate direct wallet policy.')
        seen.add(ident)
        if not isinstance(row['txids'],list) or len(row['txids'])>100000 or any(not isinstance(k,str) or not re.fullmatch('[0-9a-f]{64}',k) for k in row['txids']):raise ValueError('Invalid archive record inventory.')
        from extinct_sync import grouped
        if row['archive']!=grouped(row['public_wallet']) or row['archive'] and row['private']:raise ValueError('Invalid archive capability.')
        from wallet_labels import validate_labels
        validate_labels(row['labels'])
    return value

def missing(row,destination):
    wanted=descriptors(row['public_wallet'])
    if row['archive']:
        archives=[r for r in destination['wallets'] if r['archive']]
        return not any(wanted<=descriptors(r['public_wallet']) and set(row['txids'])<=set(r['txids']) and all(v in r['labels'] for v in row['labels']) for r in archives)
    return not any(wanted<=descriptors(r['public_wallet']) for r in destination['wallets'])

class Catalogue:
    def __init__(self,peers,transfer,operation_lock=None,guard=lambda:False):
        self.peers=peers;self.transfer=transfer;self.store=transfer.store;self.core=transfer.core;self.lock=operation_lock or threading.RLock();self.guard=guard;self.gate=threading.BoundedSemaphore(1);self.thread=None;self.cache=None;self.cache_at=0
        self.core.managed_store=self.store
        activate(self.store)
    def inventory(self):
        self.phase='local_inventory'
        if not self.lock.acquire(timeout=3):raise ValueError('Local wallet operation in progress.')
        try:
            if self.guard() or self.store.read().get('sync_batch'):raise ValueError('Local wallet operation in progress.')
            # Full inspection includes unloaded Core wallets and restores them.
            # Cache public facts briefly; transfer approval/export still checks live facts.
            if self.cache is None or time.monotonic()-self.cache_at>15:
                self.cache=snapshot(self.core,self.store);self.cache_at=time.monotonic()
            result=copy.deepcopy(self.cache);result['denied']=sorted(self.store.read().get('sync_exclusions',{}));return result
        finally:self.lock.release()
    def proposals(self,channel,origin,destination):
        self.phase='source_offers'
        from peer_protocol import PROTOCOL,CIPHER
        from managed_accounts import guard
        from wallet_preview import prepare
        result=[];keep=set()
        if not self.lock.acquire(timeout=3):raise ValueError('Local wallet operation in progress.')
        try:
            if self.guard() or self.store.read().get('sync_batch'):raise ValueError('Local wallet operation in progress.')
            from wallet_loading import ownership_wallets
            with ownership_wallets(self.core):
                for row in sorted(origin['wallets'],key=lambda r:(not r['archive'],r['public_wallet']['wallet_name'].casefold())):
                    if __import__('wallet_visibility').internal(row['public_wallet']['wallet_name']) or not row['available'] or not missing(row,destination):continue
                    raw=row['public_wallet'];policy=__import__('sync_preferences').policy_id({'public_wallet':raw})
                    if policy in destination['denied']:continue
                    own=self.peers.identity;other=channel.peer
                    common={'kind':'wallet_transfer','transfer_version':3,'direction':'send','node_ipv6':None,'public_wallet':raw,'source_has_private_keys':row['private'],'earliest_timestamp':min(r.get('timestamp',0) for r in raw['descriptors']),'requires_blockchain_redownload':False,'transport':{'protocol':PROTOCOL,'version':1,'cipher_suite':CIPHER,**{side+'_'+field:value[key] for side,value in (('sender',own),('receiver',other)) for field,key in (('endpoint','endpoint_id'),('identity','identity_key'),('noise_key','noise_public_key'))}},'peer':{'node_id':other['endpoint_id'],'hostname':destination['name'],'ipv6':None}}
                    identity=digest({'channel':channel.id,'row':row,'destination':other['endpoint_id']})
                    saved=self.store.read();candidate=next(((k,r) for k,r in saved['pending'].items() if saved.get('direct_sync_keys',{}).get(k,{}).get('offer')==identity and r['state']=='pending' and not r.get('withdrawn')),None)
                    if candidate:key,p=candidate[0],candidate[1]['proposal']
                    else:
                        p={**common,'transfer_id':secrets.token_hex(32),'preview_challenge':secrets.token_hex(32)};key=digest(p)
                        from vault_policy import validate_proposal
                        validate_proposal(p)
                        with self.store.edit() as s:
                            if len(s['pending'])>=MAX_ITEMS:raise ValueError('Authorisation queue full.')
                            s['pending'][key]={'proposal':p,'received':time.time(),'state':'pending'};s.setdefault('direct_sync_keys',{})[key]={'channel':channel.id,'peer':other['endpoint_id'],'offer':identity,'enabled':True}
                    try:
                        guard(self.core,p,self.store,public_preview=True)
                        payload=self.store.read().get('transfer_previews',{}).get(key) or prepare(self.core,self.store,key,p)
                    except ValueError as error:
                        self.phase='archive_preview' if row['archive'] else 'wallet_preview';self.log_failure(error)
                        self.retire({key});continue
                    keep.add(key);result.append({'proposal':p,'preview':payload})
            previous={k for k,v in self.store.read().get('direct_sync_keys',{}).items() if v['peer']==channel.peer['endpoint_id'] and self.store.read()['pending'].get(k,{}).get('proposal',{}).get('direction')=='send'}
            self.retire(previous-keep)
            return result
        finally:self.lock.release()
    def retire(self,keys):
        with self.store.edit() as s:
            for k in keys:
                r=s['pending'].get(k)
                if r and (r['state']!='pending' or s.get('active_transfer')==k or k in s.get('sync_batch',{}).get('keys',[])):continue
                s['pending'].pop(k,None);s.get('sync_choices',{}).pop(k,None);s.get('transfer_previews',{}).pop(k,None);s.get('direct_sync_keys',{}).pop(k,None)
    def receive(self,channel,offers,origin,destination):
        self.phase='direct_offer_validation'
        from wallet_preview import verify_bound
        from vault_policy import validate_proposal
        if not isinstance(offers,list) or len(offers)>MAX_ITEMS:raise ValueError('Invalid direct offer count.')
        keep=set()
        with self.store.edit() as state:
            for row in origin['wallets']:
                if __import__('wallet_visibility').internal(row['public_wallet']['wallet_name']):continue
                policy=__import__('sync_preferences').policy_id(row)
                if not missing(row,destination):continue
                key=digest({'direct_denied':policy,'peer':channel.peer['endpoint_id']});keep.add(key)
                state.setdefault('direct_sync_offers',{})[key]={'id':key,'transfer_id':key,'direction':'receive','peer':{'node_id':channel.peer['endpoint_id'],'hostname':origin['name']},'public_wallet':row['public_wallet'],'status':'disabled' if policy in state.get('sync_exclusions',{}) else 'discovery_pending','source_storage':row['storage']}
        for offer in offers:
            if not isinstance(offer,dict) or set(offer)!={'proposal','preview'}:raise ValueError('Invalid direct offer.')
            p=copy.deepcopy(validate_proposal(offer['proposal']));payload=offer['preview']
            if __import__('wallet_visibility').internal(p['public_wallet']['wallet_name']):continue
            matches=[r for r in origin['wallets'] if r['public_wallet']==p['public_wallet'] and r['private']==p['source_has_private_keys']]
            if p['direction']!='send' or len(matches)!=1 or not missing(matches[0],destination):raise ValueError('Direct offer does not describe a complete source wallet missing here.')
            if p['transport']['sender_endpoint']!=channel.peer['endpoint_id'] or p['transport']['receiver_endpoint']!=self.peers.identity['endpoint_id']:raise ValueError('Offer belongs to another direct peer.')
            p['direction']='receive';p['peer']={'node_id':channel.peer['endpoint_id'],'hostname':origin['name'],'ipv6':None};key=digest(p)
            if self.peers.binding(p) is not channel:raise ValueError('Catalogue channel changed.')
            verify_bound(self.store,payload,p)
            policy=__import__('sync_preferences').policy_id(p)
            with self.store.edit() as s:
                s.setdefault('direct_sync_offers',{})[key]={'id':key,'transfer_id':p['transfer_id'],'direction':'receive','peer':{k:p['peer'][k] for k in ('node_id','hostname')},'public_wallet':p['public_wallet'],'status':'disabled' if policy in s.get('sync_exclusions',{}) else 'ready','source_storage':matches[0]['storage']}
                keep.add(key)
                if policy in s.get('sync_exclusions',{}):continue
                if key in s['completed']:continue # Fresh source generation follows the next inventory.
                if key not in s['pending']:
                    if len(s['pending'])>=MAX_ITEMS:raise ValueError('Authorisation queue full.')
                    s['pending'][key]={'proposal':p,'received':time.time(),'state':'pending'}
                s.setdefault('direct_sync_keys',{})[key]={'peer':channel.peer['endpoint_id'],'channel':channel.id,'enabled':True}
                old=s.setdefault('transfer_previews',{}).get(key)
                if old is not None and old!=payload:raise ValueError('Direct reviewed preview changed.')
                s['transfer_previews'][key]=payload
        saved=self.store.read();previous={k for k,v in saved.get('direct_sync_keys',{}).items() if v['peer']==channel.peer['endpoint_id'] and saved['pending'].get(k,{}).get('proposal',{}).get('direction')=='receive'}
        self.retire(previous-keep)
        with self.store.edit() as s:
            for k,o in list(s.get('direct_sync_offers',{}).items()):
                if o['peer']['node_id']==channel.peer['endpoint_id'] and k not in keep:s['direct_sync_offers'].pop(k)
        from activity_log import event
        signature=(len(keep),len(origin['wallets']))
        if getattr(channel,'catalogue_logged',None)!=signature:event('sync.direct_discovery','Paired inventory compared · source_wallets='+str(signature[1])+' · receive_offers='+str(signature[0]));channel.catalogue_logged=signature
    @staticmethod
    def write_offers(stream,offers):
        frame_write(stream,{'offers':len(offers)})
        for offer in offers:frame_write(stream,offer)
    @staticmethod
    def read_offers(stream):
        value=frame_read(stream)
        if set(value)!={'offers'} or type(value['offers']) is not int or not 0<=value['offers']<=MAX_ITEMS:raise ValueError('Invalid direct offer batch.')
        return [frame_read(stream) for _ in range(value['offers'])]
    def exchange(self,channel):
        origin=validate(self.inventory());stream=self.peers.wallet_bridge.open_catalogue(channel)
        try:
            stream.timeout=180;write_inventory(stream,origin);remote=read_inventory(stream);offers=self.read_offers(stream)
            self.receive(channel,offers,remote,origin);self.write_offers(stream,self.proposals(channel,origin,remote))
            if frame_read(stream)!={'received':True}:raise ValueError('Catalogue acknowledgement missing.')
            frame_write(stream,{'done':True})
        finally:self.peers.wallet_bridge.abort(stream)
    def accept(self,stream):
        if not self.gate.acquire(False):return False
        def serve():
            try:
                stream.timeout=180;remote=read_inventory(stream);origin=validate(self.inventory());write_inventory(stream,origin)
                self.write_offers(stream,self.proposals(stream.channel,origin,remote));self.receive(stream.channel,self.read_offers(stream),remote,origin)
                frame_write(stream,{'received':True});frame_read(stream)
            except Exception as error:self.log_failure(error)
            finally:self.peers.wallet_bridge.abort(stream);self.gate.release()
        threading.Thread(target=serve,daemon=True,name='direct-wallet-catalogue-serve').start();return True
    def log_failure(self,error):
        from activity_log import event
        from pathlib import Path
        import traceback
        frames=traceback.extract_tb(error.__traceback__);site=frames[-1] if frames else None
        location=Path(site.filename).stem+':'+str(site.lineno) if site and Path(site.filename).parent==Path(__file__).parent else 'external'
        event('sync.direct_discovery','Inventory comparison deferred · phase='+getattr(self,'phase','connection')+' · site='+location+' · exception='+type(error).__name__+' · no_wallet_mutation=true')
    def start(self):
        def run():
            while not self.peers.stop.wait(2):
                try:
                    live=set()
                    for channel in list(self.peers.channels.values()):
                        try:
                            if channel.peer['role']=='agent' and channel.ready:self.peers.direct.require(channel);live.add(channel.id)
                        except ValueError:pass
                    saved=self.store.read()
                    self.retire({k for k,v in saved.get('direct_sync_keys',{}).items() if v['channel'] not in live})
                    with self.store.edit() as state:
                        for key,offer in list(state.get('direct_sync_offers',{}).items()):
                            c=self.peers.channels.get(offer['peer']['node_id'])
                            if not c or c.id not in live:state['direct_sync_offers'].pop(key)
                    if self.lock.acquire(False):
                        try:
                            if not self.guard():reconcile_preservation(self.core,self.store)
                        finally:self.lock.release()
                    for c in list(self.peers.channels.values()):
                        if c.peer['role']!='agent' or not c.ready or not c.initiator:continue
                        if FEATURE not in c.features or time.monotonic()-getattr(c,'catalogue_at',0)<5:continue
                        try:self.peers.direct.require(c)
                        except ValueError:continue
                        c.catalogue_at=time.monotonic()
                        if not self.gate.acquire(False):continue
                        try:self.exchange(c)
                        finally:self.gate.release()
                except Exception as error:self.log_failure(error)
        self.thread=threading.Thread(target=run,daemon=True,name='direct-wallet-discovery');self.thread.start()
