"""Locally verified address archiving and explicitly authorised local retirement."""
import copy,time,re
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc,sats
from wallet_labels import apply_labels
from vendor.embit.descriptor.checksum import checksum

ARCHIVE='Wallaby Extinct'
class MissingHistory(ValueError):pass

def validate(p):
    fields={'kind','version','request_id','wallet','public_wallet','archive_label','require_zero_balance','delete_wallet'}
    if p.get('version')==2:fields.update(('nonce','delete_wallets'))
    if set(p)!=fields or p['kind']!='wallet_retire' or (p['version'],p['delete_wallet']) not in ((1,False),(2,True)) or type(p['version']) is not int or type(p['delete_wallet']) is not bool or p['require_zero_balance'] is not True:raise ValueError('Invalid wallet retirement proposal.')
    if p['version']==2 and (not isinstance(p['nonce'],str) or not re.fullmatch('[0-9a-f]{64}',p['nonce'])):raise ValueError('Invalid retirement nonce.')
    if p['version']==2:
        targets=p['delete_wallets']
        if not isinstance(targets,list) or not 1<=len(targets)<=128:raise ValueError('Invalid local retirement target list.')
        names=set()
        for target in targets:
            if not isinstance(target,dict) or set(target)!={'wallet','public_wallet','private_keys_enabled'} or type(target['private_keys_enabled']) is not bool:raise ValueError('Invalid retirement target.')
            name=target['wallet']
            if not isinstance(name,str) or not 1<=len(name)<=200 or name in names or name in ('.','..',ARCHIVE) or any(ord(c)<32 for c in name) or '/' in name or '\\' in name:raise ValueError('Invalid or duplicate local retirement wallet.')
            names.add(name);descriptors(target['public_wallet'])
        if p['wallet'] not in names:raise ValueError('The source wallet is absent from the retirement group.')
    if p['wallet']==ARCHIVE:raise ValueError('The historical archive cannot retire itself.')
    descriptors(p['public_wallet'])
    for field in ('wallet','archive_label'):
        if not isinstance(p[field],str) or not 1<=len(p[field])<=200 or any(ord(c)<32 for c in p[field]) or '|' in p[field]:raise ValueError('Invalid retirement name or label.')
    if p['request_id']!=digest({k:v for k,v in p.items() if k!='request_id'}):raise ValueError('Retirement proposal hash differs.')
    return p

