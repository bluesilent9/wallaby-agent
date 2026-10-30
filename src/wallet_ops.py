"""Local-only wallet operations. Dashboard RPC cannot enter this module.

Core holds all private keys. Reviews are generated from actual transactions,
local previous transactions and wallet descriptors, never remote display labels.
"""
import copy, hashlib, json, re, threading, time, uuid
from decimal import Decimal
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from vendor.embit.transaction import Transaction
from vendor.embit import script
from vendor.embit.networks import NETWORKS
from approval_store import Store,digest
from vault_policy import public_vault,psbt_text

MAX_SATS=21000000*100000000

def sats(value):
    amount=Decimal(str(value))*100000000
    if not amount.is_finite() or amount!=amount.to_integral_value() or not 0<=amount<=MAX_SATS:raise ValueError('Invalid Bitcoin amount.')
    return int(amount)

def assess_fee(inputs,outputs,fee,vsize):
    if type(vsize) is not int or vsize<=0:raise ValueError('Core did not provide a usable transaction size.')
    owners={name for row in inputs for name in row['wallets']}
    payments=sum(int(row['sats']) for row in outputs if not (row['change'] and owners.intersection(row['wallets'])))
    basis=payments or sum(int(row['sats']) for row in outputs)
    share=fee>0 and (basis==0 or fee*10>=basis);rate=fee>=100*vsize
    return {'requires_ack':share or rate,'high_share':share,'high_rate':rate,'basis_sats':str(basis),'basis':'locally identified non-change outputs' if payments else 'all returned output value (no non-change payment identified)','unsigned_vsize':vsize,'rate_upper_bound':format(Decimal(fee)/vsize,'.2f'),'notice':'The rate uses the unsigned transaction size as a conservative upper bound; signatures may lower the actual rate. Change is excluded only when Core marks it as change for a locally identified input owner.'}

def rpc(core,method,params=None,wallet=None,timeout=30):
    r=core.call('local-'+uuid.uuid4().hex,method,params or [],wallet,timeout=timeout)
    if 'error' in r:
        code=r['error'].get('code') if isinstance(r['error'],dict) else None
        raise ValueError(f'Bitcoin Core rejected {method} (code {code}). Check wallet readiness, encryption and node synchronisation.')
    return r['result']

def network(core):return rpc(core,'getblockchaininfo')['chain']

def watch_name(v):return 'Wallaby Vault '+digest(v)[:16]

def verify_vault(core,v):
    public_vault(v)
    if network(core)!=v['chain']:raise ValueError('Vault network differs from the local node.')
    descinfo=rpc(core,'getdescriptorinfo',[v['descriptor']]);addresses=rpc(core,'deriveaddresses',[descinfo['descriptor']])
    if addresses!=[v['address']]:raise ValueError('Core derived a different vault address.')
    body=v['descriptor'].split('#')[0];key=re.search(r'pk\(([0-9a-f]+)\)',body)[1];owners=[]
    for name in rpc(core,'listwallets'):
        try:
            rows=rpc(core,'listdescriptors',{'private':False},name)['descriptors']
            if any(r['desc']==v['source']['descriptor'] for r in rows):
                original=Descriptor.from_string(v['source']['descriptor'].split('#')[0]);d=original.derive(v['source']['index']) if original.is_wildcard else original
                if d.key.get_public_key().sec().hex()==key:owners.append(name)
        except ValueError:continue
    return {'address':addresses[0],'height':v['height'],'descriptor':descinfo['descriptor'],'local_key_wallets':owners,'private_key_wallets':[name for name in owners if rpc(core,'getwalletinfo',[],name).get('private_keys_enabled')],'policy':'Signature by the displayed public key AND block-height CLTV; no bypass path.'}

