"""Only tunnel lifecycle/status crosses into the ordinary user service."""
import re,time,secrets
from diagnostics import ConnectionFailure,describe
from secure_bridge import call,WorkspaceFailure

class ProtectedNode:
    def __init__(self,config,port,stop,status):self.port=port;self.stop=stop;self.status=status;self.controller=secrets.token_hex(16);self.generation=None
    def run(self):
        from secure_bridge import ensure_running
        generation=None;opened=False
        try:
            ensure_running();reply=call('node.start',self.port,self.controller)
            if not isinstance(reply,dict) or not isinstance(reply.get('session'),str) or not 0<len(reply['session'])<=128 or any(ord(c)<32 for c in reply['session']):
                raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid node session. Close and restart the protected workspace after finishing sensitive work.')
            generation=reply['session'];self.generation=generation
            while not self.stop.is_set():
                result=call('node.status',generation,self.controller)
                if not isinstance(result,dict) or result.get('color') not in ('red','amber','green') or not isinstance(result.get('message'),str) or len(result['message'])>2048 or any(ord(c)<32 for c in result['message']):
                    raise WorkspaceFailure('worker_protocol','The local protected worker returned an invalid node status. Close and restart the protected workspace after finishing sensitive work.')
                if result.get('superseded') is True:raise ConnectionFailure('node','controller_superseded','A newer local node controller owns this connection. The previous controller has stopped without interrupting it.')
                self.status(result['color'],result['message'])
                if result.get('failed'):
                    failure=result.get('failure')
                    if isinstance(failure,dict) and set(failure)=={'stage','code','message'} and failure['stage'] in ('rpc','dashboard','node_identity','node','configuration','ssh','ssh_forward','ssh_local') and isinstance(failure['code'],str) and re.fullmatch('[a-z][a-z0-9_]{0,63}',failure['code']) and isinstance(failure['message'],str) and 0<len(failure['message'])<=2048 and not any(ord(c)<32 for c in failure['message']):
                        raise ConnectionFailure(failure['stage'],failure['code'],failure['message'])
                    # Older workers do not supply structured detail. Preserve their
                    # bounded, already-sanitised message without calling it bad JSON.
                    message=result.get('message')
                    if not isinstance(message,str) or not 0<len(message)<=2048 or any(ord(c)<32 for c in message):message='Protected node session failed. Close and restart the protected workspace to load the updated diagnostics.'
                    raise ConnectionFailure('node','protected_session',message)
                if result['color']=='green' and not opened:
                    call('ui.open','authorise');opened=True
                self.stop.wait(2)
        except WorkspaceFailure as error:
            raise ConnectionFailure('workspace',error.code,str(error)) from None
        except OSError as error:
            raise describe('workspace',error) from None
        except ValueError:
            raise ConnectionFailure('workspace','local_request','The local protected Bitcoin workspace could not complete the node connection request. Check its status on Services; this is not a Wallet Server protocol error.') from None
        finally:
            if generation is not None:
                try:call('node.stop',generation,self.controller)
                except Exception:pass

    def transport_failed(self,stage,code):
        if self.generation is None:return
        call('node.connection_lost',stage,code,self.generation,self.controller,timeout=2)
