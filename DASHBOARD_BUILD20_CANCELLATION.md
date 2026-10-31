# Agent Build 19 / Dashboard Build 20 cancellation contract

The Agent advertises `builder_cancellation_v1` and `wallet_retirement_cancel_v1`. Dashboard source is not modified by this Agent build.

## Builder cancellation

`builder_cancel` version 1 accepts exactly the current Dashboard fields: `builder` (wallet/transaction), 32-hex `workspace_id`, 32-hex `cancellation_id`, bounded `operations` and `request_hashes`, optional bounded `exports`, `require_local_authorisation: true`, `backup_option: true`, and `request_id`. The request ID is SHA-256 of canonical sorted compact JSON excluding that ID; the full proposal hash includes it. `exports` entries contain only `outbox_id`, `txid`, and `psbt_sha256` (SHA-256 of decoded PSBT bytes). Older requests without exports remain accepted.

After storing a RAM cancellation hold, the Agent sends exactly:

```
builder_cancel_receipt: {version: 1, cancellation_id: <id>, request_hash: <full hash>, status: "received"}
```

This is a **delivery receipt**, not local deletion approval. Dashboard may release its builder workspace after delivery to all Agents; it must not await a local completion result. There is no `builder_cancel_result` message. Duplicate deliveries do not repeat local actions. Normal protected closure remains blocked while a local choice is pending. Cancellation records intentionally remain volatile; forced power loss can lose the pending local choice after receipt.

Authorise independently inventories the affected local setup session or transaction artifacts. Signing/setup actions and original result delivery are held. Wallet names/paths for deletion come only from the Agent's locally created setup ledger, verified against Core's current public policy, never from Dashboard path claims. The Agent keeps delivered unsigned export PSBTs in protected RAM so a subsequent cancellation can refer to them. Export bindings must match its own original outbox identity, decoded PSBT hash and Core txid. Missing local session/export data is shown as incomplete evidence; it is not used to infer wallet deletion targets.

The user chooses red **Delete and Cancel** or green **Backup and Cancel** after reviewing local artifacts. Backup writes a streaming AES-256-GCM/scrypt encrypted `.wallaby` bundle containing all locally held affected PSBTs, complete proposal/policy/contribution metadata and Core backupwallet files, with an explicit manifest-to-file mapping. Plaintext remains in protected RAM; only ciphertext reaches the locally chosen home directory. A native passphrase/folder dialogue is required. Owner-only exclusive creation, readback hashing and final state checks precede deletion. A failed backup retains originals. The existing same-user, protected-cgroup-checked local helper supplies one write-only file descriptor; it neither reads wallet bytes nor accepts a remote export request. This local ciphertext backup is an explicit persistence exception.

Only the reviewed, locally tracked installed wallet group and temporary session artifacts are removed. Other wallets, existing optical media and broadcast transactions remain. This is filesystem unlink, not forensic erasure. A partial deletion or other uncertain action is marked attempted and is not automatically replayed. Active optical writing/readback blocks cleanup. Temporary generated signing wallets and installed signing/public-monitor wallets are handled as a group, including partial setup.

Transaction review checks Core mempool, raw transaction and available wallet history. It shows `No broadcast PSBTs from this Transaction Build have been detected` or red `Broadcast PSBTs from this Transaction Build have been detected`. Missing local history is separately flagged: absence of detection does not prove non-broadcast.

## Retirement withdrawal

`wallet_retire_cancel` version 1 carries the original full retirement `request_hash`. An unattempted retirement is withdrawn and responds through `wallet_retirement_result` with status `cancelled`. In-flight archiving observes the withdrawal before deletion; once deletion has begun, or an earlier outcome is uncertain, the Agent must preserve/report the actual outcome and never claim a false cancellation. A completed retirement re-sends its actual result.

## Public RPC diagnostics

Acknowledged local RPC exceptions now return `local_rpc_<category>` with safe `stage`, `category` and `method`, rather than collapsing every failure to `local_rpc_failed`. Oversized local/public responses retain the 16 MiB bound and identify `response_limit`; timeout, authentication, transport and invalid response are distinguished. No raw RPC payload, cookie or exception text is returned, and an acknowledged RPC is never replayed. This improves evidence for the unresolved verbose `getrawmempool` failure; it does not establish its cause or silently return an incomplete mempool.
