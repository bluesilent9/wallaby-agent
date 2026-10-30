"""Read-only optional Bitcoin prerequisites; SSH services never require these."""
import importlib.util,os,shutil
from pathlib import Path
from configuration import Config,discover_cookie

class NodeUnavailable(ValueError):pass

def node_support(config=None):
    config=config if config is not None else Config().values
    missing=[];packages=[]
    try:viewer=all(importlib.util.find_spec(name) is not None for name in ('PyQt6.QtWidgets','PyQt6.QtWebEngineWidgets'))
    except (ImportError,ModuleNotFoundError,ValueError):viewer=False
    if not viewer:
        missing.append('protected HTML5 viewer');packages+=['python3-pyqt6','python3-pyqt6.qtwebengine']
    if not shutil.which('pkexec'):
        missing.append('local administrator authorisation');packages+=['pkexec','polkitd']
    if not (shutil.which('kdialog') or shutil.which('zenity')):
        missing.append('native passphrase dialogue');packages+=['kdialog']
    cookie=config.get('cookie') or discover_cookie()
    try:cookie_ok=bool(cookie) and Path(cookie).expanduser().is_file() and os.access(Path(cookie).expanduser(),os.R_OK)
    except OSError:cookie_ok=False
    if not cookie_ok:missing.append('readable Bitcoin Core RPC cookie')
    if not missing:return {'available':True,'message':'Bitcoin prerequisites detected. Enabling the node interface checks Core RPC and Dashboard connectivity.','missing':[]}
    message='Node interface unavailable: '+', '.join(missing)+'. '
    if packages:message+='Install optional Bitcoin desktop components: sudo apt install '+' '.join(dict.fromkeys(packages))+'. '
    if not cookie_ok:message+='Install/start Bitcoin Core with RPC enabled, or choose its readable .cookie file in Connection settings. Core can be installed separately, including Snap; an apt package named bitcoind is not required. '
    message+='DDNS-GO and Dashboard SSH tunnels remain available without Bitcoin.'
    return {'available':False,'message':message,'missing':missing}

def require_node(config=None):
    status=node_support(config)
    if not status['available']:raise NodeUnavailable(status['message'])
    return status
