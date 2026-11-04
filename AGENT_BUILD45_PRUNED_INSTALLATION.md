# Build 45: new-wallet installation on pruned Core

## Cause

Build 44 constructs a complete signing policy in the temporary offline Core and
restores its encrypted backup onto connected Core. Offline Core has only genesis.
`importdescriptors` interprets `timestamp: "now"` using that Core's blockchain
median time, not the computer clock. This gives fresh policies an ancient birthday.
Restoring can then require blocks the receiving pruned node has already removed.
Core returns restorewallet -4. Pruning enabled does not mean all nodes retain the
same blocks; a node that retains the needed history can behave differently.

The failure was reproduced on an isolated Core 31 pruned regtest node. Numeric
birthdays alone are insufficient when the node has pruned blocks within Core's
rescan safety window. Source reference: Bitcoin Core v31.0
[src/wallet/rpc/backup.cpp](https://github.com/bitcoin/bitcoin/blob/v31.0/src/wallet/rpc/backup.cpp).

## Installation and safeguards

- Record the setup start time before generating any signing keys. Use this numeric
  birthday for both physical signing policies and connected-node imports.
- For node roles, create a blank named wallet on connected Core, encrypted from
  creation. Install the already approved full policy with exactly the original
  local role's private account; other signers remain public. Lock and verify the
  result against both approved descriptor branches. No production restorewallet,
  extra key generation, private-key synchronisation or pruning change is needed.
- Private descriptor assembly stays inside the protected worker and goes only to
  local Core over the existing authenticated IPv6 loopback RPC. It is never sent
  to Dashboard, browser, diagnostic log or a temporary backup on persistent disk.
- Physical-only signing roles still use encrypted wallets/backups inside protected
  RAM and keep their original per-role burn/read-back queues.
- A failed installation is labelled `installation_failed`, preserving RAM keys
  and the attempted authorisation. There is no automatic retry. Cancel from
  Dashboard, then review and confirm the local cancellation on each Agent.
- Cancellation can review a blank/partially imported wallet only when creation was
  positively acknowledged in this same live failed setup and every installed
  descriptor belongs to its recorded approved policy. Unknown creation outcomes
  or extra descriptors remain blocked. All existing empty-balance, history,
  physical-media and exact-directory deletion safeguards still apply.
- A restore error specifically reporting missing pruned history has a fixed safe
  diagnostic category `core_restore_pruned_history`; raw RPC text stays private.

No Dashboard protocol or disc format change is required. This build changes new
installations; it does not replay an old attempted installation during upgrade.
Do not upgrade a running unfinished protected workspace. Cancel/reconcile it first
or finish its required physical backups, close safely, and then install the DEB.

## Validation

Three independent real pruned Core nodes exercise the 3-of-5 policy with two
physical signing roles. Old blocks are genuinely removed; recent blocks remain
available. Each Agent installs a named encrypted full-policy signer using the
original contribution. Prune heights remain unchanged, production restorewallet
is prohibited in the test, and the two physical roles remain queued separately.
The old genesis-dated offline backup is rejected on the same pruned chain.

A separate injected import failure retains the RAM process, records a failed
installation and keeps the authorisation attempted. Cancellation reviews the
acknowledged blank encrypted wallet, but refuses unknown creation and unrelated
descriptors. The existing three-Agent test verifies complete transaction signing,
physical archive round-trip and an unrelated archive queued while discs are pending.

These isolated nodes use dummy keys and no external peers. They do not exercise
real optical media, the user's installed desktop/systemd environment or production
network latency. No real wallet or pruning setting is changed by the tests.
