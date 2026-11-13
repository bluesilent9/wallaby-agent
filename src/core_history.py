"""Core 31 public transaction records, merged only into an offline backup.

Never edits a live Core database. Only Core's tx records cross from a source;
private keys, ranged derivation records and wallet flags never cross with them.
"""
import io,sqlite3,struct,tempfile,hashlib,json,secrets,os
from pathlib import Path
from wallet_ops import rpc
from approval_store import digest
from vendor.embit.transaction import Transaction
MAX_BYTES=256*1024*1024
TX_KEY=b'\x02tx'
DESC_KEY=b'\x10walletdescriptor'
HISTORY_KEY=b'\x12wallaby_history_v1'


def supported(core):
    version=rpc(core,'getnetworkinfo').get('version',0)
    if not 310000<=version<320000:raise ValueError('Native Extinct history merging currently requires Bitcoin Core 31. No wallet database was changed.')


def database(path,write=False):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:raise ValueError('Unsafe or oversized Core history backup.')
    conn=sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True)
    if conn.execute('pragma integrity_check').fetchone()!=('ok',):conn.close();raise ValueError('Core history backup integrity check failed.')
    if conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall()!=[('main',)]:conn.close();raise ValueError('Unsupported Core wallet database schema.')
    return conn


def parse_record(key,value):
    if not isinstance(key,bytes) or len(key)!=35 or not key.startswith(TX_KEY) or not isinstance(value,bytes) or not 10<=len(value)<=4*1024*1024:raise ValueError('Invalid public transaction record.')
    try:
        stream=io.BytesIO(value);tx=Transaction.read_from(stream)
    except Exception:raise ValueError('Cannot decode public Core transaction record.') from None
    if tx.txid()[::-1]!=key[3:]:raise ValueError('Core transaction record hash does not match its contents.')
    # CWalletTx has confirmation and metadata following the raw transaction.
    if len(value)-stream.tell()<36:raise ValueError('Incomplete Core wallet transaction metadata.')
    return tx,stream.tell()


def collect(core,names,txids,folder):
    supported(core);found={};expected=set(txids)
    from core_ram_path import for_core
    for index,name in enumerate(names):
        path=Path(folder)/('source-'+str(index)+'.dat')
        rpc(core,'backupwallet',[for_core(core,path)],name)
        try:
            with database(path) as db:
                for key,value in db.execute('select key,value from main where substr(key,1,3)=?',(TX_KEY,)):
                    txid=key[3:][::-1].hex()
                    if txid not in expected:continue
                    tx,size=parse_record(key,value);own=rpc(core,'gettransaction',[txid,True],name)
                    if tx.serialize().hex()!=own.get('hex') or own.get('confirmations',0)<=0 or not own.get('blockhash'):raise ValueError('Source history changed or is not confirmed. Review extinction again.')
                    header=rpc(core,'getblockheader',[own['blockhash']])
                    if header.get('confirmations',0)<=0:raise ValueError('Source transaction is outside the active chain.')
                    row={'txid':txid,'blockhash':own['blockhash'],'record':value.hex()}
                    if txid in found and found[txid]['blockhash']!=row['blockhash']:raise ValueError('Local wallets disagree about confirmed history.')
                    found.setdefault(txid,row)
        finally:path.unlink(missing_ok=True)
    if set(found)!=expected:raise ValueError('A complete local source transaction record is unavailable. Historical recovery is required; no original wallet was deleted.')
    return [found[k] for k in sorted(found)]


def validate_rows(core,rows,manifest,*,allow_unfunded=False):
    if not isinstance(rows,list) or not rows and not allow_unfunded or len(rows)>10000:raise ValueError('Invalid native history record count.')
    expected={r['txid']:r['blockhash'] for r in manifest['transactions']};found={};outputs={};transactions=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'txid','blockhash','record'} or row['txid'] in found or expected.get(row['txid'])!=row['blockhash']:raise ValueError('Native history differs from the exact approved transaction manifest.')
        try:value=bytes.fromhex(row['record']);key=TX_KEY+bytes.fromhex(row['txid'])[::-1]
        except (TypeError,ValueError):raise ValueError('Malformed native history bytes.') from None
        tx,size=parse_record(key,value)
        if value[size:size+32]!=bytes.fromhex(row['blockhash'])[::-1]:raise ValueError('Native transaction confirmation metadata does not match the approved block.')
        header=rpc(core,'getblockheader',[row['blockhash']])
        if header.get('confirmations',0)<=0:raise ValueError('Native history is outside the active chain.')
        decoded=rpc(core,'decoderawtransaction',[tx.serialize().hex()]);transactions.append(decoded)
        for out in decoded['vout']:
            address=out['scriptPubKey'].get('address')
            if address in {r['address'] for r in manifest['addresses']}:outputs[(row['txid'],out['n'])]=address
        found[row['txid']]=value
    if set(found)!=set(expected) or not allow_unfunded and set(outputs.values())!={r['address'] for r in manifest['addresses']}:raise ValueError('Native history does not cover every approved address and transaction.')
    for tx in transactions:
        if not any((tx['txid'],v['n']) in outputs for v in tx['vout']) and not any((i.get('txid'),i.get('vout')) in outputs for i in tx['vin']):raise ValueError('An unrelated transaction was included in the native history.')
    return found


