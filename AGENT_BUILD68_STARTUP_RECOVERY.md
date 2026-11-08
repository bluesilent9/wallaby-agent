# Build 68 — startup and workspace recovery

The peer-trust helper now imports its local dependencies correctly under isolated Python. The denial helper also supports isolated validation of saved original-signer bindings. Package files are installed root-owned with group/world write removed. Peer failures are visible in the journal and repeated helper crashes are bounded.

Peer support starts asynchronously and is optional for the protected worker. A failed or slow peer helper leaves local Bitcoin Core and wallet operations available, while pairing and direct transfers remain unavailable until persistent local trust is readable. No trust record is replaced or silently reset. Wallet Server Build 3 and direct-only bulk transfer remain unchanged; this release requires no Server protocol change.

Peer Connections uses ordinary sidebar styling and is selectable only inside the protected workspace. Sidebar entries are alphabetical: Authorise, Disc Operations, Peer Connections, Services, Sign Message, Synchronisation.

Resuming a retained workspace validates the actual worker process identity and replaces only a precisely identified stale viewer child. It never stops the wallet worker to open a window. The resume button follows the installed/current version rather than a hard-coded historical build.

## Exact legacy recovery

The optional legacy inspector handles the reported disconnected Build 62 worker. It runs inside a protected viewer child and accepts only a nonce, worker PID/start identity, short deadline and exact retirement request. It refuses disc/archive/transfer work, queued operation results, active recovery, staged or attempted history jobs, changed wallet descriptors or private-key roles. It may dismiss only pending local history requirements tied to that request after the existing Core wallets are checked with read-only RPC. It does not claim extinction/history completion, delete wallets, alter keys, or restart Core. The old worker must then independently accept its normal safe-close gate before service cleanup.

The one-off recovery script for wallet-laptop additionally verifies every installed Build 67 source checksum and root ownership before installing that fixed inspector. It is not a generic force-close command. If inspection refuses, retain the worker and investigate the remaining work.

## Validation

Automated checks cover isolated helper entry points, optional/blocked peer startup, a real isolated Core worker with failed peer trust, safe viewer identity checks, alphabetical navigation, guarded legacy cleanup and refusal cases. Real direct SSH transfers still cover single-signature keys, original multisig signer restoration, and watch-only vault history. Browser checks cover protected peer actions and disabled ordinary-window navigation. Package extraction verifies source parity and installed permissions. Actual systemd/Qt deployment still requires laptop testing; Treasury Australia has confirmed the temporary peer-helper repair restores node startup.
