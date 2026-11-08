"""Locally approve additive public policies; keys, quorum and old history survive."""
import copy,re,time
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc,sats
from wallet_setup_signing import restricted
from vendor.embit.descriptor import Descriptor
from vendor.embit.networks import NETWORKS

FIELDS={'kind','version','request_id','chain','wallet','previous_descriptors','receive_descriptor','change_descriptor','timestamp','expires_at'}

def transition(value):
    old=value['previous_descriptors'];new=[value['receive_descriptor'],value['change_descriptor']]
    if not isinstance(old,list) or len(old)!=2:raise ValueError('Both previous receive/change policies are required.')
    descriptors({'wallet_name':'policy','descriptors':[{'desc':d} for d in old+new]})
    old_heights=[];new_heights=[]
    for branch,(a,b) in enumerate(zip(old,new)):
        x=restricted(a);y=restricted(b)
        if not x or not y or x['threshold']!=y['threshold'] or x['total']!=y['total']:raise ValueError('A vault refresh cannot replace signing keys, quorum or spending policy type.')
        keys=lambda v:sorted(str(k).replace("'",'h') for k in v['keys'])
        if keys(x)!=keys(y) or any(not str(k).endswith('/'+str(branch)+'/*') for k in y['keys']):raise ValueError('The refreshed policy must use the same public account keys and receive/change branches.')
        if y['height'] is None or y['height']<=(x['height'] or 0):raise ValueError('Refresh must preserve a mandatory, strictly later block-height lock.')
        old_heights.append(x['height']);new_heights.append(y['height'])
    if old_heights[0]!=old_heights[1] or new_heights[0]!=new_heights[1]:raise ValueError('Receive and change vault conditions must agree.')
    if type(value['timestamp']) is not int or not 0<=value['timestamp']<=4102444800:raise ValueError('Invalid public policy history timestamp.')
    return {'previous_descriptors':old,'receive_descriptor':new[0],'change_descriptor':new[1],'timestamp':value['timestamp']}

def validate(p):
    from vault_policy import NETWORK,text
    if not isinstance(p,dict) or not (FIELDS|({'peer_transport'} if p.get('version')==2 else set()))<=set(p)<=FIELDS|{'receiving_address'}|({'peer_transport'} if p.get('version')==2 else set()) or p['kind']!='wallet_policy_refresh' or type(p['version']) is not int or p['version'] not in (1,2) or not re.fullmatch('[0-9a-f]{64}',str(p['request_id'])) or p['chain'] not in NETWORK or type(p['expires_at']) is not int or not time.time()<p['expires_at']<=time.time()+86400:raise ValueError('Invalid or expired public policy refresh.')
    if p['version']==2:
        from peer_protocol import requirements
        requirements(p['peer_transport'])
    text(p['wallet'],256);transition(p)
    if 'receiving_address' in p:
        target=p['receiving_address']
        if not isinstance(target,dict) or set(target)!={'index','address'} or type(target['index']) is not int or not 0<=target['index']<=999:raise ValueError('Invalid proposed vault receiving address index.')
        text(target['address'],128)
        verify_receiving_address(p)
    return p

def verify_receiving_address(proposal,core=None):
    """The claimed destination is untrusted; derive it from the reviewed policy."""
    target=proposal.get('receiving_address')
    if target is None:return None
    index=target['index'];desc=proposal['receive_descriptor']
    address=Descriptor.from_string(desc).derive(index).script_pubkey().address(NETWORKS[proposal['chain']])
    if address!=target['address']:raise ValueError('The proposed receiving address does not match the new vault policy and index. No policy was approved.')
    if core is not None and rpc(core,'deriveaddresses',[desc,[index,index]])!=[address]:raise ValueError('Local independent receiving address derivation differs from Core.')
    return {'index':index,'address':address}

def roots(recovery):
    if recovery.get('kind')=='node_wallet':
        rows=recovery.get('public_policies',recovery['public_wallet'])['descriptors'];pairs={}
        for row in rows:
            parsed=restricted(row['desc'])
            branch=bool(row.get('internal'))
            if parsed and (branch not in pairs or (parsed['height'] or 0)>(restricted(pairs[branch])['height'] or 0)):pairs[branch]=row['desc']
        return [pairs[False],pairs[True]] if len(pairs)==2 else []
    return [recovery['receive_descriptor'],recovery['change_descriptor']]