def compact_read(f):
    raw=f.read(1)
    if not raw:raise ValueError('Truncated Core transaction metadata.')
    n=raw[0]
    if n==253:n=struct.unpack('<H',f.read(2))[0]
    elif n==254:n=struct.unpack('<I',f.read(4))[0]
    elif n==255:n=struct.unpack('<Q',f.read(8))[0]
    if n>4*1024*1024:raise ValueError('Oversized Core transaction metadata.')
    return n

def compact_write(n):
    return bytes([n]) if n<253 else b'\xfd'+struct.pack('<H',n) if n<=65535 else b'\xfe'+struct.pack('<I',n)

def archive_order(value,offset):
    # Let Core assign archive-local ordering, rather than duplicate positions
    # from several source wallets. Receipt times, smart times and comments stay.
    f=io.BytesIO(value);f.seek(offset+32)
    branch=compact_read(f);f.seek(branch*32+4,1)
    if compact_read(f)!=0:raise ValueError('Legacy embedded transaction metadata requires historical recovery before native merging.')
    begin=f.tell();count=compact_read(f);pairs=[]
    if count>10000:raise ValueError('Too many Core transaction metadata fields.')
    for _ in range(count):
        key=f.read(compact_read(f));val=f.read(compact_read(f))
        if key!=b'n':pairs.append((key,val))
    end=f.tell()
    rebuilt=compact_write(len(pairs))+b''.join(compact_write(len(k))+k+compact_write(len(v))+v for k,v in pairs)
    return value[:begin]+rebuilt+value[end:]

def merge_backup(core,path,rows,manifest,*,allow_unfunded=False):
    supported(core);found=validate_rows(core,rows,manifest,allow_unfunded=allow_unfunded)
    from wallet_labels import fixed_address
    with database(path,True) as db:
        for key,value in db.execute('select key,value from main').fetchall():
            try:length=key[0];kind=key[1:1+length].decode()
            except (IndexError,UnicodeError):raise ValueError('Malformed public archive record key.') from None
            if kind in ('key','ckey','mkey','wkey','walletdescriptorkey','walletdescriptorckey'):raise ValueError('Private-key records are forbidden in an Extinct archive.')
            if key.startswith(DESC_KEY) and len(key)==len(DESC_KEY)+32:
                # Core 31 WalletDescriptor: CompactSize descriptor, uint64 birth,
                # int32 next/range start/range end. Preserve all but birth time.
                f=io.BytesIO(value);n=f.read(1)
                if not n:raise ValueError('Invalid archive descriptor record.')
                n=n[0]
                if n==253:n=struct.unpack('<H',f.read(2))[0]
                elif n>=254:raise ValueError('Oversized archive descriptor.')
                desc=f.read(n).decode();pos=f.tell()
                if fixed_address(desc) is None or len(value)!=pos+20:raise ValueError('Extinct archives must contain fixed public addresses only.')
                db.execute('update main set value=? where key=?',(value[:pos]+bytes(8)+value[pos+8:],key))
        for txid,value in found.items():
            key=TX_KEY+bytes.fromhex(txid)[::-1];old=db.execute('select value from main where key=?',(key,)).fetchone()
            if old:
                tx,at=parse_record(key,old[0]);newtx,_=parse_record(key,value)
                if tx.serialize()!=newtx.serialize():raise ValueError('Conflicting transaction already exists in the archive.')
                # Use freshly confirmed metadata when a record moved after reorg.
                if old[0][at:at+32]==bytes.fromhex(next(r['blockhash'] for r in rows if r['txid']==txid))[::-1]:continue
            _,offset=parse_record(key,value)
            db.execute('insert or replace into main(key,value) values(?,?)',(key,archive_order(value,offset)))
        db.commit()
    return len(found)


