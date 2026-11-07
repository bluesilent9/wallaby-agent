# Build 64 validation

Isolated Core 31 fixtures cover complete incoming/final-outgoing transaction preservation, exact LOST labels, idempotent merges, pruned-node preservation and full reindex/replay, signed direct historical transfers, local extinction eligibility and encrypted original-wallet restoration. Failure checks cover loaded-database locks, replacement rollback, retained public-copy cleanup, malformed block hashes, a pruned sender gap and explicit Internet resume. The OpenSSH client also transferred Core-validated blocks over a pinned-key authenticated IPv6 connection to an isolated Python SSH fixture server. No real Core process, wallet, service or disc was changed.

The accompanying Build 64 test log records the final focused and regression results. Six browser suites cover history preparation, exact pipe notation, lifecycle Deny/Cancel controls, protected-window status, cancellation feedback and disc selection/ETA. All 13 browser scripts parse. Native desktop password prompts are forbidden by the automated runner.

No physical burner or production-system installation was tested for this history/synchronisation build. Core-native backup merging is explicitly restricted to Core 31, and unknown pre-upgrade local extinction decisions are not silently inferred. See [the implementation boundaries and Dashboard coordination](AGENT_BUILD64_HISTORY_AND_SSH.md).

# Build 48 validation

A real throttled xorriso stream now advances intermediate progress before writer
exit and passes direct read-back. Accepted pipe data alone cannot advance the
physical bar. The focused 21-check writer/disc suite and all 20 JavaScript suites
pass. UI checks include elapsed time, reported byte counts and stale-report age.
See [details and upgrade guidance](AGENT_BUILD48_WRITER_PROGRESS.md).
Full regression results accompany the distribution; no real wallets or optical
media were used in development here.

# Build 47 validation

Final regression and UI results are recorded with the distributed package. The
new repeat-archive fixture uses three isolated real Core 31 nodes, two distinct
signer discs and two encrypted captures of one existing wallet. Each file-backed
xorriso burn passes direct read-back and completes only its own archive request.
Replayed completed requests do not create another capture; fresh requests do.
Unmodified Dashboard Build 55 permits the new request after signed verification. Stage failures, disc status,
memory admission, and unapproved/approved checkbox behavior have focused checks.
All native desktop secret prompts are blocked by the test runner.

The accelerated Qt renderer soak, renderer-only kill/reload and disposable user
service OOM-continuation checks passed. No real optical hardware was tested and
these checks do not guarantee recovery from every worker or machine failure.
See [details and measured limits](AGENT_BUILD47_DISC_OPERATIONS.md).

# Build 46 validation

Native Qt widget tests run offscreen with invented passphrases. Mismatch leaves
entry open without an accepted signal; corrected confirmation succeeds. Both
Show/Hide controls, clearing/reset, short/empty/overlong creation retry, existing
short wallet unlocks, Unicode/newline framing and safe native-helper failure pass.
Eleven focused native/display-context checks pass. All 18 JavaScript suites pass,
including revealed login-password clearing and direct red-button cancellation
without the old checkbox. Existing backend cancellation guards remain unchanged.
The dialogue was rendered and visually inspected with dummy values, without
opening any password request on the user's desktop.

A separate real three-Agent pending-disc check passes inventory reads and local
approval of an unrelated David SMSF archive. Replaying those public replies
through Dashboard Build 54 inventory processing succeeds with a regtest-only
network adapter. Adding an unrelated unloaded directory reproduces the Dashboard
inventory rejection and exact UI message. Dashboard is addressing that cause.

See [Build 46 details](AGENT_BUILD46_PASSPHRASES.md). Tests use no production
wallets, installed services, profiles or actual optical media.

# Build 45 validation

The new pruned-node suite passes three focused checks: three independent actually
pruned Core nodes install the original encrypted signing accounts with their full
policy; an interrupted blank-wallet installation remains explicitly cancelable
while unknown creation/extra descriptors are refused; and pruned restore failures
emit a fixed safe reason without exposing the raw Core error. The three-Agent
fixture uses a 3-of-5 policy, including two physical roles queued on one Agent.
The old genesis-dated offline backup fails on the same pruned chain. Prune heights
are unchanged and node installation may not invoke restorewallet.

The existing three-Agent combined-wallet suite also passes: named signer wallets
jointly sign a dummy transaction, the physical archive restores and verifies the
correct role, and an unrelated private wallet remains available for archiving
while physical backups wait. A further 35 focused checks cover cancellation,
helper write preflight/reconciliation, managed-account transfer guards and key
privacy. All 17 JavaScript suites pass, including a failed-installation status
that replaces the misleading in-progress message without offering unsafe discard.

No production wallet, installed service or pruning configuration is changed by
these isolated tests. Actual optical media and the user's installed desktop are
not covered. See [Build 45 details](AGENT_BUILD45_PRUNED_INSTALLATION.md).

