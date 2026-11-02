# Agent V2 Development Build 24 validation

Final regression/focused results are in the accompanying Build24 test log. Package verification compares installed source/web/document bytes and records SHA-256. No production wallets, installed services, SSH/firewall or pruning settings were changed by automated tests.

## Build 24 reported faults and upgrade cleanup

The supplied November 2 logs confirmed repeated Agent exchange rejection/validation failures alongside successful public node registration, and Dashboard history reconstruction issuing unsuccessful historical transaction lookups. The Agent retry loop used two seconds even after reporting 30 seconds; it now uses the actual failure delay. It reports safe categories and fixed processing phases rather than raw remote error text. The Ownership gating/history publication correction belongs to Dashboard Build 28.

Real isolated Core tests send a two-child historical archive through the actual framed peer receiver into one private-key-disabled `Wallaby Extinct` wallet. They verify labels and descriptors, safely extend an existing archive with retained local addresses, refuse label conflicts before mutation, and combine older fragmented watch-only sources into one independently verified preview. An outstanding older archive-history job blocks extension until that recovery is resolved.

The persistent-denial test opens a new Store to simulate reboot, retains old child denials plus an unrelated intentional denial, receives the grouped signed preview, and removes only exact superseded child hashes after local approval. A second new Store confirms persistence. A single-child exact-policy denial can be re-enabled; a deliberate whole-container denial stays. Attempted wallet mutations are never erased merely because a Dashboard queue changes.

Eight JavaScript suites passed, including one-row/multiple-child display, locked watch-only choice and the local obsolete-denial cleanup control. The real offscreen Qt/window-close and framed-IPC suite passed 15 tests. The separate-interpreter production Dashboard Build 28/Agent Build 24 probe passes grouped queue construction, strict Agent validation, signed sender labels, Dashboard signature/binding verification and receiver acceptance. No production nodes, services, wallets, firewall rules or pruning settings were changed.

The first full regression run found two test-fixture errors from reusing an isolated Core wallet directory. The fixture now uses fresh temporary nodes per test; targeted reruns passed. The clean full regression run passed **339 tests** (628.603 seconds); the final grouped transfer/upgrade regression run passed **17 tests** (68.024 seconds), including all new denial migration tests. Additional current-source workspace/denial boundaries are recorded in the accompanying Build24 test log. Physical disc and complete target-machine GUI/privilege lifecycle testing remain outstanding.

## Build 23 archives and public policy renewal

The complete Python regression run passed **329 tests** (505.649 seconds). After the final cancellation/PSBT-binding and denial-upgrade additions, **27 focused tests** passed (67.178 seconds), including the new regression cases. The real offscreen Qt/native framed-IPC suite passed **15 tests**. Seven JavaScript suites cover protected navigation, status, account refresh, logs, cancellation, tunnel-only use and the new archive approval controls. Additional optical/denial regression results accompany the exported test log.

An isolated official Bitcoin Core 31 regtest fixture creates a **3-of-5 mandatory-height vault**, archives one signing account, and completes **two successive vault refreshes** with the archived key plus two other signing accounts. It verifies Core rejection before each unlock height, acceptance after expiry, resulting balances and exact scripts on new monitors, retention of old policy monitors, unchanged quorum/keys, PSBT output-policy bindings and re-encrypted restoration of both policy extensions. A new independently scanned, unfunded future policy must not trigger genesis history recovery; pruning configuration is never altered.

The multi-wallet test stages two existing encrypted node wallets into one authenticated package, decrypts it, independently reviews both entries, restores locked RAM-only signing routes, and verifies full versus partial replacement coverage. Corruption/salvage and legacy single-role restore/signing remain in the regression suite. No queued or merely encrypted backup produces a physical readback receipt.

A two-interpreter probe executes actual Agent and developing Dashboard Build 27 implementations, avoiding shared Python module-name collisions. It checks full-snapshot queue validation, delete/reoffer, locally signed queued/completion results, automatic destruction-task creation, own-key replacement proof after volatile restart, local physical-destruction confirmation, explicit withdrawal and supported capability names. It uses only temporary public fixture data and no live server.