def install(core,store,archive,rows,manifest,coverage=None,*,allow_unfunded=False):
    from peer_wallet import work_dir
    from core_ram_path import for_core
    from wallet_deletion import target,delete
    from archive_swap import swap,cleanup
    from public_policy import descriptors
    from wallet_labels import address_only
    supported(core)
    info=rpc(core,'getwalletinfo',[],archive);raw=rpc(core,'listdescriptors',[False],archive)
    if info.get('private_keys_enabled') is not False or info.get('scanning') or not address_only(raw):raise ValueError('Load an idle, public-only Extinct archive before upgrading its history.')
    stage='.wallaby-history-'+secrets.token_hex(12);swapped=False;committed=False
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as d:
        backup=Path(d)/'archive.dat';rpc(core,'backupwallet',[for_core(core,backup)],archive)
        # Preserve the entire old archive, including unrelated children and LOST
        # labels. Add only exact public tx records to this non-swapping copy.
        if rows:merge_backup(core,backup,rows,manifest,allow_unfunded=allow_unfunded)
        if coverage is not None:
            with database(backup,True) as db:db.execute('insert or replace into main(key,value) values(?,?)',(HISTORY_KEY,json.dumps(coverage,sort_keys=True,separators=(',',':')).encode()))
        rpc(core,'restorewallet',{'wallet_name':stage,'backup_file':for_core(core,backup),'load_on_startup':False},timeout=86400)
        try:
            check(core,stage,raw,rows,manifest)
            if coverage is not None:
                from extinct_upgrade import check_marker
                check_marker(core,stage,coverage)
            before=target(core,archive,allow_extinct=True);replacement=target(core,stage,allow_extinct=True)
            # Capture a second consistent backup to detect any late wallet update
            # before replacement. Never discard newly received archive records.
            latest=Path(d)/'latest.dat';rpc(core,'backupwallet',[for_core(core,latest)],archive)
            with database(latest) as a,database(backup) as b:
                oldrows=dict(a.execute('select key,value from main'));merged=dict(b.execute('select key,value from main'))
                for k,v in oldrows.items():
                    if k==HISTORY_KEY and coverage is not None:continue
                    if k.startswith(TX_KEY) and (k not in merged or k[3:][::-1].hex() not in {r['txid'] for r in rows} and merged.get(k)!=v):raise ValueError('Archive history changed during upgrade. Original archive was retained.')
                    if not k.startswith((TX_KEY,DESC_KEY)) and merged.get(k)!=v:raise ValueError('Archive labels or metadata changed during upgrade. Original archive was retained.')
            rpc(core,'unloadwallet',{'wallet_name':archive,'load_on_startup':False});rpc(core,'unloadwallet',{'wallet_name':stage,'load_on_startup':False})
            swap(before,replacement);swapped=True
            rpc(core,'loadwallet',{'filename':archive,'load_on_startup':True},timeout=86400);check(core,archive,raw,rows,manifest)
            if coverage is not None:check_marker(core,archive,coverage)
            # The previous complete public archive remains at stage until the
            # replacement is loaded and independently read back.
            committed=True
            cleanup(target(core,stage,allow_extinct=True))
        except Exception:
            if committed:
                with store.edit() as saved:saved.setdefault('history_cleanup',[]).append(stage)
                return {'transactions':len(rows),'archive':archive,'cleanup_required':True}
            if swapped:
                if archive in rpc(core,'listwallets'):rpc(core,'unloadwallet',{'wallet_name':archive,'load_on_startup':False})
                swap(target(core,archive,True),target(core,stage,True));rpc(core,'loadwallet',{'filename':archive,'load_on_startup':True},timeout=86400)
            elif archive not in rpc(core,'listwallets'):rpc(core,'loadwallet',{'filename':archive,'load_on_startup':True},timeout=86400)
            # Keep any uncertain staged wallet for explicit reconciliation.
            raise
    return {'transactions':len(rows),'archive':archive}


def check(core,wallet,raw,rows,manifest):
    from public_policy import descriptors
    info=rpc(core,'getwalletinfo',[],wallet)
    if info.get('private_keys_enabled') is not False or info.get('scanning') or descriptors(rpc(core,'listdescriptors',[False],wallet))!=descriptors(raw):raise ValueError('Restored public archive capability or policy differs.')
    for row in manifest['addresses']:
        found=rpc(core,'getaddressinfo',[row['address']],wallet)
        if not (found.get('ismine') or found.get('iswatchonly')) or (found.get('labels') or [''])!=[row['label']]:raise ValueError('Extinct address or LOST label readback failed.')
    for row in rows:
        found=rpc(core,'gettransaction',[row['txid'],True],wallet);tx,_=parse_record(TX_KEY+bytes.fromhex(row['txid'])[::-1],bytes.fromhex(row['record']))
        if found.get('hex')!=tx.serialize().hex() or found.get('blockhash')!=row['blockhash'] or found.get('confirmations',0)<=0:raise ValueError('Core did not retain the complete confirmed transaction history.')
