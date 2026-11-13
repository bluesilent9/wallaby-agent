"""Exact pending public-history jobs carried through a locally approved clone.

Only paired direct streams supply records. A cloned chain tip alone never clears
history jobs. Private/ranged wallet recovery and uncovered legacy entries refuse.
"""
import copy,hashlib,json,tempfile
from approval_store import digest
from wallet_ops import rpc
from wallet_labels import fixed_address,address_only,read_labels,apply_labels
from chain_clone_files import CloneError
from core_history import MAX_BYTES,collect,validate_rows,install


def requests(core,store):
    from extinct_sync import ALIASES
    groups={};original_jobs=[]
    for key,job in sorted(store.read().get('history_jobs',{}).items()):
        name=job['wallet'];raw=job['details']['public_wallet']
        if job.get('local_only') and name not in ALIASES and not job.get('staged'):
            original_jobs.append((key,job));continue
        if name not in ALIASES or job.get('staged') or job.get('expected_private_keys') or not address_only(raw):raise CloneError('This clone handover supports pending public Extinct history only. Private or ranged-wallet history still requires its own recovery.')
        info=rpc(core,'getwalletinfo',[],name)
        if info.get('private_keys_enabled') is not False or info.get('scanning'):raise CloneError('Wait for the public Extinct wallet to finish its current scan before handing recovery to a clone.')
        group=groups.setdefault(name,{'wallet':name,'keys':[],'addresses':{},'originals':[],'jobs_hash':None})
        labels={r['address']:r['label'] for r in job['details'].get('address_labels',[])}
        for r in raw['descriptors']:
            a=fixed_address(r['desc'])
            if a is None or a not in labels:raise CloneError('The pending Extinct job lacks exact public address and label evidence.')
            if a in group['addresses'] and group['addresses'][a]!=labels[a]:raise CloneError('Pending Extinct jobs disagree about historical labels.')
            group['addresses'][a]=labels[a]
        group['keys'].append(key)
    from public_policy import descriptors
    saved=store.read()
    for key,job in original_jobs:
        parents=[(k,row['proposal']) for k,row in saved['pending'].items() if row['proposal'].get('kind')=='wallet_retire' and row['proposal'].get('phase')=='preserve' and not row.get('withdrawn') and not row.get('cancel_requested') and digest({'local_retirement_source_history':k,'wallet':job['wallet']})==key]
        if len(parents)!=1:raise CloneError('Original-wallet recovery has no exact live local extinction proposal. No job was discarded.')
        parent,p=parents[0];g=groups.get(p['wallet'])
        if not g or descriptors(job['details']['public_wallet'])!=descriptors(p['public_wallet']) or not {a['address'] for a in p['manifest']['addresses']}<=set(g['addresses']):raise CloneError('The original-wallet recovery is not covered by the exact queued Extinct archive.')
        g['keys'].append(key);g['originals'].append({'key':key,'parent':parent,'wallet':job['wallet'],'policy_hash':digest(sorted(descriptors(p['public_wallet']))),'private':job.get('expected_private_keys',False),'transactions':p['manifest']['transactions']})
    if not groups:raise CloneError('No pending Extinct history recovery needs a clone handover.')
    result=[]
    for g in groups.values():
        actual=rpc(core,'listdescriptors',[False],g['wallet'])
        if not address_only(actual) or {fixed_address(r['desc']) for r in actual['descriptors']}-set(g['addresses']):raise CloneError('The receiving archive has additional entries outside this recovery approval. Include their history in the local recovery first.')
        g['addresses']=[{'address':a,'label':label} for a,label in sorted(g['addresses'].items())];g['jobs_hash']=digest({k:store.read()['history_jobs'][k] for k in g['keys']});result.append(g)
    return result


def validate_request(r):
    if not isinstance(r,dict) or set(r)!={'wallet','keys','addresses','originals','jobs_hash'} or not isinstance(r['keys'],list) or not 1<=len(r['keys'])<=128 or len(set(r['keys']))!=len(r['keys']) or not all(isinstance(k,str) and len(k)==64 for k in r['keys']):raise CloneError('Invalid direct recovery-history request.')
    from extinct_sync import ALIASES
    from wallet_labels import validate_labels
    if r['wallet'] not in ALIASES or not isinstance(r['jobs_hash'],str) or len(r['jobs_hash'])!=64 or not isinstance(r['addresses'],list) or not 1<=len(r['addresses'])<=10000:raise CloneError('Invalid direct Extinct recovery identity.')
    if any(not isinstance(a,dict) or set(a)!={'address','label'} for a in r['addresses']):raise CloneError('Invalid recovery addresses.')
    validate_labels([{**a,'is_change':False} for a in r['addresses']])
    if not isinstance(r['originals'],list) or len(r['originals'])>128 or any(not isinstance(o,dict) or set(o)!={'key','parent','wallet','policy_hash','private','transactions'} or o['key'] not in r['keys'] or type(o['private']) is not bool for o in r['originals']):raise CloneError('Invalid original-wallet recovery binding.')
    return r


