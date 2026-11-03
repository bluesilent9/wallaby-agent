# Agent V2 Build 32: installed wallet rename and local recovery

## Confirmed cause

On Treasury Russia, the original treasury/wallet.dat remained present, owned by its user. The rename socket/service was available. A probe inside the actual helper mount namespace showed the wallet parent was not writable and the mount was read-only; opening the database for the helper's lock failed with EROFS. Build 31 unloaded Core and removed its startup entry before that failure, then retained an attempted request without a reconciliation action. Reloading the original wallet through Core's GUI succeeded. This was not a Dashboard request-distribution failure.

A temporary systemd probe with an explicit writable wallet directory and ProtectHome=read-only confirmed wallet access while the rest of the user's home stayed read-only. It did not write wallet bytes or perform a rename.

## Narrow helper configuration

The fixed privileged workspace starter resolves the account home using the numeric authorised UID and the OS account database. Before starting the workspace, it writes a root-owned /run/systemd/system/wallaby-agent-renames@UID.service.d/30-wallet-paths.conf. Only standard ~/.bitcoin and ~/snap/bitcoin-core/common/.bitcoin wallet roots (main/testnet3/testnet4/signet/regtest) get ReadWritePaths exceptions. Missing roots are optional. There is no /home write exception in the rename service template. Paths are quoted/escaped; control characters, symlink drop-ins and untrusted existing configuration are refused. The generated service configuration is volatile and regenerated during first-time RAM setup. During installation/upgrade, a root-only metadata helper refreshes these exceptions for already prepared user workspaces before daemon-reload. It does not start, stop or replace a running protected session.

The rename helper retains ProtectSystem=strict, ProtectHome=read-only, the user's UID, no new privileges, socket peer/cgroup checks and file-identity/path/lock checks. The protected Bitcoin worker still has write access only to its non-swapping RAM workspace and temporary RAM filesystems. No blanket write exception or root wallet-operation worker is introduced. This change concerns the rename helper, not a broad rewrite of other filesystem helper permissions.

Reference: [systemd filesystem namespace restrictions and nested writable exceptions](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#ReadWritePaths=).

## Failure handling

An authenticated, read-only helper preflight checks actual filesystem access, supported files, source identities and destination absence before Core unloads anything. It never takes the loaded wallet's exclusive lock or renames files. A preflight failure leaves the original loaded and the request unstarted. The later move still takes the exclusive database lock and uses no-overwrite atomic rename; all existing ownership/symlink/hardlink safeguards remain.

The local pending request and bounded sanitised logs retain fixed checkpoints (preflight, lock, unload, move, reload, verify) and error categories. Helper replies expose fixed error descriptions, not wallet contents. A failure after unload restores Core's original wallet/startup entry only when the unchanged directory/database inode is positively identified at the old path and no target exists; it verifies descriptors, keys, encryption and balances. No files are renamed back, copied or overwritten and the failed rename is not automatically replayed.

If the outcome remains uncertain, Authorise keeps a **Review and reconcile** action visible even if Dashboard withdrew the request. The local user must confirm. Reconciliation checks the exact original directory/database identity at exactly one of the old/new paths, rejects ambiguous collisions, loads if necessary and verifies public policy, private-key capability and encryption. It never invokes a filesystem move. An already-moved wallet completes under the expected new name; an unmoved original reports a verified restored error outcome. The request then leaves the local unfinished queue after its signed outcome is delivered. If Dashboard still lists a failed operation, cancel it there before issuing a fresh rename; reconciliation does not secretly restart it.

All operation/reconciliation facts remain in protected RAM. This adds no persistent Bitcoin request journal. Services configuration and existing sanitised logs retain their established persistence. Root-owned runtime unit configuration contains only supported service paths.

## Upgrade and validation limits

Close the old protected session before upgrading. Build 32 cannot hot-replace a Build 31 worker holding an attempted operation. The old original can be opened in Core; the one-off stopped-session recovery provided in chat retains persistent Core wallets and hands off sanitised logs before clearing that failed RAM session. Do not relabel an uncertain attempt as an unstarted denial.

Automated tests use real isolated Bitcoin Core 31 instances and real framed Unix socket communication. They cover the exact Treasury (2022 - 2026) destination, verified same-inode moves, loaded private/watch wallets, helper preflight refusal without unload, safe restoration after failed moves, lost replies after an actual move, failed reload and later reconciliation, Dashboard withdrawal, collision refusal, unchanged policies/encryption/balances and startup persistence. Only the Unix helper's systemd cgroup attribution is simulated in the socket fixture; production checks are retained. Narrow mount behaviour was separately checked on the affected Kubuntu machine using the user's temporary diagnostic service. Automated tests do not claim an installed privileged systemd service rename on that machine or physical optical hardware testing.
