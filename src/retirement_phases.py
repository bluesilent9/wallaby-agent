"""Public preservation and separate, locally authorised zero-funds deletion."""
import copy,re,time,json
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc
from wallet_labels import address_only,fixed_address
from vendor.embit.script import address_to_scriptpubkey
from vendor.embit.descriptor.checksum import checksum
HEX=re.compile('[0-9a-f]{64}')

def name(value):
    if not isinstance(value,str) or not 1<=len(value)<=200 or value in ('.','..') or any(ord(c)<32 for c in value) or '/' in value or '\\' in value:raise ValueError('Invalid local retirement wallet name.')
    return value

def manifest(value):
    if not isinstance(value,dict) or set(value)!={'addresses','transactions'} or len(json.dumps(value,sort_keys=True,separators=(',',':')).encode())>512*1024:raise ValueError('Invalid retirement history manifest.')
    for group,fields,key in (('addresses',{'address','label'},'address'),('transactions',{'txid','blockhash'},'txid')):
        rows=value[group]
        if not isinstance(rows,list) or not 1<=len(rows)<=10000:raise ValueError('Incomplete or oversized retirement history.')
        seen=set()
        for row in rows:
            if not isinstance(row,dict) or set(row)!=fields or not isinstance(row[key],str) or row[key] in seen:raise ValueError('Duplicate or invalid retirement history record.')
            seen.add(row[key])
            if group=='addresses':
                address_to_scriptpubkey(row['address']);label=row['label']
                if not isinstance(label,str) or not 1<=len(label)<=256 or any(ord(c)<32 for c in label) or '|' in label and not re.fullmatch(r'[^|]+\s+\|\s+LOST:\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} UTC',label):raise ValueError('Invalid retirement history label.')
            elif any(not isinstance(row[f],str) or not HEX.fullmatch(row[f]) for f in fields):raise ValueError('Invalid retirement transaction identity.')
    return value

def validate(p):
    from agent_rpc import PRIVATE
    if PRIVATE.search(__import__('json').dumps(p)):raise ValueError('Private material is forbidden in extinction proposals.')
    fields={'kind','version','operation_id','phase','wallet','public_wallet','archive_label','require_zero_balance','delete_wallet','nonce','manifest','manifest_hash','delete_wallets','preservation','request_id'}
    if not isinstance(p,dict) or set(p)!=fields or p['kind']!='wallet_retire' or type(p['version']) is not int or p['version']!=3 or p['phase'] not in ('preserve','delete') or p['require_zero_balance'] is not True or p['delete_wallet'] is not (p['phase']=='delete'):raise ValueError('Invalid phased retirement proposal.')
    for f in ('operation_id','nonce','manifest_hash','request_id'):
        if not isinstance(p[f],str) or not HEX.fullmatch(p[f]):raise ValueError('Invalid retirement identity.')
    name(p['wallet']);descriptors(p['public_wallet']);manifest(p['manifest'])
    label=p['archive_label']
    if not isinstance(label,str) or not 1<=len(label)<=256 or any(ord(c)<32 for c in label) or '|' in label:raise ValueError('Invalid retirement label.')
    if p['manifest_hash']!=digest(p['manifest']) or p['request_id']!=digest({k:v for k,v in p.items() if k!='request_id'}):raise ValueError('Retirement proposal or history hash changed.')
    if p['phase']=='preserve':
        if p['delete_wallets']!=[] or p['preservation'] is not None:raise ValueError('Preservation cannot delete wallets.')
    else:
        targets=p['delete_wallets']
        if not isinstance(targets,list) or not 1<=len(targets)<=128:raise ValueError('Invalid retirement targets.')
        names=set()
        for row in targets:
            if not isinstance(row,dict) or set(row)!={'wallet','public_wallet','private_keys_enabled'} or type(row['private_keys_enabled']) is not bool:raise ValueError('Invalid retirement target.')
            n=name(row['wallet']);descriptors(row['public_wallet'])
            if n in names or n in ('Wallaby Extinct','Extinct'):raise ValueError('Duplicate or historical archive deletion target.')
            names.add(n)
        if p['wallet'] not in names:raise ValueError('Missing local retirement source.')
        proof=p['preservation']
        if not isinstance(proof,dict) or set(proof)!={'node_id','request_hash','archive_wallet','manifest_hash','verified_utc','receipt'} or proof['manifest_hash']!=p['manifest_hash'] or not isinstance(proof['node_id'],str) or not re.fullmatch('[0-9a-f]{32}',proof['node_id']) or not HEX.fullmatch(str(proof['request_hash'])):raise ValueError('Deletion requires exact signed preservation evidence.')
        name(proof['archive_wallet'])
        if not isinstance(proof['verified_utc'],str) or len(proof['verified_utc'])>40:raise ValueError('Invalid preservation timestamp.')
        envelope=proof['receipt']
        expected={'version':1,'kind':'wallet_retirement_preservation','request_hash':proof['request_hash'],'operation_id':p['operation_id'],'manifest_hash':p['manifest_hash'],'archive_wallet':proof['archive_wallet'],'address_count':len(p['manifest']['addresses']),'wallet_deleted':False}
        if not isinstance(envelope,dict) or set(envelope)!={'message','public_key','signature'} or envelope['message']!=expected:raise ValueError('Preservation receipt is bound to different retirement data.')
    return p

