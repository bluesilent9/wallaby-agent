# Build 58 — one vault refresh approval per Agent

Dashboard 80 keeps one progress row per Agent: red until a signed delivery receipt, amber after receipt while awaiting consent, and green only after it independently checks all affected wallet policies. This Agent build advertises wallet_policy_refresh_batch_v1 alongside wallet_policy_refresh_v1. The existing version-1 proposal is unchanged.

The Agent queues a wallet_policy_refresh_receipt only after storing the exact request in its durable local inbox. The setup identity signs version, request_id, request_hash and status received. Repeated identical proposals reuse the existing receipt and pending review. A receipt does not approve or install anything.

A single review independently discovers all loaded local RPC wallets containing the exact old receive/change policies. It includes related encrypted node signers, loaded disc signers and public policy monitors. The UI lists their actual names and storage. No new-wallet identity comparison or key generation is introduced. Every encrypted private wallet still requires its own local password.

All target policies, loaded archive identities, recovery histories and passwords are checked before imports begin. A changed loaded-wallet set requires a new review. The Agent imports the additive policy while retaining old descriptors, signing keys and names; it updates each affected loaded archive's policy_extensions. Unrelated wallets, staged accounts and old-disc membership records are retained. Legacy key-only accounts retain their key material while their complete-policy monitor is updated.

The existing signed wallet_policy_refresh_result adds updated_wallets, the exact local RPC aliases covered. A single approved result is emitted only after every target has been checked and any loaded-disc replacement obligations have completed. history_required remains blocking. Denials are signed and clear the one pending request. Import errors leave the request attempted, record which wallets completed, retain encrypted wallets/RAM metadata, and report error rather than full approval. No attempted import is automatically replayed.

Finish protected operations and close normally before installing. Use Dashboard 80+ for the receipt/one-row waiting flow; archive format and existing v1 policy requests remain supported.

## Replacement discs before funding

Approval of affected loaded-disc signers automatically queues replacement backups, with only the affected signers selected for this workflow. Additional approved archives are optional: omit previously co-archived wallets or add different wallets as desired. Keep different quorum signer roles on separate discs. Disc Operations retains its existing protection against putting too many roles on one disc.

Dashboard remains amber while the Agent request is awaiting_backups. Burn each replacement, complete full-disc read-back verification, then confirm physical destruction of its superseded original copies in Authorise. Replacement evidence must preserve every affected signer and include its exact new effective policy. The local destruction review explicitly names any optional old-disc wallets not carried forward; confirming destruction discards those old copies. Generic archive replacement and cancellation retain their separate full-preservation rules. Only then does the Agent release its final approval result so Dashboard can return to funding. Transaction review/signing also refuses locally recognised funding of that policy while its backup handoff is outstanding. No transaction needs to be stored on the disc.

## Cancellation and reuse

Cancellation checks confirmed UTXOs and mempool receives using both descriptor branches and all locally tracked address ranges. Funding or an unavailable check blocks retirement. An explicit Keep funded policy action retains the policy and reports retained_funded. Unfunded cancellation restores the previous active receiving descriptors and retains all keys, descriptors and history. Existing wallets are never deleted. Unstarted replacement captures of the cancelled revision are removed without affecting unrelated backups.

Physical discs already containing the cancelled policy require preserving replacements and local destruction confirmation. A fresh explicit approval can reactivate the same keys, block height and address without creating duplicate policy history. Retired-policy archives require Build 58 or newer; the retired extension marker causes older readers to refuse rather than silently reactivate it. Ordinary earlier archives remain supported.

## Transaction destination review

The Agent recognises a local destination vault from its own Core descriptors, independently of Dashboard output labels. It shows the unlock block height and estimated UTC and local date/time. The block-height condition is authoritative; date/time is an estimate based on local chain data.
