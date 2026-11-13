# Development Build 93

Receive controls retain the last confirmed transfer view during a read-only busy status response. A successful local route change is retained while awaiting the next fresh snapshot; it cannot start a transfer without the existing bound Authorise review. Real transfer activity and lost direct connections still disable the appropriate controls.

Sidebar unread dots are removed. All pages have right-aligned numeric attention badges. Counts cover authorisations, setup work, sync offers/recovery, disc reviews/loads/failed burns, peer confirmation and cleanup recovery. Denied sync offers do not count. Normal safe closure saves only aggregate integer counts to the ordinary configuration directory; the disabled unprotected sidebar labels these as the last protected state. No wallet identity, balance or transaction is persisted with these counts. A new protected snapshot replaces them.

The worker reports its closing flag immediately, before its viewer exits. Configuration remains locked through the lifecycle cleanup marker and service-stop marker, including the interval when the worker is already unavailable. The normal closed state unlocks only after cleanup finishes; abnormal recovery controls are retained.

Sync-table static cells have the default cursor. Enabled checkboxes, source menus and buttons retain the pointer. Icons are wallet, SMSF (case-insensitive wallet-name heuristic), vault, multisig, Extinct and disc, in that order. Vault/multisig icons derive from public policies, not Server-assigned flags. A discovery origin hint is cosmetic and is checked against the sending Agent's signed preview during actual review.

Vault transaction history uses local Core unspent outputs, including locally locked coins, and each output's actual descriptor rather than just the latest receive policy. It distinguishes unfunded, all unlocked, all locked, mixed funds and uncertain/unsupported states. Locked estimates use local block-header intervals and two significant units (minutes/seconds use `27:12`). These are advisory estimates read when the table opens; block-height consensus controls spending. A history view never initiates a rescan or signs anything.

## Wallet Server companion change

See [source-origin protocol addition](SYNC_SOURCE_STORAGE_V1.md). Build 12 must be updated for disc-origin previews/offers; ordinary node-wallet preview envelopes remain unchanged. No Server update is needed for numeric badges, the busy-poll fix, shutdown locking or the local vault history status.

## Validation

Checks include isolated Core 31 vault funding/unlocking, mixed old/new policies and locked coins; ordinary history and deletion; grouped direct receiving of full Extinct history and LOST labels; independent watch-only choices; busy status projection; preview concurrency; production-CSP browser regressions for stale snapshots/checkbox retention, controls, badge alignment, cleanup locking, wallet history and icons; current version and package source parity. See the exported verification file for installer identity and hashes.