def result(p,status,**extra):return {'request_hash':digest(p),'status':status,'phase':p['phase'],'manifest_hash':p['manifest_hash'],**extra}

def existing_archive(core,wallet):
    if wallet not in rpc(core,'listwallets'):raise ValueError('Load the existing Extinct wallet locally. This request cannot create an Extinct wallet.')
    info=rpc(core,'getwalletinfo',[],wallet);raw=rpc(core,'listdescriptors',[False],wallet)
    if info.get('private_keys_enabled') is not False or info.get('scanning') or not address_only(raw):raise ValueError('The existing Extinct wallet must be a non-scanning address-only watch wallet.')
    return raw

def local_archives(core):
    """Same address-only watch-wallet criteria used by Core public inventory."""
    result=[]
    for wallet in rpc(core,'listwallets'):
        raw=rpc(core,'listdescriptors',[False],wallet)
        if not address_only(raw):continue
        info=rpc(core,'getwalletinfo',[],wallet)
        if info.get('private_keys_enabled') is False and not info.get('scanning'):result.append(wallet)
    return sorted(result)

def internal(p,wallet,targets):
    q={'kind':'wallet_retire','version':2,'nonce':p['nonce'],'wallet':wallet,'public_wallet':p['public_wallet'],'archive_label':p['archive_label'],'require_zero_balance':True,'delete_wallet':True,'delete_wallets':targets};q['request_id']=digest(q);return q

def local_facts(core,store,p,collect=False):
    from wallet_retirement import inventory
    wallet=p['wallet']
    if collect:
        matches=[]
        for n in rpc(core,'listwallets'):
            if n==p['wallet']:continue
            raw=rpc(core,'listdescriptors',[False],n)
            if raw.get('descriptors') and descriptors(raw)==descriptors(p['public_wallet']):matches.append(n)
        if not matches:return None
        wallet=sorted(matches)[0];targets=[{'wallet':wallet,'public_wallet':rpc(core,'listdescriptors',[False],wallet),'private_keys_enabled':rpc(core,'getwalletinfo',[],wallet)['private_keys_enabled']}]
    else:targets=p['delete_wallets']
    facts=inventory(core,store,internal(p,wallet,targets),collect_only=collect,confirmed_manifest=p['manifest'])
    offered={r['address']:r['label'] for r in p['manifest']['addresses']}
    if any(offered.get(r['address'])!=r['label'] for r in facts['addresses']) or any(r not in p['manifest']['transactions'] for r in facts['transaction_records']):raise ValueError('Preserved manifest omits or changes independently verified local history. No deletion authorised.')
    return facts

def check_chain(core,p):
    chain=rpc(core,'getblockchaininfo')
    if chain.get('initialblockdownload') or chain.get('blocks')!=chain.get('headers'):raise ValueError('Finish local blockchain synchronisation first.')
    for record in p['manifest']['transactions']:
        if rpc(core,'getblockheader',[record['blockhash']]).get('confirmations',0)<=0:raise ValueError('Retirement history is outside the active local chain.')
    return chain

