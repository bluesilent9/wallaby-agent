# Build 86 — protected session drops caused by the clone helper launch

Build 86 fixes the packaged blockchain-clone helper's isolated Python launch and removes its ability to tear down a healthy protected workspace when it fails. Install the Agent update with the node interface off, then turn the node interface on normally. No Wallet Server update or pairing reset is required.

## Evidence and cause

The supplied Build 85 log shows one ordinary node controller remaining alive while the protected system service acquires three different main PIDs. Each replacement worker has a fresh controller epoch of zero. There are no cgroup OOM events or automatic protected-service restarts. Server registrations and identity conflicts follow these replacements. The Server's identity protection remains enforced.

The packaged clone unit runs `python3 -I -B .../chain_clone_service.py`. Python's isolated mode excludes the script directory from the import path. Unlike the other service entry points, this helper did not explicitly add its installed source directory before importing adjacent modules. Running the Build 85 entry point with the packaged interpreter flags reproduces `ModuleNotFoundError` for `chain_clone_files` before the helper can serve requests.

The clone helper was a required dependency of the protected service. Its failure can therefore stop the protected service, and subsequent node retries start another empty worker. Build 85's controller ownership protections remain useful but do not repair this launch failure. Previous clone tests imported the helper in a test process with its source already on the import path, which missed the installed launch mode.

## Changes

- The clone helper explicitly adds its own resolved installed directory before local imports. Isolated mode remains enabled; arbitrary working directories and PYTHONPATH are not used.
- The clone helper is wanted and ordered before the protected service, rather than required for its lifetime. It is still stopped with the protected service. A failed clone helper makes cloning unavailable instead of dropping normal node access. Its same-user/protected-cgroup caller checks and filesystem restrictions remain enforced.
- Ordinary startup, failure and exported logs now include allowlisted state for the clone, trust, retirement, rename, denial, Snap RAM and preparation helpers. A bounded journal reader reports only known exception/module names, exit status and fixed service failure categories. Raw journal text, arguments, credentials and wallet contents are not copied into the export. An unavailable journal is reported without changing operations.
- Visible badge, worker, application, monitor, HTTP metadata and loaded-process labels are Build 86.

## Validation and limits

The isolated-launch regression fails against Build 85 before its socket opens and passes against Build 86. It starts the real helper main loop under `/usr/bin/python3 -I -B` with only its socket path redirected into a temporary directory, refuses a caller outside the protected service, and remains alive beyond the old restart cycle. All seven packaged source service entry points are imported in fresh isolated interpreters from an unrelated directory. A malicious adjacent-working-directory module cannot replace the installed import.

Tests also check packaged dependency fault containment, helper diagnostics when no worker is available, secret omission and bounded journal failure. Existing real isolated Core 31/Wallet Server session, pairing, receiver-initiated wallet transfers and direct SSH chain-recovery suites are rerun. UI log export and existing recovery/consent controls are checked. The test report records individual outcomes.

This environment does not run the user's host systemd instance. Service dependency declarations are checked in the generated package; complete host cgroup/mount/inhibitor behaviour and the user's Wi-Fi hardware are not simulated. Core fixture data is isolated; fixture process launches substitute for production desktop-user systemd restarts. No production wallets or attached logs are included in the source publication.
