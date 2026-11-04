# Build 53: protected-workspace startup

## Confirmed failure

The configuration service’s IPv6 address-family restriction installs a system-call filter and gives it NoNewPrivs=1. A child pkexec process therefore cannot gain administrator privileges. The node toggle could connect SSH but stopped before starting the protected services. Running the fixed helper from an unrestricted terminal prepared the workspace successfully, after which the node toggle worked. The affected laptop confirmed NoNewPrivs=1 and Seccomp=2.

## Startup route

The configuration window now asks the system service manager to start the root-owned wallaby-agent-prepare@UID.service. The system manager requests normal administrator authorisation and launches the installed fixed helper outside the GUI process ancestry. The shipped Polkit rule does not automatically authorise this preparation unit. Only routine start/stop of the caller’s own unprivileged protected worker remains automatically permitted.

The helper requires root and either the exact system preparation cgroup or a matching legacy PKEXEC_UID for terminal recovery. It accepts only a numeric desktop UID, with no user-supplied commands or paths. It establishes the existing non-swapping RAM mounts and starts the existing services; it does not delete, rename or regenerate wallets.

GUI NoNewPrivileges is now explicit. IPv6-only networking, native authorisation, protected-worker restrictions and non-swapping memory remain enforced. Cancellation, failure and timeout stop the attempt without automatically repeating administrator authorisation. Preparation failure identifies the relevant service for diagnosis. No Dashboard change is required.

## Validation and upgrade

Tests cover exactly one preparation request, cancellation/failure/timeout, matching caller identity, rejection of other users and user-service cgroups, non-root rejection, routine startup without another prompt, and administrator-policy boundaries. The generated system unit passes systemd-analyze verify. Multi-agent disposable Bitcoin Core regression tests cover the existing wallet/disc workflows. The new administrator route has not been exercised against the affected laptop’s service manager; its confirmed terminal recovery remains usable.

Keep any active protected workspace open until its approved work is finished. Install this update after normal safe closure. A currently connected workspace does not need to be restarted to benefit from its already successful preparation.
