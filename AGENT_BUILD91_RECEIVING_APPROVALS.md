# Build 91 — Receiving approvals and complete Extinct history

Tick Receive on Synchronisation to create a local Authorise request. Selected wallets from the same authenticated source identity share one request. Changing the selection, source, watch-only mode or signed preview invalidates the old review. Approval authorises only the reviewed source group, expires after ten minutes, and is single-use. Cancel clears the local selections.

The Synchronisation table keeps the source dropdown, watch-only checkbox and Receive selection. It removes the redundant destination column, per-row Review Receive buttons and watch-only explanatory text. Signed wallet details, grouped Extinct children and the approval button are on Authorise, without Mobile verification. Progress and failures remain visible there.

The direct sender previously exported history_wire version 1 even when both peers advertised core_history_v2. That omitted whole-history coverage and blocked first-time imports. Current direct Extinct transfers require and export version 2. The receiving Agent still verifies coverage against its own active chain, transaction records, labels and local ownership. No Server-provided data substitutes for direct authenticated records. LOST labels and existing archive data are retained.

Validation: real Core 31 and authenticated direct SSH for grouped wallets with independent watch choices, single-signature, multisignature and original-role vault transfers, first-time complete Extinct history and LOST labels; refusal of active local ownership, busy/changed/withdrawn source and wrong identities. Unit checks cover grouping by source, changed choices/previews, one-use approval and cancellation. Browser checks use the production Content Security Policy and exercise the complete selection/Authorise flow. Runtime versions, packaged source parity and ownership are checked during release.

Install Build 91 on both Agents so the source uses the complete-history export. No additional Server protocol update is required for this build.
