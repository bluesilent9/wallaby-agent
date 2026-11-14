# Development Build 97

Extinct ownership checks no longer require the user to load every local wallet manually. The Agent temporarily loads local Core wallets for the check, retains the ownership check for active wallets and unfinished local retirements, and unloads only wallets it temporarily loaded. Wallets already open remain open. Load/unload RPCs omit the startup-preference option, so inspection does not change which wallets Core loads at startup.

The receiver keeps the inspection scope open through archive import and readback, including when an existing archive was initially unloaded. Nested preflight checks do not unload wallets owned by an outer inspection scope. A source archive unloaded after its signed preview was prepared can also be temporarily loaded for export; sender loading is restricted to archive candidates, rather than unrelated source wallets.

Partial load failures and operation failures run cleanup. Genuine active ownership still blocks import. A Core load failure or cleanup failure is reported rather than skipped, and logs include bounded load/cleanup counts and failure categories without wallet contents. Inspection does not unlock encrypted wallets, start a blockchain download, reindex Core or alter pruning settings. Existing transfer cancellation and safe operation reservations remain in place.

Both Agents should install Build 97. Wallet Server does not require a companion change.

An existing empty public Extinct archive is also accepted during import; its empty label inventory no longer trips the non-empty public-policy validator.

Validation: 62 regression checks passed, followed by four targeted checks against the final source, including the additional unloaded-existing-archive case (63 distinct checks in total). These cover unloaded receiver wallets, unloaded active owners, unloaded source archives, partial loading failures, cleanup failures, nested ownership inspection, preserved startup RPC options, pruned transfers and existing single/multisig history. The production-CSP receiving browser suite passed. Release export checks runtime/source parity and root ownership/permissions.
