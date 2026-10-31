# Agent V2 Development Build 19 validation

Final results are recorded in the accompanying Build 19 test log and package-verification receipt.

## Build 19 coverage

- Strict Dashboard Build 20 cancellation schema, full request/delivery hashes, local export outbox/PSBT/txid bindings, exact delivery-only receipt, duplicate receipt handling, cancelled action/output suppression and unrelated-artifact preservation.
- An exact snapshot of Dashboard Build 20's receipt method accepts the Agent receipt and completes Dashboard delivery while the Agent still requires a pending local approval. A receipt with deletion fields is refused.
- Real Bitcoin Core 31 regtest creates a three-role encrypted wallet setup, receives cancellation without losing live keys, exports an encrypted recovery bundle, decrypts it in the isolated fixture and restores every wallet with matching public descriptors. A second real-Core case installs a node/disc multisig setup, then deletes only its locally tracked installed signing/monitor group and RAM disc session; an unrelated wallet remains.
- Failed backup, stale local review, active optical work, active transfer and uncertain cleanup are refused without automatic replay. Cancelled requests cannot trigger a stale signing passphrase prompt or use generic Deny/old setup discard controls. Missing locally reserved-but-never-created wallet names do not become assumed deletion targets.
- Local mempool/chain evidence determines broadcast warnings; incomplete history is reported separately. Shipped UI checks cover red broadcast warnings, separate red/green cancellation actions and local deletion acknowledgement.
- Actual Unix SCM_RIGHTS transfer checks one owner-only, empty write-only file handle. Destination traversal, symlinks, overwrite and invalid bindings are refused. Only streaming ciphertext reaches the explicit local backup file; backup readback must match before cleanup.
- Retirement withdrawal before authorisation and during archiving stops before wallet deletion. Completed or uncertain outcomes never become false cancellation success. Older completed records without evidence report uncertainty.
- Typed log redaction before storage/export; distinct environment labels; chronological deduplication across restarts; cross-process concurrent append; seven UTC days and 1 MiB/day retention; private file/directory modes; symlink refusal; protected-RAM-only storage and safe ordinary-side handoff. Failed handoff prevents normal service stop. The log HTTP route requires local authentication and refuses download from the protected viewer. Shipped JavaScript checks authenticated download as `Wallaby_Agent.log`.
- An acknowledged verbose getrawmempool response-limit failure produces `local_rpc_response_limit` with safe category/method data, does not leak exception text and does not repeat the Core call. The underlying reported production mempool failure is not independently reproduced; its cause is not declared fixed.

## Existing invariants

Regression coverage retains mixed-worker upgrades, native-close/lifecycle flags, optional tunnel-only installation, restricted permission rules, real-Core multisig/vault transaction and message signing, optical archive restoration, extinction across private/watch/multisig copies, persistent local sync exclusions, fixed-address loss labels and genuine missing-block recovery with `-prune=550` unchanged.

## Deployment limits

No production Core wallets, installed Agent services, SSH/firewall rules or pruning settings were changed. No physical disc was written. Real-Core tests use isolated regtest fixtures, never mainnet coins. Native Qt/systemd/Polkit startup and mount-namespace handoff use controlled substitutes in automated tests; fresh installation and the complete protected-window lifecycle still need verification on wallet-laptop. No successful privileged service startup is claimed from this sandbox.

The existing deletion helper remains limited to supported named native/Snap wallet directories under /home and refuses live locks or unexpected filesystem contents. Unlink is not forensic erasure. Existing discs, backups and offline holders are not erased by local cancellation.

Protected request/result state remains volatile. Explicit exceptions are intentionally retained Core wallets/blockchain records, signed Dashboard outputs, physical backups, local sync Denial preferences, Services configuration/identity, sanitized diagnostics and the newly authorised encrypted cancellation backup. Force-killing a worker or losing power can lose protected diagnostics and local pending approvals before normal handoff; normal safe closure retains RAM until required work and handoff complete.
