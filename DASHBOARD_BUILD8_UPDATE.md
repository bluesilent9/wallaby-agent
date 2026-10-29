# Dashboard handoff for Agent V2 Development Build 8

**Implemented by Dashboard V1 Build 10.** Its current Agent-only synchronization path uses the multiple-request queue, version-2 signed metadata previews and recovery states below. Older synchronization compatibility was intentionally removed at the user's request. Agent application code is unchanged by this documentation update.

## Feature detection and compatibility

Agent Build 8 sends `X-Wallaby-Agent-Version: 2.0.0~dev8` on its HTTP requests, including registration/exchange. Treat this as feature negotiation only, never as proof of identity or authority. Registration authentication and node ownership remain mandatory. Older Dashboard servers ignore this extra header; the existing exchange request JSON/capability list remains unchanged. Gate the new response schemas on a registered Build 8-or-later compatible Agent; do not send them to Build 7.

The envelope is still `/agent/v2/exchange`, request version 1, and response exactly `{version:1, accepted:[outbox IDs], proposals:[...]}`. Existing caps remain `node_identity`, `partial_signing`, `broadcast`, `wallet_transfer`. No arbitrary RPC write, system command, path or credential field is added. Existing vault/partial-sign/broadcast protocol remains unchanged.

## Authoritative wallet list

Send a proposal:

```json
{
  "kind": "wallet_sync_queue",
  "revision": 12,
  "requests": []
}
```

`requests` is the complete current list of paired `wallet_transfer` proposals relevant to this Agent, at most 128, with unique `transfer_id`s. Send **all rows**, including unselected rows, not just one globally scheduled transfer. Revisions are nonnegative monotonically increasing integers persisted per Agent. Repeating the same revision requires identical ordered JSON content; lower revisions or changed contents at the same revision are rejected. Send an empty list at a newer revision to withdraw all requests. Omitting a snapshot from a poll leaves the previous list intact; network failure alone never erases it.

Withdraw missing/outdated requests when their proposing source node goes offline, and send the fresh list to the remaining online nodes. On reconnect deliver the latest snapshot again. Preserve monotonicity through Dashboard restart/database recovery; do not silently reset revisions. Stable paired IDs/challenges must survive unchanged snapshots. A changed preview/funds/labels/addresses or expired challenge requires a fresh transfer ID/challenge, not replacement of the signed contents of an existing row.

An Agent can uncheck rows and end its temporary receiving authorisation. It cannot clear/delete/deny sync requests. A withdrawn unstarted row disappears locally. An in-flight/attempted row is hidden from the request table but its audit, restored wallet and staged encrypted file remain. Withdrawal is not authority to delete a wallet or replay an uncertain operation.

Each paired proposal uses the Build 7 fields and adds `transfer_version:2`:

```json
{
  "kind": "wallet_transfer",
  "direction": "receive",
  "transfer_id": "64-lowercase-hex",
  "peer": {"node_id": "registered-peer-id", "hostname": "wallet-laptop", "ipv6": "2001:db8::2"},
  "public_wallet": {"wallet_name": "Example", "descriptors": []},
  "source_has_private_keys": false,
  "earliest_timestamp": 1609459200,
  "requires_blockchain_redownload": false,
  "preview_challenge": "64-lowercase-hex",
  "node_ipv6": "2001:db8::1",
  "transfer_version": 2
}
```

The hex strings/descriptors in this illustration are placeholders. Descriptor rows must be real checksummed public Core records. `preview_challenge` and `node_ipv6` are required for any actual transfer. Direction/peer/local IPv6 swap between the paired proposals; transfer ID/challenge/public descriptor identity agree. Computer names are display labels; authenticated node IDs, exact public descriptors, direct SSH keys and independently pinned preview identities establish the meaningful bindings. Display receiver wallet names as supplied by Dashboard. Sender wallet names are obtained locally from Core (or locally derived fixed-address group labels).

