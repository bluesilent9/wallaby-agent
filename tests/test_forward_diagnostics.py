import io,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from transport import MasterConnection,forward_category
from node_client import http_json
import http.client

class ForwardDiagnostics(unittest.TestCase):
 def test_shared_master_logs_live_forward_failure_without_raw_ssh_text(self):
  with tempfile.TemporaryDirectory() as folder:
   master=MasterConnection({},Path(folder));master.process=SimpleNamespace(stderr=io.BytesIO(b'channel 4: open failed: administratively prohibited: private response not permitted\nchannel 5: open failed: connect failed: Connection refused\n'))
   with patch('activity_log.event') as event:master._read_errors()
   self.assertEqual(event.call_count,2);self.assertIn('forward_denied',str(event.call_args_list[0]));self.assertIn('target_refused',str(event.call_args_list[1]));self.assertNotIn('private response',str(event.call_args_list));self.assertIn('service=not_attributed',str(event.call_args_list))
 def test_connection_level_and_arbitrary_remote_text_are_not_forward_categories(self):
  self.assertIsNone(forward_category('Permission denied (publickey)'))
  self.assertIsNone(forward_category('server supplied an unrecognised sentence'))
  self.assertEqual(forward_category('channel 1: open failed: connect failed: Network is unreachable'),'target_unreachable')
 def test_http_diagnostics_distinguish_close_and_invalid_status_without_echoing_response(self):
  for error,category in ((http.client.RemoteDisconnected('private raw response'),'closed_before_status'),(http.client.BadStatusLine('private raw response'),'invalid_status_line'),(ConnectionResetError('private raw response'),'connection_reset')):
   connection=Mock();connection.getresponse.side_effect=error
   with patch('node_client.Connection',return_value=connection),patch('activity_log.event') as event:
    with self.assertRaises(type(error)):http_json(12345,'/agent/v1/register',{'mac':'not logged'})
   self.assertIn(category,str(event.call_args));self.assertNotIn('private raw response',str(event.call_args));self.assertNotIn('not logged',str(event.call_args));connection.close.assert_called_once()
