# Agent V2 Build 18: coordinated extinction / actual local deletion

Agent Build 18 adds `wallet_retirement_v2` to the existing `/agent/v2/exchange` capability list. Dashboard work must be done in the Dashboard chat. This document specifies the Agent implementation; it does not claim an older Dashboard coordinates deletion.

## Proposal

The existing `wallet_retire` fields gain a fresh 64-lowercase-hex `nonce` and an explicit `delete_wallets` target list; **version must be 2 and delete_wallet must be true** for deletion. This matches the Dashboard Build 18 draft implementation. Version 1 with delete_wallet false remains archive-only; changing the interpretation of an already queued legacy proposal would bypass local informed consent.

```
{
  "kind": "wallet_retire",
  "version": 2,
  "nonce": "<fresh 64 lowercase hex characters>",
  "request_id": "<canonical digest of every other field>",
  "wallet": "<exact LOCAL Core wallet name on this Agent>",
  "public_wallet": {"wallet_name": "<name>", "descriptors": ["<existing public descriptor objects>"]},
  "archive_label": "<historical label>",
  "require_zero_balance": true,
  "delete_wallet": true,
  "delete_wallets": [
    {"wallet":"<local wallet name>","public_wallet":{"wallet_name":"<name>","descriptors":["<descriptor objects>"]},"private_keys_enabled":true}
  ]
}
```

Use the existing canonical JSON SHA-256 digest (sorted keys, separators `,` and `:`, UTF-8). The local request hash in responses is the digest of the entire validated proposal, including request_id. `public_wallet` uses the existing validated descriptor schema; the placeholder above is illustrative, not literal JSON to send. Do not send filesystem paths or deletion commands.

Dashboard must request retirement separately from **each holding Agent**, including watch-only holders. Wallet names differ across nodes: target the local name and exact public policy. Within one Agent, the reviewed plan includes every loaded exact-policy copy and dedicated local private accounts for a shared monitor. Reused keys serving a different policy are shown as retained, and never silently deleted. The Dashboard-proposed target set must exactly match the independently determined local group, and every target public descriptor/private-key flag must match Core. Missing, extra, unrelated or reused-key targets block retirement instead of allowing partial deletion. Every local name to be removed is displayed before authorisation; the complete list is returned in deleted_wallets. Every other holding Agent still needs its own request. Never treat one node’s completion as deletion on other nodes. Unloaded/unknown wallets are not automatically inspected or erased. Do not delete an account still needed by another funded policy. Discover all relevant shared/vault balances before offering extinction. Agent independently checks local balances/monitors and exact policy regardless of Dashboard's balance display.

## Local authorisation and evidence

The Agent strictly requires the nonce and explicit bounded target list for v2; archive-only legacy proposals cannot gain deletion by adding a flag. Each proposal requires review and explicit local Authorise archive and delete this local wallet. Agent accepts watch-only v2 sources without requiring a private signer. It verifies synchronised local history, exact public descriptors, zero trusted/untrusted/immature/used balances, no locked outputs, no unsettled/conflicted transactions, and zero associated vault/shared-monitor balances. Pruned history gaps stop retirement and require locally authorised recovery with pruning unchanged.

It imports used receiving/change addresses into `Wallaby Extinct`, preserves exact existing LOST labels, checks every import and final label, then repeats wallet/policy/history/balance checks. It unloads each wallet in the exact locally reviewed group with `load_on_startup:false`. A separate unprivileged local removal service accepts only the caller's protected service and a bounded path/inode identity. No wallet bytes are read/copied/written by that service. It refuses symlinks, hard links, unexpected files, changed identities, unsupported locations and loaded SQLite databases (exclusive POSIX lock). It unlinks the approved wallet files and confirms each directory was removed. If part of a group fails, the operation remains uncertain/error and is not replayed. No extra backup is created; this is normal filesystem deletion, not forensic secure erase. Discs and other existing backups are not touched.

