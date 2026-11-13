"""Locally recorded key ownership, checked before any managed private SSH transfer.

Only public record identifiers are retained. This reader never reads private
record values, and never modifies a database. Core still verifies the received
wallet, complete public policy and history before restoration is recorded.
"""
import io,secrets,tempfile
from pathlib import Path
from approval_store import digest
from public_policy import descriptors
from wallet_ops import rpc
from core_history import database,compact_read,supported


def policy_id(raw):return digest(sorted(descriptors(raw)))


def requested(p):
    value=p.get('restoration')
    if value is None:return False
    if not isinstance(value,dict) or set(value)!={'version','policy_id'} or type(value['version']) is not int or value['version']!=1 or value['policy_id']!=policy_id(p['public_wallet']) or p.get('transfer_version') not in (2,3):raise ValueError('Invalid direct SSH restoration binding.')
    return True


def backup_keys(path):
    """Read public key identities from record KEYS, never encrypted/plain values."""
    ids=set();plaintext=False;master=False
    with database(Path(path).resolve()) as db:
        for (key,) in db.execute('select key from main'):
            stream=io.BytesIO(key);n=compact_read(stream);kind=stream.read(n)
            if kind==b'mkey':master=True;continue
            if kind in (b'key',b'ckey',b'wkey'):
                n=compact_read(stream);pub=stream.read(n)
                if n not in (33,65) or len(pub)!=n or stream.read():raise ValueError('Invalid legacy private-key identity.')
                from vendor.embit.ec import PublicKey
                PublicKey.parse(pub);ids.add(digest({'legacy_public_key':pub.hex()}));plaintext|=kind!=b'ckey';continue
            if kind not in (b'walletdescriptorkey',b'walletdescriptorckey'):continue
            descriptor=stream.read(32);n=compact_read(stream);pub=stream.read(n)
            if len(descriptor)!=32 or n not in (33,65) or len(pub)!=n or stream.read():raise ValueError('Invalid Core descriptor key identity.')
            from vendor.embit.ec import PublicKey
            PublicKey.parse(pub)
            ids.add(digest({'descriptor':descriptor.hex(),'public_key':pub.hex()}));plaintext|=kind==b'walletdescriptorkey'
    if len(ids)>4096:raise ValueError('Too many private-role key identities for a single restoration.')
    return {'private_key_ids':sorted(ids),'encrypted':bool(ids) and master and not plaintext}


def capture(core,names):
    from peer_wallet import work_dir
    from core_ram_path import for_core
    supported(core);bindings=[]
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as folder:
        for index,name in enumerate(sorted(names)):
            raw=rpc(core,'listdescriptors',[False],name);info=rpc(core,'getwalletinfo',[],name)
            path=Path(folder)/(str(index)+'.dat');rpc(core,'backupwallet',[for_core(core,path)],name)
            keys=backup_keys(path);path.unlink()
            if info.get('scanning') or not raw.get('descriptors'):raise ValueError('Finish this wallet’s scan before recording its original signer assignment.')
            if not info.get('private_keys_enabled') and keys['private_key_ids']:raise ValueError('A public-only wallet unexpectedly contains private-key records.')
            row={'policy_id':policy_id(raw),'wallet_name':name,'private_key_ids':keys['private_key_ids'],'had_private':bool(keys['private_key_ids']),'restored':False}
            row['binding_id']=digest({k:v for k,v in row.items() if k!='restored'});bindings.append(row)
    return bindings


def candidates(state,raw):
    ident=policy_id(raw);found=[]
    for retirement_id,row in state.get('local_retirements',{}).items():
        if row['state'] not in ('complete','restored'):continue
        for binding in row.get('wallet_bindings',[]):
            if binding['policy_id']==ident and not binding['restored']:found.append((retirement_id,binding))
    return found