Support private-key-disabled fixed `addr()` descriptors, including a subset of a larger watch archive containing multiple labelled Extinct groups. An `addr()` row must never be advertised as a private-key wallet. Address-only records remain ineligible for Vault Builder receiving/signing, just as before. Do not convert a watch-only source into a full/private-key transfer.

## Signed initial previews: version 2

The same outbox kind `wallet_transfer_preview` and delivery proposal kind remain. Outbox payload is `{request_hash,preview,public_key,signature}`; the relayed proposal is exactly `{kind:"wallet_transfer_preview",preview,public_key,signature}`. Preserve signed contents byte-for-byte as JSON values and preserve all fields. Route a preview by its registered sender, paired transfer/challenge and receiver; never use wallet display names as routing keys.

Version-2 preview has **exactly**:

- `version`: 2
- `transfer_id`, `challenge`
- `sender_ipv6`, `receiver_ipv6`
- `public_wallet`: sender's node-verified wallet name and public descriptor rows
- `chain`: main/test/signet/regtest
- `funded_outputs`: existing bounded public outpoint/address/amount_sats/time_received/blockheight/confirmations rows
- `node_tip`: `{height,hash}`
- `generated_at`: integer Unix UTC seconds; same 15-minute validity / two-minute future tolerance
- `vaults`: array of strict public vault records, at most 128
- `address_labels`: array of `{address,label,is_change}`, at most 10,000, unique valid addresses, labels up to 256 characters without control characters, Boolean source change-address status

`vaults` uses the existing public record schema `{version:1,chain,descriptor,address,height,source:{descriptor,index},timestamp}`. Each policy must cryptographically match the displayed public source descriptor/key, network, address and block-height condition. No private key is included. Address labels are exact public Core labels, including the full `Name | LOST:DD/MM/YYYY HH:MM:SS UTC` string. Preserve them verbatim; do not strip loss timestamps, normalise names, infer owners or omit zero-balance labelled addresses.

The dedicated Agent Ed25519 key, canonical JSON encoding and SSHSIG namespace **`wallaby-wallet-preview-v1`** remain unchanged; the signed JSON `version` distinguishes the new schema. The receiver verifies the signature plus wallet/challenge/peers/expiry and requires a user-entered sender identity fingerprint obtained independently from the sender. Dashboard is not the fingerprint authority. Users also compare the complete signed preview hash. Signed preview metadata cannot be swapped when a row is selected or a Watch Only checkbox changes.

Deliver the queue snapshot before its matching preview in a poll, or in a previous poll. The Agent processes all snapshots before signed previews in the same bounded response. Allow previews for every queued row rather than only one globally active wallet. Preview generation is public/read-only and does not itself authorise transfer. Source facts come from that Agent's own Core; Dashboard must not fabricate balances, labels, descriptor metadata or public vault records.

## Watch-only choices and direct SSH

Watch-only selection is local to each endpoint and frozen by local authorisation. No new Dashboard password endpoint is needed. A source without private keys is forced watch-only. Either receiver or sender can require watch-only; a full transfer is allowed only when both permit it and the source is encrypted/locked. Dashboard must not override a local choice.

The direct connection remains authenticated IPv6 SSH on TCP 22 with independently compared receiving system SSH host fingerprint and in-memory computer login password. One wallet is processed at a time; several selected receivers use separate credentials, never Dashboard-stored credentials. Receiving authorisation expires after 15 minutes. Incoming and outgoing batches are separate local phases on an Agent; users can end idle receiving authority without removing rows.

The direct manifest for protocol 2 adds Boolean `watch_only` to `{operation:"manifest",transfer_id,peer_ipv6,details}`. `details` equals the signed public fields `{public_wallet,chain,funded_outputs,vaults,address_labels}`; all metadata and coin facts must match (confirmation counts may advance). After `review_required`, receiver replies `{status:"ready",watch_only:effective_boolean}`. Sender refuses a downgrade before making/sending a private file.

