# Build 80: independent Core restart and retained recovery

The protected service mounts persistent home data read-only. Build 79 attempted to open Core’s `.lock` with `a` after a clean shutdown. That raised `OSError` before requesting the real restart service. The earlier `/usr/bin/true` preflight therefore passed even though no Core service was launched.

Build 80 probes the existing file using a shared POSIX lock on a read-only descriptor. This conflicts with Core’s exclusive lock and never creates or modifies the file. The actual Core launcher is checked using its original configuration arguments and `-version` before Core is stopped. A missing readable lock or refused launcher leaves Core running. Only the same reviewed process may be stopped, and restart requires process exit plus release of the original lock.

Core runs in an independent desktop-user service in `app.slice`, outside the protected worker’s mount namespace, with output in the user journal and its normal debug.log. No terminal must remain open. Failure after shutdown gives an explicit retained-workspace error and does not launch a duplicate process. Pruning settings are unchanged.

The longer RPC grace belongs only to a live, locally authorised restart thread, for at most 900 seconds. A previously queued, unexpired RPC timeout is deferred during that restart; an expired session cannot be revived. Server/SSH failures retain their normal timeout. The grace is cleared on completion or error. Sanitised diagnostics include an OSError number without exposing paths, command arguments or credentials.

## Continuing a retained Build 79 operation

Starting the reviewed Core instance manually with `-reindex=1 -networkactive=0` leaves Internet peers paused. On Synchronisation, refresh **This Node**, review its recovery plan and authorise continuation. The Agent recognises paused replay, prepares the required wallets before enabling downloads, and does not restart/reindex Core a second time. Existing SSH-only receiving remains SSH-only.

An extinction request intentionally remains pending during recovery. After recovery completes, review and approve preservation again; deleting the old wallet remains a separate approval. Recovery alone does not report the retirement completed or delete the active wallet. No Wallet Server update is required for this repair.

## Validation

Tests use isolated Bitcoin Core 31 regtest nodes, never production services or wallets. Coverage includes an actual competing POSIX lock with simulated read-only mount refusal, absent-lock refusal, launch ordering, independent service arguments, failure before/after shutdown, restart grace and server-failure isolation, paused manual continuation, actual clean shutdown/reindex/encrypted-wallet restoration, and complete pruned-block Extinct migration with LOST labels and later coverage reuse.

The real Core and wallet operations run in fixtures; desktop user-service launch is adapted to isolated subprocesses. Snap confinement and installed systemd service behaviour still require device validation. No physical discs are used.
