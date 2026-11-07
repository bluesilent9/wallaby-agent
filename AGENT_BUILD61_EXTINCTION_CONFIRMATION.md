# Build 61 — extinction without a local history archive

Extinction already uses two separate local approvals. At least one existing Extinct watch wallet must first receive the complete public address/label and confirmed transaction history, with local readback and a signed preservation receipt. Dashboard independently verifies that preserved history before offering deletion of zero-balance source copies. Dashboard does not simply relabel its own database and authorise deletion immediately.

An Agent without a loaded Extinct wallet receives deletion-only work. It never creates or synchronises an archive implicitly. It verifies its local source history, current chain, zero balances (including pending/immature balances), exact preservation evidence, and the preserving Agent fingerprint entered locally. Dedicated source copies are removed only after local approval; shared signers for other policies remain protected.

Build 61 adds local detection of loaded, non-scanning, address-only watch archives using the same criteria as public Core inventory. If none is available, the deletion review warns that history is not being copied into an Extinct wallet on this node and requires a checkbox confirming preservation in another node's Extinct wallet. An unloaded archive is not treated as available: the user can load it and review again, or explicitly confirm external preservation. The protected worker requires a literal boolean True, repeats the archive-presence check, and rejects changed review facts. The checkbox does not replace signed preservation proof, independent Agent fingerprint comparison, empty-wallet verification or history checks.

## Late/offline holders

Dashboard persists known holders and the extinction operation. Retirement v3 proposals have no time expiry. A returning holder can be discovered and given a new locally authorised deletion request even after the other holders finished. This depends on retaining the Dashboard profile, retirement records and node identity. The preserving Extinct node must reconnect and finish discovery so Dashboard can freshly verify its archive before delivering late cleanup. The returning Core must synchronise and locally verify its history; new funding/activity blocks inappropriate deletion and may require reconciliation. Missing pruned history uses explicit history recovery, preserving pruning settings.

Approval on a deletion-only node removes the reviewed empty local copies; it does not import history there. Denial records a local denied item and sends a denied outcome to Dashboard; the same pending request is not silently replayed. Closing a review is not cancellation. Dashboard cancellation withdraws the operation through the existing coordinated cancellation protocol; completed physical deletion cannot be undone by cancellation.

## Local API compatibility

No Dashboard wire protocol change is required. Retirement proposals/results remain version 3 with existing exact hashes and signatures. Only the protected local approval endpoint changes:

    POST /api/authorise/retire
    {"id":"<reviewed request>","fingerprint":"<independently checked Agent fingerprint>","history_elsewhere_confirmed":true}

Preservation and deletion with a local archive use false unless the user explicitly checked the external-preservation warning. Direct protected calls accept the same third boolean argument; omission defaults to false and is rejected when external confirmation is required. The generic approve route cannot bypass the existing fingerprint or new confirmation guard.

Install after finishing and safely closing active protected workspaces. Existing retirement requests remain valid and need a fresh local review. No installer or test changes real nodes or wallets.
