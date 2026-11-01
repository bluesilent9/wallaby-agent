# Build 22: bounded node recovery

V2 Development Build 22. Recovery window: **15 seconds**, changed from the initially proposed 30 seconds at the user's request.

## Confirmed Agent cause

The supplied log records `dashboard/session_limit` at 05:41:57 UTC, then an authentication HTTP 401 from the old session, and no useful automatic recovery before the user manually closes at 05:55:30. This confirms a local Agent session-limit failure and a terminal-status race; it is not evidence of an unavoidable network hiccup. Earlier HTTP 401s cannot by themselves establish their server-side cause. The Dashboard chat separately identified valid RPC/exchange traffic not refreshing its liveness timer and is fixing that in Dashboard Build 23; duplicate live-identity protection remains. No Dashboard source is changed here.

The previous worker could overwrite its terminal `failed` status from a late heartbeat. Its ordinary controller then saw red without `failed` and kept waiting. The per-session 10,000-ID anti-replay limit remains bounded. Reaching it now ends that session, records the original category before cleanup, and reconnects with a fresh server-issued token. The Agent never clears the replay cache while its token is active, and never automatically replays an acknowledged RPC or a local signing action.

## Recovery lifecycle

After an established connection fails, one monotonic 15-second budget begins. Repeated failures do not reset it. The private UI's main content and sidebar become inert beneath an accessible countdown overlay. Worker-side guards also refuse new local wallet operations. The old Disc Operations/Sign Message prerequisite message is removed.

The protected node coordinator retries local Core health and fresh Dashboard registration at two-second intervals after each failed attempt. HTTP health, heartbeat, registration and poll waits are bounded so a long poll cannot consume the entire recovery window. The ordinary SSH worker reattaches at roughly three-second intervals; the authenticated master also retries promptly while the node is enabled. Normal DDNS/Dashboard tunnel backoff is unchanged. Late callbacks are scoped to their attempt and generation.

Recovery success before the deadline unlocks the same protected UI and preserves its local work. Deadline expiry is checked independently of HTTP or wallet-operation locks: the tracked viewer is terminated, node desired-state is disabled by the lifecycle monitor, and the ordinary Services window is restored with a persistent public diagnostic:

- `Connection issue between agent and the Dashboard Server`
- `Connection issue between the agent and Bitcoin Core`

The category comes from the first detected failure; SSH forwarding problems belong to the Dashboard path. No claim is made that a later failure supersedes that initial diagnosis. Logs retain subsequent attempt/failure categories for investigation.

## Safe handling at timeout

Timeout closes the UI; it does **not** force deletion of volatile private work. The monitor's existing busy checks retain the protected service, sleep inhibitor, non-swapping RAM and archives/queued results while work is unfinished. Services explains that RAM was retained and offers the normal node toggle to resume. No automatic local operation replay occurs. Idle workspaces use the existing guarded close, sanitized log handoff and verified RAM cleanup. Ordinary window closure still uses Build 21's argument-free native X-close gate.

Public lifecycle flags alone cross to Services. Private data, requests, addresses and keys remain protected. Logs retain the existing seven UTC days / 1 MiB per day limits. No production Core, pruning setting, SSH/firewall configuration, or installed service is changed by development tests.

## Verification and remaining deployment check

Tests cover the real session limit, late HTTP-401/heartbeat callbacks, replacement sessions, immutable deadlines, Core/Dashboard classification, framed local IPC refusal of wallet operations during recovery, tracked-viewer expiry independent of a held wallet lock, node-only disable, retained work, and notification preservation after safe cleanup. JavaScript exercises the actual inert overlay and unlock. Existing native Qt close and real-Core regressions remain.

After installing, verify a brief Core/Dashboard interruption recovers automatically, and a longer interruption closes to Services after 15 seconds without discarding unfinished work. Timing starts when a failure is detected, not at the unknown instant a cable or remote service failed. OS scheduling and the existing guarded cleanup can add time before all RAM cleanup completes. Hardware/systemd validation on wallet-laptop is still required.