def validate_extensions(recovery):
    extensions=recovery.get('policy_extensions',[])
    if not isinstance(extensions,list) or len(extensions)>128:raise ValueError('Too many public policy revisions.')
    retired=recovery.get('retired_policy_hashes',[])
    available={digest([item.get('receive_descriptor'),item.get('change_descriptor')]) for item in extensions if isinstance(item,dict)}
    if not isinstance(retired,list) or len(retired)!=len(set(retired)) or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) or v not in available for v in retired):raise ValueError('Invalid retired policy history.')
    known=roots(recovery)
    for item in extensions:
        base={'previous_descriptors','receive_descriptor','change_descriptor','timestamp'}
        if not isinstance(item,dict) or not base<=set(item)<=base|{'retired'} or ('retired' in item and (item['retired'] is not True or digest([item['receive_descriptor'],item['change_descriptor']]) not in retired)):raise ValueError('Invalid archived policy revision.')
        transition(item)
        if item['previous_descriptors']!=known:raise ValueError('Archived policy history is discontinuous or replaces keys.')
        if digest([item['receive_descriptor'],item['change_descriptor']]) not in retired:known=[item['receive_descriptor'],item['change_descriptor']]
    return known

class Refresh:
    def __init__(self,core,store,archives):self.core=core;self.store=store;self.archives=archives;self.reviews={}
    def review(self,key):
        from policy_refresh_group import review
        if self.store.read()['pending'][key]['state']=='awaiting_backups':
            from policy_refresh_backups import review as backup_review
            return backup_review(self,key)
        if self.store.read()['pending'][key]['state']!='pending':raise ValueError('This policy installation was attempted. Reconcile locally before retrying.')
        return review(self,key,validate(self.store.read()['pending'][key]['proposal']))
    def review_single(self,key,p):
        if rpc(self.core,'getblockchaininfo')['chain']!=p['chain']:raise ValueError('Policy network differs from the local node.')
        raw=rpc(self.core,'listdescriptors',[False],p['wallet'])
        first=rpc(self.core,'deriveaddresses',[p['previous_descriptors'][0],[0,0]])[0]
        labels=rpc(self.core,'getaddressinfo',[first],p['wallet']).get('labels',[])
        if any(v.startswith('Wallaby setup pending:') for v in labels) or re.fullmatch('Wallaby policy [0-9a-f]{20}',p['wallet']) and not any(v.startswith('Wallaby setup ready:') for v in labels):raise ValueError('Finish and verify the original wallet setup before refreshing its vault policy.')
        if not descriptors({'wallet_name':'old','descriptors':[{'desc':d} for d in p['previous_descriptors']]})<=descriptors(raw):raise ValueError('The old policy is not present in the selected local wallet.')
        destination=verify_receiving_address(p,self.core)
        parsed=restricted(p['receive_descriptor']);samples=[]
        for branch,desc in enumerate((p['receive_descriptor'],p['change_descriptor'])):
            canonical=rpc(self.core,'getdescriptorinfo',[desc])
            if canonical.get('hasprivatekeys'):raise ValueError('Only public policy information may be refreshed.')
            d=Descriptor.from_string(desc)
            start=destination['index'] if destination is not None else 0
            for index in range(start,min(start+3,1000)):
                local=d.derive(index).script_pubkey().address(NETWORKS[p['chain']])
                if rpc(self.core,'deriveaddresses',[desc,[index,index]])!=[local]:raise ValueError('Local independent policy derivation differs from Core.')
                samples.append({'branch':'Receive' if branch==0 else 'Change','index':index,'address':local})
        result=rpc(self.core,'scantxoutset',['start',[{'desc':p[k],'range':[0,999]} for k in ('receive_descriptor','change_descriptor')]],timeout=600)
        if not result.get('success') or not isinstance(result.get('unspents'),list) or len(result['unspents'])>10000:raise ValueError('Core did not complete its independent UTXO scan. No policy was changed.')
        outputs=[]
        from vendor.embit.script import Script
        for row in result['unspents']:
            actual=rpc(self.core,'gettxout',[row['txid'],row['vout'],True])
            if not actual or sats(actual['value'])!=sats(row['amount']) or actual['scriptPubKey']['hex']!=row['scriptPubKey']:raise ValueError('The local UTXO set changed during verification; review again.')
            address=Script(bytes.fromhex(row['scriptPubKey'])).address(NETWORKS[p['chain']]);header=rpc(self.core,'getblockheader',[rpc(self.core,'getblockhash',[row['height']])])
            outputs.append({'address':address,'txid':row['txid'],'vout':row['vout'],'amount_sats':str(sats(row['amount'])),'time_received':header['time'],'blockheight':row['height'],'confirmations':actual['confirmations']})
        facts={'wallet':p['wallet'],'chain':p['chain'],'height':parsed['height'],'threshold':parsed['threshold'],'total':parsed['total'],'policy_hash':digest(transition(p)),'previous_descriptors':p['previous_descriptors'],'receive_descriptor':p['receive_descriptor'],'change_descriptor':p['change_descriptor'],'samples':samples,'funded_outputs':outputs,'scan_range':[0,999],'old_policies_retained':True}
        facts['sample_start_index']=destination['index'] if destination is not None else 0
        if destination is not None:facts['receiving_address']=destination
        self.reviews[key]=(copy.deepcopy(p),facts,time.monotonic())
        from vault_time import estimates
        return {'kind':p['kind'],'id':key,'refresh':facts,'unlock_estimates':estimates(self.core,[facts['height']],expected_chain=facts['chain'])}
    def approve(self,key):
        from policy_refresh_group import approve
        return approve(self,key)
    def deny(self,key):
        from policy_refresh_group import deny
        return deny(self,key)

