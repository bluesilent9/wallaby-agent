# Build 14 connection investigation

The provided node_connect.log contains one Dashboard-side error: `expected string or bytes-like object, got NoneType` (30 October 2026 20:22:03 UTC). It has no traceback, endpoint or matching Agent exception. The Dashboard chat independently identified a missing-version exception and is fixing it in Dashboard Build 14. Its relationship to the Agent disconnect is unconfirmed.

A separate **confirmed Agent bug** caused the misleading message: secure_worker converted the real failure into safe text, ProtectedNode raised that text as ValueError, and runtime.describe('dashboard', error) discarded it and substituted the incompatible-data message. Build 14 sends bounded structured ConnectionFailure detail across that boundary and reconstitutes it without relabelling its origin. Older worker safe text is also retained. Tests cover unreadable cookies, local RPC refusal, malformed Dashboard JSON and malformed detail. This fixes diagnostic attribution; the real connection failure is still unconfirmed.

To repeat the isolated probe, run `python3 tests/probe_current_dashboard.py /path/to/dashboard/source` with a writable TMPDIR. It creates disposable simulated Core and Dashboard services, not a connection to the installed server.

Isolated tests against the shipped Dashboard Build 13 HTTP handler/registry/broker passed Agent registration, polling, acknowledgement, fractional deadline decoding, public wallet RPC result forwarding with exact decimal values, and clean disconnection. A Dashboard snapshot/health refresh was also initiated. These do not reproduce the real protected desktop, SSH transport or server configuration. Both chats report that their isolated connection exchanges pass; neither has confirmed the reported disconnection's cause.

Agent Build 14 now retains bounded local categories for invalid endpoint JSON (`json_register`, `json_poll`, etc.), invalid response objects, command lists/fields/IDs/deadlines, and locally refused RPC scope. Server-controlled values, tokens, cookies, RPC parameters and private contents are never reflected in these messages. Existing transport, authentication, forwarding and local Core diagnostics remain. The read-only RPC allowlist is unchanged.

If the failure persists with both new builds, the new Agent message/category and corresponding Dashboard traceback are needed. On the affected computer the service journal can be read with `journalctl --user -u wallaby-agent-node.service --since "10 minutes ago" --no-pager`; protected-worker service diagnostics may also be needed. Do not paste cookie contents, private keys or passwords. This build makes that next test actionable; it does not claim the disconnect is fixed without reproducing its cause.

No wire-protocol change is required for the command-copy UI or these diagnostic categories. No Dashboard code was changed by the Agent chat.
