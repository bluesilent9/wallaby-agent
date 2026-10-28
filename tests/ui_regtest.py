"""Manual browser fixture using isolated regtest coins; no installed Agent state."""
import sys,tempfile,os,threading,json
from pathlib import Path
from datetime import datetime,timedelta
root=tempfile.TemporaryDirectory(prefix='wallaby-ui-test-');os.environ['XDG_CONFIG_HOME']=root.name;os.environ['XDG_RUNTIME_DIR']=root.name
sys.path.insert(0,str(Path(__file__).resolve().parent));from regtest_support import Regtest
from wallet_ops import WalletOps,rpc
from approval_store import Store
from app import Server,Handler
node=Regtest();c=node.core
try:
 for name in ('Test miner','Test treasury','Test storage'):rpc(c,'createwallet',{'wallet_name':name,'passphrase':'regtest-only'})
 rpc(c,'walletpassphrase',['regtest-only',600],'Test miner');address=rpc(c,'getnewaddress',[],'Test miner');rpc(c,'generatetoaddress',[105,address]);rpc(c,'sendtoaddress',[rpc(c,'getnewaddress',[],'Test treasury'),'1.0'],'Test miner');rpc(c,'generatetoaddress',[1,address])
 ops=WalletOps(c,Store());r=ops.build('Test treasury','Test storage','2',(datetime.now()+timedelta(days=30)).date().isoformat(),'Australia/Sydney');ops.store=Store(Path(root.name)/'peer');ops.store.receive({'kind':'vault_sync','vault':r['vault']})
 server=Server(('127.0.0.1',0),Handler);server.token='REGTEST-UI-ONLY';server.config_lock=threading.Lock();server.preview=False;server.wallet_ops=ops
 Path('work/build5-ui-url.txt').write_text(f'http://127.0.0.1:{server.server_port}/#REGTEST-UI-ONLY');print('Regtest browser fixture ready',server.server_port,flush=True);server.serve_forever()
finally:node.close();root.cleanup()
