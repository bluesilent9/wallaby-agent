# Build 85: protected node session ownership and automatic fault evidence

Close protected workspaces normally before installing. Start the node interface again after installation. Build 84's receiver-initiated trusted direct transfer behaviour remains; the peer wire protocol is unchanged and no Wallet Server update is required.

## Connection fix

The reported logs showed a changed local node session, closely spaced Server registrations, an identity conflict and subsequent worker unavailability. They did not contain enough process/service provenance to identify the initial source of the overlap. A reproducible Agent defect made that overlap unsafe: obsolete ordinary-service cleanup reported an unscoped transport failure, which could stop a newer protected connection.

The ordinary node service now has one local process lock and a per-controller identity. Reattaching to the same live worker/tunnel reuses the existing authenticated Server session rather than registering another one. Status, stop and transport-failure messages bind both the worker generation and its current controller. Superseded controllers exit without publishing a failure or interrupting the current owner. Old unscoped cleanup cannot stop an explicitly owned session. Genuine current-owner failures still enter the normal recovery budget; protected RAM cleanup safeguards remain.

The ordinary service always uses the protected-node proxy. Missing environment flags cannot select an ordinary-process Core/Server client. Packaged user services also explicitly require protection. The Server's genuine identity-conflict protection is retained.

## Automatic diagnostics

Startup, controller changes and failures record bounded, sanitised process/service evidence automatically. This includes process IDs, separately captured loaded module build labels, protection flags, memory/thread counts, session sequence and reuse/obsolete-cleanup outcomes. Read-only fixed-unit checks capture service state, MainPID, restarts, exit result, memory current/peak/limit and available cgroup OOM counts. Launcher/unit checks record packaged-versus-custom classification and drop-in count, without exporting arbitrary arguments or paths.

Registration, failure and closure events record session sequence, safe failure category, observed RPC count and whether disconnect was confirmed. They do not log session/controller tokens, MACs, credentials, cookies, wallet contents, RPC arguments/results or private keys. Packaging verifies the new loaded-process build labels too, so a stale label cannot silently ship.

Saving the ordinary Agent log now requests current sanitised protected diagnostics before returning the consolidated text. It does not need to wait for safe workspace closure, approve an operation, acquire the wallet-operation lock or change the workspace. If the worker is already down, export still includes the ordinary process and fixed-service snapshot and explicitly records that protected events were unavailable. Existing protected-window log-export refusal and safe-close handoff remain. Failure of a diagnostic command never starts/stops Core or retries a wallet action.

Checks have short timeouts; background capture is rate limited and allows only one capture at a time. Additional manual diagnostics can still be necessary for faults outside the observable service/process state, but these session faults should leave substantially more evidence in the normal exported log.

## Validation

An isolated actual Core/Wallet Server reproduction fails on Build 84 when obsolete cleanup stops the current node; it passes on Build 85. Controller handover tests verify the same Server registration survives, stale stop/failure requests are ignored, the current owner can stop normally and Core data remains untouched. Process-lock, missing-environment and scoped-proxy tests cover duplicate ordinary workers and the protected boundary.

Diagnostic tests cover live protected event collection, unavailable-worker export, busy-wallet export without taking its operation lock, read-only command timeouts and omission of secret command arguments/controller/wallet fields. Startup, control-traffic, real multi-Agent Server health, planned Core restart, receiver-only wallet transfers and clone/block recovery regressions remain. UI suites check receiver consent, separate deletion, navigation and polling.

Tests use isolated Core 31 nodes and actual authenticated HTTP/direct SSH. Desktop systemd launch and protected-memory attestation are adapted in fixtures; production laptop services, Snap confinement, real Wi-Fi and user wallets were not modified or exercised. This release fixes the reproduced ownership defect and adds the evidence absent from the reported logs; it does not claim that every possible external restart cause was proved from those attachments.
