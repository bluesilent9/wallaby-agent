# Build 71 — one wallet synchronisation table

Synchronisation combines locally loaded Core wallets, Server-discovered missing-
wallet offers, executable requests and persistent receive denials. All rows sort
alphabetically by wallet name, regardless of status. Exact public policy identity
combines repeated peer offers and local accounts; names never identify a policy.
Multiple local multisig signing accounts sharing the complete wallet policy appear
in one main wallet row, with a separate Signer column. Locally known role names
come from the Agent's policy records; unknown source accounts require signed review.

Send-to and Receive-from menus list only exact current requests whose immutable
transport binds an independently QR-paired Agent with a live direct connection.
No online suitable route shows a disabled red "No Agent Detected" menu. Mobile
channels, unpaired/offline peers, different policies and legacy relay transports
cannot become menu choices. Public offers stay visible before pairing. Original
signer restoration and managed-key cloning restrictions remain enforced.

A private source permits either a private-wallet or watch-only selection. A
watch-only source forces a checked, disabled watch box. Changing peer deselects
other peers for that exact policy/direction atomically. Overlapping older peer
selections are refused before transfer, so one displayed wallet cannot hide
additional recipients. All choices remain local;
review, local receiver approval and sender approval still precede transfer. Direct
readiness is checked again before a batch starts. No transfer auto-starts.

Receive denial and re-enable controls are in the same wallet table. The separate
public-offer and sync-denial sections are removed; lifecycle denial controls stay
on Authorise. A Synchronisation sidebar count reports distinct wallets with pending
send/receive work, including connection-waiting offers, excluding disabled incoming
work and fully local wallets with no outstanding offer. Multiple peer choices do
not multiply that count.

Local public inventory is cached from successful local Core responses and the
local wallet listing. Table rendering makes no Core, network or private-key calls.
Exact descriptor sets determine grouping. Different policy histories are not
silently merged based on similar wallet labels. Inventory and peer changes update
the table without resetting an unchanged selected route.

Requires existing Wallet Server Build 6 for public offers; this UI change needs no
additional Server protocol change. Older-server optional-capability compatibility
from Build 70 remains. Existing local denials, wallet files, historical policies,
LOST labels and direct-only bulk transfer behavior are retained.

Validation: public-table and preference checks, watch-only / atomic-route tests,
multisig account grouping, Server 6 interoperability, real isolated Core and direct
SSH transfers (single signature, multisig role and vault history), batch watch-only
history, progressive/daisy-chain block regressions, JavaScript suites and a real
headless-browser check of sorting, badge, menus, denial, watch lock and offline
controls. Physical laptop installation is still a deployment test; your wallets
and running services were not changed during these checks.
