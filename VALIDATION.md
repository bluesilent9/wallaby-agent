# Agent V2 Development Build 17 validation

The final shipped-source regression run passed **212 Python tests in 259.455 seconds**. The focused lifecycle/startup/denial checks also passed (46 tests in 5.246 seconds before the final full run). Four JavaScript UI/policy suites passed and all web scripts passed Node syntax checks. All Python files parse successfully.

## New lifecycle coverage

- First green Core/Dashboard status opens one protected window, with no duplicate per status poll.
- Monitor-driven viewer exit disables only the node, preserves DDNS-GO/Dashboard, and schedules cleanup without browser polling.
- Unknown status never proves the viewer closed. Busy/forced viewer loss retains RAM and its protections while switching the node off.
- Settings/monitor control locking avoids enable/cleanup races; reconnect is blocked during cleanup. Stale markers clear only on confirmed inactive/failed systemd state.
- Native/overlay close refuses active wallet work, loaded archives and critical undelivered results. Sync exclusions and denial notices are not unfinished work.
- Close approval gates subsequent wallet operations. Expired requests cannot arm the closing gate. Public node status/stop remain responsive while a signing dialogue holds the operation lock.
- Successful service stop must also prove the non-swapping RAM directory empty before reporting cleared state. Failure explanations do not include raw/private exception contents; retries are delayed.
- Actual shipped UI handlers cover ordinary-window inertness, disconnect feedback, absent manual Start/Close workspace buttons and protected-viewer Services disabling.

## Existing invariants

Real Bitcoin Core 31 regtest nodes exercised single/multisig/vault signing, archival restoration, BIP-322 messages, local denial persistence and address/label history recovery with pruning unchanged. Remote RPC remains public/read-only. The restrictive-umask parent-directory repair, script serving and tunnel-only installation checks continue to pass.

No production node data, wallets, SSH/firewall rules or pruning settings were changed. No optical device was written. Unit tests substitute fixed local service/GUI process boundaries; the actual privileged Qt window lifecycle still needs verification on wallet-laptop after installation. This build does not install a virtual optical driver or save wallet disc images outside protected RAM.
