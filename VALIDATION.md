# Agent V2 Development Build 18 validation

The regression run passed **237 Python tests in 533.547 seconds**. After the final loss-label/legacy-evidence hardening, 13 focused tests passed in 30.326 seconds; 26 focused lifecycle/deletion/retirement-delivery checks passed in 1.162 seconds. Seven final deletion-boundary/legacy-archive compatibility checks passed in 28.948 seconds. Four JavaScript UI/policy suites and Python/web syntax checks passed. The integration result-validator fixture was compared to the current Dashboard Build 18 function and matched structurally.

## Build 18 coverage

- Actual framed Unix-socket exchange with an older worker, including SO_PEERCRED identity and the explicit unsupported-action response. Fresh-worker reuse, one verified idle restart, no restart loop, busy-worker preservation, refusal propagation and failed/stale inspection are exercised.
- Legacy inspection exports only nonce/PID/start-time-bound idle evidence; private requests, keys and outbox contents remain inside protection. Incomplete evidence, loaded/staged archives, unfinished setups and real undelivered results prevent replacement. Denial/preferences notices remain completed user choices; retirement cancellation/result delivery is explicitly retained until acknowledgement.
- First green Core/Dashboard status opens one protected window. Monitor-driven native close disables only the node, preserves unrelated tunnels and waits for verified RAM cleanup. Unknown state never proves closure. Native close reports actual local errors and has an older-worker fallback checked within the protected process.
- Shipped JavaScript exercises ordinary-window Services-only navigation, protected-window Services disabling, moved protected evidence, inert ordinary-page locking, disconnect feedback and absence of manual Start/Close workspace controls. Sidebar clicks no longer launch viewers.
- Real Bitcoin Core 31 regtest exercises private and watch-only retirement, all reviewed local copies, a shared multisig monitor plus dedicated signing accounts, successful archive/deletion, refusal of funded or mismatched targets, helper failure with no completion/replay, and POSIX lock refusal on a loaded Core SQLite database.
- Exact LOST labels survive merging private/watch copies; conflicting LOST labels stop retirement. Legacy archive-only success keeps the original strict minimal response and never deletes wallets. The new result passes the copied Dashboard Build 18 strict result validator; all proposed deletion names must match.
- Deletion boundaries refuse paths outside supported locations, symbolic/hard links, unexpected files and changed inodes. A fake helper's success reply cannot establish completion while the original directory still exists. No wallet bytes are read by the unlink helper.

## Existing invariants

Real Core regtest also covers vault/multisig transaction signing, unsigned vault composition, archive restoration, BIP-322 proofs, persistent local sync exclusions, address/label history and pruned-chain recovery with pruning unchanged. Dashboard direct RPC remains public/read-only; secret or mutating operations still require local Authorise approval. Tunnel-only optional-dependency installation, restrictive-umask directory preparation and fixed service-policy checks continue to pass.

## Deployment limits

No production Core wallets/data, installed services, SSH/firewall rules or pruning settings were changed. No optical disc was written. The root systemd/Qt window and in-service upgrade inspection boundaries use controlled substitutes in tests; native GUI startup/close and fresh-OS service installation still need deployment verification on wallet-laptop. systemd-analyze verify could not initialise its working directory in this read-only execution sandbox; no successful privileged service startup is claimed.

The narrow removal helper supports named standard native/Snap wallet directories under /home. Custom/default/nested paths are refused. Filesystem unlink is not forensic secure erasure; existing discs/backups and undiscovered/offline copies cannot be declared destroyed by an Agent. Dashboard Build 18 owns all-holder coordination and physical-disc confirmation. Bitcoin requests/results remain in protected RAM; only existing Services configuration and the sync Denial list persist as before.
