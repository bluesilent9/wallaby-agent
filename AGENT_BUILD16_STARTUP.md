# Agent V2 Development Build 16

## Confirmed diagnosis

Wallet-laptop's wallet-free probe passed every protection check, then failed while creating the supervisor socket with PermissionError errno 13. `namei` confirmed `/run/wallaby-agent-secure` and its UID parent were root-owned 0700, while the RAM mount was correctly user-owned 0700. Changing only the two parent modes to 0755 made the workspace and node connect successfully. A change under /run alone is not persistent across reboot.

The helper now explicitly sets validated root-owned parent modes independently of inherited UMask=0077. It uses O_DIRECTORY/O_NOFOLLOW and fstat/fchmod; symlinks, non-root owners and group/world-writable parents are refused. No RAM contents, ownership or private mode are changed. The same helper creates the persistent systemd mount unit for subsequent boots.

## Workflow

The node toggle prepares the protected workspace before enabling or saving the node service. Workspace startup, Core RPC and Dashboard diagnostics belong to that service row. Startup/cancellation failures do not enable the node. There is no separate Start protected workspace button. An already responding worker is reused without authorisation; initial mount preparation has one fixed administrator prompt. No automatic authorisation retry follows a worker protection refusal.

The ordinary page is inert while a protected viewer is alive. Its overlay can close only the tracked viewer child processes, leaving the node and workspace active. The separate Close workspace control requires the node off and protected operations finished; it then retains the existing supervisor's child cleanup and RAM clearing. The protected viewer's Services navigation is disabled and Services content hidden.

Sign Message and Disc Operations assets previously returned 404. All scripts referenced by index.html now have tested static routes. Signing-account refresh has progress, empty/error results, and invalidates obsolete reviews while preserving still-available account selections.

## Scope and limits

No Dashboard code, global SSH/firewall settings, wallet backups or pruning settings are changed. Desktop locking is a UI control, not protection against a compromised local user or OS. Startup protections are still enforced by the protected system service. Unit/regression tests cannot substitute for privileged installation and GUI verification on wallet-laptop; that remains an end-to-end deployment check.
