# Agent V2 Development Build 63: planned Core restart

The supplied Agent log confirms the normal 15-second Core disconnect budget
expired during locally authorised history recovery. Protected RAM was retained,
but the node interface switched off. The supplied logs do not contain the
replacement Core service's launch error, so its exact machine-specific failure
cannot be established from these attachments alone.

The restart now exercises the separate desktop user service's working directory,
environment and output configuration before requesting Core shutdown. A failed
preflight leaves Core running. Its output uses the user journal instead of a
file inside the protected workspace's mount namespace. Core retains its own
normal debug.log. No raw launcher stderr is exported through sanitised logs.

A live, locally authorised recovery thread owns a bounded 900-second Core
restart grace, covering clean shutdown and RPC startup. It ends immediately on
failure or RPC readiness. During that period Agent heartbeats keep the Dashboard
session alive and report an amber planned restart, without pretending Core RPC
is ready. Dashboard/tunnel failures retain the ordinary 15-second budget. A
stored recovery flag alone cannot activate this grace after a crash.

Recovery still binds the process lock, data directory, chain and original Core
arguments; preserves pruning; pauses network while registering wallets; refuses
duplicate launches; and requires fresh local approval. No wallet is deleted by
recovery and no successful extinction receipt is produced before history
read-back passes.

An old wallet database may retain transactions whose raw blocks were pruned.
Importing its public addresses into a separate Extinct wallet does not copy
those transactions. Build 62's exact existing-archive read-back shortcut is
retained. If that archive is incomplete and the required history is pruned,
the explicit replay/download path remains necessary with the current protocol;
retaining the original wallet alone is not sufficient proof of preservation.

Validation uses isolated IPv6 regtest nodes and a real pruned replay, with no
Internet peers or real desktop Core shutdown. Service-manager launches are
substituted in regtest; separate tests cover preflight refusal, timeout,
launch uncertainty, grace ownership/expiry and ordinary disconnect handling.

An additional exploratory legacy multisig retirement test failed with an exact
target-list mismatch. The same unchanged test fails on the Build 62 baseline.
That pre-existing issue is outside this restart patch; it does not bypass the
delete-target guard. The focused restart, lifecycle, pruning and Build 62 history
regressions are recorded separately from that exploratory failure.

Core 31 offers importprunedfunds for importing individual transactions with
active-chain Merkle proofs, and getblockfrompeer can request particular previously
validated pruned blocks. This confirms a full replay is not a fundamental
requirement of extinction. Replacing the current rescan/replay path with selective
proof-backed imports needs its own completeness, spending-history and deletion
coverage checks; Build 63 does not claim to implement that separate change.
References: https://github.com/bitcoin/bitcoin/blob/v31.0/src/wallet/rpc/backup.cpp
and https://doxygen.bitcoincore.org/blockchain_8cpp_source.html .
