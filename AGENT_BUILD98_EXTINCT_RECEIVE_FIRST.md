# Build 98 — Extinct receiving and preservation review

A saved preservation request remains pending until local preservation checks pass, including while its source Agent is offline. It is not an announcement that the source is currently connected.

Preservation review now handles a missing local archive instead of failing a wallet-info lookup. It inspects an existing unloaded archive temporarily and restores its prior loaded state. When no history recovery job is prepared, missing history directs the user to receive/merge the current archive first, then check again. Review re-evaluates current local data after the archive arrives. It does not silently import, approve, restart Core or start a blockchain download. Explicit local history recovery remains available under a disclosure. Previously authorised recovery keeps its continuation.

Services now uses an outline wallet icon matching the other service icons.

## Companion Wallet Server repair

Wallet Server Build 17 repairs extinct_watch summary discovery and creates fresh receive offers after deletion despite completed earlier transfers. Agent 98 cannot fabricate executable Server requests. Both Agents and their paired connection must be online for direct receiving. No Server-supplied transaction data is trusted or imported.

## Validation

Isolated Core 31 tests cover missing archives, unloaded archives, existing recovery jobs, and reviewing again after receiving. Maintained transfer, cancellation, loading, release identity, deletion and transaction-history regressions are run for this release. Browser checks enforce the production CSP and verify receive-first controls, hidden alternate recovery controls, navigation and monochrome service icon, alongside the existing wallet/sync UI checks. Packaging compares installed runtime bytes, release identity, ownership and permissions against the current source.
