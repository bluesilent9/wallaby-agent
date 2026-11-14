"""Extinct history discovery is a hint; authenticated SSH supplies all records.

No summary or Server assertion can approve extinction, replace labels or delete
recipient-only history. Whole-history coverage comes from a locally verified
scan or the explicitly approved, authenticated direct peer's verified coverage.
"""
import re
from approval_store import digest
from wallet_ops import rpc
from wallet_labels import fixed_address,read_labels
from extinct_upgrade import snapshot,valid


def summary(core,wallet):
    from extinct_sync import ALIASES
    if wallet not in ALIASES:raise ValueError('Select the exact local Extinct archive for history comparison.')
    state=snapshot(core,wallet,with_transactions=True);chain=rpc(core,'getblockchaininfo')
    if state['info'].get('lastprocessedblock',{}).get('height',-1)<chain['blocks']:raise ValueError('Wait for the Extinct archive to process the current node tip before comparing histories.')
    # One consistent offline public backup, rather than one RPC per transaction.
    # These are discovery fingerprints only; transfer validates every header.
    transactions=state['transactions']
    labels=read_labels(core,wallet,state['raw'],[])
    result={'version':1,'chain':chain['chain'],'addresses':len(state['addresses']),
        'transactions':len(transactions),'address_hash':digest(state['addresses']),
        'transaction_hash':digest(transactions),'label_hash':digest(labels),
        'history_complete':valid(core,state) and all(r['blockhash']!='0'*64 for r in transactions)}
    result['digest']=digest(result)
    return result


def coverage(core,wallet,wanted,txids):
    """Project verified whole local coverage onto exactly the approved addresses."""
    state=snapshot(core,wallet);chain=rpc(core,'getblockchaininfo')
    if not valid(core,state) or not set(wanted)<=set(state['addresses']):raise ValueError('Upgrade and verify the source Extinct archive before sending a complete history update.')
    if set(wanted)==set(state['addresses']) and set(txids)!=set(state['txids']):raise ValueError('The complete source history changed or contains records absent from this transfer. Review the archive again; no complete update was sent.')
    marker={'version':1,'chain':chain['chain'],'addresses':sorted(wanted),'txids':sorted(txids),'tip':chain['bestblockhash'],'height':chain['blocks']}
    if state['marker'].get('basis')=='trusted_direct_snapshot':marker['basis']='trusted_direct_snapshot'
    marker['checksum']=digest(marker)
    return marker


def validate_coverage(core,value,wanted,txids):
    fields={'version','chain','addresses','txids','tip','height','checksum'}
    if not isinstance(value,dict) or set(value)-{'basis'}!=fields or value.get('basis','local_scan') not in ('local_scan','trusted_direct_snapshot') or type(value['version']) is not int or value['version']!=1 or value['checksum']!=digest({k:v for k,v in value.items() if k!='checksum'}):raise ValueError('Invalid direct Extinct history coverage.')
    if value['addresses']!=sorted(wanted) or value['txids']!=sorted(txids) or type(value['height']) is not int or value['height']<0 or not isinstance(value['tip'],str) or not re.fullmatch('[0-9a-f]{64}',value['tip']):raise ValueError('Direct history coverage differs from the exact authorised addresses or records.')
    chain=rpc(core,'getblockchaininfo')
    if value['chain']!=chain['chain'] or chain.get('initialblockdownload') or chain['blocks']!=chain['headers']:raise ValueError('Finish local chain synchronisation before accepting Extinct history coverage.')
    header=rpc(core,'getblockheader',[value['tip']])
    if header.get('confirmations',0)<=0 or header.get('height')!=value['height']:raise ValueError('Direct history coverage is not anchored to the locally validated active chain.')
    return value


def preflight(core,store,p,packet):
    """Refuse unknown local extinction or uncovered legacy history before imports."""
    from local_extinction import eligible
    from extinct_sync import archive_name
    eligible(core,store,p['public_wallet'],verified_history=packet['coverage'])
    covered=set(packet['coverage']['addresses'])
    target=archive_name(core)
    directories={w['name'] for w in rpc(core,'listwalletdir')['wallets']}
    if target in directories:
        if target not in rpc(core,'listwallets'):raise ValueError('Load the existing Extinct archive before updating its history.')
        old=snapshot(core,target)
        if valid(core,old):covered.update(old['addresses'])
        if not set(old['addresses'])<=covered:raise ValueError('The receiving archive has additional legacy entries without verified coverage. Upgrade those entries locally first; no history was replaced.')
    return covered


def install_packet(core,store,key,p,details,packet):
    from extinct_sync import import_watch
    from core_history import install
    from extinct_upgrade import certify
    covered=preflight(core,store,p,packet)
    name,_,merged=import_watch(core,store,key,p,details,native=True,coverage=packet['coverage'])
    install(core,store,name,packet['records'],packet['manifest'],allow_unfunded=True,trusted_inventory=packet['version']>=4)
    # Native install preserves the entire receiving database. Certify only the
    # independently covered union after Core has read back every incoming row.
    basis=packet['coverage'].get('basis','local_scan')
    old=snapshot(core,name)
    if (old['marker'] or {}).get('basis')=='trusted_direct_snapshot':basis='trusted_direct_snapshot'
    certify(core,store,name,covered,basis=basis)
    return name
