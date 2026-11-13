# Build 89

## Fixes

Wallet cards now apply their randomly seeded per-wallet hue to actual pastel backgrounds and borders. Their spacing, 190px geometry, top balance and icon/name layout follow the Wallet Server Wallets cards. Hover/focus deletion and click-to-open history remain separate.

The Agent log shows a review before pairing at 04:49:58 UTC and another after pairing at 04:51:35 UTC on 13 November 2026. Build 88's periodic authenticated ping omitted the capability its initial ping advertised; receiving it cleared the comparison feature. All pings now advertise it. Comparison jobs are bound to the review timestamp and eligible direct channel identities, so the previous unavailable answer cannot mask newly connected peers. Matching remote evidence replaces the preservation warning and uses the same complete counts and address/transaction samples as local evidence. Diagnostics report candidate counts and completion counts without wallet contents.

## Cleanup and development workflow

Pre-88 release notes, obsolete probes/tests and installers are removed from the current source/repository tree; Build 88 remains the reference. Current feature tests and the fixtures they need have descriptive names rather than release numbers. Another 267 unused historical test methods were removed from retained helper fixtures. The public policy module is renamed for its function. Obsolete IP-based wallet transfers, combined-retirement and old QR workflows, the old viewer-close wire method and the one-off pre-68 workspace recovery hook are removed.

Persistent wallet policies, denial/trust records, physical recovery discs and legacy address-only Extinct entries remain data requiring preservation/upgrading, not obsolete network compatibility. Their protection and upgrade paths remain.

Packaging handles one current version. Its cache binds every packaging/source/web/document input and the resulting installer hash. Editing any input or corrupting the installer forces a fresh build. The reusable exporter verifies runtime files, documents, root ownership/modes and version, and writes one source bundle. Git publication removes retired paths from the current tree without rewriting history. Tests can be selected by current feature so routine changes do not rerun unrelated whole-release matrices.

## Validation

Isolated Core and actual paired SSH tests cover full comparison, mismatch, disconnect, warning-only deletion, capability retention through periodic heartbeat and fresh review/topology invalidation. Chromium checks actual card background colours and layout, hover deletion, automatic refresh, transaction copying/toggling, and the no-peer → connect → review → matching-history transition. Current release identity, package protections and production worker startup are checked. These use temporary regtest wallets and synthetic browser API data; they do not change production wallets or claim an end-to-end physical laptop run.
