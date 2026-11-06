# Agent Build 60: exact refresh address comparison

Implementation: Agent Build 60 and matching Dashboard Build 84. Agent 59 rejects the new optional field, so Dashboard must require worker_version >= 2.0.0~dev60 before sending it. Do not change an already delivered/approved proposal in place.

Confirmed diagnosis: the green proposed receiving address matched index 15 of the exact new descriptor under review. Earlier reviews displayed only samples 0 and 1. No incorrect derivation was found.

## Request

Keep wallet_policy_refresh version 1 and all existing mandatory fields. Add one optional field:

    "receiving_address": {"index": 15, "address": "<reserved green receiving address>"}

The index must be an integer (not bool), 0–999 inclusive. The address is the receiving descriptor at that index, on the proposal network. Both fields are required together; no other members are accepted. Dashboard should copy both values from the same saved destination used by the Address page and funding transaction; never reserve another address for the review. Do not infer the index from Agent Core next_index.

## Agent verification and presentation

Validate the address by local independent descriptor derivation at acceptance. Before presenting review, also compare that result with local Core deriveaddresses. A mismatch refuses the request/review. The index/address are covered by the canonical request hash and exact reviewed proposal equality before approval.

Show the actual proposed receiving address prominently. Then show Receive #15, #16, #17 and Change #15, #16, #17, each independently derived and checked against Core. Both lists start at the requested receiving index for comparison; the change samples are not a promise that a future transaction will use that change index. At indexes 998 and 999 show only remaining in-range entries; never wrap or exceed 999.

Old requests without the field remain valid with three samples per branch starting at 0, but explicitly say they do not identify Dashboard's reserved destination. No field is guessed or silently added to an existing approved request.

The underlying descriptor-pair policy hash and archive policy extension format do not change: selecting an address does not create a new spending policy. The complete proposal request hash does include the new field. Existing receipts/results/cancellation hashes continue to bind the complete proposal. No new capability string is introduced (old Dashboard capability allowlists reject unknown capabilities).

## Dashboard side needed

wallet_policy_updates.queue: add receiving_address using d['index'] and d['address'], only when the target Agent supports Build 60. Keep the saved green destination and proposed height unchanged. Show the same receive/change comparison indexes in Dashboard, independently derived from its saved descriptor pair. Test nonzero index 15, mismatches, boundary 999, and no change to reservation/reuse behaviour. Existing requests should be preserved; explain that their old review samples are not the reserved address.

## Cancellation responsiveness

A cancelled refresh whose policy was never installed and has no new physical disc now performs one fresh confirmed/mempool funding check at confirmation, then rechecks that the exact local wallet installation set remains unchanged. It clears only the unstarted request; no wallet, key, descriptor or physical disc is deleted. Previously this empty mutation path repeated the full funding scan three times. Installed policies retain the full retirement and post-mutation funding checks. The cancellation page displays an inline waiting message and any refusal while the operation runs, and prevents duplicate submissions. Loaded archive RAM copies remain explicit separate unload actions after cancellation.