# Build 44 validation

A three-Agent IPv6 HTTP test uses three independent isolated Core nodes. Each
Agent receives an identity challenge while its sender-preview worker is blocked.
Each also encounters one deliberately dropped poll connection. All three signed
identity replies are verified before the slow work is released; there are exactly
three registrations, proving that the transient faults did not replace sessions.

Focused tests check non-blocking command admission under full RPC capacity, a
fixed control retry deadline, immediate rejection of expired authentication,
non-replay after lost ACK/result replies, prompt exchange retries, and amber/green
protected-window recovery using one client. Existing 15-second cleanup and stale
callback guards remain covered. IPv6 restrictions and native DNS repair stay in
place. The tests do not reproduce the user’s real internet latency or installed
systemd/desktop environment, nor prove the separate Dashboard login fix.

# Build 43 validation

The Build 42 regression was reproduced on the installed laptop: ordinary IPv6
name lookup works, while the same lookup fails when IPv4 sockets are forbidden.
The native resolver IPC query works under that restriction. The corrected
Agent then authenticated to the configured real server, added an IPv6 Dashboard
forward and received HTTP 200 through it, with IPv4 still denied. The temporary
connection was closed and no installed service or configuration changed.

Automated tests cover bounded/framed native resolver replies, IPv6-only results,
link-local scope, refusal of mapped/invalid addresses, safe resolver errors,
trying another IPv6 address, original hostname trust settings, and actual file
descriptor handoff from a child with IPv4 sockets denied by seccomp. Existing
shared SSH, Dashboard access, diagnostics, webpage and three-Agent wallet
regression checks remain included. The native-desktop-dialogue test guard stays
enabled. Physical optical hardware and the target systemd service manager are
not simulated by these tests.

# Build 42 validation

IPv6-specific checks cover real HTTP requests over `::1`, exclusive listener
behaviour, refusal of IPv4 connections to both the webpage and offline Core,
strict origin checks, and migration of a custom-named Wallaby desktop shortcut.
Services and protected-page assets share the IPv6 server implementation.
Additional API/security, wallet routing, logging and JavaScript suites run
alongside the independent three-Agent combined multisig wallet tests.

The package is extracted and its installed source, web assets, documentation and
helpers compared byte for byte with this source. Installed desktop launchers
and service address-family restrictions are checked separately. Target-machine
Qt, systemd and real network testing remains necessary.

# Inherited combined-wallet regression coverage

The focused regression suite covers 95 Python checks, including real isolated
Bitcoin Core 31 nodes, plus 17 JavaScript interface suites. The development test
runner isolates runtime/configuration directories and refuses any unmocked native
desktop dialogue. Release evidence is recorded in the supplied test log.

The new cluster test uses three independent Agents for a 3-of-5 height-locked
wallet, with two physical roles produced on the Australia-like node. Each node
signer is restored as one encrypted named wallet containing the exact complete
receive/change policy; no additional persistent monitor is created there. The
private keys remain distinct. Three named wallets produce a complete spend of
regtest coins after independent signing. Ordinary signer-clone offers remain
blocked, including after RAM-state loss.

The same producer serves public wallet inventory and stages an unrelated existing
David SMSF fixture while its two original physical roles wait for disc writing.
A separate contention check overlaps two public requests with optical writing
flagged active; both return successful public results while unsafe closure stays
blocked. Existing generation, installation, restoration, capture and recovery
restrictions are also tested.

A combined role backup restores into an offline RAM Core, independently verifies
its assigned private account and stays encrypted/locked. Substituting another
role's encrypted backup is refused despite identical public policies. A private
wallet refresh keeps the same Core wallet name and retains old descriptors while
adding the new height policy. Existing tests exercise two archival refreshes,
policy history, message/output checks, multi-wallet packages, cancellation and
helper preflight/reconciliation, startup, public RPC privacy and queue behaviour.

The tests do not replace testing your three physical laptops against the deployed
Dashboard. Physical optical writing/read-back, a privileged installer run on a
fresh OS and your real wallet files were not exercised or modified. Dashboard
Build 52 supplies companion workflow/UI fixes; see the Build 41 format document
for role identity, logical wallet grouping and archive routing requirements.

Packaging checks compare every shipped source/web file, helper and documentation
file with the extracted DEB, verify version and dependencies, and record hashes.
Only source, tests, documentation and the built package are published. Machine
logs, recovery scripts, real wallets, credentials and test runtime directories are
excluded. There is no automatic migration or deletion of old persistent wallets.

Build 44 cross-application integration: the current Dashboard Build 54 source
accepted three signed identities from three separate Agent processes and three
isolated Core nodes in 2.277 seconds after discovery, with no session replacement.
This is a local regtest measurement, not a prediction of live network latency.

Final route checks cover direct peer IPv6 addresses without DNS and named hosts
through native IPv6 resolver IPC.