def validate_output_policies(rows):
    from vault_policy import text
    if not isinstance(rows,list) or len(rows)>16:raise ValueError('Invalid vault output policy list.')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'policy_hash','descriptor','index','address','amount_sats'} or not re.fullmatch('[0-9a-f]{64}',str(row['policy_hash'])) or type(row['index']) is not int or not 0<=row['index']<=999:raise ValueError('Invalid vault output policy binding or unsupported scan index.')
        descriptors({'wallet_name':'output','descriptors':[{'desc':row['descriptor']}]});parsed=restricted(row['descriptor'])
        if not parsed or not parsed['height']:raise ValueError('A vault output must have one restricted mandatory-height policy.')
        text(row['address'],128)
        if not isinstance(row['amount_sats'],str) or not re.fullmatch('[1-9][0-9]{0,15}',row['amount_sats']) or int(row['amount_sats'])>2100000000000000:raise ValueError('Invalid fixed vault output amount.')
        value=(row['descriptor'],row['index'],row['address'])
        if value in seen:raise ValueError('Duplicate vault output binding.')
        seen.add(value)
    return rows

def verify_output_policies(ops,p,review):
    from collections import Counter
    declared=validate_output_policies(p.get('output_policies',[]))
    if not declared:return
    saved=ops.store.read();used=set()
    for row in declared:
        proof=saved.get('public_policy_updates',{}).get(row['policy_hash'])
        approved=bool(proof and row['descriptor'] in (proof['receive_descriptor'],proof['change_descriptor']))
        if not approved:
            # Public Core markers and locally reviewed archive histories survive a
            # new volatile signing session; Wallet Server labels cannot establish them.
            import node_client
            router=node_client.LOCAL_ROUTER
            if router:
                approved=any(any(digest(ext)==row['policy_hash'] and row['descriptor'] in (ext['receive_descriptor'],ext['change_descriptor']) for ext in r['recovery'].get('policy_extensions',[])) for r in router.loaded.values())
            if not approved:
                first=rpc(ops.core,'deriveaddresses',[row['descriptor'],[0,0]])[0]
                for name in rpc(ops.core,'listwallets'):
                    info=rpc(ops.core,'getaddressinfo',[first],name)
                    if 'Wallaby setup ready:'+row['policy_hash'] in info.get('labels',[]) and descriptors({'wallet_name':'output','descriptors':[{'desc':row['descriptor']}]})<=descriptors(rpc(ops.core,'listdescriptors',[False],name)):approved=True;break
        if not approved:raise ValueError('The output vault policy has not been independently approved on this Agent.')
        d=Descriptor.from_string(row['descriptor']).derive(row['index']);address=d.script_pubkey().address(NETWORKS[p['chain']]);script=d.script_pubkey().data.hex()
        if address!=row['address'] or rpc(ops.core,'deriveaddresses',[row['descriptor'],[row['index'],row['index']]])!=[address]:raise ValueError('Vault output address/index differs from the approved public policy.')
        matches=[o for o in review['outputs'] if o['script']==script and o['sats']==row['amount_sats'] and o['n'] not in used]
        if len(matches)!=1:raise ValueError('A bound vault output script or amount was changed, removed or duplicated.')
        out=matches[0];used.add(out['n']);parsed=restricted(row['descriptor']);out['vault_policy']={k:parsed[k] for k in ('height','threshold','total')}|{'policy_hash':row['policy_hash'],'index':row['index']}
        out.setdefault('traits',{}).update(vault=True,multisig=parsed['threshold']>1)
