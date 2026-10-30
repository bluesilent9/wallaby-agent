"""Protocol errors and structured prerequisite advice; no live services."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from capabilities import node_support
from diagnostics import ConnectionFailure
from node_client import NodeClient,decode
class Build14(unittest.TestCase):
 def client(self):
  c=NodeClient({},1,threading.Event(),lambda *_:None);self.addCleanup(c.pool.shutdown,wait=True);return c
 def test_install_command_is_separate_from_explanation(self):
  with patch('capabilities.importlib.util.find_spec',side_effect=ModuleNotFoundError),patch('capabilities.shutil.which',return_value=None),patch('capabilities.discover_cookie',return_value=''):
   s=node_support({'cookie':''});self.assertNotIn('sudo apt',s['message']);self.assertEqual(s['commands'],['sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine pkexec polkitd kdialog'])
 def test_invalid_json_names_the_endpoint_without_echoing_response(self):
  c=self.client()
  with patch('node_client.http_json',side_effect=ValueError('SECRET REMOTE RESPONSE')):
   with self.assertRaises(ConnectionFailure) as e:c.post('poll',{})
  self.assertEqual(e.exception.code,'json_poll');self.assertIn('poll endpoint',str(e.exception));self.assertNotIn('SECRET',str(e.exception))
 def test_bad_command_schema_has_specific_safe_diagnostic(self):
  with self.assertRaises(ConnectionFailure) as e:self.client().consume({'commands':[{'secret':'NEVER DISPLAY'}]})
  self.assertEqual(e.exception.code,'rpc_fields');self.assertNotIn('NEVER',str(e.exception))
 def test_public_policy_still_blocks_mutating_rpc(self):
  c=self.client();c.pending.acquire();command={'id':'fixture','method':'walletpassphrase','params':['SECRET',30],'wallet':'private','kind':'rpc','expires_in_seconds':10}
  with patch.object(c,'post') as post:c.execute(command,0);post.assert_not_called()
  self.assertEqual(c.error.code,'rpc_scope');self.assertNotIn('SECRET',str(c.error))
 def test_wire_fractional_deadline_remains_accepted(self):
  c=self.client();c.pending.acquire();command=decode('{"id":"fixture","method":"getblockcount","params":[],"wallet":null,"kind":"rpc","expires_in_seconds":29.987}')
  import time
  with patch.object(c,'post',return_value={'execute':False}) as post:c.execute(command,time.monotonic());post.assert_called_once_with('ack',{'id':'fixture'})
  self.assertIsNone(c.error)

class ProtectedFailureBoundary(unittest.TestCase):
 def test_local_rpc_and_dashboard_failures_survive_worker_boundary(self):
  from protected_node import ProtectedNode
  from diagnostics import describe
  for stage,code,message in [('rpc','cookie_access','The Bitcoin Core cookie cannot be read.'),('rpc','refused','Local Core refused the connection.'),('dashboard','json_poll','The poll endpoint did not return valid JSON.')]:
   with self.subTest(stage=stage,code=code),patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=[{'session':'fixture'},{'color':'red','message':message,'failed':True,'failure':{'stage':stage,'code':code,'message':message}},{'ok':True}]):
    with self.assertRaises(ConnectionFailure) as caught:ProtectedNode({},1,threading.Event(),lambda *_:None).run()
    failure=describe('dashboard',caught.exception);self.assertEqual((failure.stage,failure.code,str(failure)),(stage,code,message))
 def test_legacy_worker_failure_is_not_misreported_as_invalid_dashboard_data(self):
  from protected_node import ProtectedNode
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=[{'session':'fixture'},{'color':'red','message':'Core is warming up.','failed':True},{'ok':True}]):
   with self.assertRaises(ConnectionFailure) as caught:ProtectedNode({},1,threading.Event(),lambda *_:None).run()
  self.assertEqual(caught.exception.stage,'node');self.assertEqual(str(caught.exception),'Core is warming up.')
 def test_malformed_worker_detail_cannot_inject_multiline_failure(self):
  from protected_node import ProtectedNode
  with patch('secure_bridge.ensure_running'),patch('protected_node.call',side_effect=[{'session':'fixture'},{'color':'red','message':'bad\nmessage','failed':True,'failure':{'stage':'rpc','code':None,'message':'bad'}},{'ok':True}]):
   with self.assertRaises(ConnectionFailure) as caught:ProtectedNode({},1,threading.Event(),lambda *_:None).run()
  self.assertNotIn('\n',str(caught.exception));self.assertIn('restart',str(caught.exception))
