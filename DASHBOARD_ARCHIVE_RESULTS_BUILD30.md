# Agent Build 30: archive results and Dashboard notifications

This is a Dashboard implementation handoff, not a change to Dashboard source. Dashboard Build 36 accepts `queued`, `disabled`, `complete`, `error`; Agent Build 30 now emits no `disabled` result and requires `deleted` support. The request queue schema remains `wallet_archive_queue` version 1.

## Signed outcome

Agent uses the existing `archive_queue_result` outbox delivery and signature namespace. A local deletion has exactly this public body, plus its existing signed_receipt:

```json
{"version":1,"queue_id":"QUEUE_ID","request_id":"REQUEST_ID","status":"deleted","signed_receipt":{"message":{"version":1,"queue_id":"QUEUE_ID","request_id":"REQUEST_ID","status":"deleted"},"public_key":"PINNED_AGENT_KEY","signature":"EXISTING_SSH_SIGNATURE"}}
```

Verify the pinned Agent signature, exact body, queue and request/Agent binding as for other outcomes. Accept `deleted` only as deletion of the request: it is never proof of optical burning, read-back, physical destruction, wallet deletion or successful preservation. Accept exact replay idempotently. Reject a contradictory terminal outcome. Both unapproved and unused staged archive_wallet requests can be deleted locally; staged captures and burner membership are removed only when no write/uncertain outcome is involved. Destroy-disc reminders can also be dismissed as `deleted`; this does not complete the underlying physical destruction requirement.

Mark the archive task terminal/deleted, remove it from future active snapshots, increment revision, and acknowledge the outbox item normally. Keep a readable terminal status in Dashboard. A new deliberate archive request for the same wallet must use a fresh nonce/request_id and remain possible. Do not install any persistent wallet inhibition, archive denial list or implicit requeue of the identical deleted task. Ordinary wallet synchronisation denials are unrelated and unchanged. During a temporary disconnection Agent retains the signed result and exact terminal request in RAM, and never treats it as a successful burn.

Existing `complete` receipts are unchanged. Agent completes only the selected members after *every requested separate disc* passes full read-back; unselected pending requests stay active. An incomplete multi-disc set or failed read-back produces no successful completion receipt. Retain all existing signature/read-back/replacement checks.

## Notifications and Wallets

For each accepted terminal `complete` or `deleted` archive outcome, make a single deduplicated user-facing event, keyed by queue_id + request_id + terminal status (not every receipt retry). Resolve wallet and Agent names from the existing verified task. Display whether the archive was successfully burned/read-back verified or its request was deleted. Never say a disc was destroyed because a reminder was deleted.

Show a red event for deleted requests and a green event for successfully completed archives in Notifications, initially unread unless the user is viewing Notifications or Wallets when it arrives. Mark the shared outcome read when they view either page; allow its X button to dismiss it. An acknowledged/dismissed event must not be recreated by a retried identical signed receipt.

Also show the outcome on Wallets. This Wallets message starts unread unless the user is viewing either Notifications or Wallets. Viewing either page marks the Wallets message read. Use one shared outcome read state across the two relevant pages. Do not move the user to either page. Existing archive queue tracking must remain independent of unrelated Ownership questions.

Before releasing the Dashboard update, test repeated signed delivery, deletion before staging, deletion after RAM staging, new requests for a previously deleted wallet, subset burns, two-disc incomplete/complete sets, deleted destruction reminders, unread/read state on both pages, X dismissal, disconnected delivery and malformed or conflicting outcomes.
