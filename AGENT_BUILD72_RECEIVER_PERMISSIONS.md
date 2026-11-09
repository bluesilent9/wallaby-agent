# Build 72 — Wallet branding and receiver-controlled sender options

The Services card uses the Wallet project's existing Wallet icon, title
"Wallaby Wallet" and description "Open Wallaby Wallet securely from this computer.
Bitcoin Core is not required." Internal service identifiers remain compatible.

A live direct connection alone no longer makes an old sender request selectable.
A matching current authenticated wallet-offer snapshot must still list the exact
transfer, recipient and public policy, without disabled/permissions-pending status.
Withdrawn or permission-unconfirmed recipients disappear from Send-to choices and
pending counts. A wallet held locally remains in the unified local inventory;
its unavailable transfer option is removed. Other enabled recipients are unaffected.
The same check runs at selection and batch validation, so stale page controls
cannot start a transfer after withdrawal.

When the receiver enables the policy, its confirmed offer restores the sender
option automatically on the next exchange. No refresh or new pairing is needed.
This is network propagation, not an instantaneous offline notification. A signed
receive-preference reply is flushed in one bounded immediate follow-up exchange
rather than waiting for another normal poll. No wallet operation is repeated.
A withdrawn unstarted sender tick is cleared; a returning offer does not restore
that selection. Active batches, attempted records, proofs and wallet data remain.

Public offers restrict visibility and selection; they do not grant secret access,
import, signing or multisig restoration authority. All existing local review,
pairing, receiver approval, managed-signer and live Core checks still apply.
Wallet Server Build 6 already sends these snapshots; no new Server protocol is
required. New sender behavior is in Agent Build 72; receivers also benefit from
Build 72's faster preference-reply delivery.

Tests include an actual Server 6 fixture in one process and Agent 72 in another:
sender pending count 1 -> 0 -> 1 across receiver denial/re-enable, while intentionally
retaining an old executable request. It cannot remain selectable or auto-transfer.
Unit tests cover target/policy binding, disabled/stale permissions, source selection,
batch refusal, preserved local rows and bounded preference flushing. Real isolated
Core/direct SSH checks cover single-sig, original multisig roles, vault history and
multi-wallet watch-only history. Browser/JavaScript checks cover the unified table,
watch controls, sidebar and exact Services branding. Your real wallet files and
running services are not modified by these development tests.
