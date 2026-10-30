"""Only tunnel lifecycle/status crosses into the ordinary user service."""
import time
from secure_bridge import call

class ProtectedNode:
    def __init__(self,config,port,stop,status):self.port=port;self.stop=stop;self.status=status
    def run(self):
        from secure_bridge import ensure_running
        ensure_running();generation=call('node.start',self.port)['session']
        try:
            while not self.stop.is_set():
                result=call('node.status',generation);self.status(result['color'],result['message'])
                if result.get('failed'):raise ValueError(result['message'])
                self.stop.wait(2)
        finally:
            try:call('node.stop',generation)
            except Exception:pass