def verify_public(core,p,verify_transactions=True,transaction_wallet=None):
    """Prove membership from public descriptors and chain records, never labels alone."""
    from wallet_retirement import MissingHistory
    allowed=set()
    for row in p['public_wallet']['descriptors']:
        desc=row['desc'];fixed=fixed_address(desc)
        if fixed:allowed.add(fixed);continue
        args=[desc]
        if '*' in desc:
            limits=row.get('range',[0,999]);limits=[0,limits] if type(limits) is int else limits
            if len(limits)!=2 or any(type(x) is not int for x in limits) or not 0<=limits[0]<=limits[1]<=10000:raise ValueError('Public policy derivation range is unsafe.')
            args.append(limits)
        allowed.update(rpc(core,'deriveaddresses',args))
    addresses={r['address'] for r in p['manifest']['addresses']}
    if not addresses<=allowed:raise ValueError('An archived address does not belong to the proposed public wallet range.')
    if not verify_transactions:return
    txs=[];outpoints=set();found=set()
    for record in p['manifest']['transactions']:
        try:
            if transaction_wallet is None:tx=rpc(core,'getrawtransaction',[record['txid'],True,record['blockhash']])
            else:
                saved=rpc(core,'gettransaction',[record['txid'],True],transaction_wallet)
                tx=rpc(core,'decoderawtransaction',[saved['hex']]);tx.update(blockhash=saved.get('blockhash'),confirmations=saved.get('confirmations',0))
        except ValueError:raise MissingHistory('The Extinct wallet does not yet contain the complete confirmed history. Prepare and authorise local history recovery; no wallet was deleted.') from None
        if tx.get('txid')!=record['txid'] or tx.get('blockhash')!=record['blockhash'] or tx.get('confirmations',0)<=0:raise ValueError('Core did not verify the exact archival transaction in the active chain.')
        txs.append(tx)
        for output in tx['vout']:
            address=output['scriptPubKey'].get('address')
            if address in addresses:found.add(address);outpoints.add((tx['txid'],output['n']))
    if found!=addresses:raise ValueError('The manifest includes an address absent from its confirmed history.')
    for tx in txs:
        if not any((tx['txid'],o['n']) in outpoints for o in tx['vout']) and not any((i.get('txid'),i.get('vout')) in outpoints for i in tx['vin']):raise ValueError('A proposed transaction is unrelated to this wallet history.')

def receipt(store,p):
    from setup_messages import verify
    from wallet_preview import fingerprint
    proof=p['preservation'];envelope=proof['receipt'];verify(store,envelope,envelope['public_key'])
    return fingerprint(envelope['public_key'])

def native_sources(core,p):
    # Trust the user's local, caught-up Core wallet as the historical source.
    # Names and Dashboard balance claims never establish wallet identity.
    if p['wallet'] not in ('Wallaby Extinct','Extinct'):return []
    matches=[];chain=check_chain(core,p)
    for wallet in rpc(core,'listwallets'):
        if wallet==p['wallet']:continue
        public=rpc(core,'listdescriptors',[False],wallet)
        if descriptors(public)!=descriptors(p['public_wallet']):continue
        info=rpc(core,'getwalletinfo',[],wallet)
        if info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:continue
        try:verify_public(core,p,transaction_wallet=wallet)
        except ValueError:continue
        matches.append(wallet)
    return matches

