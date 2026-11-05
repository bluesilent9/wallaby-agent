# Build 56 — sign first, broadcast when Dashboard requests it

Signing returns signatures to Dashboard without publishing the transaction. When the user subsequently chooses Broadcast on Dashboard, its fully signed broadcast request is handled automatically by the Agent. No second local review or password is requested.

Core independently finalizes the supplied PSBT, checks the requested network and TXID, and tests mempool acceptance before sending. Already known exact transactions are confirmed without resending. Cancellation before submission is respected. An uncertain send is not retried; the Agent checks Core read-only, otherwise reports uncertainty for reconciliation. Results are queued immutably and acknowledged by Dashboard without repeating signing or sending.

The Agent exposes the result and TXID, but no redundant broadcast authorisation card. Closing waits for active broadcast and queued result delivery. Public inventory remains available.

## Compatibility and installation

Requires Dashboard Build 64 or later, which recognises `automatic_broadcast_v1` and checks the exact finalized transaction against Core after receipt. Install the matching Dashboard update before Agent 56. Complete current protected operations and close the workspace normally before installing the Agent package; do not restart a workspace containing unfinished ceremony material.

## Validation

Isolated Core 31 tests cover single signature, multiple recipients and 2-of-3 multisig. Each transaction stays out of the mempool after signing, then enters it only after the later broadcast request. Refusal tests cover incomplete signatures, wrong TXID, Core rejection, cancellation, closing and uncertain replies. Dashboard 64 interoperability checks receipt acknowledgement and Core's exact transaction. No production wallets, coins or services are used.
