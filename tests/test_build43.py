"""DNS through IPC and SSH socket handoff without an IPv4 transport exception."""
import array,contextlib,ctypes,errno,json,os,socket,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from ipv6_resolver import resolve,connect
from diagnostics import ConnectionFailure,ssh_failure

@contextlib.contextmanager
def resolver(reply,fragmented=False):
 with tempfile.TemporaryDirectory() as directory:
  path=str(Path(directory)/'resolve.sock');listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(path);listener.listen(1);requests=[]
  def serve():
   try:
    channel,_=listener.accept()
    with channel:
     data=b''
     while not data.endswith(b'\0'):data+=channel.recv(4096)
     requests.append(json.loads(data[:-1]));raw=json.dumps(reply).encode()+b'\0'
     if fragmented:channel.sendall(raw[:8]);raw=raw[8:]
     channel.sendall(raw)
   finally:listener.close()
  thread=threading.Thread(target=serve,daemon=True);thread.start()
  try:yield path,requests
  finally:thread.join(5)

def response(*addresses):
 return {'parameters':{'addresses':[{'family':socket.AF_INET6,'ifindex':scope,'address':list(socket.inet_pton(socket.AF_INET6,address))} for address,scope in addresses]}}

class NativeDNS(unittest.TestCase):
 def test_native_ipc_requests_ipv6_and_preserves_link_scope(self):
  with resolver(response(('2001:db8::1',3),('fe80::1',7),('2001:db8::1',3)),True) as (path,requests),patch('ipv6_resolver.SOCKET',path):
   self.assertEqual(resolve('Server.Example',2222),[('2001:db8::1',2222,0,0),('fe80::1',2222,0,7)])
  self.assertEqual(requests[0]['parameters'],{'name':'server.example','family':socket.AF_INET6,'flags':0})
 def test_non_ipv6_mapped_and_unusable_results_are_not_accepted(self):
  data=response(('::ffff:192.0.2.1',0),('::',0),('ff02::1',2),('fe80::1',0));data['parameters']['addresses'].append({'family':2,'address':[127,0,0,1]})
  with resolver(data) as (path,_),patch('ipv6_resolver.SOCKET',path),self.assertRaises(ConnectionFailure) as failure:resolve('server.test',22)
  self.assertEqual(failure.exception.code,'dns_no_ipv6')
 def test_os_resolver_failure_categories_are_safe(self):
  for reply,code in [({'error':'io.systemd.Resolve.QueryTimedOut'},'dns_timeout'),({'error':'io.systemd.Resolve.DNSError'},'dns_lookup_failed'),({'error':'org.varlink.service.PermissionDenied'},'dns_local_failure'),({'parameters':{'addresses':[{'family':10,'address':[300]*16}]}},'dns_local_failure')]:
   with resolver(reply) as (path,_),patch('ipv6_resolver.SOCKET',path),self.assertRaises(ConnectionFailure) as failure:resolve('server.test',22)
   self.assertEqual(failure.exception.code,code)
   self.assertEqual(ssh_failure(['WALLABY_RESOLVER '+code+': raw hidden'],0).code,code)
 def test_missing_resolver_is_actionable_and_does_not_fall_back(self):
  with patch('ipv6_resolver.SOCKET','/nonexistent-wallaby-test-resolver'),patch('socket.getaddrinfo',side_effect=AssertionError('No libc DNS fallback')),self.assertRaises(ConnectionFailure) as failure:resolve('server.test',22)
  self.assertEqual(failure.exception.code,'dns_local_unavailable')
 def test_ssh_keeps_original_host_identity_and_fd_handoff(self):
  from transport import ssh_command
  from configuration import Config
  config=Config().values;config['hostname']='server.test';config['ssh_port']=2222
  command=ssh_command(config,None,None,'/tmp/fixture.sock')
  self.assertEqual(command[-2:],['--','server.test']);self.assertIn('ProxyUseFdpass=yes',command);self.assertIn('StrictHostKeyChecking=yes',command)
  self.assertTrue(any(x.startswith('ProxyCommand=') and x.endswith(' %h %p') for x in command));self.assertFalse(any(x.startswith(('HostKeyAlias=','Hostname=')) for x in command))
 def test_unreachable_address_does_not_prevent_trying_next_ipv6_address(self):
  with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as listener:
   listener.bind(('::1',0));listener.listen(1);port=listener.getsockname()[1]
   with patch('ipv6_resolver.resolve',return_value=[('::1',0,0,0),('::1',port,0,0)]):
    with connect('server.test',port) as client:
     connection,_=listener.accept();connection.close();self.assertEqual(client.family,socket.AF_INET6)
 def test_socket_handoff_works_with_ipv4_denied_in_real_child(self):
  from ctypes.util import find_library
  if not find_library('seccomp'):self.skipTest('libseccomp is unavailable')
  with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as listener:
   listener.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1);listener.bind(('::1',0));listener.listen(1);port=listener.getsockname()[1]
   with resolver(response(('::1',0))) as (path,_):
    parent,child=socket.socketpair()
    source=Path(__file__).resolve().parents[1]/'src'
    script="""
import ctypes,errno,socket,sys
from ctypes.util import find_library
lib=ctypes.CDLL(find_library('seccomp'));lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
class Compare(ctypes.Structure):_fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('a',ctypes.c_uint64),('b',ctypes.c_uint64)]
lib.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Compare)];lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_release.argtypes=[ctypes.c_void_p]
c=lib.seccomp_init(0x7fff0000);comparison=Compare(0,4,socket.AF_INET,0)
assert lib.seccomp_rule_add_array(c,0x00050000|errno.EAFNOSUPPORT,lib.seccomp_syscall_resolve_name(b'socket'),1,ctypes.byref(comparison))==0
assert lib.seccomp_load(c)==0;lib.seccomp_release(c)
try:socket.socket(socket.AF_INET);raise AssertionError('IPv4 unexpectedly permitted')
except OSError:pass
sys.path.insert(0,sys.argv[1]);import ipv6_resolver
ipv6_resolver.SOCKET=sys.argv[2];sys.argv=['resolver','server.test',sys.argv[3]];sys.exit(ipv6_resolver.main())
"""
    process=subprocess.Popen([sys.executable,'-c',script,str(source),path,str(port)],stdout=child,stderr=subprocess.PIPE);child.close();parent.settimeout(10)
    try:
     _,ancillary,_,_=parent.recvmsg(1,socket.CMSG_SPACE(array.array('i').itemsize));fds=array.array('i')
     for level,kind,data in ancillary:
      if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:fds.frombytes(data)
     self.assertEqual(len(fds),1)
     with socket.socket(socket.AF_INET6,socket.SOCK_STREAM,fileno=fds[0]) as handed:
      accepted,_=listener.accept()
      with accepted:accepted.sendall(b'IPv6 SSH transport');self.assertEqual(handed.recv(64),b'IPv6 SSH transport')
     self.assertEqual(process.wait(5),0,process.stderr.read().decode())
    finally:
     parent.close()
     if process.poll() is None:process.kill();process.wait()
     process.stderr.close()