def offer(store,p,watch):
    if not requested(p):return None
    rows=candidates(store.read(),p['public_wallet'])
    if not rows:raise ValueError('No independently recorded original wallet assignment exists for this restoration. Wallet Server cannot supply that authority; use locally verified original recovery evidence.')
    allowed=[r for _,r in rows if watch or r['had_private']]
    if not allowed:raise ValueError('This Agent did not originally hold a private signer for this wallet. Choose watch-only restoration; private-role replication is forbidden.')
    return {'version':1,'transfer_id':p['transfer_id'],'policy_id':policy_id(p['public_wallet']),'challenge':secrets.token_hex(32),'watch_only':watch,'bindings':[{'binding_id':r['binding_id'],'private_key_ids':r['private_key_ids']} for r in allowed]}


def validate_offer(p,value,watch):
    if not requested(p) or not isinstance(value,dict) or set(value)!={'version','transfer_id','policy_id','challenge','watch_only','bindings'} or type(value['version']) is not int or value['version']!=1 or value['transfer_id']!=p['transfer_id'] or value['policy_id']!=policy_id(p['public_wallet']) or type(value['watch_only']) is not bool or value['watch_only']!=watch:raise ValueError('The receiving Agent did not authorise this exact SSH restoration.')
    import re
    if not isinstance(value['challenge'],str) or not re.fullmatch('[0-9a-f]{64}',value['challenge']) or not isinstance(value['bindings'],list) or not 1<=len(value['bindings'])<=128:raise ValueError('Invalid receiving restoration permit.')
    for row in value['bindings']:
        if not isinstance(row,dict) or set(row)!={'binding_id','private_key_ids'} or not re.fullmatch('[0-9a-f]{64}',str(row['binding_id'])) or not isinstance(row['private_key_ids'],list) or len(row['private_key_ids'])>4096 or len(set(row['private_key_ids']))!=len(row['private_key_ids']) or any(not re.fullmatch('[0-9a-f]{64}',str(i)) for i in row['private_key_ids']):raise ValueError('Invalid original private-role identity.')
    return value


def permit_backup(p,offer,path):
    validate_offer(p,offer,False);facts=backup_keys(path)
    if not facts['encrypted']:raise ValueError('A private restoration requires an encrypted backup with private keys.')
    rows=[r for r in offer['bindings'] if r['private_key_ids']==facts['private_key_ids']]
    if not rows:raise ValueError('This backup contains a different signer or additional private keys. Restoring it would change the original Agent role; no wallet file was sent or loaded.')
    return {'permit_hash':digest(offer),'binding_id':rows[0]['binding_id']}


def verify_received(p,offer,path,proof):
    chosen=permit_backup(p,offer,path)
    if proof!=chosen:raise ValueError('Private wallet bytes differ from the receiver’s current restoration authorisation.')
    return chosen['binding_id']


def finish(core,store,p,name,binding_id,offer):
    rows=candidates(store.read(),p['public_wallet'])
    if not any(b['binding_id']==binding_id for _,b in rows):raise ValueError('Original local signer assignment changed before restoration completed.')
    raw=rpc(core,'listdescriptors',[False],name);info=rpc(core,'getwalletinfo',[],name);tip=rpc(core,'getblockchaininfo')
    if policy_id(raw)!=policy_id(p['public_wallet']) or info.get('scanning') or info.get('lastprocessedblock',{}).get('height',-1)<tip['blocks'] or not offer['watch_only'] and not info.get('private_keys_enabled'):raise ValueError('Restored wallet policy, capability or current-chain checks failed.')
    with store.edit() as saved:
        for retirement_id,binding in rows:
            if binding['binding_id']!=binding_id:continue
            row=saved['local_retirements'][retirement_id]
            for item in row['wallet_bindings']:
                if item['binding_id']==binding_id or offer['watch_only'] and item['policy_id']==policy_id(p['public_wallet']):item['restored']=True
            # One available original role is enough to restore local active status.
            # Other missing roles remain independently pending; no quorum is required.
            row['state']='restored'