- Watch-only sends `{operation:"public_wallet"}` only. Receiver creates a blank `disable_private_keys:true` descriptor wallet, imports public rows, preserves labels and creates verified vault monitors. A wallet-file header/payload is rejected in this mode.
- Full transfer retains the size/SHA256/encrypted file path from Build 7 and verifies encryption/key capability/descriptors/labels/history after restore.

A loaded/verified wallet returns the existing `{status:"loaded",transfer_id,wallet_identity}` with an explicit sender confirmation. If blocks are missing, direct receipt returns `{status:"recovery_required",transfer_id}` and the sender confirms learning that incomplete state. Both Agents retain it as incomplete. Do not report Success from bytes received alone.

## Recovery results and notifications

Accept `wallet_transfer_result` payloads with `request_hash` and `status`:

- `complete`: wallet loaded and verified, as before.
- `recovery_required`: data was received but local blockchain history must be recovered/verified. Optional bounded public `message` explains this. Keep it incomplete; do not reschedule/replay file transfer.
- Existing historical `denied` results from old Agents remain accepted, although Build 8 has no sync-row denial UI.

On locally approved recovery, the receiver emits a new content-addressed `complete` result for the same receiving request hash. Correlate the paired transfer and update **both** Agents' queue snapshots; the sender's waiting recovery row can then disappear. Duplicate public results are idempotent. Do not ask the sender to retransmit because an intermediate result is still pending or a response is lost. A new request must not overwrite an already attempted restoration.

Dashboard notifications can warn about missing wallet data/history based on these results and locally reported public Core state (`getblockchaininfo`, `getwalletinfo`, scanning/lastprocessedblock). The Agent never opens a browser or switches pages for sync/history requests. The user opens Agent → Synchronisation manually. No Dashboard RPC, proposal or notification can authorise a rescan, stop/restart Core or choose recovery flags/paths. Recovery approval remains local.

Agent recovery **never changes pruning settings or limits**. A missing-history recovery restarts Core with `-reindex=1` and briefly pauses network activity while restoring received encrypted wallets, original descriptor timestamps and vault monitors. Only after all of these are registered does it resume the download. Core scans transactions before pruning blocks and keeps the wallet history afterwards; no archival storage allocation is required. Native/Snap identification and recovery authorisation remain local. A correctly registered wallet is not forced into another reindex simply because its original blocks were pruned during that download. No automatic backup/configuration copies are created. An encrypted full-wallet transfer file remains necessary as the actual transport payload and is removed after verified restoration.

## Dashboard acceptance checks

1. Three or more Agents, several wallets per Agent, stable authoritative revisions and offline-source withdrawal; no Agent clear action.
2. Sender verifies its own node, receiver reviews signed public facts, all independent fingerprint/hash checks retained.
3. Full and watch-only choices, forced watch sources, multiple receivers, no private file for any effective watch-only transfer.
4. Extinct address subsets, zero-balance labels, loss-label timestamps and change-address status survive relay/import without enabling them as payment/vault destinations.
5. Vault descriptor/address/height/source derivation and associated funded outputs survive both modes.
6. Expiry/changed labels/funds/peers require fresh pairing. Reject stale revision, duplicated IDs, forged preview, mismatched key, metadata or network.
7. Pruned receiver reports recovery_required; locally authorised recovery later reports complete for the same pair; sender is cleared only on the updated Dashboard snapshot.
8. Read-only RPC restriction, request/result authentication, bounded outboxes and no uncertain operation replay remain intact.

Build 8 Agent tests cover isolated Core imports/restoration, two-wallet batches, Extinct labels, vault monitors, rescan and clean stop/reindex/restart. Actual multi-laptop system SSH, password prompts, Snap confinement, user-systemd, UFW/modem conditions and a full mainnet redownload still need live deployment testing after Dashboard integration.
