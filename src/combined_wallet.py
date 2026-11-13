"""Install one encrypted signing wallet containing the complete approved policy.

Private descriptors exist only inside the protected worker and its offline Core.
The production node receives the encrypted wallet backup, never a plaintext key.
"""
import hashlib
from pathlib import Path
from wallet_ops import rpc
from public_policy import descriptors
from vendor.embit.descriptor import Descriptor
from vendor.embit.descriptor.checksum import checksum
from vendor.embit.descriptor.arguments import Key

LAYOUT='combined-policy-key-v1'

def account_key(private,public):
    """Core may export a master xprv with hardened suffix, not an account xprv."""
    expected=Key.from_string(public)
    path=private.allowed_derivation.indexes if private.allowed_derivation else []
    suffix=expected.allowed_derivation.indexes if expected.allowed_derivation else []
    if not suffix or path[-len(suffix):]!=suffix:raise ValueError('Private signing derivation differs from the approved public role.')
    prefix=path[:-len(suffix)]
    if any(type(i) is not int for i in prefix):raise ValueError('Private signing account has an unexpected derivation.')
    result=Key(private.key.derive(prefix),expected.origin,expected.allowed_derivation)
    if str(result.to_public())!=str(expected):raise ValueError('The unlocked account differs from its locally signed contribution.')
    return result

def wallet_name(proposal,role=None):
    from wallet_rename import name
    return name(proposal['name'] if role is None or len(proposal['cosigners'])==1 else proposal['name']+' '+role['name']+' - Signer')

def public_policy(facts):
    return {'wallet_name':'approved','descriptors':[{'desc':facts[field]} for field in ('receive_descriptor','change_descriptor')]}

def role_wallet(setup,session,role,facts,destination=None,target=None):
    from wallet_setup import secret_dialog
    source=session['wallets'][role['id']]['name'];core=session['core'].core
    contribution=next(e['message'] for e in session['contributions'] if e['message']['cosigner_id']==role['id'])
    password=secret_dialog('Unlock signing role to install its complete wallet policy: '+role['name']+'\nWallet: '+session['proposal']['name'],setup.environment)
    private=None;requests=None;branches=None
    try:
        rpc(core,'walletpassphrase',[password,120],source)
        private=session['core'].private_descriptors(source);branches={}
        for row in private:
            desc=Descriptor.from_string(row['desc'])
            if row.get('active') and row['desc'].startswith('wpkh(') and len(desc.keys)==1 and desc.keys[0].is_private:
                branches[bool(row.get('internal'))]=desc.keys[0]
        requests=[]
        for i,(field,keyfield) in enumerate((('receive_descriptor','receive_key'),('change_descriptor','change_key'))):
            key=branches.get(bool(i))
            if key is None:raise ValueError('The unlocked account lacks its locally signed branch.')
            key=account_key(key,contribution[keyfield])
            body=facts[field].split('#')[0]
            if body.count(contribution[keyfield])!=1:raise ValueError('The approved policy does not contain the exact local signing role once.')
            body=body.replace(contribution[keyfield],str(key))
            requests.append({'desc':body+'#'+checksum(body),'timestamp':session['created_at'],'active':True,'internal':bool(i),'range':[0,999]})
        working=destination or core
        target=target or 'policy_'+hashlib.sha256(role['id'].encode()).hexdigest()[:20]
        rpc(working,'createwallet',{'wallet_name':target,'blank':True,'descriptors':True,'passphrase':password,'load_on_startup':destination is not None})
        if destination is not None:session.setdefault('created_wallets',[]).append(target)
        rpc(working,'walletpassphrase',[password,120],target)
        try:
            result=rpc(working,'importdescriptors',[requests],target,timeout=86400)
            if len(result)!=2 or not all(r.get('success') for r in result):
                from diagnostics import LocalActionFailure
                raise LocalActionFailure('policy_import_incomplete','Core could not install both approved signing policies. The encrypted wallet and RAM keys were retained for local reconciliation.')
        finally:rpc(working,'walletlock',[],target)
        if descriptors(rpc(working,'listdescriptors',[False],target))!=descriptors(public_policy(facts)):raise ValueError('The complete signing wallet differs from the approved public policy.')
        if rpc(working,'getwalletinfo',[],target).get('unlocked_until')!=0:raise ValueError('The completed signing wallet is not encrypted and locked.')
        return target
    finally:
        password=None;private=None;requests=None;branches=None
        rpc(core,'walletlock',[],source)