Denial tests verify that persistent sync and archive preferences stay separate and survive opening a new preference store; the new runtime socket does not collide with a running legacy helper. Signed policy-result deliveries are held when their builder request is cancelled. Combined-disc cancellation preserves unrelated selected wallet jobs.

The generic legacy single-interpreter current-Dashboard transport probe cannot load modern Dashboard and Agent modules together because they share module filenames. This is a test-harness limitation, not a live connection failure; Build 23 uses the separate-interpreter production archive protocol probe above, and retains the isolated transport fixture in the full regression suite.

No physical optical disc was written or read. Tests use fixture files, xorriso's file target, framed local sockets and isolated regtest coins. Hardware media capacity, supported burn speeds, USB-drive permissions, optical readback and full installed-system lifecycle must still be verified on the target laptop. These results are functional checks, not an independent security audit.

## Build 22 connection recovery

New recovery tests exercise the real request-cap exception, stale-heartbeat 401, monotonic 15-second deadline, successful replacement session, stale callback isolation, worker-side operation refusal over actual framed JSON IPC, independent timeout closure with a held wallet lock, Core/Dashboard notices, guarded cleanup and retained private work. The protected UI is inert during recovery and returns on success. Initial connection failures remain distinct from loss of an established connection. See AGENT_BUILD22_RECOVERY.md.

## Native close regression

The critical new test uses the actual Unix socket Handler, framing, same-user peer check, JSON encoding and production Decimal decoder. It reproduces the original Build20 validator rejecting a fresh fractional deadline before expiry. The production viewer close_allowed call now sends exactly `ui.request_close` with an empty argument list and receives an explicit successful close gate. The exact QMainWindow closeEvent body accepts its event after that real wire round trip.

Active private work and queued signed results refuse closure and do not arm closing. Legacy fresh Decimal deadlines are accepted; malformed new arguments, boolean/stale legacy deadlines are refused. The ordinary safe-stop helper uses the identical new no-argument gate. Existing archive/delivery/cleanup protections remain.

Known affected open Build17–20 workers may use a narrowly guarded escape route. Version/window checks are independent at the HTTP endpoint; guarded close must succeed before the node is disabled or cleanup attempted. Current, future and unknown open workers do not qualify. A busy old worker cannot be force-stopped. JavaScript verifies that only the known-legacy exception or confirmed failed cleanup exposes the ordinary recovery button.

## Existing regression coverage

The suite retains real-Core public mempool paging and exact Dashboard projection compatibility; large local HTTP versus ordinary result caps; safe diagnostic measurement/redaction/retention/handoff; native/private viewer boundaries; guarded mixed-version upgrades; optional tunnel-only installation; real-Core vault/multisig transaction and message signing; archive restoration; local cancellation backup/restore; private/watch/multisig retirement; sync exclusions; loss labels; and missing-block replay with pruning unchanged.

## Deployment limits

The close tests mock OS protection evidence, but not the socket, JSON codec, production viewer request or worker close dispatch. An additional real PyQt6 offscreen QMainWindow test exercises the actual event: the window hides on success and remains visible on a busy refusal. It is stronger than the direct-call Build20 check and specifically covers the confirmed cause. The complete native Qt/systemd lifecycle still needs confirmation on wallet-laptop after installing Build23. No physical disc was written and no production coins were used.

The user confirmed that the documented guarded ui.close command closed the currently stuck wallet-laptop viewer. No forced service kill, root RAM deletion or private-operation replay was used.

Build20's Dashboard fee-paging follow-up is unchanged and still documented in DASHBOARD_FEE_PAGING.md; Build21's close fix introduces no additional Dashboard protocol requirement. Logs retain seven UTC days and 1 MiB/day, with existing protected RAM/persistence boundaries unchanged.
