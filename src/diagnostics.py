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
    from agent_rpc import PublicDataFailure
    if isinstance(error,PublicDataFailure):
        advice={'response_limit':'Bitcoin Core/public RPC response exceeds the 16 MiB transport limit. For getrawmempool this can be a large verbose mempool. A bounded/paged Dashboard request is needed; no incomplete mempool was substituted.','private_material':'Public RPC output was blocked because it contained private-key material. No private result was sent.','response_json':'Local Core/public HTTP response was not valid JSON. Check the configured RPC service.','mempool_busy':'Another local mempool capture is in progress. Retry this read-only capture after it finishes.','mempool_limit':'The complete local mempool exceeds the bounded snapshot capacity. No partial projection data was returned.','mempool_expired':'The mempool snapshot expired or was replaced. Discard incomplete pages and begin a new capture.','mempool_offset':'The requested mempool page is outside this snapshot.','mempool_core':'Bitcoin Core refused its public mempool snapshot. Check node readiness.'}
        message=advice.get(error.code,'Public RPC data was refused.')
        if error.code=='response_limit' and error.details:
            message='RPC response exceeds its '+str(error.details.get('limit_bytes'))+' byte limit at '+str(error.details.get('boundary'))+'. For fee projection, Dashboard must use the paged wallaby_mempool_snapshot interface. No partial data was returned.'
        failure=ConnectionFailure(stage,error.code,message);failure.measurements=error.details;return failure
    label = {'rpc': 'Local Bitcoin Core RPC', 'dashboard': 'Wallaby Dashboard',
             'workspace': 'Protected Bitcoin workspace', 'ssh': 'SSH', 'configuration': 'Agent configuration'}.get(stage, 'Node interface')
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


def action_code(error):
    """Classify known local refusals without recording arbitrary exception text."""
    if isinstance(error,ConnectionFailure):return error.code
    from secure_bridge import WorkspaceFailure
    if isinstance(error,WorkspaceFailure):return error.code
    text=str(error)
    for prefix,code in (('Dashboard requested cancellation.', 'builder_cancellation_pending'),('Choose Delete and Cancel', 'builder_cancellation_choice_required'),('This build is cancelled.', 'builder_cancellation_pending'),('Close request expired;', 'close_admission_expired'),('Finish the active protected operation', 'local_action_busy'),('Finish active wallet work,', 'unfinished_wallet_work'),('The protected workspace is closing.', 'workspace_closing')):
        if text.startswith(prefix):return code
    return 'local_action_refused'
