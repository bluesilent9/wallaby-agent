"""Public pre-reindex wallet evidence; never a replacement wallet/key backup.

Used only to retain the receiver's prior validated-chain anchor during a locally
approved recovery handover. It cannot certify an Extinct scan or delete a wallet.
"""
import hashlib,tempfile
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from core_history import database,TX_KEY,parse_record
from public_policy import descriptors


def wallet(core,name):
    from peer_wallet import work_dir
    from core_ram_path import for_core
    info=rpc(core,'getwalletinfo',[],name);raw=rpc(core,'listdescriptors',[False],name);records={};locators={};stored=[]
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as folder:
        path=Path(folder)/'checkpoint.dat';rpc(core,'backupwallet',[for_core(core,path)],name)
        with database(path) as db:
            import io
            from core_history import compact_read
            for key,value in db.execute('select key,value from main'):
                f=io.BytesIO(key);kind=f.read(compact_read(f))
                if kind==b'walletdescriptor' and len(key)==49:
                    v=io.BytesIO(value);stored.append(hashlib.sha256(v.read(compact_read(v))).hexdigest())
                if kind in (b'bestblock',b'bestblock_nomerkle') and not f.read():locators[kind.decode()]=value.hex()
            for key,value in db.execute('select key,value from main where substr(key,1,3)=?',(TX_KEY,)):
                tx,_=parse_record(key,value);records[key[3:][::-1].hex()]=hashlib.sha256(tx.serialize()).hexdigest()
                if len(records)>100000:raise ValueError('Wallet recovery checkpoint exceeds its bounded transaction limit.')
    return {'db_policy':digest(sorted(stored)),'locators':locators,'policy':digest(sorted(descriptors(raw))),'private':bool(info.get('private_keys_enabled')),'records':records,'processed':info.get('lastprocessedblock',{}).get('height',-1),'scanning':bool(info.get('scanning'))}


def capture(core,store):
    from extinct_sync import ALIASES
    from wallet_recovery import persistent_wallets
    chain=rpc(core,'getblockchaininfo');result={'chain':chain['chain'],'height':chain['blocks'],'hash':chain['bestblockhash'],'wallets':{}}
    total=0
    for name in persistent_wallets(core):
        if name in ALIASES:continue # Incomplete archive coverage is supplied separately.
        row=wallet(core,name);total+=len(row['records'])
        if total>100000:raise ValueError('Combined wallet recovery checkpoints exceed the bounded history limit.')
        if row['scanning'] or row['processed']<chain['blocks']:continue
        result['wallets'][name]=row
    return result


def floor(core,store):
    """A pre-reindex anchor is useful only while original public data still matches."""
    from extinct_sync import ALIASES
    from chain_clone_files import CloneError
    from wallet_recovery import persistent_wallets
    checkpoint=store.read().get('recovery',{}).get('plan',{}).get('clone_checkpoint')
    if not checkpoint:return None
    if checkpoint['chain']!=rpc(core,'getblockchaininfo')['chain']:raise CloneError('The recovery checkpoint is on a different chain.')
    for name in persistent_wallets(core):
        if name in ALIASES:continue
        before=checkpoint['wallets'].get(name)
        if not before:raise CloneError('A loaded wallet has no complete pre-reindex checkpoint. Its historical recovery cannot be silently replaced by a pruned clone.')
        after=wallet(core,name)
        if before['db_policy']!=after['db_policy'] or before['policy']!=after['policy'] or before['private']!=after['private'] or any(after['records'].get(k)!=v for k,v in before['records'].items()):raise CloneError('An original wallet changed or lost records after recovery began. Its private data was not replaced and recovery remains pending.')
    return checkpoint
