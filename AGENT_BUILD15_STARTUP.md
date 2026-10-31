# Agent Build 15: protected workspace startup

Scope: Agent only. No Dashboard source changes or Dashboard fault-finding in this work.

## Confirmed findings

The affected computer's protected service exited at systemd-inhibit with status 1. A wallet-free transient background-service test with the same user, NoNewPrivileges and no-dump library reproduced: the inhibitor was denied because interactive authentication was required. The ordinary terminal's local login context differs from a background system service. This confirms an Agent startup policy fault before any Dashboard registration.

The installer now grants only the two block-inhibitor actions to the matching root-owned system unit and UID with NoNewPrivileges enabled. The rule checks polkit's authoritative system_unit and no_new_privileges properties, not a caller-provided process name. It grants no shutdown, reboot, suspend, ignore-inhibitor, arbitrary-unit or pkexec action. Existing sleep-proof checks remain. See the [polkit subject documentation](https://polkit.pages.freedesktop.org/polkit/polkit.8.html) and [systemd 259 login policy](https://github.com/systemd/systemd/blob/v259/src/login/org.freedesktop.login1.policy).

Services includes a red/amber/green workspace indicator and explicit in-progress/ready/off labels. An ordinary disabled button uses a disabled cursor; only the operation currently in progress uses a wait cursor.

- On the affected wallet-laptop, calling the installed local worker's service_status directly failed: the protected workspace was not running or did not respond. This check does not contact Dashboard.
- Build 14 corrected failures reported from inside an already-running worker, but its ProtectedNode startup and local IPC failures still escaped as ValueError and runtime labelled them as incompatible Dashboard data. All startup/status bridge paths now preserve a local workspace category.
- The node toggle previously enabled its user service without first preparing the required protected workspace. Enabling it now performs the existing fixed local setup first, and saves/enables the node only on success. Cancelled/failed setup leaves it off. Previously enabled nodes show the local workspace problem and can be restarted via Services after setup.
- Explicit local protection refusals are no longer swallowed by ten-second readiness retries. The worker's bounded local error is returned. No local protection is disabled to obtain a green state.

## Device follow-up

Read the three system units (not systemctl --user): wallaby-agent-secure@UID.service, wallaby-agent-snap-ram@UID.service and wallaby-agent-denials@UID.service. UID is the desktop user's numeric ID. The service status distinguishes missing first-time setup, failed dependencies and a process exit. Protected worker stdout/stderr remain suppressed; no wallet/private RPC responses are newly logged.

Local startup tests use disposable sockets and mocked system-service control. They do not create RAM mounts, start real protected services, change Core, alter pruning or enable tunnels. The real privileged startup on the affected laptop must still be verified.
