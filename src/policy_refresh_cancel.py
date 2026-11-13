"""Retire an unused receiving generation, never delete a wallet or signing key."""
import copy,time
from approval_store import digest
from public_policy import descriptors
from wallet_ops import rpc


def policy_id(p):return digest([p['receive_descriptor'],p['change_descriptor']])

def proposals(c,p):
    saved=c.store.read();known={**saved['completed'],**saved['pending']}
    return {key:row['proposal'] for key in p['request_hashes'] if (row:=known.get(key)) and row.get('proposal',{}).get('kind')=='wallet_policy_refresh'}

def handles(c,p):
    return p['builder']=='wallet' and not p['operations'] and bool(proposals(c,p))

def archives(c):return getattr(c,'archives',None)

def wallets(c,p):
    loaded=archives(c);routes={name:(ident,r) for ident,r in (loaded.loaded.items() if loaded else []) for name in r['routes']};old=descriptors({'wallet_name':'old','descriptors':[{'desc':d} for d in p['previous_descriptors']]});new=descriptors({'wallet_name':'new','descriptors':[{'desc':p[k]} for k in ('receive_descriptor','change_descriptor')]});rows=[]
    for name in sorted(rpc(c.core,'listwallets')):
        raw=rpc(c.core,'listdescriptors',[False],name);actual=descriptors(raw)
        if not old<=actual:continue
        ident,record=routes.get(name,(None,None));info=rpc(c.core,'getwalletinfo',[],name)
        if info.get('scanning'):raise ValueError('A related wallet is scanning. Cancellation is blocked until its funding can be checked.')
        if record:
            ext_ids={policy_id(ext) for ext in record['recovery'].get('policy_extensions',[])}
            if new<=actual and policy_id(p) not in ext_ids:raise ValueError('This archive lacks the retained pre-refresh transition. Keep its policy and inspect locally before retirement.')
            from policy_refresh import validate_extensions
            latest=validate_extensions(record['recovery'])
            if latest not in (p['previous_descriptors'],[p['receive_descriptor'],p['change_descriptor']]):raise ValueError('A later vault generation exists. This cancellation cannot rewind it.')
        active=descriptors({'wallet_name':name,'descriptors':[r for r in raw['descriptors'] if r.get('active')]}) if any(r.get('active') for r in raw['descriptors']) else set()
        if active and not (old<=active or new<=active):raise ValueError('Another receiving policy is active. Reconcile it before cancelling this generation.')
        rows.append({'wallet':name,'public':raw,'private':info.get('private_keys_enabled') is True,'archive':ident,'installed':new<=actual})
    return rows

def funding(c,p,rows):
    """Confirmed UTXOs plus mempool receives, across both tracked branches."""
    limit=999
    wanted=descriptors({'wallet_name':'new','descriptors':[{'desc':p[k]} for k in ('receive_descriptor','change_descriptor')]})
    for wallet in rows:
        for row in wallet['public']['descriptors']:
            if descriptors({'wallet_name':'row','descriptors':[row]})<=wanted:
                end=row.get('range',[0,999]);limit=max(limit,end[-1] if isinstance(end,list) else end,row.get('next',0),row.get('next_index',0))
    if limit>99999:raise ValueError('This policy exceeds the safe cancellation scan range. It was retained.')
    chain=rpc(c.core,'getblockchaininfo')
    if chain.get('initialblockdownload') or chain.get('headers',chain['blocks'])>chain['blocks']:raise ValueError('Wait for node synchronisation before checking cancellation funding.')
    scans=[{'desc':p[k],'range':[0,limit]} for k in ('receive_descriptor','change_descriptor')]
    result=rpc(c.core,'scantxoutset',['start',scans],timeout=600)
    if result.get('success') is not True or not isinstance(result.get('unspents'),list):raise ValueError('Core could not establish policy funding. Cancellation is blocked.')
    activity=rpc(c.core,'getdescriptoractivity',[[],scans,True],timeout=600)
    if not isinstance(activity,dict) or not isinstance(activity.get('activity'),list):raise ValueError('Core could not check unconfirmed vault funding. Cancellation is blocked.')
    funded=bool(result['unspents'] or any(r.get('type')=='receive' for r in activity['activity']))
    return {'funded':funded,'confirmed_outputs':len(result['unspents']),'unconfirmed_receives':sum(r.get('type')=='receive' for r in activity['activity']),'scan_range':[0,limit]}

