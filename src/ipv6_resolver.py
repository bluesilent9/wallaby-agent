"""Native Ubuntu resolver over local IPC; IPv6 SSH socket handoff only."""
import array,errno,ipaddress,json,os,socket,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from configuration import hostname
from diagnostics import ConnectionFailure

SOCKET='/run/systemd/resolve/io.systemd.Resolve'
LIMIT=128*1024

def resolve(name,port,timeout=8):
    name=hostname(name)
    if type(port) is not int or not 0<port<=65535:raise ValueError('Invalid server port.')
    request={'method':'io.systemd.Resolve.ResolveHostname','parameters':{'name':name,'family':socket.AF_INET6,'flags':0}}
    try:
        deadline=time.monotonic()+timeout
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
            channel.settimeout(timeout);channel.connect(SOCKET);channel.sendall(json.dumps(request,separators=(',',':')).encode()+b'\0')
            data=bytearray()
            while b'\0' not in data:
                channel.settimeout(max(.001,deadline-time.monotonic()));chunk=channel.recv(min(8192,LIMIT+1-len(data)))
                if not chunk:raise ValueError('Incomplete resolver reply.')
                data.extend(chunk)
                if len(data)>LIMIT:raise ValueError('Resolver reply exceeds limit.')
            result=json.loads(bytes(data).split(b'\0',1)[0])
            if result.get('error') in ('io.systemd.Resolve.QueryTimedOut','io.systemd.Resolve.MaxAttemptsReached'):raise TimeoutError()
            if result.get('error')=='io.systemd.Resolve.DNSError':raise ConnectionFailure('ssh','dns_lookup_failed','Ubuntu’s resolver could not resolve the server’s IPv6 address. Check DNS and the hostname, then retry.')
            if result.get('error') and result['error']!='io.systemd.Resolve.NoSuchResourceRecord':raise ValueError('Resolver refused query.')
            rows=result.get('parameters',{}).get('addresses',[])
            if not isinstance(rows,list) or len(rows)>1024:raise ValueError('Invalid resolver address list.')
            addresses=[]
            for row in rows:
                if not isinstance(row,dict) or row.get('family')!=socket.AF_INET6:continue
                raw=row.get('address')
                if not isinstance(raw,list) or len(raw)!=16 or any(type(b) is not int or not 0<=b<=255 for b in raw):raise ValueError('Invalid resolver address.')
                address=ipaddress.IPv6Address(bytes(raw))
                if address.ipv4_mapped or address.is_unspecified or address.is_multicast:continue
                scope=row.get('ifindex',0) or 0
                if type(scope) is not int or not 0<=scope<=2**32-1:raise ValueError('Invalid resolver interface.')
                if address.is_link_local and not scope:continue
                item=(str(address),port,0,scope if address.is_link_local else 0)
                if item not in addresses:addresses.append(item)
            if not addresses:raise ConnectionFailure('ssh','dns_no_ipv6','The local resolver returned no usable IPv6 address for the server. Check its hostname and AAAA record.')
            return addresses
    except ConnectionFailure:raise
    except (FileNotFoundError,ConnectionRefusedError):raise ConnectionFailure('ssh','dns_local_unavailable','Ubuntu’s local resolver is unavailable. Start systemd-resolved, then retry the server connection. IPv6-only protection remains enabled.') from None
    except (TimeoutError,socket.timeout):raise ConnectionFailure('ssh','dns_timeout','Ubuntu’s local resolver timed out looking up the server’s IPv6 address. Check DNS and retry.') from None
    except (OSError,ValueError,TypeError,AttributeError):raise ConnectionFailure('ssh','dns_local_failure','The Agent could not obtain an IPv6 address through Ubuntu’s local resolver. Check systemd-resolved and DNS; no alternate transport was used.') from None

def connect(name,port,timeout=10):
    deadline=time.monotonic()+timeout;addresses=resolve(name,port,timeout=min(timeout,8));last=None
    for address in addresses:
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        connection=socket.socket(socket.AF_INET6,socket.SOCK_STREAM)
        try:
            connection.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            connection.settimeout(min(remaining,3) if len(addresses)>1 else remaining);connection.connect(address);connection.settimeout(None);return connection
        except OSError as error:last=error;connection.close()
    if last is not None:raise last
    raise TimeoutError('IPv6 connection deadline expired.')

def main():
    try:
        if len(sys.argv)!=3:raise ValueError('Invalid SSH socket handoff arguments.')
        with connect(sys.argv[1],int(sys.argv[2])) as connection:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM,fileno=os.dup(sys.stdout.fileno())) as channel:
                if channel.sendmsg([b'\0'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[connection.fileno()]))])!=1:raise OSError('Socket handoff failed.')
    except ConnectionFailure as error:
        print('WALLABY_RESOLVER '+error.code+': '+str(error),file=sys.stderr);return 1
    except (OSError,ValueError) as error:
        code='timeout' if isinstance(error,TimeoutError) else 'refused' if isinstance(error,ConnectionRefusedError) else 'ipv6_route' if getattr(error,'errno',None) in (errno.ENETUNREACH,errno.EHOSTUNREACH) else 'io'
        print('WALLABY_CONNECT '+code+': IPv6 SSH socket connection or handoff failed.',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