def review(core,store,p):
    validate(p);chain=check_chain(core,p)
    if p['phase']=='preserve':
        existing_archive(core,p['wallet'])
        # Read back an already preserved manifest before asking an old source
        # wallet on a pruned node to establish broader historical coverage.
        try:
            readback(core,p)
            verify_public(core,p,transaction_wallet=p['wallet'])
            preserved=True
        except ValueError:preserved=False
        sources=[] if preserved else native_sources(core,p)
        if not preserved and not sources and chain.get('pruned') and chain.get('pruneheight',0):
            from wallet_retirement import MissingHistory
            raise MissingHistory('The Extinct wallet is missing required historical transactions on this pruned node. Prepare local history recovery, then authorise This Node on Synchronisation. No original wallet was deleted.')
        facts=None if preserved else local_facts(core,store,p,True)
        local_addresses={(r['address'],r['label']) for r in facts['addresses']} if facts else set()
        local_transactions={digest(r) for r in facts['transaction_records']} if facts else set()
        if not preserved and (facts is None or not {(r['address'],r['label']) for r in p['manifest']['addresses']}<=local_addresses or not {digest(r) for r in p['manifest']['transactions']}<=local_transactions):verify_public(core,p)
        return {'phase':'preserve','wallet':p['public_wallet'].get('wallet_name','Retiring wallet'),'archive':p['wallet'],'addresses':p['manifest']['addresses'],'transactions':len(p['manifest']['transactions']),'blocks':chain['blocks'],'manifest_hash':p['manifest_hash'],'delete_wallet':False,'local_wallets':[],'retained_signers':[],'history_method':'existing' if preserved else 'native' if sources else 'rescan','native_sources':sources}
    facts=local_facts(core,store,p);available=local_archives(core);facts.update(phase='delete',archive=None,manifest_hash=p['manifest_hash'],preservation_fingerprint=receipt(store,p),preservation_archive=p['preservation']['archive_wallet'],preservation_node=p['preservation']['node_id'],local_extinct_wallets=available,history_elsewhere_confirmation_required=not bool(available));return facts

def imports(core,p,timestamp=0,only_missing=False):
    existing_archive(core,p['wallet']);requests=[]
    for r in p['manifest']['addresses']:
        info=rpc(core,'getaddressinfo',[r['address']],p['wallet']);labels=info.get('labels',[])
        if labels and labels!=[r['label']]:raise ValueError('Existing Extinct labels conflict with the proposed history; reconcile without overwriting them.')
        if only_missing and (info.get('ismine') or info.get('iswatchonly')):
            if labels!=[r['label']]:rpc(core,'setlabel',[r['address'],r['label']],p['wallet'])
            continue
        body='addr('+r['address']+')';requests.append({'desc':body+'#'+checksum(body),'timestamp':timestamp,'label':r['label']})
    if not requests:return
    from activity_log import event
    event('extinction.history','Public address import · mode='+('non_rescanning_staging' if only_missing else 'historical_rescan')+' · addresses='+str(len(requests)))
    results=rpc(core,'importdescriptors',{'requests':requests},p['wallet'],timeout=86400)
    event('extinction.history','Public address import returned · successful='+str(sum(r.get('success') is True for r in results))+' · requested='+str(len(requests)))
    if len(results)!=len(requests) or not all(r.get('success') for r in results):raise ValueError('Historical import was incomplete; no wallet was deleted.')

def readback(core,p):
    check_chain(core,p);existing_archive(core,p['wallet']);chain=rpc(core,'getblockchaininfo');info=rpc(core,'getwalletinfo',[],p['wallet'])
    if info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('The Extinct archive has not processed the current local chain.')
    for r in p['manifest']['addresses']:
        own=rpc(core,'getaddressinfo',[r['address']],p['wallet'])
        if not (own.get('ismine') or own.get('iswatchonly')) or own.get('labels')!=[r['label']]:raise ValueError('Extinct address/label readback failed.')
    for r in p['manifest']['transactions']:
        tx=rpc(core,'gettransaction',[r['txid'],True],p['wallet'])
        if tx.get('confirmations',0)<=0 or tx.get('blockhash')!=r['blockhash']:raise ValueError('Extinct transaction readback failed. Recover complete history before preservation can complete.')