def export(core,store,r):
    validate_request(r)
    from extinct_sync import archive_name
    from extinct_upgrade import snapshot,valid
    from extinct_history_sync import coverage
    name=archive_name(core);state=snapshot(core,name)
    wanted={a['address'] for a in r['addresses']}
    if not valid(core,state) or not wanted<=set(state['addresses']):raise CloneError('The source Extinct wallet does not have verified complete history for every pending receiver address. Finish its extinction/upgrade first, or use full block recovery.')
    labels={a['address']:a['label'] for a in read_labels(core,name,state['raw'],[])}
    if any(labels.get(a['address'])!=a['label'] for a in r['addresses']):raise CloneError('The source and pending recovery have different historical labels. Reconcile them locally; LOST information was not overwritten.')
    if len(state['txids'])>10000:raise CloneError('The source archive exceeds the bounded recovery-history limit. No partial history was offered.')
    txs={};total_hex=0
    for txid in state['txids']:
        tx=rpc(core,'gettransaction',[txid,True],name)
        if tx.get('confirmations',0)<=0:raise CloneError('Source historical transactions are not all confirmed.')
        total_hex+=len(tx.get('hex',''))
        if total_hex>128*1024*1024:raise CloneError('Source historical transactions exceed the recovery memory budget. No partial history was offered.')
        txs[txid]=(tx,rpc(core,'decoderawtransaction',[tx['hex']]))
    own={(i,v['n']) for i,(tx,d) in txs.items() for v in d['vout'] if v['scriptPubKey'].get('address') in wanted}
    ids={i for i,(tx,d) in txs.items() if any((i,v['n']) in own for v in d['vout']) or any((v.get('txid'),v.get('vout')) in own for v in d['vin'])}
    if len(ids)>10000:raise CloneError('The required source history exceeds one bounded recovery handover. No partial history was offered.')
    manifest={'addresses':r['addresses'],'transactions':[{'txid':i,'blockhash':txs[i][0]['blockhash']} for i in sorted(ids)]}
    from peer_wallet import work_dir
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as folder:records=collect(core,[name],ids,folder)
    validate_rows(core,records,manifest,allow_unfunded=True)
    packet={'version':1,'request_hash':digest(r),'manifest':manifest,'records':records,'coverage':coverage(core,name,wanted,ids)}
    raw=json.dumps(packet,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>MAX_BYTES:raise CloneError('Recovery history exceeds the bounded direct-transfer size.')
    return raw,{'request_hash':digest(r),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'addresses':len(wanted),'transactions':len(ids)}


def live(store,r):
    saved=store.read()
    from lifecycle_preferences import blocked
    for key in r['keys']:
        job=saved.get('history_jobs',{}).get(key)
        if not job:raise CloneError('A pending recovery job was removed; no completion was inferred.')
        rows=[]
        if key in saved['pending']:rows.append(saved['pending'][key])
        if job.get('extinct_upgrade') and job.get('local_only'):
            parents=[row for parent,row in saved['pending'].items() if digest({'local_retirement_history':parent})==key]
            if not parents:raise CloneError('The local extinction request was removed. Its recovery was not completed automatically.')
            rows.extend(parents)
        for row in rows:
            if row.get('withdrawn') or row.get('cancel_requested') or blocked(saved,row['proposal']):raise CloneError('The recovery or extinction request was cancelled or denied. No history job was cleared.')
    return True


def apply(core,store,r,raw):
    validate_request(r);live(store,r)
    jobs=store.read().get('history_jobs',{})
    if any(k not in jobs for k in r['keys']) or digest({k:jobs[k] for k in r['keys']})!=r['jobs_hash']:raise CloneError('Pending recovery changed since clone review. No recovery completion was recorded.')
    packet=json.loads(raw)
    if not isinstance(packet,dict) or set(packet)!={'version','request_hash','manifest','records','coverage'} or type(packet['version']) is not int or packet['version']!=1 or packet['request_hash']!=digest(r) or packet['manifest'].get('addresses')!=r['addresses']:raise CloneError('Direct history does not match the locally reviewed recovery jobs.')
    from history_wire import validate_manifest
    from extinct_history_sync import validate_coverage
    from extinct_upgrade import certify,snapshot,valid
    validate_manifest(packet['manifest']);wanted={a['address'] for a in r['addresses']}
    validate_coverage(core,packet['coverage'],wanted,{t['txid'] for t in packet['manifest']['transactions']})
    validate_rows(core,packet['records'],packet['manifest'],allow_unfunded=True)
    info=rpc(core,'getwalletinfo',[],r['wallet']);current=rpc(core,'listdescriptors',[False],r['wallet'])
    if info.get('private_keys_enabled') is not False or info.get('scanning') or not address_only(current) or {fixed_address(a['desc']) for a in current['descriptors']}!=wanted:raise CloneError('Receiving public archive changed after recovery review; no historical replacement was authorised.')
    apply_labels(core,r['wallet'],[{**a,'is_change':False} for a in r['addresses']],write=False)
    # install() merges with the existing public Core backup. Receiver-only
    # transaction records remain; private/key/descriptor records are not imported.
    install(core,store,r['wallet'],packet['records'],packet['manifest'],allow_unfunded=True)
    certify(core,store,r['wallet'],wanted)
    after=snapshot(core,r['wallet'])
    if not valid(core,after) or not {t['txid'] for t in packet['manifest']['transactions']}<=set(after['txids']):raise CloneError('Core did not retain the direct recovery history and complete coverage.')
    # Verify the Core readback of every incoming raw transaction and confirmation.
    for row in packet['records']:
        from core_history import parse_record,TX_KEY
        tx,_=parse_record(TX_KEY+bytes.fromhex(row['txid'])[::-1],bytes.fromhex(row['record']));actual=rpc(core,'gettransaction',[row['txid'],True],r['wallet'])
        if actual.get('hex')!=tx.serialize().hex() or actual.get('blockhash')!=row['blockhash'] or actual.get('confirmations',0)<=0:raise CloneError('Historical transaction readback did not match the reviewed source.')
    verify_originals(core,store,r,packet['records'])
    return {'wallet':r['wallet'],'keys':r['keys'],'jobs_hash':r['jobs_hash'],'coverage':digest(after['marker'])}


def verify_originals(core,store,r,records):
    from public_policy import descriptors
    from core_history import parse_record,TX_KEY
    available={row['txid']:row for row in records};saved=store.read()
    for o in r['originals']:
        parent=saved['pending'].get(o['parent'])
        if not parent or parent.get('withdrawn') or parent.get('cancel_requested') or parent['state']!='pending' or digest(parent['proposal'])!=o['parent']:raise CloneError('The original extinction was cancelled or changed. Pending recovery was retained.')
        info=rpc(core,'getwalletinfo',[],o['wallet']);actual=rpc(core,'listdescriptors',[False],o['wallet'])
        if bool(info.get('private_keys_enabled'))!=o['private'] or info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<rpc(core,'getblockchaininfo')['blocks'] or digest(sorted(descriptors(actual)))!=o['policy_hash']:raise CloneError('An original signing wallet changed or has not finished processing the clone.')
        for expected in o['transactions']:
            row=available.get(expected['txid'])
            if not row or row['blockhash']!=expected['blockhash']:raise CloneError('The clone source does not cover all original-wallet history. No original recovery job was cleared.')
            tx,_=parse_record(TX_KEY+bytes.fromhex(row['txid'])[::-1],bytes.fromhex(row['record']));local=rpc(core,'gettransaction',[row['txid'],True],o['wallet'])
            if local.get('hex')!=tx.serialize().hex() or local.get('blockhash')!=row['blockhash'] or local.get('confirmations',0)<=0:raise CloneError('The original wallet lacks a matching confirmed transaction. Its keys were retained and its recovery remains pending.')


def finish(core,store,requests_,proofs):
    from extinct_upgrade import snapshot,valid
    from public_policy import descriptors
    chain=rpc(core,'getblockchaininfo')
    if chain.get('initialblockdownload') or chain['blocks']!=chain['headers']:raise CloneError('The cloned node is not caught up. Pending recovery remains; no history completion was claimed.')
    for name in rpc(core,'listwallets'):
        info=rpc(core,'getwalletinfo',[],name)
        if info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise CloneError('A local wallet has not processed the cloned tip. Recovery remains pending.')
    if len(proofs)!=len(requests_):raise CloneError('Not every pending archive received verified history.')
    for r,proof in zip(requests_,proofs):
        live(store,r)
        jobs=store.read().get('history_jobs',{});state=snapshot(core,r['wallet'])
        if proof!={'wallet':r['wallet'],'keys':r['keys'],'jobs_hash':r['jobs_hash'],'coverage':digest(state['marker'])} or not valid(core,state) or any(k not in jobs for k in r['keys']) or digest({k:jobs[k] for k in r['keys']})!=r['jobs_hash']:raise CloneError('Recovery evidence changed before completion. Pending work was retained.')
        for key in r['keys']:
            job=jobs[key]
            if not job.get('local_only'):store.queue('wallet_transfer_result',{'request_hash':key,'status':'complete','message':'Complete public wallet history verified from the locally approved direct clone source.'})
            with store.edit() as s:
                s.setdefault('history_coverage',{})[job['wallet']]={'identity':digest(sorted(descriptors(job['details']['public_wallet']))),'from_time':job['timestamp'],'tip':chain['bestblockhash']}
                s['history_jobs'].pop(key);s['pending'].pop(key,None);s['completed'][key]={'kind':'wallet_transfer','at':__import__('time').time()}
    if store.read().get('history_jobs'):raise CloneError('Other history work remains. No whole-recovery completion was claimed.')
    from retirement_continuation import finish as continue_extinction
    continue_extinction(core,store)
    with store.edit() as s:s.setdefault('recovery',{}).update(state='complete',finished=__import__('time').time(),message='Recovery completed from a trusted direct clone and separately verified Extinct history. No Internet blockchain download was resumed.')
