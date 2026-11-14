# Development Build 96

The Build 95 source log located the reported failure at `history_wire:49`: the source compared an address-filtered export or requested subset with the entire native archive inventory. That mismatch did not establish that anything had changed during export. The logs do not reveal which individual records or addresses differed.

Build 96 negotiates direct history V4 between paired Agents. A whole-archive transfer carries every stored public CWalletTx record, including records without a direct match to the current fixed-address set. A subset transfer projects only its requested addresses and matching records. Actual changes are measured by comparing the source's original and final native inventories and the approved address labels, rather than comparing a filtered selection with an unrelated total. Logs contain scope, counts and fixed change categories without transaction contents.

V4 accepts the pinned source's native inventory under the receiver's direct local approval. Raw transaction hashes, confirmation metadata, active-chain headers, signed packet binding, private-key-disabled archive capability, LOST labels and Core readback remain checked. Strict per-address relationship checks remain the default for other imports and retirement validation. Genuine changes during export still fail before import. Sender and receiver should both install Build 96 for V4 support; Wallet Server needs no change.

The existing Build 95 stream-close, cancellation and pruned-node support are retained. No historical blockchain download is required merely to copy a current trusted archive. The transfer cannot discover history absent from its source.

Validation: 53 isolated Core checks passed, including whole native inventory, requested subsets, real inventory/LOST-label mutation, malformed records, active owners, pruned sender/receiver, cancellation and existing single/multisig transfers. The updated inventory test separately confirms that ordinary imports still reject unrelated records. The production-CSP receiving browser suite passed. Release export verifies version labels, all installed runtime files and package ownership/permissions.
