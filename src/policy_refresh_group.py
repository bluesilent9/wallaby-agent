"""One local policy consent for an exact set of related signer wallets."""
import copy,time
from approval_store import digest
from build8_policy import descriptors
from wallet_ops import rpc


def targets(ops,p):
    """Discover locally; names supplied by Dashboard do not establish a role."""
    from policy_refresh import validate_extensions,transition
    wanted=descriptors({'wallet_name':'old','descriptors':[{'desc':d} for d in p['previous_descriptors']]})
    new=descriptors({'wallet_name':'new','descriptors':[{'desc':p[k]} for k in ('receive_descriptor','change_descriptor')]})
    loaded={name:(ident,r) for ident,r in ops.archives.loaded.items() for name in r['routes']}
    result=[]
    for name in sorted(rpc(ops.core,'listwallets')):
        raw=rpc(ops.core,'listdescriptors',[False],name)
        if not wanted<=descriptors(raw):continue
        info=rpc(ops.core,'getwalletinfo',[],name)
        if info.get('scanning'):raise ValueError('A related signing wallet is scanning. Wait before reviewing this policy.')
        ident,record=loaded.get(name,(None,None))
        if record:
            latest=validate_extensions(record['recovery'])
            if latest!=p['previous_descriptors'] and not (latest==[p['receive_descriptor'],p['change_descriptor']] and record['recovery'].get('policy_extensions',[])[-1:]==[transition(p)]):raise ValueError('A loaded archive has different approved policy history. Reconcile it before this refresh.')
        first=rpc(ops.core,'deriveaddresses',[p['previous_descriptors'][0],[0,0]])[0]
        labels=rpc(ops.core,'getaddressinfo',[first],name).get('labels',[])
        if any(v.startswith('Wallaby setup pending:') for v in labels):raise ValueError('Finish the original wallet setup and physical backups before refreshing.')
        active=[r for r in raw['descriptors'] if r.get('active')]
        new_active=bool(active and new<=descriptors({'wallet_name':name,'descriptors':active}))
        result.append({'wallet':name,'storage':'disc' if record else 'node','private':info.get('private_keys_enabled') is True,'archive':ident,'history':digest(record['recovery']) if record else None,'public':digest(raw),'already_installed':new_active})
    if not result or p['wallet'] not in {r['wallet'] for r in result}:raise ValueError('The requested policy is not present in a locally verified wallet.')
    if len(result)>64:raise ValueError('Too many related wallets for one policy approval.')
    return result


def review(ops,key,p):
    before=targets(ops,p)
    base={k:v for k,v in p.items() if k not in ('wallets',)};base['version']=1
    shown=ops.review_single(key,base)
    if targets(ops,p)!=before:raise ValueError('Loaded signing wallets changed during review. Review again.')
    shown['refresh']['targets']=[{k:r[k] for k in ('wallet','storage','private')} for r in before]
    shown['refresh']['grouped']=True
    ops.reviews[key]=(copy.deepcopy(p),shown['refresh'],time.monotonic(),before)
    return shown


def result(ops,key,p,status,**extra):
    from setup_messages import sign
    from approval_store import MAX_ITEMS
    payload={'version':1,'request_hash':key,'request_id':p['request_id'],'status':status,'wallet':p['wallet'],**extra}
    item={'kind':'wallet_policy_refresh_result','payload':sign(ops.store,payload)}
    with ops.store.edit() as saved:
        if len(saved['outbox'])>=MAX_ITEMS:raise ValueError('Dashboard outbox is full; policy outcome retained locally.')
        saved['outbox'][digest(item)]=item
        if status in ('approved','history_required'):
            saved['pending'].pop(key,None);saved['completed'][key]={'kind':p['kind'],'at':time.time(),'proposal':p,'updated_wallets':extra['updated_wallets']}
            saved.setdefault('public_policy_updates',{})[extra['policy_hash']]=__import__('policy_refresh').transition(p)
        elif status=='denied':
            from approval_store import title
            saved['pending'].pop(key,None);saved['denied'][key]={'proposal':{'kind':p['kind']},'wallet_name':title(p)}
    return payload