def install_vault(core,v,store,owner=None):
    proof=verify_vault(core,v);name=watch_name(v)
    if name not in rpc(core,'listwallets'):
        if any(r['name']==name for r in rpc(core,'listwalletdir')['wallets']):rpc(core,'loadwallet',{'filename':name,'load_on_startup':True})
        else:rpc(core,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
    info=rpc(core,'getwalletinfo',[],name)
    if info.get('private_keys_enabled') or not info.get('descriptors'):raise ValueError('Vault monitor must be a private-key-disabled descriptor wallet.')
    # Historical imports must not claim successful balance recovery on a pruned chain.
    chain=rpc(core,'getblockchaininfo')
    if chain.get('pruned') and chain.get('pruneheight',0)>0 and v['timestamp']<rpc(core,'getblockheader',[rpc(core,'getblockhash',[chain['pruneheight']])])['time']:
        raise ValueError('Vault history predates available pruned blocks. Restore the required history before authorising this import.')
    original=Descriptor.from_string(v['source']['descriptor'].split('#')[0]);derived=original.derive(v['source']['index']) if original.is_wildcard else original
    annotated=v['descriptor'].split('#')[0].replace(derived.key.get_public_key().sec().hex(),str(derived.key))
    annotated=annotated+'#'+checksum(annotated)
    rows=rpc(core,'importdescriptors',{'requests':[{'desc':annotated,'timestamp':v['timestamp'],'active':False,'label':'Wallaby Vault'}]},name,timeout=3600)
    if not rows or not all(r.get('success') for r in rows):raise ValueError('Core did not import the vault descriptor. No synchronisation success was recorded.')
    addr=rpc(core,'getaddressinfo',[v['address']],name)
    if not addr.get('iswatchonly',False) and not addr.get('ismine',False):raise ValueError('Core did not recognise the imported vault address.')
    with store.edit() as s:s['vaults'][digest(v)]={'public':v,'owner_wallet':owner,'monitor_wallet':name,'verified':proof,'imported':time.time()}
    return {**proof,'monitor_wallet':name,'viewable':True,'key_control':bool(proof['private_key_wallets'])}

class WalletOps:
    def __init__(self,core,store=None):
        self.core=core;self.store=store or Store();self.lock=threading.Lock();self.prepared={}
    def review(self,psbt,wallet,chain,require_owned=True):
        psbt_text(psbt)
        if network(self.core)!=chain:raise ValueError('PSBT network does not match this node.')
        info=rpc(self.core,'getwalletinfo',[],wallet) if require_owned else {}
        if require_owned and not info.get('private_keys_enabled'):raise ValueError('Signing requires a local private-key-enabled wallet.')
        decoded=rpc(self.core,'decodepsbt',[psbt]);tx=decoded['tx'];scopes=decoded.get('inputs',[])
        if not tx.get('vin') or len(tx['vin'])!=len(scopes) or len(scopes)>1000 or len(tx.get('vout',[]))>1000:raise ValueError('Invalid or oversized transaction.')
        names=rpc(self.core,'listwallets');inputs=[];outputs=[];total=0;own=False
        local_vaults=self.store.read()['vaults']
        from wallet_setup_signing import inventory
        shared_inventory=inventory(self.core)
        def owners(address):
            result=[];change=False
            if address:
                for name in names:
                    a=rpc(self.core,'getaddressinfo',[address],name)
                    if a.get('ismine') or a.get('iswatchonly'):
                        result.append(name);change=change or a.get('ischange',False)
            for record in local_vaults.values():
                v=record['public']
                if v['address']==address:
                    for name in verify_vault(self.core,v)['local_key_wallets']:
                        if name not in result:result.append(name)
            from wallet_setup_signing import matches
            for record in matches(self.core,self.store,address,shared_inventory):
                for name in record['wallets']:
                    if name not in result:result.append(name)
            return result,change
        for vin,scope in zip(tx['vin'],scopes):
            if scope.get('sighash','ALL') not in ('ALL','DEFAULT'):raise ValueError('Only signatures committing to the entire transaction are accepted.')
            # Fetch the full previous transaction locally. Never trust PSBT input values.
            try:previous=rpc(self.core,'getrawtransaction',[vin['txid'],True])
            except ValueError:
                previous=None
                for name in ([wallet] if wallet is not None else [])+[n for n in names if n!=wallet]:
                    try:previous=rpc(self.core,'decoderawtransaction',[rpc(self.core,'gettransaction',[vin['txid'],True],name)['hex']]);break
                    except ValueError:continue
                if previous is None:raise ValueError('The local node cannot verify an input’s full previous transaction. Load its history before signing.')
            if previous.get('txid')!=vin['txid'] or type(vin['vout']) is not int or not 0<=vin['vout']<len(previous['vout']):raise ValueError('Input outpoint failed verification.')
            prev=previous['vout'][vin['vout']];value=sats(prev['value']);spk=prev['scriptPubKey'];address=spk.get('address','');local,change=owners(address)
            if wallet in local:own=True
            from wallet_setup_signing import matches
            for policy in matches(self.core,self.store,address,shared_inventory):
                if not policy['setup_ready']:raise ValueError('This wallet setup lacks independently verified policy or physical-backup completion. Dashboard cannot declare it ready without the signed proofs.')
                if policy['height'] is not None and (tx['locktime']>=500000000 or tx['locktime']<policy['height'] or vin['sequence']==0xffffffff):raise ValueError('The final transaction bypasses or changes an approved mandatory vault height.')
            witness=scope.get('witness_utxo')
            if witness and (sats(witness['amount'])!=value or witness['scriptPubKey']['hex']!=spk['hex']):raise ValueError('PSBT witness input differs from the locally verified previous output.')
            nonwitness=scope.get('non_witness_utxo')
            if nonwitness and nonwitness.get('txid')!=vin['txid']:raise ValueError('PSBT previous transaction does not match its input.')
            total+=value;inputs.append({'txid':vin['txid'],'vout':vin['vout'],'sats':str(value),'address':address,'wallets':local,'change':change,'sequence':vin['sequence']})
        for row in tx['vout']:
            spk=row['scriptPubKey'];address=spk.get('address','');local,change=owners(address);amount=sats(row['value'])
            outputs.append({'n':row['n'],'sats':str(amount),'address':address or 'Script '+spk['hex'],'wallets':local,'change':change,'script':spk['hex']})
        fee=total-sum(int(o['sats']) for o in outputs)
        if (require_owned and not own) or fee<0 or fee>MAX_SATS:raise ValueError('No locally controlled signing input, or invalid transaction fee.')
        if 'fee' in decoded and sats(decoded['fee'])!=fee:raise ValueError('PSBT fee differs from the independently verified fee.')
        # The transaction bytes, not remote labels, bind all amounts, outputs, sequences and locktime.
        fee_review=assess_fee(inputs,outputs,fee,tx.get('vsize'))
        return {'fee_review':fee_review,'wallet':wallet,'chain':chain,'inputs':inputs,'outputs':outputs,'fee_sats':str(fee),'locktime':tx['locktime'],'tx_hash':digest(tx),'psbt_hash':hashlib.sha256(psbt.encode()).hexdigest()}
    def prepare_request(self,key):
        row=self.store.read()['pending'][key]
        if row['state']!='pending':raise ValueError('This request was already attempted; reconcile its outcome before proceeding.')
        p=row['proposal']
        if p['kind']=='vault_sync':return {'kind':'vault_sync','id':key,'vault':p['vault'],'proof':verify_vault(self.core,p['vault'])}
        if p['kind'] not in ('sign_psbt_partial','broadcast_transaction'):raise ValueError('This request requires the Synchronisation page or an updated Dashboard.')
        wallet=p.get('wallet');review=self.review(p['psbt'],wallet,p['chain'],require_owned=p['kind']=='sign_psbt_partial')
        from transaction_requests import intents
        intents(self,p,review)
        if p['kind']=='broadcast_transaction':
            final=rpc(self.core,'finalizepsbt',[p['psbt']])
            if not final.get('complete') or rpc(self.core,'decoderawtransaction',[final['hex']])['txid']!=p['txid']:raise ValueError('The completed PSBT does not match its requested transaction ID.')
        self.prepared[key]={**p,'wallet':wallet,'review':review,'created':time.time()}
        return {'kind':p['kind'],'id':key,'review':review}
    def approve_sync(self,key):
        with self.lock:
            with self.store.edit() as s:
                row=s['pending'][key]
                if row['state']!='pending' or row['proposal']['kind']!='vault_sync':raise ValueError('This sync request cannot be approved.')
                row['state']='attempted';v=copy.deepcopy(row['proposal']['vault'])
            proof=install_vault(self.core,v,self.store)
            with self.store.edit() as s:s['completed'][key]={'kind':'vault_sync','at':time.time()};s['pending'].pop(key,None)
            return proof
    def sign(self,key,password,action,fee_ack=False):
        if type(fee_ack) is not bool:raise ValueError('Invalid local fee acknowledgement.')
        if action not in ('broadcast','partial'):raise ValueError('Invalid signing action.')
        with self.lock:
            p=self.prepared.get(key)
            if not p or time.time()-p['created']>600:raise ValueError('Review expired. Recalculate or review again before signing.')
            if p['kind']=='sign_psbt_partial' and action!='partial':raise ValueError('Dashboard signing requests return signatures only; broadcasting requires a separate local approval.')
            if p['kind']=='broadcast_transaction' and action!='broadcast':raise ValueError('Review and authorise broadcast locally.')
            if p['kind'] not in ('sign_psbt_partial','broadcast_transaction'):raise ValueError('This retired local builder operation is unavailable.')
            current=self.review(p['psbt'],p['wallet'],p['chain'],require_owned=p['kind']!='broadcast_transaction')
            for i in current['inputs']:
                if rpc(self.core,'gettxout',[i['txid'],i['vout'],True]) is None:raise ValueError('A reviewed input is no longer unspent. Review a fresh transaction.')
            if current!=p['review']:raise ValueError('Transaction or local wallet interpretation changed. Review again.')
            if current['fee_review']['requires_ack'] and fee_ack is not True:raise ValueError('Review and explicitly acknowledge the unusually high total network fee on this Agent.')
            self.prepared.pop(key)
            from transaction_requests import intents
            intents(self,p,current)
            if p['kind']=='broadcast_transaction':
                with self.store.edit() as state:
                    if state['pending'][key]['state']!='pending':raise ValueError('Request was already attempted.')
                    state['pending'][key]['state']='attempted'
                if action!='broadcast':raise ValueError('Review and authorise broadcast locally.')
                final=rpc(self.core,'finalizepsbt',[p['psbt']])
                if not final.get('complete') or rpc(self.core,'decoderawtransaction',[final['hex']])['txid']!=p['txid']:raise ValueError('The completed transaction ID changed.')
                if not rpc(self.core,'testmempoolaccept',[[final['hex']]])[0].get('allowed'):raise ValueError('Core rejected the transaction; nothing was broadcast.')
                txid=rpc(self.core,'sendrawtransaction',[final['hex']]);result={'request_hash':key,'status':'broadcast','txid':txid}
                self.store.queue('broadcast_result',result)
                with self.store.edit() as state:state['completed'][key]={'kind':p['kind'],'at':time.time()};state['pending'].pop(key,None)
                return {'txid':txid,'message':'Locally authorised transaction broadcast.'}
            if p['kind']=='sign_psbt_partial':
                with self.store.edit() as state:
                    if state['pending'][key]['state']!='pending':raise ValueError('Request was already attempted.')
                    state['pending'][key]['state']='attempted'
            info={};sign_attempted=False
            try:
                info=rpc(self.core,'getwalletinfo',[],p['wallet'])
                if 'unlocked_until' in info:rpc(self.core,'walletpassphrase',[password,30],p['wallet'])
                signing_psbt=p['psbt']
                for record in self.store.read()['vaults'].values():
                    if record['public']['address'] in [i['address'] for i in current['inputs']]:
                        signing_psbt=rpc(self.core,'walletprocesspsbt',{'psbt':signing_psbt,'sign':False,'bip32derivs':True,'finalize':False},record['monitor_wallet'])['psbt']
                for record in self.store.read().get('approved_wallets',{}).values():
                    if p['wallet'] in record['signing_wallets'].values():signing_psbt=rpc(self.core,'walletprocesspsbt',{'psbt':signing_psbt,'sign':False,'bip32derivs':True,'finalize':False},record['monitor_wallet'])['psbt']
                from wallet_setup_signing import matches
                from wallet_setup_signing import inventory
                known_shared=inventory(self.core)
                monitors={record['monitor_wallet'] for vin in current['inputs'] for record in matches(self.core,self.store,vin['address'],known_shared) if p['wallet'] in record['wallets']}
                for name in sorted(monitors):signing_psbt=rpc(self.core,'walletprocesspsbt',{'psbt':signing_psbt,'sign':False,'bip32derivs':True,'finalize':False},name)['psbt']
                sign_attempted=True
                signed=rpc(self.core,'walletprocesspsbt',{'psbt':signing_psbt,'sign':True,'bip32derivs':True,'finalize':False},p['wallet'])
            except Exception:
                if p['kind']=='sign_psbt_partial' and not sign_attempted:
                    with self.store.edit() as s:s['pending'][key]['state']='pending'
                raise
            finally:
                password=None
                try:
                    if 'unlocked_until' in info:rpc(self.core,'walletlock',[],p['wallet'])
                except Exception:raise ValueError('Core wallet could not be relocked. Lock it in Core immediately; no transaction was broadcast.') from None
            signed_psbt=psbt_text(signed['psbt']);after=self.review(signed_psbt,p['wallet'],p['chain'])
            if after['tx_hash']!=current['tx_hash']:raise ValueError('Core changed the approved transaction; it was not broadcast.')
            if p['kind']=='sign_psbt_partial':
                self.store.queue('partial_sign_result',{'request_hash':key,'status':'signed','psbt':signed_psbt})
                with self.store.edit() as state:state['completed'][key]={'kind':p['kind'],'at':time.time()};state['pending'].pop(key,None)
                return {'queued':True,'message':'Approved signatures returned to Dashboard. No transaction was broadcast.'}