def disc_plans(c,policies):
    """Only physical sets positively recorded/read with the cancelled policy."""
    from archive_inventory import member
    wanted=[(policy_id(p),descriptors({'wallet_name':'new','descriptors':[{'desc':p[k]} for k in ('receive_descriptor','change_descriptor')]})) for p in policies.values()];saved=c.store.read();available=dict(saved.get('verified_archive_discs',{}));pool=archives(c)
    for archive,catalog in (pool.catalogs.items() if pool else []):available.setdefault(archive,{'members':[member(r) for r in catalog.values()],'disc_count':1,'retired_members':{member(r)['member_id']:r.get('retired_policy_hashes',[]) for r in catalog.values()}})
    plans=[]
    for archive,row in available.items():
        members=row.get('members',[])
        if any(any(pid not in row.get('retired_members',{}).get(m['member_id'],[]) and w<=descriptors(raw) for pid,w in wanted) for m in members for raw in [m['public_wallet'],*m.get('related_policies',[])]):plans.append({'archive_id':archive,'names':[m['name'] for m in members],'members':sorted(m['member_id'] for m in members),'copies':row.get('disc_count',1),'replacement_required':True})
    return sorted(plans,key=lambda r:r['archive_id'])

def facts(c,p):
    original=proposals(c,p);rows=[];saved=c.store.read()
    for key,proposal in original.items():
        local=wallets(c,proposal);record={**saved['completed'],**saved['pending']}.get(key,{})
        expected=record.get('updated_wallets',record.get('batch_completed',[]))
        missing=set(expected)-{w['wallet'] for w in local}
        if missing:raise ValueError('Load the original related archive signers before cancellation: '+', '.join(sorted(missing)))
        proof=funding(c,proposal,local)
        rows.append({'request_hash':key,'policy_hash':policy_id(proposal),'wallets':[{'wallet':w['wallet'],'installed':w['installed']} for w in local],**proof})
    burner=c.setup.burner;active=bool(burner.thread and burner.thread.is_alive())
    for plan in (discs:=disc_plans(c,original)):
        proof=getattr(c,'archive_ops',None) and c.archive_ops.verified_replacements.get(plan['archive_id'],{}) or {}
        plan['replacement_verified']=bool(proof.get('readback_verified') and set(plan['members'])<=set(proof.get('members',[])))
    return {'builder':'wallet','policy_refresh':True,'policies':rows,'funded':any(r['funded'] for r in rows),'discs':discs,'active_disc_write':active,'request_hashes':list(original),'wallets':[],'psbts':[],'untracked_operations':[],'untracked_exports':[],'retains_keys':True,'retains_descriptors':True}

def review(c,key):
    row=c.store.read()['pending'][key]
    if row['state'] not in ('pending','policy_retired'):raise ValueError('Cancellation was attempted. Reconcile locally before retrying.')
    f=facts(c,row['proposal']);f['retired']=row['state']=='policy_retired';f['destroyed_archives']=row.get('destroyed_archives',[]);c.reviews[key]=(digest(f),time.time())
    return {'kind':'builder_cancel','id':key,'cancellation':f}

def complete(c,key,p,original,destroyed,status='complete'):
    from setup_messages import sign
    message={'version':1,'cancellation_id':p['cancellation_id'],'request_hash':key,'status':status,'policy_request_hashes':sorted(original),'retired_policy_hashes':sorted({policy_id(v) for v in original.values()}) if status=='complete' else [],'descriptors_retained':True,'keys_retained':True,'destroyed_archives':sorted(destroyed)}
    item={'kind':'wallet_policy_refresh_cancel_result','payload':sign(c.store,message)}
    with c.store.edit() as saved:
        if len(saved['outbox'])>=128:raise ValueError('Wallet Server outbox is full; local cancellation outcome retained.')
        for original_key in original:saved['pending'].pop(original_key,None);c.ops.prepared.pop(original_key,None)
        for ident,value in list(saved['outbox'].items()):
            previous_message=value.get('payload',{}).get('message',{})
            if isinstance(previous_message,dict) and previous_message.get('request_hash') in original:saved['outbox'].pop(ident)
        saved['outbox'][digest(item)]=item;saved['pending'].pop(key,None);saved['completed'][key]={'kind':'builder_cancel','at':time.time(),'policy_cleanup':message}
    return {'message':'Funded policy retained without alteration; cleanup request dismissed locally.' if status=='retained_funded' else 'Unused vault receiving policy retired. All signing wallets, keys and recovery history were retained. Required disc destruction was confirmed locally.'}

