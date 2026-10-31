"""Only tunnel lifecycle/status crosses into the ordinary user service."""
import re,time
from diagnostics import ConnectionFailure,describe
from secure_bridge import call,WorkspaceFailure

class ProtectedNode:
    def __init__(self,config,port,stop,status):self.port=port;self.stop=stop;self.status=status
    def run(self):
        from secure_bridge import ensure_running
        generation=None
        try:
            ensure_running();reply=call('node.start',self.port)
            if not isinstance(reply,dict) or not isinstance(reply.get('session'),str) or not 0<len(reply['session'])<=128 or any(ord(c)<32 for c in reply['session']):
                raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid node session. Close and restart the protected workspace after finishing sensitive work.')
            generation=reply['session']
            while not self.stop.is_set():
                result=call('node.status',generation)
                if not isinstance(result,dict) or result.get('color') not in ('red','amber','green') or not isinstance(result.get('message'),str) or len(result['message'])>2048 or any(ord(c)<32 for c in result['message']):
                    raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid node status. Close and restart the protected workspace after finishing sensitive work.')
                self.status(result['color'],result['message'])
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
        except WorkspaceFailure as error:
            raise ConnectionFailure('workspace',error.code,str(error)) from None
        except OSError as error:
            raise describe('workspace',error) from None
        except ValueError:
            raise ConnectionFailure('workspace','local_request','The local protected Bitcoin workspace could not complete the node connection request. Check its status on Services; this is not a Dashboard protocol error.') from None
        finally:
            if generation is not None:
                try:call('node.stop',generation)
                except Exception:pass
