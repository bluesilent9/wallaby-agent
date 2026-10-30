"""Locally verified public address archiving; never deletes a signing wallet."""
import copy,time
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc,sats
from wallet_labels import apply_labels
from vendor.embit.descriptor.checksum import checksum

ARCHIVE='Wallaby Extinct'
class MissingHistory(ValueError):pass

def validate(p):
    if set(p)!={'kind','version','request_id','wallet','public_wallet','archive_label','require_zero_balance','delete_wallet'} or p['kind']!='wallet_retire' or p['version']!=1 or p['require_zero_balance'] is not True or p['delete_wallet'] is not False:raise ValueError('Invalid wallet retirement proposal.')
    descriptors(p['public_wallet'])
    for field in ('wallet','archive_label'):
        if not isinstance(p[field],str) or not 1<=len(p[field])<=200 or any(ord(c)<32 for c in p[field]) or '|' in p[field]:raise ValueError('Invalid retirement name or label.')
    if p['request_id']!=digest({k:v for k,v in p.items() if k!='request_id'}):raise ValueError('Retirement proposal hash differs.')
    return p

def inventory(core,store,p):
    validate(p);name=p['wallet'];chain=rpc(core,'getblockchaininfo');info=rpc(core,'getwalletinfo',[],name)
    if chain.get('initialblockdownload') or chain.get('blocks')!=chain.get('headers') or info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('Complete local wallet history is required. Finish node download and rescan first.')
    from wallet_setup_signing import signers_for_policy
    if (not info.get('private_keys_enabled') and not signers_for_policy(core,p['public_wallet'])) or descriptors(rpc(core,'listdescriptors',[False],name))!=descriptors(p['public_wallet']):raise ValueError('The selected local wallet policy has no matching private signer or differs from the proposed public policy.')
    if chain.get('pruned') and chain.get('pruneheight',0):
        floor=rpc(core,'getblockheader',[rpc(core,'getblockhash',[chain['pruneheight']])])['time'];coverage=store.read().get('history_coverage',{}).get(name,{})
        if info.get('birthtime',0)-7200<floor and coverage.get('identity')!=digest(sorted(descriptors(p['public_wallet']))):raise MissingHistory('This pruned node cannot establish complete address history from retained blocks. Locally recover wallet history with pruning unchanged before retiring it.')
    def zero(wallet):
        balances=rpc(core,'getbalances',[],wallet)
        if any(sats(value)!=0 for group in balances.values() if isinstance(group,dict) for key,value in group.items() if key in ('trusted','untrusted_pending','immature','used')) or rpc(core,'listlockunspent',[],wallet):raise ValueError('Wallet or vault contains funds, pending movements or locked outputs. Retirement requires a fully empty wallet.')
    zero(name)
    from wallet_setup_signing import monitors_for_key
    monitors=monitors_for_key(core,name)
    for monitor in monitors:zero(monitor)
    for record in store.read()['vaults'].values():
        if record.get('owner_wallet')==name or record.get('owner')==name:
            monitor=record.get('monitor_wallet')
            if not monitor or monitor not in rpc(core,'listwallets'):raise ValueError('Load the associated vault monitor and verify its history before retiring.')
            zero(monitor);monitors.append(monitor)
    addresses={};transactions={}
    for wallet in [name,*monitors]:
        start=0
        while True:
            rows=rpc(core,'listtransactions',['*',1000,start,True],wallet);start+=len(rows)
            for row in rows:
                if row.get('confirmations',0)<=0:raise ValueError('Pending, conflicted or abandoned movements need local review before retirement.')
                txid=row['txid']
                if (wallet,txid) in transactions:continue
                tx=rpc(core,'gettransaction',[txid,True],wallet)
                if tx.get('confirmations',0)<=0 or not tx.get('blockhash'):raise ValueError('A wallet transaction is not confirmed in the local chain.')
                if rpc(core,'getblockheader',[tx['blockhash']]).get('confirmations',0)<=0:raise ValueError('Wallet transaction is outside the active chain.')
                transactions[(wallet,txid)]=tx
                decoded=rpc(core,'decoderawtransaction',[tx['hex']])
                for output in decoded['vout']:
                    address=output['scriptPubKey'].get('address')
                    if not address:continue
                    own=rpc(core,'getaddressinfo',[address],wallet)
                    if own.get('ismine') or own.get('iswatchonly'):
                        old=own.get('labels',[]);lost=[x for x in old if ' | LOST:' in x]
                        if len(lost)>1:raise ValueError('Ambiguous existing loss metadata.')
                        addresses[address]={'address':address,'label':lost[0] if lost else p['archive_label'],'is_change':False}
            if len(rows)<1000:break
            if start>100000:raise ValueError('Wallet exceeds the safe automatic history review size.')
    loaded=rpc(core,'listwallets')
    if ARCHIVE not in loaded and any(row['name']==ARCHIVE for row in rpc(core,'listwalletdir')['wallets']):raise ValueError('Load the existing historical archive locally before review so its exact LOST labels can be preserved.')
    if ARCHIVE in loaded:
        if rpc(core,'getwalletinfo',[],ARCHIVE)['private_keys_enabled']:raise ValueError('Historical archive must have private keys disabled.')
        for address,item in addresses.items():
            labels=rpc(core,'getaddressinfo',[address],ARCHIVE).get('labels',[])
            lost=[label for label in labels if ' | LOST:' in label]
            if len(lost)>1 or lost and ' | LOST:' in item['label'] and item['label']!=lost[0]:raise ValueError('Conflicting existing loss metadata requires local reconciliation.')
            if lost:item['label']=lost[0]
    if not addresses:raise ValueError('This wallet has no confirmed used addresses to archive.')
    return {'wallet':name,'archive':ARCHIVE,'public_identity':digest(sorted(descriptors(p['public_wallet']))),'addresses':sorted(addresses.values(),key=lambda x:x['address']),'transactions':len({txid for wallet,txid in transactions}),'blocks':chain['blocks'],'tip':chain['bestblockhash'],'private_wallet_retained':True,'creates_loss_declaration':False}

