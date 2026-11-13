"""Isolated subprocess adapter to the actual companion Server relay."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from secure_relay import SecureRelay
config=Path(sys.argv[2])/'server.json';hub=SimpleNamespace(registry=SimpleNamespace(connections={}),wallet_builder=None);relay=SecureRelay(config,hub)
for line in sys.stdin:
 try:
  request=json.loads(line)
  if request.get('reset'):relay.reset();result={'reset':True}
  elif request.get('audit'):result={'registered':len(relay.endpoints),'buffered':len(relay.messages),'mesh':relay.mesh(list(hub.registry.connections))}
  else:
   who=request['identity'];principal=relay.principal(who['role'],who['identity_key'],who['endpoint_id'],who['endpoint_id']);hub.registry.connections[who['endpoint_id']]={'node_id':who['endpoint_id']};result=relay.dispatch(principal,request['body'])
  print(json.dumps({'result':result}),flush=True)
 except Exception as error:print(json.dumps({'error':str(error)}),flush=True)
