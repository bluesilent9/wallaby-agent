"""Whole public Extinct archive coverage, recorded inside its Core wallet backup.

The marker is local scan provenance, not transaction storage or Server evidence.
Unknown/missing provenance is conservative: existing txcount/birthtime is no proof
that every historic address was scanned. Never edits a live wallet database.
"""
import json,tempfile
from pathlib import Path
from approval_store import digest
from wallet_ops import rpc
from wallet_labels import fixed_address,address_only,read_labels
from core_history import database,HISTORY_KEY,TX_KEY,supported


def snapshot(core,wallet):
    from peer_wallet import work_dir
    from core_ram_path import for_core
    supported(core)
    raw=rpc(core,'listdescriptors',[False],wallet);info=rpc(core,'getwalletinfo',[],wallet)
    if info.get('private_keys_enabled') is not False or info.get('scanning') or not address_only(raw):raise ValueError('Whole Extinct history verification requires an idle public address-only wallet.')
    addresses=sorted({fixed_address(r['desc']) for r in raw['descriptors']})
    if len(addresses)>10000:raise ValueError('The Extinct wallet exceeds the bounded migration address limit.')
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as folder:
        path=Path(folder)/'coverage.dat';rpc(core,'backupwallet',[for_core(core,path)],wallet)
        with database(path) as db:
            row=db.execute('select value from main where key=?',(HISTORY_KEY,)).fetchone()
            txids=sorted(k[3:][::-1].hex() for (k,) in db.execute('select key from main where substr(key,1,3)=?',(TX_KEY,)))
    if len(txids)>100000:raise ValueError('The Extinct wallet exceeds the bounded migration transaction limit.')
    marker=None
    if row:
        try:
            if len(row[0])>8*1024*1024:raise ValueError('Oversized coverage record')
            from denial_storage import strict_json
            candidate=strict_json(row[0]);body={k:v for k,v in candidate.items() if k!='checksum'}
            if set(candidate)!={'version','chain','addresses','txids','tip','height','checksum'} or candidate['version']!=1 or candidate['checksum']!=digest(body):raise ValueError('Invalid coverage record')
            if not isinstance(candidate['addresses'],list) or len(candidate['addresses'])>10000 or candidate['addresses']!=sorted(set(candidate['addresses'])) or not all(isinstance(v,str) for v in candidate['addresses']):raise ValueError('Invalid coverage addresses')
            import re
            if not isinstance(candidate['txids'],list) or len(candidate['txids'])>100000 or candidate['txids']!=sorted(set(candidate['txids'])) or not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in candidate['txids']):raise ValueError('Invalid coverage transactions')
            if type(candidate['height']) is not int or candidate['height']<0 or not isinstance(candidate['tip'],str) or not re.fullmatch('[0-9a-f]{64}',candidate['tip']):raise ValueError('Invalid coverage chain')
            marker=candidate
        except (ValueError,TypeError,KeyError,AttributeError):pass
    return {'raw':raw,'info':info,'addresses':addresses,'txids':txids,'marker':marker}


def valid(core,state,allow_additions=False,require_current=True):
    marker=state['marker']
    if not marker:return False
    chain=rpc(core,'getblockchaininfo')
    if chain.get('initialblockdownload') or chain.get('blocks')!=chain.get('headers') or require_current and state['info'].get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:return False
    if marker['chain']!=chain['chain'] or not set(marker['txids'])<=set(state['txids']):return False
    if not set(marker['addresses'])<=set(state['addresses']) or not allow_additions and marker['addresses']!=state['addresses']:return False
    try:header=rpc(core,'getblockheader',[marker['tip']])
    except ValueError:return False
    return header.get('confirmations',0)>0 and header.get('height')==marker['height']


def status(core,wallet):
    state=snapshot(core,wallet)
    chain=rpc(core,'getblockchaininfo')
    if state['info'].get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:
        from diagnostics import LocalActionFailure
        raise LocalActionFailure('extinct_wallet_sync','Wait for the Extinct wallet to finish processing the current node tip, then review extinction again. This is not evidence that a full blockchain download is needed.')
    required=bool(state['addresses']) and not valid(core,state)
    return {'required':required,'addresses':len(state['addresses']),'mode':'download' if required and chain.get('pruned') and chain.get('pruneheight',0)>0 else 'rescan' if required else 'verified'}


def details(core,wallet,state=None):
    state=state or snapshot(core,wallet)
    raw=__import__('copy').deepcopy(state['raw'])
    for row in raw['descriptors']:row['timestamp']=0
    return {'public_wallet':raw,'chain':rpc(core,'getblockchaininfo')['chain'],'funded_outputs':[],'address_labels':read_labels(core,wallet,state['raw'],[]),'vaults':[]}


def check_marker(core,wallet,expected):
    state=snapshot(core,wallet)
    if state['marker']!=expected or state['addresses']!=expected['addresses'] or not set(expected['txids'])<=set(state['txids']):raise ValueError('Core did not retain the complete Extinct history coverage record. No extinction completion was recorded.')
    if not valid(core,state):raise ValueError('The verified Extinct history coverage is no longer on the current chain.')


def certify(core,store,wallet,allowed_addresses):
    state=snapshot(core,wallet);chain=rpc(core,'getblockchaininfo')
    if set(state['addresses'])!=set(allowed_addresses):raise ValueError('Extinct addresses changed during the whole-wallet upgrade. Review again; no completion was recorded.')
    if chain.get('initialblockdownload') or chain['blocks']!=chain.get('headers') or state['info'].get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('Finish Core and Extinct wallet synchronisation before recording complete history.')
    marker={'version':1,'chain':chain['chain'],'addresses':state['addresses'],'txids':state['txids'],'tip':chain['bestblockhash'],'height':chain['blocks']};marker['checksum']=digest(marker)
    if state['marker']==marker:return
    labels=read_labels(core,wallet,state['raw'],[])
    # Exact labels, including LOST text, are checked on the restored replacement.
    manifest={'addresses':[{'address':r['address'],'label':r['label']} for r in labels],'transactions':[]}
    from core_history import install
    install(core,store,wallet,[],manifest,coverage=marker)
    check_marker(core,wallet,marker)
    from activity_log import event
    event('extinction.upgrade','Whole Extinct history verified · addresses='+str(len(state['addresses']))+' · transaction_records='+str(len(state['txids'])))


def upgrade(core,store,wallet):
    state=snapshot(core,wallet)
    if not state['addresses'] or valid(core,state,require_current=False):return
    chain=rpc(core,'getblockchaininfo')
    if chain.get('pruned') and chain.get('pruneheight',0)>0:
        from wallet_retirement import MissingHistory
        raise MissingHistory('The whole Extinct wallet needs legacy history recovery. Prepare local history recovery and authorise This Node on Synchronisation. The active wallet has not been deleted.')
    from wallet_recovery import Recovery
    # Core imports/reloads all fixed descriptors at timestamp zero, rescanning
    # retained history. Success is required before any coverage marker is written.
    Recovery(core,store).register_watch_history(wallet,details(core,wallet,state))
    certify(core,store,wallet,state['addresses'])


def preserved(core,store,p):
    state=snapshot(core,p['wallet']);covered=set()
    if valid(core,state,allow_additions=True):covered.update(state['marker']['addresses'])
    covered.update(r['address'] for r in p['manifest']['addresses'])
    # Newly added entries are independently verified from their active wallet or
    # chain by retirement_phases. All previous entries must already be certified.
    certify(core,store,p['wallet'],covered)
