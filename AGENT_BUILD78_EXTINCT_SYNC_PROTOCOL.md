# Build 78: Extinct history update signalling

Server counterpart required. The Server discovers routes and carries public
availability notices; it is never the source of history, labels, coverage,
signing authority or local extinction consent.

## Discovery RPC

Add `wallaby_extinct_summary` to the Server's wallet RPC allowlist. An Agent
advertises it in registration `rpc.methods`. Call with `params=[]` (or `{}`)
and the exact loaded Extinct wallet name, after normal public inventory. Older
Agents do not advertise it and must keep their existing behaviour.

Result v1 has exactly `version`, `chain`, `addresses`, `transactions`,
`address_hash`, `transaction_hash`, `label_hash`, `history_complete`, `digest`.
Counts are integers. Hashes are lowercase SHA256 of canonical JSON. No addresses,
transaction records, wallet database or private material are returned. `digest`
hashes the other fields. It excludes the moving node tip and confirmation count.
`history_complete` is local scan provenance, not Server authority.

Differences are signals, not an ordered version. Larger counts do not prove a
superset. For two current summaries with different digests and at least one
complete source, offer ordinary watch-only `wallet_transfer` v3 requests even
when the receiver already contains all public descriptors. Extinct addresses
and names in these requests remain untrusted until compared on direct SSH.
Do not suppress such updates merely because no extinction request exists.
Do not label an incomplete source authoritative. If both have complete but
different histories, permit either direction; the receiving Agent preserves
its own additional history. A subsequent reverse route can converge the union.

Existing receive denials, current pairing, local batch/transfer approval and
active-work restrictions apply. Do not bypass them. A completed attempt does
not suppress a later different history pair: include both summary digests in
the route's change identity. Do not repeatedly renew an unchanged attempt.
After completion refresh both summaries. Matching current digests withdraw
unstarted update offers; retain recorded operation outcomes. An old completed
route must not cause `contains()` or retry logic to hide changed history.

Do not add history fields to wallet-transfer proposals or signed previews.
The existing exact schemas remain unchanged. No new exchange capability is
needed: RPC method advertisement negotiates discovery support.

## Direct Agent protocol

Build 78 receivers add `core_history_v2` to the existing direct SSH ready
features. Build 78 senders use v2 when available; legacy v1 remains readable.
The existing authenticated/signed `core_history` envelope binds the exact
transfer id, live details hash, payload checksum and length. V2 history packets
add coverage provenance to the public Core records; these travel over direct
SSH only, never through the Server or relay. Sender/receiver independently
validate local chain, fixed descriptors, labels, native record contents and
active confirmation headers. No blind replacement or automatic key access.

The receiver still requires completed local extinction consent for every
incoming address and refuses an active local owner. A missing queued Server
request cannot substitute for that approval. Existing locally verified, whole-history-upgraded Extinct entries also count as local
extinction evidence for pre-Agent legacy retirements. A pending/restored local
decision overrides that membership; unknown unloaded wallets require local review.
New addresses with unknown local retirement consent are deferred explicitly, not
treated as permission. Existing unique history and
LOST labels are preserved; conflicting labels stop the update. An older local
coverage record is retained unless the union is fully covered. No permanent
backup is made: staging and the old public wallet survive only until verified
atomic replacement/cleanup (uncertain failures retain reconciliation evidence).
