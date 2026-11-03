# Build 38: approvals, disc staging and cancellation recovery

Authorise has a searchable, filterable request queue beside a dedicated review pane. Setup progress is separate from actionable requests. Local wallet cards follow the work area; collapsed denial lists remain last. Selecting another request clears stale review content, and cancellation still supersedes an earlier creation review. Retype prompts retain the assigned wallet and signer role names.

Disc Operations explains how to add an independent backup: Dashboard Wallets → Archive this Wallet → select this Agent, then review and authorise the incoming archive request. Staged backups can share a selected disc set with one vault signer. Different signer roles of the same multisig policy must still be placed on separate discs. Queued signer rows now include the role name. Idle disc waits and queued captures allow the existing public read-only RPC interface, while generation, installation, copying, optical reading/writing and cancellation remain guarded.

## Cancellation permissions and preflight

A parent /home write exception does not override the helper's nested read-only home mount on all installations. The root-owned workspace starter now prepares explicit per-user native and Snap wallet-directory exceptions for the deletion helper as well as the rename helper. Installer metadata refresh covers already prepared accounts. Home protection, the main worker's RAM-only write restriction, process attribution, path and inode checks, and the database lock required for actual deletion remain in place. The deletion helper's existing encrypted-export support is retained.

Cancellation checks every persistent deletion target through the actual helper before unloading any wallet. A failed preflight leaves wallets loaded and the request reviewable. Errors after unloading record the fixed cleanup stage and numeric operating-system error when available, without recording raw RPC or exception contents.

## Reconcile an uncertain cancellation

Select Reconcile cleanup on an attempted wallet cancellation and confirm locally. The original live setup must still exist. The Agent reloads only its recorded surviving installed wallets, verifies their public policies, checks helper access, and restores a fresh review. It does not delete files or repeat cleanup. Review the artifact list and explicitly choose Delete and Cancel or Backup and Cancel. Active transfers, history work and optical operations remain guarded. Missing original session metadata requires local inspection; wallets are never inferred from a name prefix.

This recovery is for a responding Build 38 worker. An older stuck worker cannot be replaced while it holds unfinished private material; finish or recover that session before upgrading. The installer does not force-stop it.

## Dashboard compatibility

No RPC method, signing authority or Dashboard message schema is expanded in this build. Dashboard catalog removal and withdrawal of stale sync requests are separate from local wallet deletion; use the Dashboard's cancelled-setup cleanup support for stale records from earlier builds. Cancelling an individual synchronisation request is not a persistent exclusion and does not remove the Dashboard's inventory. No new Dashboard protocol change is required by Build 38.
