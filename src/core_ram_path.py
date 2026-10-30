"""Core can read the same RAM inode through its Snap-authorised directory."""
from pathlib import Path
from protected_memory import required,root,noswap_path

def for_core(core,path):
    path=Path(path)
    if not required():return str(path)
    resolved=path.resolve()
    if not resolved.is_relative_to(root()) or not noswap_path(resolved):raise ValueError('Core transfer files must remain inside protected non-swapping RAM.')
    if '/snap/bitcoin-core/' not in str(core.config['cookie']):return str(resolved)
    alias=Path.home()/'snap/bitcoin-core/common/wallaby-agent-volatile'
    try:valid=alias.samefile(root()) and noswap_path(alias)
    except OSError:valid=False
    if not valid:raise ValueError('The existing Core Snap cannot access the protected RAM workspace. Complete its local protection setup or use a native Core instance; no file was staged on a laptop drive.')
    return str(alias/resolved.relative_to(root()))
