# Agent V2 Development Build 22 validation

Final regression/focused results are in the accompanying Build22 test log. Package verification compares installed source/web/document bytes and records SHA-256. No production wallets, installed services, SSH/firewall or pruning settings were changed by automated tests.

## Build 22 connection recovery

New recovery tests exercise the real request-cap exception, stale-heartbeat 401, monotonic 15-second deadline, successful replacement session, stale callback isolation, worker-side operation refusal over actual framed JSON IPC, independent timeout closure with a held wallet lock, Core/Dashboard notices, guarded cleanup and retained private work. The protected UI is inert during recovery and returns on success. Initial connection failures remain distinct from loss of an established connection. See AGENT_BUILD22_RECOVERY.md.

## Native close regression

The critical new test uses the actual Unix socket Handler, framing, same-user peer check, JSON encoding and production Decimal decoder. It reproduces the original Build20 validator rejecting a fresh fractional deadline before expiry. The production viewer close_allowed call now sends exactly `ui.request_close` with an empty argument list and receives an explicit successful close gate. The exact QMainWindow closeEvent body accepts its event after that real wire round trip.

Active private work and queued signed results refuse closure and do not arm closing. Legacy fresh Decimal deadlines are accepted; malformed new arguments, boolean/stale legacy deadlines are refused. The ordinary safe-stop helper uses the identical new no-argument gate. Existing archive/delivery/cleanup protections remain.

Known affected open Build17–20 workers may use a narrowly guarded escape route. Version/window checks are independent at the HTTP endpoint; guarded close must succeed before the node is disabled or cleanup attempted. Current, future and unknown open workers do not qualify. A busy old worker cannot be force-stopped. JavaScript verifies that only the known-legacy exception or confirmed failed cleanup exposes the ordinary recovery button.

## Existing regression coverage

The suite retains real-Core public mempool paging and exact Dashboard projection compatibility; large local HTTP versus ordinary result caps; safe diagnostic measurement/redaction/retention/handoff; native/private viewer boundaries; guarded mixed-version upgrades; optional tunnel-only installation; real-Core vault/multisig transaction and message signing; archive restoration; local cancellation backup/restore; private/watch/multisig retirement; sync exclusions; loss labels; and missing-block replay with pruning unchanged.

## Deployment limits

The close tests mock OS protection evidence, but not the socket, JSON codec, production viewer request or worker close dispatch. An additional real PyQt6 offscreen QMainWindow test exercises the actual event: the window hides on success and remains visible on a busy refusal. It is stronger than the direct-call Build20 check and specifically covers the confirmed cause. The complete native Qt/systemd lifecycle still needs confirmation on wallet-laptop after installing Build22. No physical disc was written and no production coins were used.

The user confirmed that the documented guarded ui.close command closed the currently stuck wallet-laptop viewer. No forced service kill, root RAM deletion or private-operation replay was used.

Build20's Dashboard fee-paging follow-up is unchanged and still documented in DASHBOARD_FEE_PAGING.md; Build21's close fix introduces no additional Dashboard protocol requirement. Logs retain seven UTC days and 1 MiB/day, with existing protected RAM/persistence boundaries unchanged.
