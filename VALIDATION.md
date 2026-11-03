# Build 35 validation

All **26 focused Python tests** passed in 15.895 seconds: cancellation state/visibility, independent replacement bindings, safe diagnostic categories, cancellation consent and dispatch guards, seven startup-authorisation checks, and two real Bitcoin Core 31 cancellation regressions. The real-Core cases verify retained encrypted keys followed by recoverable encrypted backup, and cancellation of an installed multisig/disc setup while an unrelated wallet survives. They run on isolated regtest fixtures.

One additional live-settings startup-metadata regression passed after updating its current-build fixture.

All **15 JavaScript suites** and web syntax checks passed. The new transition test executes the shipped selection/poll/render flow: cancellation replaces the open creation controls with the exact cancellation link, cancellation rows come first, deletion requires explicit acknowledgement, completion clears the review, late responses cannot resurrect creation controls, unrelated queue changes preserve a valid review, and unfinished setup cards route to cancellation. Existing denial ordering and rename/card regressions pass. Package export compares installed source, web, metadata helpers and documentation with the source tree. No native Qt close implementation or Dashboard wire protocol changed; the existing close guard still retains unfinished private work. The supplied production log and successful manual cancellation review corroborate the display defect; no production wallet was changed by automated tests.


Earlier build validation remains available in the repository history and the corresponding build notes.
