import copy,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from configuration import Config
from transport import MasterConnection,Tunnel,fingerprint,ssh_command
from runtime import monitor

class SharedSSH(unittest.TestCase):
 def test_master_login_has_no_initial_tunnel_or_remote_command(self):
  c=Config().values;c['hostname']='server.test';args=ssh_command(c,None,None,'/tmp/master.sock')
  self.assertNotIn('-L',args);self.assertIn('-N',args);self.assertIn('-6',args);self.assertIn('StrictHostKeyChecking=yes',args)
 def test_forward_add_cancel_share_socket_without_starting_another_login(self):
  with tempfile.TemporaryDirectory() as root:
   c=Config(root).values;c['hostname']='server.test';sock=Path(root)/'ssh-test.sock';sock.touch();(Path(root)/'master.json').write_text(json.dumps({'control':str(sock),'config_hash':fingerprint(c)}))
   with patch('transport.subprocess.run',return_value=Mock(returncode=0)) as run,patch('transport.subprocess.Popen') as start:
    a=Tunnel(c,'node',root);a.start();self.assertTrue(a.alive());a.close()
    self.assertIn('forward',run.call_args_list[0].args[0]);self.assertIn('cancel',run.call_args_list[-1].args[0]);start.assert_not_called()
    self.assertTrue(all(str(sock) in call.args[0] for call in run.call_args_list))
 def test_new_master_generation_invalidates_old_forward(self):
  with tempfile.TemporaryDirectory() as root:
   c=Config(root).values;c['hostname']='server.test';sock=Path(root)/'ssh-one.sock';sock.touch();meta=Path(root)/'master.json';meta.write_text(json.dumps({'control':str(sock),'config_hash':fingerprint(c)}))
   with patch('transport.subprocess.run',return_value=Mock(returncode=0)):
    t=Tunnel(c,'node',root);t.start();meta.write_text(json.dumps({'control':str(Path(root)/'ssh-two.sock'),'config_hash':fingerprint(c)}));self.assertFalse(t.alive());t.close()
 def test_changed_ssh_user_cannot_attach_to_previous_user_session(self):
  with tempfile.TemporaryDirectory() as root:
   c=Config(root).values;c['hostname']='server.test';sock=Path(root)/'ssh-test.sock';sock.touch();(Path(root)/'master.json').write_text(json.dumps({'control':str(sock),'config_hash':fingerprint(c)}));c['ssh_user']='another-user'
   with self.assertRaises(ConnectionError):Tunnel(c,'node',root).start()
 def test_monitor_authenticates_with_all_services_off_and_reports_drop(self):
  class Stop:
   count=0
   def is_set(self):return self.count>=3
   def set(self):self.count=3
   def wait(self,d):self.count+=1;return self.is_set()
  stop=Stop()
  with tempfile.TemporaryDirectory() as root:
   c=Config(root).values;c['hostname']='server.test';master=Mock();master.alive.side_effect=lambda:stop.count==0;master.process.poll.return_value=255;master.info.return_value={'control':str(Path(root)/'ssh-test.sock'),'config_hash':fingerprint(c)}
   from diagnostics import ConnectionFailure
   master.failure.return_value=ConnectionFailure('ssh','transport','SSH connection dropped.')
   with patch('runtime.retire_jellyfin'),patch('runtime.ctl'),patch('runtime.signal.signal'),patch('runtime.threading.Event',return_value=stop),patch('runtime.Config') as cfg,patch('runtime.runtime_dir',return_value=Path(root)),patch('runtime.MasterConnection',return_value=master) as connect,patch('runtime.notify_approvals'),patch('runtime.write_status') as status:
    cfg.return_value.values=c;monitor()
   connect.assert_called_once();master.start.assert_called_once();self.assertEqual(status.call_args_list[0].args[1],'amber');colors=[a.args[1] for a in status.call_args_list];self.assertIn('green',colors);self.assertIn('red',colors);self.assertFalse((Path(root)/'master.json').exists())
 def test_ping_is_removed(self):
  import transport,runtime
  self.assertFalse(hasattr(transport,'ping'));self.assertFalse(hasattr(runtime,'ping'))

 def test_connect_on_healthy_master_does_not_replace_login(self):
  class Stop:
   count=0
   def is_set(self):return self.count>=2
   def set(self):self.count=2
   def wait(self,d):
    self.count+=1
    if self.count==1:(root/'connect-request.json').write_text('retry-button')
    return self.is_set()
  stop=Stop()
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);c=Config(root).values;c['hostname']='server.test';master=Mock();master.alive.return_value=True;master.info.return_value={'control':str(root/'ssh-test.sock'),'config_hash':fingerprint(c)}
   with patch('runtime.retire_jellyfin'),patch('runtime.ctl'),patch('runtime.signal.signal'),patch('runtime.threading.Event',return_value=stop),patch('runtime.Config') as cfg,patch('runtime.runtime_dir',return_value=root),patch('runtime.MasterConnection',return_value=master) as connect,patch('runtime.notify_approvals'),patch('runtime.write_status'):
    cfg.return_value.values=c;monitor()
   connect.assert_called_once();master.start.assert_called_once()
