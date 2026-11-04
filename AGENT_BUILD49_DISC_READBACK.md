# Build 49: fixed disc membership and verification-only recovery

## Observed failure

The Build 47 writer ran for about 47 minutes and returned success. Immediate direct read-back ended before any bytes were confirmed. This attempt did not hit its 3 GiB memory limit: its recorded peak was about 1.1 GiB, with no OOM events. After the user reloaded the drive, direct reads worked. Thirty-two complete encrypted packages, distributed from the first repeat through repeat 218176 near the end of the 25,023,217,664-byte track, matched the original package retained in protected RAM. The samples establish intact copies at those locations; they are not a full-track verification receipt. The evidence supports a drive/kernel readiness issue at the transition to reading. The exact original short-read return count was not logged, so its underlying hardware mechanism cannot be proved retrospectively.

## Fixed request list

Burner.state previously appended pending jobs to the same list stored in the compiled job's private members. Every poll added more rows. This was a request-list alias, not a list of physical redundant copies. State now copies the collection; compilation stores a tuple. Before completion, rebuilding the original bundle must exactly reproduce its metadata and wallet-file mapping. Unselected signers cannot receive completion receipts for another role's disc.

## Full read-back

One aligned 1 MiB buffer hashes the entire intended track and compares it with the hash generated while streaming the writer input. Initial unavailable/empty reads reopen the drive with a bounded 30-second readiness window. Positive sector-aligned partial reads advance by the actual count. Mid-track read errors stop with offset and errno diagnostics; they do not skip missing sectors. A complete checksum mismatch fails verification.

An idle failed verification offers **Verify written disc**. The original job identity, device, prepared image hash and layout must remain available. The user reinserts the same written disc; the retry reads only. No writer process, fresh encryption, key generation or wallet deletion is involved. Complete hash equality is required for normal signed Dashboard completion and the next required role remains queued. Cancellation, active optical work, stale job IDs and unavailable original images refuse recovery. New burns still require explicit confirmation of a fresh blank disc.

## Recovery of the current Build 47 test

Installing a package cannot replace an already-running protected worker safely. The separately delivered session-specific recovery tool uses CPython 3.14's supported remote-execution facility to repair this one idle worker without a restart. It reconstructs the actual two members from compiled bundle identities, preserves staged files and the unselected Russia role, installs the tested polling/read-back methods in that process, then starts full verification of the existing disc. It neither forges a full-verification receipt from the 32 samples nor changes keys. Its launcher checks the systemd cgroup, exact worker executable/UID and Build 47 version. Requests expire before mutation if not promptly handled. This tool is for the exact diagnosed test session, not a general update mechanism.

After the Australia + David SMSF disc passes and Dashboard completes that archive request, request David SMSF again from Dashboard Wallets and combine it with Archive Russia. Finish the ceremony and close the protected workspace normally before installing Build 49 for subsequent refresh tests.

## Bounded writing and loading

The existing format streams a small recovery filesystem followed by independently checksummed copies of the same encrypted multi-wallet bundle. Every repeat contains both selected accounts; David SMSF is not placed in a separate outer region. Copies are generated sequentially without retaining per-copy lists. Full post-burn verification checks the whole track. Normal disc loading stops after recovering its first intact package and validates its authenticated metadata; it need not scan every repeat.

## Validation

154 Python regression checks include actual isolated Core vault creation with three Agents, successive signer + SMSF archive requests, repeated polling while writing, full-track verification retry, short reads, checksum mismatch and ordinary policy refresh/archive flows. A separate real-Core test exercised the delivered in-process recovery payload in a live disposable Python process with the original duplicated queue: only the two actual members completed and the next role stayed pending. No physical drive or production wallet was accessed during development. The interface tests also check the same-disc verification button dispatches a read-only retry for the original job.
