"""Fresh public-only Core 31 snapshot; private records never enter its database."""
import io,sqlite3,struct,tempfile
from pathlib import Path
from core_history import database,compact_read,supported
from wallet_ops import rpc
from signer_restoration import backup_keys

# Explicit Core 31 public record types. Unknown types stop rather than guess.
PUBLIC={b'activeexternalspk',b'activeinternalspk',b'bestblock',b'bestblock_nomerkle',b'destdata',b'flags',b'lockedutxo',b'minversion',b'name',b'orderposnext',b'purpose',b'settings',b'tx',b'version',b'walletdescriptor',b'walletdescriptorcache',b'walletdescriptorlhcache'}
SECRET={b'key',b'ckey',b'mkey',b'wkey',b'walletdescriptorkey',b'walletdescriptorckey'}


def create(core,name,path):
    from peer_wallet import work_dir
    from core_ram_path import for_core
    from build8_policy import descriptors
    supported(core);path=Path(path)
    if path.exists():raise ValueError('A public recovery snapshot already exists.')
    with tempfile.TemporaryDirectory(dir=work_dir(core)) as folder:
        original=Path(folder)/'original.dat';rpc(core,'backupwallet',[for_core(core,original)],name)
        # Start a NEW database so deleted secrets cannot survive in free pages.
        with database(original) as source,sqlite3.connect(path) as dest:
            path.chmod(0o600)
            for setting in ('application_id','user_version'):
                value=source.execute('pragma '+setting).fetchone()[0];dest.execute('pragma '+setting+'='+str(value))
            dest.execute('create table main(key BLOB PRIMARY KEY NOT NULL,value BLOB NOT NULL)')
            flags=False
            for (key,) in source.execute('select key from main'):
                stream=io.BytesIO(key);kind=stream.read(compact_read(stream))
                if kind in SECRET:continue
                if kind not in PUBLIC:raise ValueError('Unknown Core record type prevents a safe public-only restoration snapshot.')
                value=source.execute('select value from main where key=?',(key,)).fetchone()[0]
                if kind==b'walletdescriptor':
                    data=io.BytesIO(value);desc=data.read(compact_read(data)).decode()
                    descriptors({'wallet_name':'Verified public recovery','descriptors':[{'desc':desc}]})
                if kind==b'flags':
                    if len(value)!=8:raise ValueError('Unsupported Core wallet flags.')
                    value=struct.pack('<Q',struct.unpack('<Q',value)[0]|(1<<32));flags=True
                dest.execute('insert into main values(?,?)',(key,value))
            if not flags:raise ValueError('Core wallet flags are missing from its public snapshot.')
            dest.commit()
    verify(path)
    return path


def verify(path):
    from build8_policy import descriptors
    flags=False
    with database(Path(path).resolve()) as db:
        for key,value in db.execute('select key,value from main'):
            stream=io.BytesIO(key);kind=stream.read(compact_read(stream))
            if kind not in PUBLIC:raise ValueError('Watch-only restoration contains a private or unsupported Core record.')
            if kind==b'walletdescriptor':
                data=io.BytesIO(value);desc=data.read(compact_read(data)).decode();descriptors({'wallet_name':'Verified public recovery','descriptors':[{'desc':desc}]})
            if kind==b'flags':
                if len(value)!=8 or not struct.unpack('<Q',value)[0]&(1<<32):raise ValueError('Public restoration has not disabled private keys.')
                flags=True
    if not flags:raise ValueError('Public restoration flags are missing.')
    return True
