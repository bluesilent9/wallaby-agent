# Agent V2 Development Build 16 validation

## Scope

Agent-only changes. No real wallets, production node data, SSH services, firewall rules or pruning settings were changed by these checks. Bitcoin integration tests use disposable Core 31 regtest nodes. No physical optical drive was written.

## Confirmed remote diagnosis

On wallet-laptop, the wallet-free startup probe passed the OS protection checks then failed with EACCES when creating the supervisor socket. Root-owned parent directories had mode 0700 due to inherited UMask=0077. The user changed only these parents to 0755 and confirmed the protected workspace/node connected. Build 16 applies this correction in the privileged setup helper, without changing the private RAM directory mode.

## Automated verification

The full regression run passed **194 tests in 260.978 seconds**. After the final non-blocking liveness change, the focused startup, viewer, node-boundary and native-prompt suite passed **26 tests in 2.146 seconds**. Four JavaScript UI/policy suites passed; all shipped web scripts passed syntax checks. Results are recorded in the distribution test logs. Coverage includes Core 31 single/multisig/vault signing, archive restoration, BIP-322 messages, persistent exclusions, labels and address-only watches, full historical replay with pruning unchanged, public-only remote RPC and local authorisation boundaries.

New focused regressions exercise real filesystem modes under umask 077, repair of existing parents, no-follow/ownership/mode refusal, all HTML script routes, viewer termination/reaping without stopping the worker, and non-blocking public viewer liveness while a signing operation holds the operation lock.

All shipped web scripts pass Node syntax checks. Four JavaScript VM suites execute the actual UI handlers for node-toggle preparation, error retention/retry, code-box copying, protected-window locking/close, Services disabling in the protected viewer, and signing-account refresh progress/empty/error results/selection preservation/review invalidation. The shipped polkit rule is tested for its exact unit/UID/NoNewPrivileges boundary.

## Deployment limits

The full privileged service and Qt window lifecycle must still be verified after installing Build 16 on wallet-laptop. Automated DOM tests are not a native desktop GUI test. The existing RAM-only protection boundaries, sleep inhibitor, mandatory node workspace and optional tunnel-only installation are retained.
