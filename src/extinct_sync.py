"""One address-only historical archive; child labels never confer key authority."""
import copy
from build8_policy import descriptors
from wallet_labels import address_only,fixed_address,read_labels
from wallet_ops import rpc

ARCHIVE='Wallaby Extinct'

def grouped(raw):
    return raw.get('wallet_name') in (ARCHIVE,'Extinct') and address_only(raw)

def local_details(core,p,store):
    """Old imports may be spread across several watch-only Core containers."""
    from peer_wallet import wallet_details
    wanted=descriptors(p['public_wallet']);covered=set();records={};labels={};outputs={};chain=None
    for name in sorted(rpc(core,'listwallets')):
        info=rpc(core,'getwalletinfo',[],name)
        if info.get('private_keys_enabled'):continue
        raw=rpc(core,'listdescriptors',[False],name)
        if not address_only(raw):continue
        rows=[r for r in raw['descriptors'] if descriptors({'wallet_name':name,'descriptors':[r]})<=wanted]
        if not rows:continue
        if info.get('scanning'):raise ValueError('An Extinct source archive is still scanning. Finish its history recovery before synchronising.')
        part={**p,'public_wallet':{'wallet_name':'Local historical review','descriptors':rows}}
        facts=wallet_details(core,part,store,local_source=name);chain=facts['chain']
        for row in facts['public_wallet']['descriptors']:
            ident=row['desc'].split('#')[0];old=records.get(ident)
            if old:old['timestamp']=min(old.get('timestamp',0),row.get('timestamp',0))
            else:records[ident]=copy.deepcopy(row)
        covered|=descriptors(facts['public_wallet'])
        for row in facts['address_labels']:
            old=labels.get(row['address'])
            if old and old['label'] and row['label'] and old['label']!=row['label']:raise ValueError('Local Extinct archive copies have conflicting labels. Reconcile locally before sending.')
            if not old or row['label']:labels[row['address']]=row
        for row in facts['funded_outputs']:
            ident=(row['txid'],row['vout']);old=outputs.get(ident)
            if old and old!=row:raise ValueError('Local Extinct output facts changed during review. Review again.')
            outputs[ident]=row
    if covered!=wanted:raise ValueError('The local watch-only archives do not contain every requested Extinct address. No Dashboard assertion can fill missing data.')
    return {'public_wallet':{'wallet_name':ARCHIVE,'descriptors':[records[k] for k in sorted(records)]},'chain':chain,'funded_outputs':sorted(outputs.values(),key=lambda r:(r['txid'],r['vout'])),'address_labels':sorted(labels.values(),key=lambda r:r['address']),'vaults':[]}

def children(details):
    if not details or not grouped(details['public_wallet']):return []
    addresses={fixed_address(r['desc']) for r in details['public_wallet']['descriptors']}
    labels={r['address']:r['label'] for r in details.get('address_labels',[])};groups={}
    for address in sorted(addresses):
        name=labels.get(address,'').split(' | LOST:',1)[0].strip() or 'Unlabelled historical addresses'
        group=groups.setdefault(name,{'name':name,'addresses':[],'amount_sats':'0'})
        group['addresses'].append(address)
        group['amount_sats']=str(int(group['amount_sats'])+sum(int(o['amount_sats']) for o in details['funded_outputs'] if o['address']==address))
    return sorted(groups.values(),key=lambda r:r['name'].casefold())

def obsolete_denials(store):
    """Suggest exact old child policies; names alone never identify a denial."""
    from approval_store import digest
    from wallet_preview import verify
    saved=store.read();found={}
    if not saved.get('sync_exclusions'):return []
    for p in saved.get('sync_snapshot_requests',[]):
        if p['direction']!='receive' or not grouped(p['public_wallet']):continue
        # A one-child container may itself be suppressed by the old exact hash.
        group_id=digest(sorted(descriptors(p['public_wallet'])))
        old=saved.get('sync_exclusions',{}).get(group_id)
        if old and old['wallet_name'] not in (ARCHIVE,'Extinct'):
            found[group_id]={**old,'group':'Extinct','verified_by':'identical_public_policy'}
        payload=saved.get('transfer_previews',{}).get(digest(p))
        if not payload:continue
        try:verify(store,payload)
        except ValueError:continue
        facts=payload['preview']
        if descriptors(facts['public_wallet'])!=descriptors(p['public_wallet']):continue
        by_address={fixed_address(r['desc']):r for r in facts['public_wallet']['descriptors']}
        for child in children(facts):
            rows=[by_address[a] for a in child['addresses']]
            ident=digest(sorted(descriptors({'wallet_name':child['name'],'descriptors':rows})))
            if ident==group_id:continue # A deliberate current container denial stays.
            old=saved.get('sync_exclusions',{}).get(ident)
            if old:found[ident]={**old,'group':'Extinct','verified_by':'signed_sender_labels'}
    return sorted(found.values(),key=lambda r:(r['wallet_name'].casefold(),r['policy_id']))

