# Build 99 — Wallet discovery and complete scope belong to paired Agents

The old wallet bytes travelled directly, but the Server still selected executable offers and address subsets. Build 99 removes that Server role from ordinary wallet synchronisation. Both Agents need Build 99. Existing QR pairing remains valid; no profile or trust reset is required.

## Discovery and receiving

The two Agents exchange bounded public inventories through the existing authenticated, encrypted Agent-only direct SSH stream. The receiver inventories its own Core wallets, including unloaded wallets through temporary loading with prior states restored. The source supplies full public descriptor sets and signs a complete-wallet preview tied to both pinned identities. The receiver verifies this before showing a selectable request. Explicit receiving approval freezes the exact preview and watch-only choice. The source automatically responds on that direct channel, with no sender click. Mobile cannot use inventory or wallet streams.

Wallet Server queues, scope, preview deliveries and permission offers cannot create or modify these local direct jobs. Empty or restrictive Server snapshots do not withdraw them. Direct previews and transfer job outcomes no longer use the old Server queue protocol. The Server still supports connection establishment and maintenance and other separately validated Agent operations. As a signalling service it can still interrupt initial connection availability; it cannot authenticate as a paired Agent or change signed transfer contents.

Single-signature encrypted private wallets support private or watch receiving. Managed multisig and vault policies are public-only offers: ordinary sync does not clone assigned private signer roles. Existing private backup encryption/lock requirements and operation-specific restoration restrictions remain.

## Extinct updates

A source advertises the complete archive, including its transaction-id set and labels, not a Server-selected address subset. A receiver missing addresses, transaction records or labels gets the same Wallet Sync selection and Authorise flow. Native history merges retain receiver-only records and LOST metadata; conflicting labels stop the update. Current source scope is checked again before export. Both pruned nodes use retained block headers to validate historical block references; transferring a native archive does not itself initiate a complete blockchain download or historical rescan.

A receiver denial is local and exchanged directly. Extinct denial identity remains stable as new retired wallets are added. Previous exact-container deny entries migrate without enabling receiving. Denied wallet rows stay visible; enabled missing-wallet rows require a live direct peer. Completed transfers never prevent a fresh generation after actual deletion. Failed reads and unloaded folders never establish deletion.

## Obsolete preservation

Core directory absence cancels an unstarted preservation task targeting a deleted archive. It does not claim preservation completed and does not delete a wallet. An unloaded archive, attempted task, authorised continuation or prepared history job retains its existing safeguards. The exact cancelled phase/result is returned to the Server so it can retire its obsolete per-node task. The Server needs a companion change to stop scheduling legacy transfers for Build 99 and respect these cancellations; see the integration handoff.

## Validation

Isolated Core/direct SSH tests cover Server-free discovery and private receiving, hostile Server withdrawal, full-scope substitution rejection, normal and historical multisig/vault watch policies, actual unloaded-wallet inspection/restoration, completed-transfer rediscovery after deletion, receiver denial and re-enable, denial surviving real archive growth, complete Extinct merge including LOST labels, identical address sets with missing records, and both nodes pruned. Stale preservation tests distinguish absent/unloaded archives and retain authorised continuation.

Maintained transfer, cancellation, source mutation, encryption, active-owner, raw-history, wallet deletion, release identity and transaction-table regressions are also checked. Production-CSP browser checks cover existing receiving/approval flows and wallet/peer/table behaviour. Package verification compares installed bytes with source and checks ownership, permissions and consistent Build 99 identity.
