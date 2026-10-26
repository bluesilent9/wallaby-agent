"""Actionable, bounded diagnostics; never expose credentials or raw server responses."""
import http.client
import socket


class ConnectionFailure(ConnectionError):
    def __init__(self, stage, code, message):
        self.stage = stage
        self.code = code
        super().__init__(message)

    def detail(self):
        return {'stage': self.stage, 'code': self.code, 'message': str(self)}


def describe(stage, error):
    if isinstance(error, ConnectionFailure):
        return error
    label = {'rpc': 'Local Bitcoin Core RPC', 'dashboard': 'Wallaby Dashboard',
             'ssh': 'SSH', 'configuration': 'Agent configuration'}.get(stage, 'Node interface')
    status = getattr(error, 'status', None)
    if status in (401, 403):
        advice = ('Check the cookie location and restart Core if its RPC setting changed.'
                  if stage == 'rpc' else 'Check Dashboard Agent access and session compatibility.')
        return ConnectionFailure(stage, 'http_auth', f'{label} rejected authentication (HTTP {status}). {advice}')
    if isinstance(status, int):
        return ConnectionFailure(stage, 'http_status', f'{label} returned HTTP {status}. Check the service on the configured port.')
    if isinstance(error, ConnectionRefusedError):
        advice = ('Enable RPC, restart Bitcoin Core, and check the configured local RPC port.'
                  if stage == 'rpc' else 'Check the server Agent listener on [::1]:56443 and SSH forwarding permissions.')
        return ConnectionFailure(stage, 'refused', f'{label} refused the connection. {advice}')
    if isinstance(error, (TimeoutError, socket.timeout)):
        return ConnectionFailure(stage, 'timeout', f'{label} timed out. Check connectivity and whether the service is responding.')
    if isinstance(error, socket.gaierror):
        return ConnectionFailure(stage, 'dns', f'{label} name could not be resolved. Check DNS and the server hostname.')
    if isinstance(error, (http.client.HTTPException, ConnectionResetError, BrokenPipeError)):
        return ConnectionFailure(stage, 'transport', f'{label} connection closed or returned an invalid HTTP response. Check the service and tunnel forwarding destination.')
    if isinstance(error, ValueError):
        return ConnectionFailure(stage, 'response', f'{label} returned invalid or incompatible data. Check the configured service and protocol version.')
    if isinstance(error, OSError):
        return ConnectionFailure(stage, 'io', f'{label} could not be reached or read. Check its local permissions and network route.')
    return ConnectionFailure(stage, 'unexpected', f'{label} encountered an unexpected error. Consult the user-service journal for the error category.')


def ssh_failure(lines, port, exit_code=None):
    text = '\n'.join(lines).lower()
    if 'administratively prohibited' in text:
        return ConnectionFailure('ssh_forward', 'forward_denied', f'SSH login succeeded, but the server denied forwarding to [::1]:{port}. Check PermitOpen and the key/account forwarding restrictions.')
    if 'open failed' in text and 'connection refused' in text:
        return ConnectionFailure('ssh_forward', 'target_refused', f'SSH connected, but the server service at [::1]:{port} refused the forwarded connection. Check that its listener is running.')
    if 'host key verification failed' in text or 'remote host identification has changed' in text:
        return ConnectionFailure('ssh', 'host_key', 'SSH server key verification failed. Verify the server fingerprint in a terminal under this desktop user; do not bypass host-key checking.')
    if 'permission denied' in text:
        return ConnectionFailure('ssh', 'authentication', 'SSH key authentication failed in the user service. Check its SSH username, selected private key and access to your unlocked SSH agent.')
    if 'could not resolve hostname' in text or 'no address associated' in text:
        return ConnectionFailure('ssh', 'dns', 'SSH could not resolve an IPv6 address for the server. Check its hostname and AAAA record.')
    if 'address already in use' in text:
        return ConnectionFailure('ssh_local', 'port_busy', 'The local tunnel port is already in use. Stop the conflicting listener or old tunnel.')
    if 'controlpath too long' in text or 'unix_listener' in text:
        return ConnectionFailure('ssh_local', 'control_socket', 'SSH could not create its local control socket. Check the runtime directory and path length.')
    if 'network is unreachable' in text or 'no route to host' in text:
        return ConnectionFailure('ssh', 'ipv6_route', 'SSH has no working IPv6 route to the server. Check this computer’s IPv6 network connection.')
    if 'connection timed out' in text or 'operation timed out' in text:
        return ConnectionFailure('ssh', 'timeout', 'The IPv6 SSH connection timed out. Check the server SSH port and network reachability.')
    if 'connection refused' in text:
        return ConnectionFailure('ssh', 'refused', 'The server refused the SSH connection. Check the configured SSH port and its IPv6 listener.')
    suffix = f' (exit {exit_code})' if isinstance(exit_code, int) else ''
    return ConnectionFailure('ssh', 'transport', f'SSH tunnel could not be established or was lost{suffix}. Check the user-service journal and server SSH service.')