def approve(owner,key,fingerprint_value=None,history_elsewhere_confirmed=False):
    if type(history_elsewhere_confirmed) is not bool:raise ValueError('Confirm preservation on another node explicitly before deletion.')
    p=validate(owner.store.read()['pending'][key]['proposal']);old=owner.reviews.get(key)
    if not old or time.time()-old[1]>600 or owner.store.read()['pending'][key]['state']!='pending':raise ValueError('Review this phased extinction request again.')
    facts=review(owner.core,owner.store,p)
    # A new block is harmless; any changed wallet/evidence/path needs new review.
    if {k:v for k,v in facts.items() if k not in ('blocks','tip')}!={k:v for k,v in old[0].items() if k not in ('blocks','tip')}:raise ValueError('Retirement data changed since review.')
    if p['phase']=='delete' and fingerprint_value!=facts['preservation_fingerprint']:raise ValueError('Independently compare the preserving Agent fingerprint before deletion.')
    if p['phase']=='delete' and facts['history_elsewhere_confirmation_required'] and not history_elsewhere_confirmed:raise ValueError('No Extinct wallet is loaded on this node. Confirm that the reviewed transaction history is already preserved in another node’s Extinct wallet before deleting local copies.')
    from activity_log import event
    event('extinction.'+p['phase'],'Local approval accepted · addresses='+str(len(p['manifest']['addresses']))+' · transactions='+str(len(p['manifest']['transactions'])))
    with owner.store.edit() as s:s['pending'][key]['state']='attempted'
    try:
        if owner.store.read().get('retirement_cancel_pending',{}).get(key):return owner._cancel_result(key)
        if p['phase']=='preserve':
            try:readback(owner.core,p);verify_public(owner.core,p,transaction_wallet=p['wallet']);complete_history=True
            except ValueError:complete_history=False
            if not complete_history and facts.get('history_method')=='native':
                from wallet_recovery import staging_timestamp
                from peer_wallet import work_dir
                from core_history import collect,install
                import tempfile
                with tempfile.TemporaryDirectory(dir=work_dir(owner.core)) as folder:
                    rows=collect(owner.core,facts['native_sources'],[r['txid'] for r in p['manifest']['transactions']],folder)
                imports(owner.core,p,timestamp=staging_timestamp(owner.core),only_missing=True)
                install(owner.core,owner.store,p['wallet'],rows,p['manifest'])
            elif not complete_history:imports(owner.core,p)
            readback(owner.core,p)
            if owner.store.read().get('retirement_cancel_pending',{}).get(key):return owner._cancel_result(key)
            from setup_messages import sign
            message={'version':1,'kind':'wallet_retirement_preservation','request_hash':key,'operation_id':p['operation_id'],'manifest_hash':p['manifest_hash'],'archive_wallet':p['wallet'],'address_count':len(p['manifest']['addresses']),'wallet_deleted':False}
            outcome=result(p,'complete',archive_verified=True,history_verified=True,wallet_deleted=False,deleted_wallets=[],archive_wallet=p['wallet'],address_count=len(p['manifest']['addresses']),archive_receipt=sign(owner.store,message))
            text='History preserved and independently read back in the existing Extinct wallet. No original wallet was deleted. Dashboard must verify this receipt before offering separate deletion requests.'
            if owner.store.read().get('history_cleanup'):text+=' A previous public archive copy was retained because cleanup could not finish; inspect it locally before removing it.'
        else:
            # Repeat all local balances, associated policies, transaction and path
            # checks immediately before unloading the exact approved group.
            fresh=review(owner.core,owner.store,p)
            for f in ('addresses','transaction_records','deletion','local_wallets','retained_signers','local_extinct_wallets','history_elsewhere_confirmation_required'):
                if fresh[f]!=facts[f]:raise ValueError('Local wallet changed before deletion. No deletion authorised.')
            if owner.store.read().get('retirement_cancel_pending',{}).get(key):return owner._cancel_result(key)
            from local_extinction import prepare as prepare_local,complete as complete_local
            local_id=prepare_local(owner.store,p,fresh['local_wallets'])
            for item in fresh['deletion']:rpc(owner.core,'unloadwallet',{'wallet_name':item['wallet'],'load_on_startup':False})
            if set(fresh['local_wallets'])&set(rpc(owner.core,'listwallets')):raise ValueError('Not every approved wallet unloaded; deletion blocked.')
            from wallet_deletion import delete
            deleted=[]
            for item in fresh['deletion']:
                if delete(item['target']).get('deleted') is not True:raise ValueError('Wallet deletion was not confirmed.')
                deleted.append(item['wallet'])
            complete_local(owner.store,local_id)
            outcome=result(p,'complete',zero_balance_verified=True,history_verified=True,wallet_deleted=True,deleted_wallets=deleted)
            text='The exact empty local wallet copies were unloaded, removed from startup and deleted. No Extinct wallet was created or updated on this node.'
        owner.store.queue('wallet_retirement_result',outcome)
        with owner.store.edit() as s:s['completed'][key]={'kind':'wallet_retire','at':time.time(),'result':outcome};s['pending'].pop(key,None)
        owner.reviews.pop(key,None);event('extinction.'+p['phase'],'Completed · deleted_wallets='+str(len(outcome['deleted_wallets'])));return {'message':text}
    except Exception as error:
        event('extinction.'+p['phase'],'Incomplete or uncertain · error_type='+type(error).__name__+' · automatic_replay=false')
        owner.store.queue('wallet_retirement_result',result(p,'error',message='Phased extinction incomplete or uncertain. Inspect local Core and reconcile; no automatic replay.'));raise