def inventory(core,store,p):
    validate(p);name=p['wallet'];chain=rpc(core,'getblockchaininfo');info=rpc(core,'getwalletinfo',[],name)
    if chain.get('initialblockdownload') or chain.get('blocks')!=chain.get('headers') or info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('Complete local wallet history is required. Finish node download and rescan first.')
    from wallet_setup_signing import signers_for_policy
    if (p['version']==1 and not info.get('private_keys_enabled') and not signers_for_policy(core,p['public_wallet'])) or descriptors(rpc(core,'listdescriptors',[False],name))!=descriptors(p['public_wallet']):raise ValueError('The selected local wallet policy has no matching private signer or differs from the proposed public policy.')
    if chain.get('pruned') and chain.get('pruneheight',0):
        floor=rpc(core,'getblockheader',[rpc(core,'getblockhash',[chain['pruneheight']])])['time'];coverage=store.read().get('history_coverage',{}).get(name,{})
        if info.get('birthtime',0)-7200<floor and coverage.get('identity')!=digest(sorted(descriptors(p['public_wallet']))):raise MissingHistory('This pruned node cannot establish complete address history from retained blocks. Locally recover wallet history with pruning unchanged before retiring it.')
    def zero(wallet):
        balances=rpc(core,'getbalances',[],wallet)
        groups=[balances[key] for key in ('mine','watchonly') if key in balances]
        if not groups or any(not isinstance(group,dict) or not {'trusted','untrusted_pending','immature'}<=set(group) for group in groups):raise ValueError('Core returned incomplete balance evidence; retirement is blocked.')
        if any(sats(value)!=0 for group in groups for value in group.values()) or rpc(core,'listlockunspent',[],wallet):raise ValueError('Wallet or vault contains funds, pending movements or locked outputs. Retirement requires a fully empty wallet.')
    zero(name)
    from wallet_setup_signing import monitors_for_key
    monitors=monitors_for_key(core,name)
    for monitor in monitors:zero(monitor)
    for record in store.read()['vaults'].values():
        if record.get('owner_wallet')==name or record.get('owner')==name:
            monitor=record.get('monitor_wallet')
            if not monitor or monitor not in rpc(core,'listwallets'):raise ValueError('Load the associated vault monitor and verify its history before retiring.')
            zero(monitor);monitors.append(monitor)
    local_wallets=[name];retained_signers=[]
    if p['delete_wallet']:
        wanted=descriptors(p['public_wallet'])
        for candidate in rpc(core,'listwallets'):
            if candidate!=ARCHIVE and descriptors(rpc(core,'listdescriptors',[False],candidate))==wanted:local_wallets.append(candidate)
        # A shared monitor's dedicated private accounts are part of this local
        # retirement. Keys reused by a different policy must remain intact.
        for signer in signers_for_policy(core,p['public_wallet']):
            associated=monitors_for_key(core,signer)
            if any(descriptors(rpc(core,'listdescriptors',[False],m))!=wanted for m in associated):retained_signers.append(signer)
            else:local_wallets.append(signer)
        local_wallets=sorted(set(local_wallets)|set(monitors))
        requested={item['wallet']:item for item in p['delete_wallets']}
        if set(requested)!=set(local_wallets):raise ValueError('The retirement target list differs from independently identified local copies, monitors or dedicated signing accounts. Refresh the Dashboard request; no wallet was deleted.')
        for candidate in local_wallets:
            local_info=rpc(core,'getwalletinfo',[],candidate)
            if local_info.get('private_keys_enabled') is not requested[candidate]['private_keys_enabled'] or descriptors(rpc(core,'listdescriptors',[False],candidate))!=descriptors(requested[candidate]['public_wallet']):raise ValueError('A retirement target policy or private-key status differs from local Core.')
            zero(candidate)
            other=rpc(core,'getwalletinfo',[],candidate)
            if other.get('scanning') or other.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('Every local wallet copy must have complete history before retirement.')
    addresses={};transactions={}
    for wallet in sorted(set([name,*monitors,*local_wallets])):
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
                        previous=addresses.get(address,{})
                        previous_loss=previous.get('label','') if ' | LOST:' in previous.get('label','') else None
                        if previous_loss and lost and previous_loss!=lost[0]:raise ValueError('Conflicting loss metadata between local wallet copies requires reconciliation.')
                        addresses[address]={'address':address,'label':lost[0] if lost else previous_loss or p['archive_label'],'is_change':False}
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
    deletion=None
    if p['delete_wallet']:
        from wallet_deletion import target
        deletion=[{'wallet':wallet,'target':target(core,wallet)} for wallet in local_wallets]
    return {'delete_wallet':p['delete_wallet'],'deletion':deletion,'local_wallets':local_wallets,'retained_signers':retained_signers,'watch_only':not info.get('private_keys_enabled'),'wallet':name,'archive':ARCHIVE,'public_identity':digest(sorted(descriptors(p['public_wallet']))),'addresses':sorted(addresses.values(),key=lambda x:x['address']),'transactions':len({txid for wallet,txid in transactions}),'blocks':chain['blocks'],'tip':chain['bestblockhash'],'private_wallet_retained':not p['delete_wallet'],'creates_loss_declaration':False}

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
        if (p['version']==1 and not private and not signers_for_policy(self.core,raw)) or descriptors(raw)!=descriptors(p['public_wallet']):raise ValueError('Local signer/policy differs; no recovery job created.')
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
            # Recheck every safety condition after the possibly long archive rescan.
            # The block tip may advance, but wallet history/addresses/policy may not.
            fresh=inventory(self.core,self.store,row['proposal'])
            for field in ('addresses','transactions','public_identity','deletion','local_wallets','retained_signers'):
                if fresh[field]!=facts[field]:raise ValueError('Wallet changed during archiving. No deletion was attempted; review a fresh request.')
            deleted=False;deleted_wallets=[]
            if facts['delete_wallet']:
                from wallet_deletion import delete
                # All paths/policies/zero balances were reviewed together. Unload
                # the whole approved local group before deleting the first file.
                for item in facts['deletion']:
                    rpc(self.core,'unloadwallet',{'wallet_name':item['wallet'],'load_on_startup':False})
                if set(facts['local_wallets'])&set(rpc(self.core,'listwallets')):raise ValueError('Core did not confirm every wallet unload; no deletion attempted.')
                for item in facts['deletion']:
                    if delete(item['target']).get('deleted') is not True:raise ValueError('Local wallet deletion was not confirmed.')
                    deleted_wallets.append(item['wallet'])
                deleted=True
            result={'request_hash':key,'status':'complete'}
            if row['proposal']['version']==2:result.update(archive_verified=True,history_verified=True,zero_balance_verified=True,wallet_deleted=deleted,archive_wallet=ARCHIVE,address_count=len(facts['addresses']),deleted_wallets=deleted_wallets)
            self.store.queue('wallet_retirement_result',result)
            with self.store.edit() as s:s['completed'][key]={'kind':'wallet_retire','at':time.time()};s['pending'].pop(key,None)
            return {'message':'Used public addresses and labels verified in Wallaby Extinct. '+('This node’s approved local wallet copies were unloaded, removed from startup and deleted.' if deleted else 'The original wallet remains loaded and unchanged (legacy archive-only request).')}
        except Exception:
            self.store.queue('wallet_retirement_result',{'request_hash':key,'status':'error','message':'Archive operation incomplete or uncertain. Inspect Core locally before a fresh request.'});raise
