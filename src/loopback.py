"""Strict IPv6 loopback HTTP. No generic address-family selection or fallback."""
import http.client
from http.server import ThreadingHTTPServer
import socket
from urllib.parse import urlsplit

HOST='::1'

def origin(port):
    if type(port) is not int or not 0<port<=65535:raise ValueError('Invalid IPv6 loopback port.')
    return 'http://[::1]:'+str(port)

def valid_origin(value):
    try:
        u=urlsplit(value)
        return u.scheme=='http' and u.netloc=='[::1]:'+str(u.port) and type(u.port) is int and 0<u.port<=65535 and not (u.path or u.query or u.fragment)
    except (ValueError,TypeError):return False

def same_origin(value,expected):
    if not valid_origin(expected):return False
    try:
        u=urlsplit(value);return u.scheme=='http' and u.netloc==urlsplit(expected).netloc
    except (ValueError,TypeError):return False

class IPv6HTTPServer(ThreadingHTTPServer):
    address_family=socket.AF_INET6
    daemon_threads=True
    def server_bind(self):
        if self.server_address[0]!=HOST:raise ValueError('Agent HTTP must bind only to IPv6 loopback.')
        self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
        super().server_bind()

class Connection(http.client.HTTPConnection):
    def __init__(self,port,timeout=30):super().__init__(HOST,port,timeout=timeout)
    def connect(self):
        connection=socket.socket(socket.AF_INET6,socket.SOCK_STREAM)
        try:
            connection.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            connection.settimeout(self.timeout);connection.connect((HOST,self.port,0,0))
        except BaseException:
            connection.close();raise
        self.sock=connection