def approve(ops,key):
    from policy_refresh import validate,transition,validate_extensions
    from combined_wallet import extension_requests,local_private_descriptors
    from wallet_recovery import history_missing,staging_timestamp
    from wallet_setup import secret_dialog
    from diagnostics import LocalActionFailure
    reviewed=ops.reviews.get(key)
    if not reviewed or len(reviewed)!=4 or time.monotonic()-reviewed[2]>600:raise ValueError('Review the refreshed public policy and all loaded signers again.')
    row=ops.store.read()['pending'][key];p=validate(row['proposal'])
    if row['state']!='pending':raise ValueError('This policy installation was attempted. Reconcile its local outcome; it will not be replayed automatically.')
    if p!=reviewed[0] or targets(ops,p)!=reviewed[3]:raise ValueError('The policy or loaded signer set changed. Review again before approval.')
    facts=reviewed[1];chain=rpc(ops.core,'getblockchaininfo');future=not facts['funded_outputs'] and facts['height']>chain['blocks'];plans=[];importing=False;completed=[];history=False;records={}
    from policy_refresh_backups import plan as backup_plan,stage as backup_stage,hold as backup_hold
    backup_discs=backup_plan(ops,reviewed[3])
    try:
        for target in reviewed[3]:
            name=target['wallet'];record=ops.archives.loaded.get(target['archive']) if target['archive'] else None
            core=record['node'].core if record else ops.core;route=record['routes'][name] if record else name
            missing=bool(not record and not future and not target['already_installed'] and history_missing(ops.core,p['timestamp']))
            timestamp=staging_timestamp(ops.core) if missing else 'now' if record or future else p['timestamp']
            plan={'target':target,'core':core,'route':route,'record':record,'missing':missing,'password':None,'requests':None}
            plans.append(plan)
            if record:records[target['archive']]=record
            if target['already_installed']:continue
            if target['private']:
                password=secret_dialog('Unlock '+name+' for the approved vault policy update. This is one approval covering all listed signers.',getattr(ops,'environment',{}));plan['password']=password;rows=None
                try:
                    rpc(core,'walletpassphrase',[password,120],route)
                    rows=record['node'].private_descriptors(route) if record else local_private_descriptors(core,route)
                    plan['requests']=extension_requests(rows,[p['receive_descriptor'],p['change_descriptor']],timestamp)
                finally:
                    password=None;rows=None;rpc(core,'walletlock',[],route)
            else:plan['requests']=[{'desc':p[k],'timestamp':timestamp,'active':True,'internal':bool(i),'range':[0,999]} for i,k in enumerate(('receive_descriptor','change_descriptor'))]
        # Every password/key/metadata check succeeds before the first import.
        if time.monotonic()-reviewed[2]>600 or p['expires_at']<=time.time() or targets(ops,p)!=reviewed[3]:raise ValueError('The policy review expired or loaded signers changed. Review again.')
        with ops.store.edit() as saved:
            if len(saved['outbox'])>=__import__('approval_store').MAX_ITEMS:raise ValueError('Dashboard outbox is full; connect before installing this policy.')
            current=saved['pending'][key]
            if current['state']!='pending' or current['proposal']!=p:raise ValueError('Policy work changed before installation.')
            current['state']='attempted';current['batch_wallets']=[r['wallet'] for r in reviewed[3]]
        importing=True
        for plan in plans:
            target=plan['target'];core=plan['core'];route=plan['route'];name=target['wallet']
            if not target['already_installed']:
                try:
                    if target['private']:rpc(core,'walletpassphrase',[plan['password'],120],route)
                    imported=rpc(core,'importdescriptors',[plan['requests']],route,timeout=86400)
                    if len(imported)!=2 or any(not r.get('success') for r in imported):raise ValueError('Core did not confirm both refreshed policies.')
                finally:
                    if target['private']:rpc(core,'walletlock',[],route)
            raw=rpc(core,'listdescriptors',[False],route)
            expected=descriptors({'wallet_name':'approved','descriptors':[{'desc':d} for d in p['previous_descriptors']+[p['receive_descriptor'],p['change_descriptor']]]})
            if not expected<=descriptors(raw):raise ValueError('An affected wallet did not retain and install both exact policy generations.')
            address=rpc(core,'deriveaddresses',[p['receive_descriptor'],[0,0]])[0];rpc(core,'setlabel',[address,'Wallaby setup ready:'+facts['policy_hash']],route)
            if target['private'] and rpc(core,'getwalletinfo',[],route).get('unlocked_until')!=0:raise ValueError('A refreshed signer could not be confirmed locked.')
            completed.append(name)
            # Preserve the approved history of each archive as soon as one of
            # its routes is installed, even if a later wallet in the batch fails.
            record=plan['record']
            if record:
                pid=digest([p['receive_descriptor'],p['change_descriptor']]);recovery=record['recovery']
                if pid in recovery.get('retired_policy_hashes',[]):
                    recovery['retired_policy_hashes'].remove(pid)
                    if not recovery['retired_policy_hashes']:recovery.pop('retired_policy_hashes')
                    for i,ext in enumerate(recovery['policy_extensions']):
                        if [ext['receive_descriptor'],ext['change_descriptor']]==[p['receive_descriptor'],p['change_descriptor']] and ext['previous_descriptors']==p['previous_descriptors']:recovery['policy_extensions'][i]=transition(p)
                elif validate_extensions(recovery)==p['previous_descriptors']:recovery.setdefault('policy_extensions',[]).append(transition(p))
                record['review'].update(height=facts['height'],effective_policy_hash=digest(recovery.get('policy_extensions',[])),additional_policies=copy.deepcopy(recovery.get('policy_extensions',[])))
            with ops.store.edit() as saved:saved['pending'][key]['batch_completed']=list(completed)
            if plan['missing']:
                from wallet_recovery import require
                for item in raw['descriptors']:item['timestamp']=min(item.get('timestamp',p['timestamp']),p['timestamp'])
                require(ops.store,digest({'refresh':key,'wallet':name}),name,{'public_wallet':raw,'chain':p['chain'],'funded_outputs':facts['funded_outputs']});history=True
        for record in records.values():
            latest=validate_extensions(record['recovery'])
            if latest==p['previous_descriptors']:record['recovery'].setdefault('policy_extensions',[]).append(transition(p))
            elif latest!=[p['receive_descriptor'],p['change_descriptor']]:raise ValueError('Archive history changed during installation.')
        # Disc participants remain amber on Dashboard until their replacements
        # pass full read-back and old-disc destruction is confirmed locally.
        outcome={'monitor_wallet':p['wallet'],'policy_hash':facts['policy_hash'],'receive_descriptor':p['receive_descriptor'],'change_descriptor':p['change_descriptor'],'previous_descriptors':p['previous_descriptors'],'updated_wallets':completed}
        if backup_discs:
            backup_stage(ops,backup_discs)
            backup_hold(ops,key,facts,{'status':'history_required' if history else 'approved','extra':outcome},backup_discs)
        else:result(ops,key,p,'history_required' if history else 'approved',**outcome)
        with ops.store.edit() as saved:saved.get('retired_policies',{}).pop(digest([p['receive_descriptor'],p['change_descriptor']]),None)
        ops.reviews.pop(key,None)
        return {'message':'Vault policy approved for all '+str(len(completed))+' related local wallets. Keys, old policies and archive members retained.'+(' Finish replacement discs in Disc Operations, then confirm old-disc destruction in Authorise. Dashboard will wait.' if backup_discs else '')+(' Blockchain history recovery is required.' if history else ''),'history_required':history,'updated_wallets':completed,'burn_authorised':bool(backup_discs)}
    except Exception as error:
        if importing:
            result(ops,key,p,'error',updated_wallets=completed,message='Policy installation is incomplete or uncertain. Retained keys and any installed policies were not replayed; reconcile this protected workspace.')
            raise LocalActionFailure('policy_batch_incomplete','Policy installation is incomplete or uncertain. The workspace and signing keys were retained. Inspect the affected wallets locally before retrying.') from None
        raise
    finally:
        for plan in plans:plan['password']=None;plan['requests']=None
        plans.clear()


def received(store,p):
    """Receipt proves a durably queued request, never policy approval."""
    key=digest(p);saved=store.read()
    if key not in saved['pending'] or saved['pending'][key].get('policy_receipt'):return
    from setup_messages import sign
    item={'kind':'wallet_policy_refresh_receipt','payload':sign(store,{'version':1,'request_id':p['request_id'],'request_hash':key,'status':'received'})}
    from approval_store import MAX_ITEMS
    with store.edit() as saved:
        row=saved['pending'].get(key)
        if not row or row.get('policy_receipt'):return
        if len(saved['outbox'])>=MAX_ITEMS:raise ValueError('Dashboard outbox is full; request receipt remains pending.')
        ident=digest(item);saved['outbox'][ident]=item;row['policy_receipt']=ident


def deny(ops,key):
    row=ops.store.read()['pending'][key]
    if row['state']!='pending':raise ValueError('An attempted policy update needs reconciliation; it cannot be denied as unstarted.')
    return result(ops,key,row['proposal'],'denied')
