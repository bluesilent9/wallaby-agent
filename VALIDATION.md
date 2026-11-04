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