def private_branch(key,contribution):
    """Bind actual private derivation/account to exactly one approved branch."""
    matches=[]
    for branch,field in enumerate(('receive_key','change_key')):
        try:account_key(key,contribution[field])
        except ValueError:continue
        matches.append(bool(branch))
    if len(matches)!=1:raise ValueError('The archived private signing role differs from the approved disc role.')
    return matches[0]

def verify_private_role(node,name,contribution,policies):
    """Verify every retained generation, even when Core omits inactive flags."""
    approved={}
    for pair in policies:
        if len(pair)!=2:raise ValueError('Both approved policy branches are required.')
        for branch,desc in enumerate(pair):
            canonical=next(iter(descriptors({'wallet_name':'approved','descriptors':[{'desc':desc}]})))
            approved[canonical]=bool(branch)
    rows=node.private_descriptors(name)
    try:
        seen=set()
        for row in rows:
            desc=Descriptor.from_string(row['desc']);private=[k for k in desc.keys if k.is_private]
            if len(private)!=1:raise ValueError('The archived private signing role differs from the approved disc role.')
            branch=private_branch(private[0],contribution)
            # An absent flag is normal for inactive historical Core descriptors.
            # A supplied flag must still agree with the verified derivation.
            if 'internal' in row and (type(row['internal']) is not bool or row['internal']!=branch):raise ValueError('The archived descriptor branch contradicts its approved signing derivation.')
            public=str(desc).replace(str(private[0]),contribution['change_key' if branch else 'receive_key'])
            canonical=next(iter(descriptors({'wallet_name':'approved','descriptors':[{'desc':public+'#'+checksum(public)}]})))
            if canonical not in approved or approved[canonical]!=branch:raise ValueError('The archived signing policy is not in its approved recovery history.')
            seen.add(branch)
        if seen!={False,True}:raise ValueError('The archived signing role lacks a complete receive/change policy.')
    finally:rows=None

def local_private_descriptors(core,name):
    """Fixed internal read following native local consent; no public dispatcher."""
    from node_client import http_json
    from urllib.parse import quote
    result=http_json(core.config['rpc_port'],'/wallet/'+quote(name,safe=''),{'jsonrpc':'2.0','id':'private-local-refresh','method':'listdescriptors','params':[True]},auth=Path(core.config['cookie']).read_text().strip(),response_limit=1024*1024)
    if not isinstance(result,dict) or result.get('error') or not isinstance(result.get('result'),dict):raise ValueError('Core could not read the unlocked local signing policy. No private diagnostic was exported.')
    return result['result']['descriptors']

def extend(core,name,new_descriptors,timestamp,environment,read_private=None):
    """Add a policy generation in-place, retaining every old funded descriptor."""
    from wallet_setup import secret_dialog
    password=secret_dialog('Unlock '+name+' to add the approved policy generation. Existing policies and history are retained.',environment)
    rows=None;requests=None
    try:
        rpc(core,'walletpassphrase',[password,120],name)
        rows=(read_private or (lambda:local_private_descriptors(core,name)))()
        requests=extension_requests(rows,new_descriptors,timestamp)
        result=rpc(core,'importdescriptors',[requests],name,timeout=86400)
        if len(result)!=2 or any(not r.get('success') for r in result):raise ValueError('Core could not confirm the additive signing-policy refresh. Inspect locally before retrying.')
    finally:
        password=None;rows=None;requests=None;rpc(core,'walletlock',[],name)

def extension_requests(rows,new_descriptors,timestamp):
    requests=[]
    for branch,public in enumerate(new_descriptors):
        new=Descriptor.from_string(public);body=str(new);replaced=set()
        for old in rows:
            for key in Descriptor.from_string(old['desc']).keys:
                if not key.is_private:continue
                for wanted in new.keys:
                    try:private=account_key(key,str(wanted))
                    except ValueError:continue
                    text=str(wanted)
                    if text not in replaced:
                        body=body.replace(text,str(private));replaced.add(text)
        if not replaced:raise ValueError('The refreshed policy has no matching local signing role. No public-only policy was imported into a private wallet.')
        requests.append({'desc':body+'#'+checksum(body),'timestamp':timestamp,'active':True,'internal':bool(branch),'range':[0,999]})
    return requests
