# Build 51: stage countdowns and stable disc selection

## Estimated remaining time

Burn and verification have independent measured estimates. Burning uses recognized xorriso written-byte reports, never data merely accepted by its input pipe. Verification uses directly read and hashed bytes. Each stage starts with Calculating, samples throughput at intervals of at least one second, and shows a countdown after five seconds of measured progress. A weighted throughput estimate uses constant-size state rather than retaining a history of copies or read chunks. Snapshot timestamps advance the countdown between fresh progress reports. Thirty seconds without progress pauses the estimate until fresh progress arrives. A completed byte count does not claim that optical finalisation or verification has completed; the display says it is finishing the stage.

Times are estimates. Changing drive speed, media retry, finalisation and device readiness can alter them. The existing complete direct read-back checksum is still required for success. No optical format or Dashboard protocol has changed.

## Selection bug

Checkbox changes previously passed through the shared UI busy gate. A second change while another action was pending could be ignored. Changes also derived their selection from the last status snapshot rather than earlier edits still being saved. An older poll could therefore restore a different signer selection.

The page now keeps an explicit draft keyed by the current disc job. Each checkbox immediately updates that draft; saves are serialized and carry the job identity. Old status snapshots cannot overwrite an edited draft. New queue entries are not silently selected; a changed job starts a new draft. While saving or after an unresolved save error, burning stays unavailable. The selected-wallet summary names the current accounts beside the burn controls. Drive discovery, selected drive, disc count, speed and blank-disc confirmation survive ordinary rendering. Changing/refreshing drives still clears the blank-disc confirmation deliberately.

A burn waits for the selection saves, carries the exact visible wallet IDs and job ID, and checks/applies them inside the same protected dispatch as burn admission. Stale job IDs are refused before opening the passphrase dialogue or writer. During burn admission, checkboxes are disabled. Once preparation starts, the compiled member list remains fixed as in Build 49. Older local clients remain compatible with the original API argument shape.

## Validation and installation

Focused checks cover measured burn/verify countdowns, no ETA from pipe acceptance or zero progress, stale progress, independent verification timing, stale job admission, and selection application before optical checks. Interface regression deliberately toggles three rows before any save completes, receives an old poll, refreshes drives, rejects the intermediate empty selection, and confirms that the final exact signer + SMSF set reaches the burn request. It also checks drive selection and blank-disc confirmation survive a later redraw, and the next job starts with its own selection.

The full regression suite includes isolated three-Agent Core ceremonies, original and successive signer + archive burns, same-disc verification recovery, public inventory, policy refresh, archive load/signing and password retry safeguards. All development media are disposable file tracks; no production wallet, laptop service or physical burner was changed during these tests.

Finish the current burn, verification and remaining required setup work before closing the protected workspace normally and installing Build 51. Installing a package or refreshing a webpage cannot update a protected worker already running in RAM. The ongoing recovered Build 47 session is left unchanged.
