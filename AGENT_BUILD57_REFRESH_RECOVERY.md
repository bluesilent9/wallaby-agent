# Build 57 — recover signer backups after repeated vault refreshes

## Cause and scope

Core 31 omits the internal (receive/change) flag on inactive historical descriptor records. After refreshing a combined signing wallet, Agent 56 interpreted that missing flag as receive. Restoring a fresh backup of that live wallet then rejected a legitimate historical change descriptor as the wrong private derivation. The normal replacement queue, which uses the original wallet file plus approved extension metadata, can avoid this symptom; it does not fix validation of a fresh backup containing all generations.

## Correction

The private derivation and account must match exactly one of the locally signed public contribution's receive/change keys. Every descriptor, including old inactive records, must contain exactly the one approved private role and match a full policy in the validated recovery history. An explicitly supplied branch flag must agree. Both receive and change policies remain required. Wrong roles, extra private keys, incomplete branches and substituted or unapproved policies are rejected.

Additive private-policy installation also matches actual keys rather than discarding historical change keys solely because their branch flag is missing. All original policies and signing keys are retained. The overall wallet name, role name and route alias stay unchanged through repeated refreshes and reloads.

## Compatibility and upgrade

No disc format or Dashboard protocol change. Existing valid archive files and approved extension histories remain usable. Build 56's deferred broadcast flow still requires Dashboard 64+. Finish protected operations and close the workspace normally before installing Build 57. Failed recovery can then be retried from the same archive; do not rebuild keys solely for this validator fault.

## Validation

Use tests/test_build57.py with the isolated Core 31 test fixture. It recreates a 3-of-5 setup across three nodes, loads an encrypted disc role, performs three refreshes, backs up and reloads the actual multi-generation private wallet after each, verifies stable names, and signs both branches. It also reloads the exact file selected by the normal replacement queue. Synthetic rejection tests exercise wrong roles, extra/missing private keys, wrong explicit flags, incomplete branch sets and substituted/unapproved policy generations. Tests use disposable keys and test coins; no live wallet or physical disc is modified.