def prepare_history(core,store,key,p):
    validate(p);check_chain(core,p);existing_archive(core,p['wallet']);verify_public(core,p,verify_transactions=False)
    ident=digest({'local_retirement_history':key});saved=store.read()
    if ident in saved.get('history_jobs',{}):
        from activity_log import event
        event('extinction.history','Existing recovery job retained; no repeated import or rescan.')
        return {'message':'History recovery is already prepared. Open Synchronisation and review This Node; repeated preparation will not rescan or replace the existing recovery job.','history_prepared':True}
    try:
        readback(core,p);verify_public(core,p,transaction_wallet=p['wallet'])
    except ValueError:pass
    else:return {'message':'This Extinct wallet already contains the verified history. Return to Authorise and review the preservation request; no rescan was needed.','history_ready':True}
    # Do not start a doomed genesis rescan before the guarded recovery job exists.
    from wallet_recovery import staging_timestamp,require
    imports(core,p,timestamp=staging_timestamp(core),only_missing=True)
    from peer_wallet import wallet_details
    raw=rpc(core,'listdescriptors',[False],p['wallet'])
    q={'public_wallet':raw,'source_has_private_keys':False,'transfer_version':2,'direction':'send'}
    details=wallet_details(core,q,store)
    # Preserve original historical timestamps for explicit replay, even though
    # newly staged descriptors use a future timestamp to avoid import rescans.
    for row in details['public_wallet']['descriptors']:row['timestamp']=0
    require(store,ident,p['wallet'],details)
    with store.edit() as state:state['history_jobs'][ident].update(expected_private_keys=False,local_only=True)
    # Recover the matching original wallets in the same explicitly authorised
    # node replay, so their later deletion can verify complete local coverage.
    for name in rpc(core,'listwallets'):
        if name==p['wallet']:continue
        public=rpc(core,'listdescriptors',[False],name)
        if descriptors(public)!=descriptors(p['public_wallet']):continue
        source_id=digest({'local_retirement_source_history':key,'wallet':name})
        if source_id in store.read().get('history_jobs',{}):continue
        private=rpc(core,'getwalletinfo',[],name).get('private_keys_enabled') is True
        source_details=wallet_details(core,{'public_wallet':public,'source_has_private_keys':private,'transfer_version':2,'direction':'send'},store)
        require(store,source_id,name,source_details)
        with store.edit() as state:state['history_jobs'][source_id].update(expected_private_keys=private,local_only=True)

    from activity_log import event
    event('extinction.history','Public addresses staged; local recovery prepared; separate Synchronisation approval required.')
    return {'message':'Missing public addresses staged without rescanning. Open Synchronisation and authorise This Node history recovery. Pruning stays unchanged. Then review preservation again; original wallets remain intact.','history_prepared':True}

def require_current(p):
    if p.get('version')!=3:raise ValueError('This combined extinction request is obsolete. Deny it and use Dashboard Build 34 to request separate preservation and deletion. No wallet operation was started.')
    return validate(p)