def clear_obsolete_denials(store):
    from sync_preferences import enable
    matches=obsolete_denials(store)
    with store.edit() as saved:
        if saved.get('active_transfer') or saved.get('sync_batch'):raise ValueError('Finish or end the active transfer before clearing obsolete denials.')
    # Each exact match is re-enabled through the normal persistent preference path.
    for row in matches:enable(store,row['policy_id'])
    return {'message':str(len(matches))+' obsolete child-wallet denial(s) removed. Other wallet denials are unchanged; the grouped Extinct request still requires local authorisation.'}

def import_watch(core,store,key,p,details,native=False):
    """Keep one local archive; save exact merged recovery evidence before mutation."""
    from wallet_recovery import history_missing,earliest,require,staging_timestamp
    from wallet_labels import apply_labels
    group=grouped(p['public_wallet'])
    if native and not group:raise ValueError('Native historical merging is restricted to Extinct archives.')
    if group:
        from local_extinction import eligible
        eligible(core,store,p['public_wallet'])
    from wallet_rename import watch_name
    name=ARCHIVE if group else watch_name(details['public_wallet']['wallet_name'] or 'Default wallet')
    loaded=rpc(core,'listwallets');exists=any(w['name']==name for w in rpc(core,'listwalletdir')['wallets'])
    merged=copy.deepcopy(details)
    if exists:
        if not group:raise ValueError('A wallet with this transfer identity already exists. Inspect Core before retrying.')
        if any(k!=key and job['wallet']==name for k,job in store.read().get('history_jobs',{}).items()):raise ValueError('Finish the existing Extinct archive history recovery before extending it. Earlier recovery evidence was retained.')
        if name not in loaded:raise ValueError('Load the existing Wallaby Extinct archive in Core before synchronising it. No archive was overwritten.')
        info=rpc(core,'getwalletinfo',[],name);raw=rpc(core,'listdescriptors',[False],name)
        if info.get('private_keys_enabled') or info.get('scanning') or not address_only(raw):raise ValueError('Existing Wallaby Extinct must be an idle private-key-disabled address-only archive. No wallet was changed.')
        labels=read_labels(core,name,raw,[]);by_address={r['address']:r for r in labels}
        for row in details.get('address_labels',[]):
            old=by_address.get(row['address'])
            if old and old['label'] and old['label']!=row['label']:raise ValueError('Existing extinct address label conflicts with the signed sender preview. Reconcile locally; no labels were replaced.')
            by_address[row['address']]=row
        rows={r['desc'].split('#')[0]:copy.deepcopy(r) for r in raw['descriptors']}
        for row in details['public_wallet']['descriptors']:
            ident=row['desc'].split('#')[0]
            if ident in rows:rows[ident]['timestamp']=min(rows[ident].get('timestamp',0),row.get('timestamp',0))
            else:rows[ident]=copy.deepcopy(row)
        merged['public_wallet']={'wallet_name':ARCHIVE,'descriptors':list(rows.values())}
        descriptors(merged['public_wallet']);merged['address_labels']=sorted(by_address.values(),key=lambda r:r['address'])
    missing=native or history_missing(core,earliest(merged))
    if not native:require(store,key,name,merged)
    with store.edit() as state:state['pending'][key]['state']='attempted'
    if not exists:rpc(core,'createwallet',{'wallet_name':name,'disable_private_keys':True,'blank':True,'descriptors':True,'load_on_startup':True})
    requests=[]
    for item in merged['public_wallet']['descriptors']:
        request={k:v for k,v in item.items() if k in ('desc','timestamp','active','internal','range','next_index')}
        if 'next' in item:request['next_index']=item['next']
        if missing:request['timestamp']=staging_timestamp(core)
        requests.append(request)
    result=rpc(core,'importdescriptors',{'requests':requests},name,timeout=600)
    if len(result)!=len(requests) or any(not r.get('success') for r in result):raise ValueError('Core did not import all approved public addresses/descriptors. Inspect the watch archive; no operation will be replayed.')
    if rpc(core,'getwalletinfo',[],name).get('private_keys_enabled'):raise ValueError('Watch-only wallet unexpectedly permits private keys.')
    apply_labels(core,name,merged.get('address_labels',[]),write=True)
    return name,False if native else missing,merged