class Retirement:
    def __init__(self,core,store):self.core=core;self.store=store;self.reviews={}
    def review(self,key):
        p=self.store.read()['pending'][key]['proposal']
        try:facts=inventory(self.core,self.store,p)
        except MissingHistory as error:return {'kind':'wallet_retire','id':key,'retirement':{'wallet':p['wallet'],'history_required':True,'message':str(error)}}
        self.reviews[key]=(facts,time.time());return {'kind':'wallet_retire','id':key,'retirement':facts}
    def prepare_history(self,key):
        p=validate(self.store.read()['pending'][key]['proposal']);name=p['wallet'];raw=rpc(self.core,'listdescriptors',[False],name)
        from wallet_setup_signing import signers_for_policy
        private=bool(rpc(self.core,'getwalletinfo',[],name).get('private_keys_enabled'))
        if (not private and not signers_for_policy(self.core,raw)) or descriptors(raw)!=descriptors(p['public_wallet']):raise ValueError('Local signer/policy differs; no recovery job created.')
        from wallet_recovery import require
        from wallet_labels import read_labels
        details={'public_wallet':raw,'chain':rpc(self.core,'getblockchaininfo')['chain'],'funded_outputs':[],'address_labels':read_labels(self.core,name,raw,[]),'vaults':[r['public'] for r in self.store.read()['vaults'].values() if r.get('owner_wallet')==name]}
        history_key=digest({'local_retirement_history':key});require(self.store,history_key,name,details)
        with self.store.edit() as saved:saved['history_jobs'][history_key].update(expected_private_keys=private,local_only=True)
        return {'message':'Local history requirement recorded. On Synchronisation, review and authorise the This Node recovery plan. The original pruning settings stay unchanged. Retirement still needs a separate review and approval afterwards.'}
    def approve(self,key):
        row=self.store.read()['pending'][key];old=self.reviews.get(key)
        if row['state']!='pending' or not old or time.time()-old[1]>600:raise ValueError('Review the retirement request again.')
        facts=inventory(self.core,self.store,row['proposal'])
        if facts!=old[0]:raise ValueError('Local wallet history changed. Review it again.')
        # An uncertain import is not automatically replayed, even after a restart.
        with self.store.edit() as s:s['pending'][key]['state']='attempted'
        try:
            if ARCHIVE not in rpc(self.core,'listwallets'):
                if any(w['name']==ARCHIVE for w in rpc(self.core,'listwalletdir')['wallets']):rpc(self.core,'loadwallet',{'filename':ARCHIVE,'load_on_startup':True})
                else:rpc(self.core,'createwallet',{'wallet_name':ARCHIVE,'disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
            if rpc(self.core,'getwalletinfo',[],ARCHIVE)['private_keys_enabled']:raise ValueError('Historical archive must have private keys disabled.')
            requests=[]
            for item in facts['addresses']:
                desc='addr('+item['address']+')';requests.append({'desc':desc+'#'+checksum(desc),'timestamp':0,'label':item['label']})
            result=rpc(self.core,'importdescriptors',{'requests':requests},ARCHIVE,timeout=86400)
            if not result or not all(x.get('success') for x in result):raise ValueError('Core did not complete every historical address import. Inspect the archive; no operation was replayed.')
            apply_labels(self.core,ARCHIVE,facts['addresses'],write=False)
            self.store.queue('wallet_retirement_result',{'request_hash':key,'status':'complete'})
            with self.store.edit() as s:s['completed'][key]={'kind':'wallet_retire','at':time.time()};s['pending'].pop(key,None)
            return {'message':'Used public addresses and labels archived. The original private wallet remains loaded and unchanged.'}
        except Exception:
            self.store.queue('wallet_retirement_result',{'request_hash':key,'status':'error','message':'Archive operation incomplete or uncertain. Inspect Core locally before a fresh request.'});raise
