# Build 70 — visible wallet offers and local deny list

Wallet Server Build 6 advertises public wallet availability before direct pairing.
Synchronisation shows the wallet, source Agent and reason it cannot transfer yet,
with a link to Peer Connections when pairing is needed. The deny list is always
visible, including when empty. Existing executable incoming requests can also be
denied from Synchronisation. Denials persist locally for the exact wallet policy,
across sources and worker restarts; removing one permits an offer to return.

These notices never create approvals, transfers, imports or signing authority.
Actual transfer still requires pairing, signed previews and existing local approvals.
Private signer cloning and original-role restoration restrictions are unchanged.
No existing Core wallet is added, removed or renamed by availability discovery.

Wire: wallet_sync_offers version 1, revisioned full snapshot, capability
wallet_sync_offers_v1. Strict public descriptors, unique identifiers, bounded
128 rows / 2 MiB and authenticated-session revision checks apply. Local denials
filter the snapshot independently. Only an exact existing executable request can
be linked to a notice. Source display names are informational Server metadata.

An older Server that rejects precisely this optional capability is retried once
without it; other capabilities and validation remain intact. The UI explains that
a matching Server update is needed. Support is probed again after 60 seconds.
This preserves the existing connection while installations are upgraded separately.

Validation includes real Server Build 6 to Agent Build 70 notices, pre-pair deny /
re-enable without executable requests, revision/private-data rejection, attempted-
transfer preservation, compatibility fallback, browser navigation and persistent
preferences. Existing Core / direct SSH and startup regressions are also run.
Physical laptop installation and your real wallet data are not exercised by tests.
