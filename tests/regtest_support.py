"""Isolated real-Core fixture. Never contacts production RPC or spends real coins."""
import os,socket,subprocess,tempfile,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from node_client import Core
from wallet_ops import rpc

class Regtest:
    def __init__(self,extra_args=()):
        self.root=tempfile.TemporaryDirectory(prefix='wallaby-regtest-');p=Path(self.root.name)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        binary=os.environ.get('WALLABY_TEST_BITCOIND','/tmp/wallaby-core31-test/bitcoin-31.0/bin/bitcoind')
        self.log=(p/'process.log').open('w');self.process=subprocess.Popen([binary,'-regtest','-server','-listen=0','-connect=0','-dnsseed=0','-discover=0','-txindex=1','-fallbackfee=0.00002','-datadir='+str(p),'-rpcport='+str(port)]+list(extra_args),stdout=self.log,stderr=subprocess.STDOUT)
        self.core=Core({'rpc_port':port,'cookie':str(p/'regtest/.cookie')})
        for _ in range(100):
            try:self.core.ready();break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Isolated Core did not start: '+(p/'process.log').read_text()[-1000:])
    def close(self):
        try:rpc(self.core,'stop')
        except Exception:pass
        self.process.wait(timeout=20);self.log.close();self.root.cleanup()
