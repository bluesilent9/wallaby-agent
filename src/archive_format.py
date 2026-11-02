"""Strict encrypted multi-wallet container metadata; no executable archive paths."""
import copy,re
from approval_store import digest
from build8_policy import descriptors

MAX_ENTRIES=15
HEX=re.compile('[0-9a-f]{64}')

def entry_kind(recovery):
    return 'node_wallet' if recovery.get('kind')=='node_wallet' else 'setup_role'

def identity(recovery):
    if entry_kind(recovery)=='setup_role':
        return digest({'policy_hash':recovery['policy_hash'],'role':recovery['physical_cosigner_file']})
    return digest({'public_wallet':recovery['public_wallet'],'chain':recovery['chain']})

def validate_node(recovery):
    required={'version','kind','chain','name','policy_hash','public_wallet','labels'}
    if not isinstance(recovery,dict) or not required<=set(recovery)<=required|{'policy_extensions','public_policies','policy_labels','display_name'} or recovery['version']!=1 or recovery['kind']!='node_wallet':raise ValueError('Invalid node-wallet recovery record.')
    from vault_policy import NETWORK,text
    if recovery['chain'] not in NETWORK:raise ValueError('Invalid archive network.')
    text(recovery['name'],256);descriptors(recovery['public_wallet'])
    if recovery['policy_hash']!=digest(recovery['public_wallet']):raise ValueError('Archive public descriptor code differs.')
    from wallet_labels import validate_labels
    validate_labels(recovery['labels'])
    if 'display_name' in recovery:__import__('wallet_rename').name(recovery['display_name'])
    if 'public_policies' in recovery:descriptors(recovery['public_policies'])
    if 'policy_labels' in recovery:validate_labels(recovery['policy_labels'])
    return recovery

def validate(value):
    if not isinstance(value,dict) or set(value)!={'version','format','policy_hash','entries','replaces'} or value['version']!=2 or value['format']!='wallaby-archive-set':raise ValueError('Unsupported archive set.')
    entries=value['entries']
    if not isinstance(entries,list) or not 1<=len(entries)<=MAX_ENTRIES:raise ValueError('Use 1 to 15 wallets per archive set.')
    ids=set();identities=set()
    for e in entries:
        if not isinstance(e,dict) or set(e)!={'id','kind','name','recovery'} or not HEX.fullmatch(str(e['id'])) or e['id'] in ids or e['kind']!=entry_kind(e['recovery']):raise ValueError('Invalid or duplicate archive entry.')
        ids.add(e['id']);r=e['recovery'];ident=identity(r)
        if ident in identities:raise ValueError('An archive contains a duplicate wallet role.')
        identities.add(ident)
        if e['kind']=='node_wallet':validate_node(r)
        elif r.get('version')!=1 or not HEX.fullmatch(str(r.get('physical_cosigner_file'))):raise ValueError('Invalid physical-role archive.')
        from vault_policy import text
        text(e['name'],256)
    if not isinstance(value['replaces'],list) or len(value['replaces'])>32 or len(set(value['replaces']))!=len(value['replaces']) or any(not HEX.fullmatch(str(v)) for v in value['replaces']):raise ValueError('Invalid replaced-archive list.')
    if digest({k:v for k,v in value.items() if k!='policy_hash'})!=value['policy_hash']:raise ValueError('Archive-set code does not match its contents.')
    return value

def bundle(items,replaces=()):
    entries=[];wallets={};seen_policies={}
    for job_id,files,recovery in items:
        if len(files)!=1:raise ValueError('Each archive row must identify one locally verified signing wallet.')
        r=copy.deepcopy(recovery);ident=digest({'job':job_id,'recovery':r});kind=entry_kind(r)
        # Combining independent wallets is supported; accidentally putting several
        # threshold roles for the same policy onto one disc is refused.
        if kind=='setup_role':
            old=seen_policies.setdefault(r['policy_hash'],r['physical_cosigner_file'])
            if old!=r['physical_cosigner_file']:raise ValueError('Choose only one signing role per shared wallet on a disc. Put its other threshold roles on separate discs.')
        name=r.get('display_name',r['name'] if kind=='node_wallet' else r['proposal']['name'])
        entries.append({'id':ident,'kind':kind,'name':name,'recovery':r});wallets[ident]=next(iter(files.values()))
    value={'version':2,'format':'wallaby-archive-set','entries':entries,'replaces':sorted(set(replaces))};value['policy_hash']=digest(value);validate(value)
    return wallets,value
