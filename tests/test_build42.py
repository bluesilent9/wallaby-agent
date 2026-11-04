"""IPv6-only transport, origin checks and legacy desktop shortcut migration."""
import http.client,os,socket,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from loopback import Connection,IPv6HTTPServer,origin,valid_origin,same_origin
from http.server import BaseHTTPRequestHandler

class IPv6Only(unittest.TestCase):
 def test_listener_client_and_rejection_of_other_family(self):
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'IPv6')
   def log_message(self,*args):pass
  server=IPv6HTTPServer(('::1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   self.assertEqual(server.socket.family,socket.AF_INET6);self.assertEqual(server.socket.getsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY),1)
   c=Connection(server.server_port);c.request('GET','/');self.assertEqual(c.getresponse().read(),b'IPv6');c.close()
   with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as rejected:
    rejected.settimeout(1)
    with self.assertRaises(OSError):rejected.connect(('127.0.0.1',server.server_port))
  finally:server.shutdown();server.server_close();thread.join()
 def test_no_family_selection_or_hostname_resolution_in_client(self):
  with patch('loopback.socket.socket') as socket_factory:
   connection=Connection(12345);connection.connect()
   socket_factory.assert_called_once_with(socket.AF_INET6,socket.SOCK_STREAM)
   socket_factory.return_value.connect.assert_called_once_with(('::1',12345,0,0))
 def test_only_exact_bracketed_origin_is_authorised(self):
  expected=origin(12345);self.assertTrue(valid_origin(expected));self.assertTrue(same_origin(expected+'/?page=authorise',expected))
  for bad in ('http://127.0.0.1:12345','http://localhost:12345','http://[::ffff:127.0.0.1]:12345','http://[::]:12345','http://[::1]:12346','http://[::1]:12345@evil.example','https://[::1]:12345'):
   self.assertFalse(same_origin(bad+'/',expected),bad)
  for bad in (expected+'/',expected+'#x',expected+'?x','http://[::1]:0','http://[::1]:65536'):self.assertFalse(valid_origin(bad),bad)
 def test_production_sources_have_no_inet_or_old_loopback_paths(self):
  root=Path(__file__).resolve().parents[1]
  for folder in ('src','packaging','web'):
   for p in (root/folder).rglob('*'):
    if p.suffix not in ('.py','.js','.html','.c'):continue
    text=p.read_text();self.assertNotIn('127.0.0.1',text,str(p));self.assertNotRegex(text,r'\bAF_INET\b',str(p))
 def test_desktop_url_shortcuts_repaired_without_touching_other_files(self):
  from desktop_links import repair
  with tempfile.TemporaryDirectory() as tmp,patch('desktop_links.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'XDG_CONFIG_HOME':tmp+'/.config','XDG_DATA_HOME':tmp+'/.local/share'}):
   home=Path(tmp);desktop=home/'My Desktop';desktop.mkdir();(home/'.config').mkdir();(home/'.config/user-dirs.dirs').write_text('XDG_DESKTOP_DIR="$HOME/My Desktop"\n')
   old=desktop/'my-custom-wallaby-shortcut.desktop';old.write_text('[Desktop Entry]\nType=Link\nName=Wallaby Agent\nURL=http://127.0.0.1:12345/\n');old.chmod(0o755)
   other=desktop/'Other.desktop';other.write_text('[Desktop Entry]\nName=Other\nURL=http://127.0.0.1/\n')
   repair();self.assertIn('Exec=wallaby-agent configure',old.read_text());self.assertNotIn('URL=',old.read_text());self.assertEqual(old.stat().st_mode&511,0o755);self.assertIn('URL=',other.read_text())
   before=old.read_text();repair();self.assertEqual(old.read_text(),before)

 def test_offline_core_rpc_has_only_ipv6_listener(self):
  from wallet_setup import MemoryCore
  from wallet_ops import rpc
  with tempfile.TemporaryDirectory() as tmp:
   core=MemoryCore(Path(tmp)/'offline','regtest',os.environ['WALLABY_TEST_BITCOIND'])
   try:
    self.assertEqual(rpc(core.core,'getblockchaininfo')['chain'],'regtest')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as rejected:
     rejected.settimeout(1)
     with self.assertRaises(OSError):rejected.connect(('127.0.0.1',core.core.config['rpc_port']))
   finally:core.close()