Automatic filesystem removal supports named descriptor-wallet directories below the usual `~/.bitcoin[/network]/wallets` and `~/snap/bitcoin-core/common/.bitcoin[/network]/wallets` locations on /home. Empty/default wallet names, nested/path names and custom wallet directories require local review and are not automatically removed. The wallet must be loaded for independent Core verification; an offline/unloaded holder cannot be declared complete.

## Responses and Dashboard state

Existing outbox item kind: `wallet_retirement_result`.

A successful version-2 payload is:
```
{
  "request_hash": "<digest of full proposal>",
  "status": "complete",
  "archive_verified": true,
  "history_verified": true,
  "zero_balance_verified": true,
  "wallet_deleted": true,
  "archive_wallet": "Wallaby Extinct",
  "address_count": 3,
  "deleted_wallets": ["<exact local wallet name>"]
}
```

Results are returned through the Agent's authenticated node/exchange session; bind them to that Agent and exact request hash. A version-1 result retains its original minimal request_hash/status schema (no deletion proof) and MUST NOT satisfy deletion. Do not add extra success fields: the Dashboard strictly validates its allowed result keys. Agent success fields match its result validator, including history_verified, zero_balance_verified, archive_wallet, address_count and deleted_wallets. Unknown or mismatched results must not mark completion. Dashboard must compare deleted_wallets against the exact proposed delete_wallets names, not merely check the main wallet name. `status:error` means incomplete/uncertain and never completion; the attempted request is not automatically replayed. A timeout/offline Agent is pending, never implicitly successful. A locally denied/cancelled request emits `status:denied` and its retirement result is retained in protected RAM until acknowledged (including cancellation, so closing cannot silently lose that outcome). It does not create a new persistent denial/history store. It is separate from optional wallet-sync denial preferences. The Agent sends `status:denied` with the exact request_hash; Dashboard must flag it for user review, rather than silently mark the wallet extinct or resubmit in a loop. Retry after reconciliation requires a fresh proposal/review, not replaying an attempted deletion.

Dashboard should preserve the per-holder target list/status even as holders stop reporting the deleted wallets. Mark overall extinction complete only when all expected private/watch holders confirm archive_verified AND wallet_deleted for v2, and separately record the user's physical archival-disc destruction confirmation where applicable. Suppress ordinary wallet synchronisation for policies undergoing retirement, including pending/uncertain requests, to avoid recreating a deleted wallet from another holder. Historical addresses in Wallaby Extinct remain reportable; they must not be scheduled as missing active wallets or used to trigger resynchronisation of deleted signing wallets. The Agent cannot verify destruction of physical discs, offline backups or undiscovered nodes. Do not represent those as automatically deleted.

Dashboard must not offer extinction while any linked multisig/vault holds funds. A pending transaction, missing node/history or incomplete holder verification must be shown as unresolved rather than zero. A local cancellation remains visible as a cancellation. This is additional Dashboard state, not the Agent's persistent sync Denial list; the Agent's Bitcoin request/results remain in protected RAM until delivered as before.

## Coordination review of the Dashboard Build 18 draft

The reviewed Dashboard draft now uses `wallet_retirement_v2`, a fresh nonce and explicit delete_wallets, with the exact result schema exercised by the Agent's fixture. Its coordination update creates a per-known-holder checklist, includes pure watch-only holders, retains offline/unsupported holders as pending, and requires every holder's confirmation before overall completion. Reconnecting holders receive their own locally approved request. Disc confirmation is a separate user action. This replaces the earlier one-selected-holder draft; no additional Agent wire fields were introduced by coordination.

The Agent independently verifies the local target set and refuses shared signing accounts still serving a different policy. Dashboard must not count an error or a retained account as a successful deletion. Unknown/custom wallets and offline backups cannot be inferred deleted from a node result.

Core SQLite locking reference: https://github.com/bitcoin/bitcoin/blob/v31.0/src/wallet/sqlite.cpp (exclusive database lock while loaded).