def confirm(c,key,action):
    from policy_refresh import transition
    from combined_wallet import extension_requests,local_private_descriptors
    from wallet_setup import secret_dialog
    saved=c.store.read();row=saved['pending'][key];p=row['proposal'];original=proposals(c,p);current=facts(c,p)
    if current['active_disc_write']:raise ValueError('Wait for the current disc write/read-back before cancellation.')
    if current['funded'] and action=='retain':
        if row['state']=='policy_retired' and any(policy_id(v) in saved.get('retired_policies',{}) for v in original.values()):raise ValueError('Funds arrived after retirement. Retained keys and descriptors still monitor them; explicitly approve this receiving policy again before dismissing cleanup.')
        return complete(c,key,p,original,[],status='retained_funded')
    if current['funded']:raise ValueError('The new vault policy is funded, including confirmed or unconfirmed funds. Cancellation is not allowed.')
    if row['state']=='policy_retired':
        if action.startswith('replace:'):
            archive=action[8:];plan=next((d for d in current['discs'] if d['archive_id']==archive),None)
            if not plan:raise ValueError('The disc is not part of this exact cancellation.')
            pool=archives(c)
            from archive_format import identity
            catalog=pool.catalogs.get(archive)
            if not catalog:raise ValueError('Read the complete original disc before preparing its replacement.')
            ids=[]
            for member_id in plan['members']:
                choice=next((ident for ident,record in pool.loaded.items() if identity(record['recovery'])==member_id and c.archive_ops.covers(record['recovery'],catalog[member_id])),None)
                if choice is None:raise ValueError('Read and load every original disc member before preparing its replacement.')
                ids.append(choice)
            return c.archive_ops.queue_loaded(ids,True)
        if action.startswith('destroy:'):
            archive=action[8:];plan=next((d for d in current['discs'] if d['archive_id']==archive),None)
            proof=c.archive_ops.verified_replacements.get(archive,{}) if getattr(c,'archive_ops',None) else {}
            if not plan or not proof.get('readback_verified') or not set(plan['members'])<=set(proof.get('members',[])):raise ValueError('A verified replacement preserving every wallet is required before confirming destruction.')
            with c.store.edit() as state:
                pending=state['pending'][key];pending['destroyed_archives']=sorted(set(pending.get('destroyed_archives',[]))|{archive})
            destroyed=c.store.read()['pending'][key]['destroyed_archives']
            if {d['archive_id'] for d in current['discs']}<=set(destroyed):return complete(c,key,p,original,destroyed)
            return {'message':'Destruction recorded locally for this disc. Other matching discs still require a verified replacement and destruction confirmation.'}
        raise ValueError('Complete the listed replacement and destruction steps.')
    checked=c.reviews.get(key)
    if row['state']!='pending' or action!='delete' or not checked or time.time()-checked[1]>600:raise ValueError('Review this policy cancellation again before retiring it.')
    shown={**current,'retired':False,'destroyed_archives':row.get('destroyed_archives',[])}
    if digest(shown)!=checked[0]:raise ValueError('Local policy, funding or disc facts changed. Review the cancellation again.')
    # No installed generation or physical backup exists to retire. A fresh
    # funding check above is sufficient; do not run it two more times around
    # an empty mutation plan. Recheck local installations before acknowledging.
    if not current['discs'] and all(not w['installed'] for policy in current['policies'] for w in policy['wallets']):
        for request,proposal in original.items():
            expected=next(v['wallets'] for v in current['policies'] if v['request_hash']==request)
            actual=[{'wallet':w['wallet'],'installed':w['installed']} for w in wallets(c,proposal)]
            if actual!=expected:raise ValueError('Local policy installation changed. Review the cancellation again.')
        return complete(c,key,p,original,[])
    plans=[];started=False
    try:
        for request,proposal in original.items():
            for target in wallets(c,proposal):
                if not target['installed']:continue
                pool=archives(c);record=pool.loaded[target['archive']] if target['archive'] else None;core=record['node'].core if record else c.core;route=record['routes'][target['wallet']] if record else target['wallet'];password=None;rows=None
                plan={'proposal':proposal,'core':core,'route':route,'record':record,'password':None,'private':target['private'],'wallet':target['wallet']};plans.append(plan)
                try:
                    if target['private']:
                        password=secret_dialog('Unlock '+target['wallet']+' to retire an unused receiving policy. Signing keys and all policies will be retained.',c.environment);plan['password']=password;rpc(core,'walletpassphrase',[password,120],route);rows=record['node'].private_descriptors(route) if record else local_private_descriptors(core,route)
                        new=extension_requests(rows,[proposal['receive_descriptor'],proposal['change_descriptor']],'now');old=extension_requests(rows,proposal['previous_descriptors'],'now')
                    else:
                        new=[{'desc':proposal[field],'timestamp':'now','active':False,'internal':bool(i),'range':[0,999]} for i,field in enumerate(('receive_descriptor','change_descriptor'))];old=[{'desc':desc,'timestamp':'now','active':True,'internal':bool(i),'range':[0,999]} for i,desc in enumerate(proposal['previous_descriptors'])]
                    for item in new:item['active']=False
                    end=max([999]+[v.get('range',[0,999])[-1] for v in target['public']['descriptors'] if isinstance(v.get('range'),list)])
                    for item in new+old:item['range']=[0,end]
                    plan['requests']=new+old
                finally:
                    rows=None;password=None
                    if target['private']:rpc(core,'walletlock',[],route)
        # Password entry may take time; establish funding again before mutation.
        if facts(c,p)['funded']:raise ValueError('The new vault policy received funds. Cancellation is not allowed.')
        with c.store.edit() as state:state['pending'][key]['state']='attempted'
        started=True
        for plan in plans:
            core=plan['core'];route=plan['route'];proposal=plan['proposal']
            try:
                if plan['private']:rpc(core,'walletpassphrase',[plan['password'],120],route)
                imported=rpc(core,'importdescriptors',[plan['requests']],route,timeout=86400)
                if len(imported)!=4 or any(not v.get('success') for v in imported):raise ValueError('Core did not confirm policy retirement.')
            finally:
                if plan['private']:rpc(core,'walletlock',[],route)
            raw=rpc(core,'listdescriptors',[False],route);active=descriptors({'wallet_name':route,'descriptors':[v for v in raw['descriptors'] if v.get('active')]});old=descriptors({'wallet_name':'old','descriptors':[{'desc':v} for v in proposal['previous_descriptors']]})
            if not old<=active:raise ValueError('The previous receiving policy was not restored.')
            pid=policy_id(proposal)
            with c.store.edit() as state:state.setdefault('retired_policies',{})[pid]={'request_hash':digest(proposal),'receive_descriptor':proposal['receive_descriptor'],'change_descriptor':proposal['change_descriptor'],'previous_descriptors':proposal['previous_descriptors'],'wallets':sorted({*state.get('retired_policies',{}).get(pid,{}).get('wallets',[]),plan['wallet']})}
            if plan['record']:
                record=plan['record'];record['recovery']['retired_policy_hashes']=sorted(set(record['recovery'].get('retired_policy_hashes',[]))|{pid})
                for ext in record['recovery'].get('policy_extensions',[]):
                    if policy_id(ext)==pid:ext['retired']=True
                record['review']['height']=__import__('wallet_setup_signing').restricted(proposal['previous_descriptors'][0])['height']
        if facts(c,p)['funded']:raise ValueError('Funds arrived during cancellation. Policies and keys were retained; reconcile before continuing.')
        # Unstarted replacement jobs captured the now-cancelled policy. Remove
        # only those exact local captures; unrelated queued backups stay intact.
        archive_ops=getattr(c,'archive_ops',None)
        if archive_ops:
            wanted={policy_id(v) for v in original.values()}
            stale={k for k,v in archive_ops.jobs.items() if v.get('source_archive') and v.get('request') is None and v['phase']=='queued' and any(policy_id(ext) in wanted for ext in v['recovery'].get('policy_extensions',[]))}
            if stale:
                c.setup.burner.cancel_members(stale)
                for ident in stale:archive_ops.jobs.pop(ident)
        with c.store.edit() as state:state['pending'][key]['state']='policy_retired'
        if current['discs']:return {'message':'Unused receiving policy retired; all keys and history retained. Complete verified replacement and physical destruction for the listed discs.'}
        return complete(c,key,p,original,[])
    except Exception:
        if started:raise ValueError('Policy retirement is incomplete or funding changed. All keys and descriptors were retained; inspect locally before any retry.') from None
        raise
    finally:
        for plan in plans:plan['password']=None;plan['requests']=None
        plans.clear()


def restore_retired(node,name,recovery):
    """Inside an already locally unlocked archive; never drops descriptors."""
    from policy_refresh import validate_extensions
    from combined_wallet import extension_requests
    effective=validate_extensions(recovery);rows=node.private_descriptors(name);requests=[]
    try:
        for ext in recovery.get('policy_extensions',[]):
            if policy_id(ext) in recovery.get('retired_policy_hashes',[]):
                old=extension_requests(rows,[ext['receive_descriptor'],ext['change_descriptor']],'now')
                for item in old:item['active']=False
                requests+=old
        requests+=extension_requests(rows,effective,'now');installed=rpc(node.core,'importdescriptors',[requests],name)
        if len(installed)!=len(requests) or any(not r.get('success') for r in installed):raise ValueError('Core could not restore the retired-policy receiving state. All keys retained.')
    finally:rows=None;requests=None
