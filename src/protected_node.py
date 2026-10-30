"""Only tunnel lifecycle/status crosses into the ordinary user service."""
import re,time
from diagnostics import ConnectionFailure
from secure_bridge import call

class ProtectedNode:
    def __init__(self,config,port,stop,status):self.port=port;self.stop=stop;self.status=status
    def run(self):
        from secure_bridge import ensure_running
        ensure_running();generation=call('node.start',self.port)['session']
        try:
            while not self.stop.is_set():
                result=call('node.status',generation);self.status(result['color'],result['message'])
                if result.get('failed'):
                    failure=result.get('failure')
                    if isinstance(failure,dict) and set(failure)=={'stage','code','message'} and failure['stage'] in ('rpc','dashboard','node_identity','node','configuration','ssh','ssh_forward','ssh_local') and isinstance(failure['code'],str) and re.fullmatch('[a-z_]{1,64}',failure['code']) and isinstance(failure['message'],str) and 0<len(failure['message'])<=2048 and not any(ord(c)<32 for c in failure['message']):
                        raise ConnectionFailure(failure['stage'],failure['code'],failure['message'])
                    # Older workers do not supply structured detail. Preserve their
                    # bounded, already-sanitised message without calling it bad JSON.
                    message=result.get('message')
                    if not isinstance(message,str) or not 0<len(message)<=2048 or any(ord(c)<32 for c in message):message='Protected node session failed. Close and restart the protected workspace to load the updated diagnostics.'
                    raise ConnectionFailure('node','protected_session',message)
                self.stop.wait(2)
        finally:
            try:call('node.stop',generation)
            except Exception:pass
