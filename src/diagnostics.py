"""Actionable, bounded diagnostics; never expose credentials or raw server responses."""
import http.client
import socket
import re


class LocalActionFailure(ValueError):
    """Locally authored, public diagnostic text; never constructed from RPC output."""
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


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
        advice = ('Enable RPC on [::1], restart Bitcoin Core, and check the configured local RPC port. The Agent requires IPv6 loopback RPC.'
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
    for code,message in {
        'dns_local_unavailable':'Ubuntu’s local resolver is unavailable. Start systemd-resolved, then retry the server connection.',
        'dns_timeout':'Ubuntu’s local resolver timed out looking up the server’s IPv6 address. Check DNS and retry.',
        'dns_lookup_failed':'Ubuntu’s resolver could not resolve the server’s IPv6 address. Check DNS and the hostname, then retry.',
        'dns_no_ipv6':'The local resolver returned no usable IPv6 address for the server. Check its hostname and AAAA record.',
        'dns_local_failure':'The Agent could not obtain an IPv6 address through Ubuntu’s local resolver. Check systemd-resolved and DNS.'
    }.items():
        if 'wallaby_resolver '+code+':' in text:return ConnectionFailure('ssh',code,message)
    for code in ('refused','timeout','ipv6_route'):
        if 'wallaby_connect '+code+':' in text:return ConnectionFailure('ssh',code,{'refused':'The server refused the IPv6 SSH connection. Check its SSH port and listener.','timeout':'The IPv6 SSH connection timed out. Check the server port and network reachability.','ipv6_route':'SSH has no working IPv6 route to the server. Check this computer’s IPv6 network connection.'}[code])
    if 'wallaby_connect server_unreachable:' in text:
        return ConnectionFailure('ssh','server_unreachable','Could not connect to the server over IPv6 or IPv4. Check its hostname, SSH port and network connection.')
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
    if isinstance(error,(ConnectionFailure,LocalActionFailure)):return error.code
    from secure_bridge import WorkspaceFailure
    if isinstance(error,WorkspaceFailure):return error.code
    text=str(error)
    if core_refusal(text):return 'core_rpc_refused'
    for prefix,code in (('Dashboard requested cancellation.', 'builder_cancellation_pending'),('Choose Delete and Cancel', 'builder_cancellation_choice_required'),('This build is cancelled.', 'builder_cancellation_pending'),('Close request expired;', 'close_admission_expired'),('Finish the active protected operation', 'local_action_busy'),('Finish active wallet work,', 'unfinished_wallet_work'),('The protected workspace is closing.', 'workspace_closing')):
        if text.startswith(prefix):return code
    return 'local_action_refused'


LOCAL_SETUP_MESSAGES=frozenset({
    'A locally generated contribution was replaced.',
    'An independently entered Agent fingerprint does not match.',
    'An installed setup wallet no longer matches its locally recorded public policy. No cancellation cleanup was performed.',
    'An unfinished monitor changed since creation. Inspect locally; it was retained.',
    'Approve this exact participation proposal locally before reviewing its complete policy. A RAM workspace restart requires a fresh setup session.',
    'Authorisation queue is full; cancellation receipt was not sent.',
    'Backup destination selection cancelled. Original artifacts remain intact.',
    'Cancellation binding differs.',
    'Cancellation cleanup is incomplete or uncertain. Retained artifacts were not replayed; inspect this protected workspace before a fresh local recovery action.',
    'Cancellation was already attempted; reconcile the local outcome before retrying.',
    'Choose Delete and Cancel or Backup and Cancel locally.',
    'Complete policy changed. Review again.',
    'Core could not install the approved public policy.',
    'Core did not confirm a ranged public policy.',
    'Core did not return one public BIP84 key per branch.',
    'Dashboard policy differs from the independently constructed threshold, keys, branches or mandatory height. There is no editable or alternative spending path.',
    'Dashboard requested cancellation. Review Delete and Cancel or Backup and Cancel on Authorise before continuing.',
    'Duplicate cancellation export binding.',
    'Enter a non-empty passphrase, up to 1024 characters.',
    'Finish the current wallet setup and its physical backups before starting another wallet.',
    'Independent address derivation differs from Core.',
    'Install kdialog or zenity for the local backup folder chooser.',
    'Install kdialog or zenity. Secrets are never requested through the browser.',
    'Invalid builder cancellation.',
    'Invalid cancellation export bindings.',
    'Invalid cancellation identity.',
    'Invalid cancellation targets.',
    'Local artifacts or broadcast status changed. Review the cancellation again.',
    'Local secret entry cancelled. No operation was authorised.',
    'Local state changed while backing up. Originals were retained; review again before cleanup.',
    'New signing wallet must be encrypted and locked.',
    'Only an unfinished setup before policy installation can be discarded. Reconcile any attempted installation locally.',
    'Passphrases did not match.',
    'Persistent signer failed encrypted/locked verification.',
    'Protected Core has not finished closing. Keep the RAM workspace running; it was not killed.',
    'Protected Core network differs.',
    'Review and independently verify every distinct producing Agent.',
    'Review the complete public policy again.',
    'Review this cancellation again before deleting or backing up artifacts.',
    'Setup already attempted. Inspect local outcome; nothing was replayed.',
    'Temporary keys retained.',
    'The cancellation export differs from its locally held PSBT. No artifacts were removed.',
    'The cancellation transaction identity differs from local Core.',
    'The proposed network differs from this local node.',
    'The setup monitor already exists; no existing wallet was claimed.',
    'The setup signing-wallet name already exists; no existing wallet was claimed or overwritten.',
    'This setup already generated keys. No secret generation was repeated.',
    'Unknown cosigner contribution.',
    'Unknown external archive completion.',
    'Unsupported local recovery metadata; originals retained.',
    'Use at least 12 characters for the cancellation backup passphrase.',
    'Use at least 12 characters for the encrypted signing wallet.',
    'Verify each distinct producing Agent in this exact wallet setup.',
    'Wait for the active optical write/read-back to finish. No active writer was killed.',
    'Wallet installation was attempted. Reconcile the local outcome before discarding anything.',
})

def core_refusal(message):
    return bool(re.fullmatch(r'Bitcoin Core rejected [a-z0-9_]{1,64} \(code (?:-?[0-9]{1,8}|None)\). Check wallet readiness, encryption and node synchronisation\.',message))

def action_detail(error):
    """Only trusted authored errors or exact known messages, never raw exception text."""
    if isinstance(error,LocalActionFailure):return str(error)
    if type(error) is ValueError and (str(error) in LOCAL_SETUP_MESSAGES or core_refusal(str(error))):return str(error)
    if isinstance(error,OSError):return "Operating system refused the operation; errno="+str(error.errno)
    return "No safe error text is available; raw exception contents were withheld."
