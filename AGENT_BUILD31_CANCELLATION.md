# Agent V2 Build 31: archive cancellation and local vault estimates

Development build; pairs with Dashboard V1 Build 40 for the new archive cancellation queue. Existing Services, synchronisation, multi-disc RAM loading, phased extinction and local signing remain available.

## Archive cancellation

Advertise `wallet_archive_cancel_v1` alongside `wallet_archive_queue_v1`. The queue envelope remains version 1. An `archive_cancel` task has exactly: kind, version=1, nonce, request_id, wallet, archive_request (the exact original archive_wallet task), completed_receipt (original signed completion envelope or null), finish_inflight_burn_and_verify=true, require_local_destruction_confirmation=true, preserve_unrelated_members=true. request_id hashes every other field. Duplicate cancellations for the same original and simultaneous original/cancellation tasks are rejected.

Unstarted requests and positively known unused RAM captures can be withdrawn safely. Missing prior RAM state does not establish that no disc was written. Unknown outcomes require local reconciliation: explicitly confirm that no disc was ever written, or read/authenticate the original disc and bind its exact members. A cleanup obligation cannot be dismissed through generic Cancel, Delete or Deny.

If an optical write has started it finishes and a read-back attempt finishes. No extra requested copies are started after cancellation. Failed writes still attempt read-back and require destruction of the partial medium. Verification-finished does not mean verification-succeeded; the review distinguishes them. Software cannot physically detect destruction: the user must confirm every written/partial physical disc and enter a count no smaller than the known attempts.

A shared disc's unrelated members must first be included in a replacement with full successful read-back. Required members cannot be unchecked. Simultaneous cancellations share physical cleanup evidence, but each request receives its own signed outcome. Later cancellations also follow locally known replacement provenance; every affected disc set must be reconciled. Unrelated queued requests and Core wallets are not deleted by this action.

Completion uses existing Agent-signed `archive_queue_result`, status=complete, request_cancelled=true, disc_created. A created disc additionally returns archive_id, disc_count, destroyed_disc_count, burn_finished, verification_finished, destruction_confirmed_locally, unrelated_members_preserved and replacement_required; replacement_required also requires replacement_readback_verified and replacement_image_sha256. Public destroyed_disc_sets/destroyed_archives/cancelled_member_ids describe multi-set reconciliation. Original successful evidence anchors archive_id. Dashboard acknowledges exact retries idempotently and must retain uncertain cleanup tasks.

## Discs created by a different Agent

Portable completed-disc cancellation, superseded-disc destruction and phased extinct-disc cleanup verify the original Agent's SSH inventory/receipt signature against its supplied public identity, require a full matching locally authenticated disc catalog, and require the user to independently compare and type the original Agent fingerprint. Dashboard display labels alone do not establish the author. Extinction also requires its separate preserving-Agent fingerprint and current preservation proof. Replacement readiness comes from actual local read-back, not an online assertion. An in-progress burner remains owned by the Agent running it; this does not remotely cancel a drive.

## Vault unlock estimate

Signing and broadcast reviews include advisory unlock_estimates for independently verified vault outputs, recognised local vault inputs and verified legacy vault intents. Transaction locktime by itself is not treated as proof of a vault policy. The estimate is separate from immutable reviewed transaction facts and cannot weaken signing or fresh-state checks.

The Agent reads getblockchaininfo, getblockhash and getblockheader only from its local Core. It averages header timestamps over up to 157,788 blocks (roughly three years at the target interval); pruned nodes retain headers and do not need old block bodies. At least 144 blocks and a plausible positive interval are required. Unavailable or unrepresentative history uses a labelled 600-second target-interval fallback; unavailable current headers produce no date. No external site or Dashboard estimate is queried.

For a CLTV height H, a transaction with nLockTime=H is first final in candidate block H+1. Estimate = max(current local clock, tip header timestamp) + remaining blocks to H+1 times the observed average. UTC and Agent system local time/offset/timezone are shown with the sample span, source and a rough-estimate warning. A reached height is reported as reached rather than a promised future date. Catching-up or stale nodes show an extra warning. This is not a 99% forecast, and future mining speed, timestamp noise, reorganisations and an inaccurate system clock can move it. The actual block-height condition remains authoritative.

All Bitcoin work and cancellation plans stay in the existing protected RAM environment. This adds no new persistent Bitcoin data files. Services settings and sync denial preferences keep their existing persistence. Optical writing/read-back is simulated in automated tests; actual burner/media testing is still required.
