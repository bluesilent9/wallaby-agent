# Build 81: continue approved extinction after recovery; prove history before deletion

## Stage detection from Core

Opening a preservation request first checks the existing archive against the independently enumerated original local wallet history: labels, every confirmed transaction, exact transaction bytes and active-chain blocks. If they already match, the Agent reports the existing preservation result without another import, scan or preservation approval. The Server can then offer its separate deletion request. No Core data is changed by this detection. Missing global scan provenance is not mistaken for missing data for this independently matched wallet. This does not certify unrelated legacy entries as complete; their coverage remains unverified unless a tracked whole-history recovery establishes it.

## Approval and recovery

The local history-preparation action now explicitly authorises the exact preservation request to finish after locally approved history recovery. It is bound to the proposal hash and manifest hash and cannot authorise deletion. Existing prepared jobs can receive that approval without repeating imports. After all recovery jobs and wallet-tip checks finish, the Agent freshly reviews the pending proposal, reads back history, and emits the existing signed preservation receipt. Wallet Server can then send its existing separate deletion request. No Server protocol update is required.

Cancellation, dismissal and denial revoke the continuation. Changed/withdrawn proposals cannot reuse it. An uncertain attempt is not automatically replayed. Consent remains in the protected RAM session: Server rediscovery, an installer update, existing transactions and a Core tip do not manufacture authorisation after the workspace was cleared. Pre-Build-81 approvals cannot be retroactively inferred.

## Deletion evidence

When the preserving archive named in the signed receipt is loaded locally, review checks every manifest address and label, every confirmed transaction and its block against the local chain, and exact raw transaction bytes against the original local wallets/monitors. The original local inventory must independently fit the manifest. Any mismatch blocks deletion. Checks are repeated immediately before unloading the reviewed empty wallets. Existing funded-wallet, pending-transaction, shared-signer, local-assignment and path safeguards remain.

The GUI shows full verified counts and up to five deterministic address and transaction examples, including labels (and LOST metadata) and formatted block heights. Examples are explicitly samples of the complete comparison; displaying them does not delete anything.

An unrelated Extinct wallet does not prove local preservation. Where the preserving archive is unavailable locally, the existing independently verified signed receipt/fingerprint and prominent preservation-elsewhere warning remain. The deletion Authorise click is sufficient local consent; there is no extra checkbox. An existing unloaded archive must be loaded rather than silently ignored. No private signers beyond those actually present are required for retirement.

## Existing archive names

The existing Core archive keeps its name, including `extinct_watch`. The exchange helper previously accepted only two display names. It now verifies both reviewed, unloaded database inodes as private-keys-disabled, fixed-address-only Core public wallets before exchange. Private records, ranged wallet descriptors, unknown record types, symlinks, changed identities and loaded databases are refused. SQLite inspection closes before reacquiring the whole-file POSIX lock so its own descriptor lifecycle cannot release the final lock. Original and staged directories remain bound to the same approved Core wallet base.

## Missing verification versus missing data

A current node tip establishes synchronisation, not complete legacy archive provenance. This Node shows an outstanding extinction review separately. History review reports existing transaction counts and explains missing coverage without asserting the data is absent. No new download starts without the separate reviewed recovery plan.

In the reported retained session, Core shows 51 transactions and 38 timestamp-1 archive descriptors at its current tip. Build 81 retains those records and checks the relevant original-wallet history directly before deciding its stage. It cannot safely manufacture whole-archive certification for unrelated legacy entries from those counts alone. No further download is automatically started or asserted necessary based solely on the missing completion marker.

## Validation boundaries

Isolated Core 31 fixtures cover automatic preservation following recovery, whole legacy Extinct upgrade and LOST retention, cancellation and uncertain-state refusal, all-record deletion comparison, changed raw transaction/label refusal, unrelated archive handling, missing multisig signer retirement, and real pruned-block reindex/replay with automatic completion. Browser-model tests cover evidence samples, separate deletion controls, prepared recovery, version identity and existing approval layout. Real desktop installation, physical media and the user's archive are not mutated by tests.

The isolated regtest fixture uses Core’s test-only `-unsafesqlitesync=1` setting and a longer budget for generating synthetic maturity blocks, to avoid test-disk contention. Production Core launch arguments, wallet durability and non-mining RPC timeouts are unchanged by those fixture settings. Power-loss durability is not tested.
