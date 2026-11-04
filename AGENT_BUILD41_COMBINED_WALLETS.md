# Build 41 — named signing wallets and archive availability

This is a Development format change for new Wallet Builder setups. Cancel and
locally clean up an unfinished Build 40 test first, close its protected workspace,
then install Build 41. Refreshing the browser does not replace a running worker.
No existing Core wallet is silently renamed, merged or deleted by this upgrade.
The cancelled QR experiment is not included.

## One wallet per local signing role

Each persistent signing wallet now stores its encrypted signing key and both
complete receive/change descriptors for the approved policy. There is no extra
persistent watch-only monitor on a machine with a node signing role.

* Multisig Core names: `Treasury Node Live - Signer`, for example. The format is
  `<wallet name> <role name> - Signer`; every local role remains independent.
* A single-signer wallet uses the proposed wallet name directly.
* A producer with only physical/disc roles keeps a public watch-only wallet under
  the proposed wallet name. Its disc keys remain in protected RAM until backed up.
* Names must satisfy the existing safe Core wallet-name rules. Collisions, unsafe
  names and duplicate resulting role names stop before key generation; installation
  checks again before restoring anything. No existing name is claimed or replaced.

Participation still generates independently encrypted keys in an offline RAM
Core and publishes signed public contributions. At complete-policy approval, a
native dialogue requests each local role's existing passphrase again. The worker
reads private descriptors directly from that offline Core, derives the exact
previously approved account, and constructs a blank encrypted full-policy wallet
in RAM. Only that encrypted backup is restored to the persistent node, or queued
for its physical disc. Temporary standalone key accounts never become persistent
node wallets.

Core can export a master private descriptor with hardened paths. The worker
normalises it to the signed account, verifies the complete public policy after
import and restore, and checks that the result is encrypted and locked. An archive
load independently unlocks and verifies the exact assigned private role; a backup
from another role with the same public policy is rejected.

Existing Core private wallets retain their explicitly chosen persistent storage.
Temporary private descriptors, passphrases and backup staging remain inside the
protected worker/RAM Core. They are never returned to Dashboard or browser APIs,
written as a recovery file on ordinary disk, or admitted through public RPC.
The fixed internal private-descriptor readers have no public dispatcher action.

## Refreshes keep history in the same wallet

A public-only wallet adds the new policy to its existing wallet. A private wallet
uses a native local passphrase prompt and its own keys to add the matching private
policy there. Older receive/change descriptors remain available for old addresses
and funds; the new generation becomes active. No additional `Wallaby refresh …`
Core wallet is created. Refresh does not change conditions on existing outputs.
The original setup must be complete before a pending setup policy is refreshed.
Read-back-verified archive replacement and signed policy lineage remain required.

## Public inventory while preparing/burning discs

Public RPC waits up to three seconds for the workspace lock instead of returning
`busy` merely because another public read or viewer status poll overlaps it.
Optical writing uses an already captured encrypted package and no longer blocks
Core's read-only wallet inventory. Key creation, installation, archive capture,
restoration and actual wallet mutation remain guarded. Pending cleanup/transfer
and history recovery retain their existing restrictions. Safe workspace closure
still refuses unfinished disc/setup work.

Rate-limited `rpc.busy` diagnostics distinguish `workspace_lock_timeout` from
`active_wallet_operation`; neither includes RPC payloads or descriptors.

## Dashboard integration

The existing signed `wallet_setup_inventory` schema is unchanged. A monitor
wallet name can now equal one value in `signing_wallets`: this is intentional.
All full public policy descriptors still agree across the independent roles.
`wallaby_managed.kind=combined` is optional public getwalletinfo metadata, with
role ID/name, setup/policy identity and readiness. Names are display information,
never proof of which private key is present.

Dashboard must treat these as independent signing roles of one logical wallet,
not interchangeable private-key replicas merely because descriptors match.
Deduplicate displays and balances by logical policy while retaining every role
for signature collection, archive routing and cancellation. Distinct roles on the
same node require distinct signer IDs; hashing only node plus common descriptors
is insufficient. Keep using the authenticated setup role-to-wallet inventory.

Do not queue ordinary private-wallet replication for these combined policies.
Agent refuses managed signer clones, including matching restricted multisig/vault
policies after RAM restart and a wallet rename. A watch-only policy-only transfer
must remain public-only; it must never clone the producer's private wallet. A new
archive request must remain selectable on a node with an idle pending disc job;
transient busy reads must not be presented as permanent lack of a private copy.
Existing Wallet Builder inventory, archive-result and cancellation wire messages
remain unchanged; no new capability is advertised to older Dashboards.

Reference: Bitcoin Core's descriptor import API:
https://bitcoincore.org/en/doc/32.0.0/rpc/wallet/importdescriptors/
