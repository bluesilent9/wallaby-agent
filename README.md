> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent V2 — Development

Wallaby Agent manages per-user **IPv6 SSH tunnels** from a Linux desktop to your server. Its local HTML5 configuration page uses the Wallaby gear emblem and black sidebar.

**V2 Development Build 6** fixes fresh-page authentication, adds live configuration saving/reloading, and replaces all ping checks with one authenticated IPv6 SSH connection shared by the three services. It retains Vault Builder, Authorise and the public/read-only Dashboard RPC policy. [Download the Ubuntu 26.04 LTS amd64 DEB](dist/wallaby-agent_2.0.0~dev6_amd64.deb) and verify [SHA256SUMS.txt](dist/SHA256SUMS.txt). This is a Development build, not a Stable release. Dashboard-side vault exchange and Transaction Builder Stage 2 reception are specified but not implemented in the Dashboard by this change.

The previous [Build 3 DEB](dist/wallaby-agent_2.0.0~dev3_amd64.deb) and its [checksums](dist/SHA256SUMS.txt) remain for historical access. Build 3 contains the wallet RPC routing defect and must be upgraded for automatic node wallet loading.

## Current capabilities at a glance

- **Services:** independently enable per-user IPv6 SSH access to DDNS-GO Administration, the Dashboard browser and the Bitcoin Core node interface. Services default OFF, reconnect automatically when enabled and start with the desktop session.
- **Public/read-only Dashboard RPC:** direct remote requests cannot create wallets, import descriptors, change addresses or labels, unlock wallets, export private keys, sign or broadcast. Sensitive local workflows use separate fixed code paths.
- **Vault Builder:** a local Agent feature, replacing the proposed standalone vault application. Build a single-key P2WSH block-height vault, sweep the source wallet’s available receiving/change funds into one output, verify the policy/key/address with local Core and roll a matured vault into a new one. Unavailable funds stop a partial sweep.
- **Timing and review:** bundled timezone map, local/UTC 99% model and most-likely arrival estimates, annotated commands/descriptors/PSBTs, locally reconstructed wallet identities and exact amounts/total fees in pipe notation. The timing model is an estimate, not a calendar-date guarantee.
- **Authorise:** locally approve or deny staged public imports and signing proposals. Deny records persist; transaction reviews expire and are consumed once. Local signing can broadcast after review, while Vault Builder’s Send to Transaction Builder action queues a signed PSBT without broadcasting.
- **Integration boundary:** Build 6 retains the Agent side of the [approval/exchange protocol](APPROVAL_PROTOCOL.md). Dashboard V1 Build 7 has not implemented its exchange or immutable Stage 2 receiver; public vault records and signed PSBT exports remain queued locally. Ordinary read-only node queries and existing tunnels continue to work. The Dashboard’s earlier direct watch-wallet creation/import operations are blocked by the Agent and require the later approval integration.

## Three independent services

| Configuration switch | Local endpoint | Server destination | Requires Bitcoin Core? |
| --- | --- | --- | --- |
| DDNS-GO Administration | `http://[::1]:9876` | `[::1]:9876` | No |
| Wallaby Dashboard | `http://[::1]:38951` | `[::1]:38951` | No |
| Bitcoin Core Node Dashboard Interface | private ephemeral IPv6 loopback port | `[::1]:56443` | Yes |

**Wallaby Dashboard** supplies browser access. Switch it on, then use **Open Dashboard**. It can be enabled on a computer with no Bitcoin Core installation. The **Node Dashboard Interface** separately connects local Core RPC to the Dashboard's Agent listener; it does not provide browser access on port 38951. Enable either or both according to the computer's role.

All three switches default OFF for a new user. Upgrading an existing V1/V2 configuration preserves DDNS-GO and node choices and adds Dashboard access OFF. ON connects immediately, reconnects automatically and starts at the next user login. OFF stops and disables only that user's corresponding service. Jellyfin administration remains removed.

## Install and configure

Install the Build 6 DEB after verifying its accompanying checksum:

```sh
sudo apt install ./wallaby-agent_2.0.0~dev6_amd64.deb
```

Installing a DEB uses normal administrator permission. Tunnels, settings and login startup subsequently run as your user, without sudo, system services or lingering. Open **Utilities → Wallaby Agent Configuration**, or run `wallaby-agent configure`.

1. Enter a server hostname/domain. It saves automatically; **Connect** applies pending valid edits and immediately retries the saved SSH connection. IP literals are rejected; the server requires an AAAA record and a working IPv6 route.
2. Enter the **server SSH account**, which can differ from your desktop login. For example, desktop user `alice` may use a separate server SSH account `wallet-node`. Verify the trusted server fingerprint and key authentication with `ssh -6 -F /dev/null USER@HOSTNAME` before enabling services. Encrypted keys must be unlocked in the desktop SSH agent. An optional absolute private-key path can be selected.
3. Settings save automatically after a short 350 ms typing debounce and are reread every two seconds. No Save button is needed. Valid edits update config.cfg atomically; invalid drafts stay visibly unsaved and cannot replace the last valid settings. Partial updates preserve other fields and service choices. SSH edits replace the shared login; RPC edits refresh the local node client. Direct file edits are reflected on the page too.
4. Enable the services needed on this computer. Dashboard browser access and DDNS-GO need no RPC cookie.
5. For the node interface, enable RPC (`server=1`) and restart Bitcoin Core. Agent checks owned Core processes, custom datadir/cookie options, Snap `~/snap/bitcoin-core/common/.bitcoin` and `current/.bitcoin`, then `~/.bitcoin`, with local config/settings hints. Bitcoin Core has no standard datadir environment variable. If needed, select the local `.cookie` with **Choose file**, the selected path saves automatically. Only its path is saved, and its contents are reread for each RPC call.

## IPv6 and SSH forwarding

SSH always uses `ssh -6`; local listeners and remote forward destinations use IPv6 loopback `[::1]`. The tunnel command ignores `~/.ssh/config` forwarding directives, uses normal `known_hosts` and the SSH agent, and enforces host-key verification. It never stores an SSH password or accepts an unknown server key automatically. The configuration page and local Core RPC use IPv4 loopback independently of SSH.

Server forwarding rules must permit the exact destinations. A restricted key that uses all three services can permit `[::1]:9876`, `[::1]:38951` and `[::1]:56443`, subject to existing account restrictions. An IPv4-only `PermitOpen 127.0.0.1:PORT` rule does not permit `[::1]:PORT`. The installer does not alter server SSH rules or expose public listeners.

Remove an old Dashboard startup forward before enabling the Agent's Dashboard switch if it occupies port 38951. Identify the exact legacy unit and inspect its command before retiring it; do not disable the new `wallaby-agent-node.service` or a storage mount. See [LEGACY_DASHBOARD_TUNNEL.md](LEGACY_DASHBOARD_TUNNEL.md).

## Status and diagnostics

Red means off/disconnected, amber means connecting/checking, and green means connected. The switch records desired ON/OFF; the separate dot reports actual state. DDNS-GO and Dashboard browser tunnel green confirms authenticated SSH and its forwarding listener, not the application's HTTP health. Node green requires **SSH, healthy local Core RPC, and successful Dashboard registration/heartbeat**.

The server indicator is green only while an authenticated IPv6 SSH master is connected, amber during authentication, and red after a drop or configuration/authentication error. Reconnects use 15–300 second backoff with jitter; Connect requests an immediate retry. There are no ping/ICMP probes. The master keeps the login connected even when every service switch is OFF. Turning a switch ON/OFF adds/cancels that forwarding with OpenSSH `-O forward` / `-O cancel`, without another login. New master generations invalidate old forwards so workers reattach after reconnect. SSH keepalives detect lost transports.

Errors distinguish SSH/DNS/IPv6 routing, server-key verification, key authentication, local port conflicts, denied server forwarding, a refused remote target, Core cookie discovery/readability/format, RPC authentication/port/warmup, and Dashboard HTTP/protocol/session failures. RPC/Dashboard errors are no longer overwritten with a generic SSH-key warning. The original failure remains visible during long retry waits and is shown as the previous failure during the next connection attempt.

```sh
journalctl --user -u wallaby-agent-dashboard.service -n 50 --no-pager
journalctl --user -u wallaby-agent-node.service -n 50 --no-pager
```

The journal includes classified stage/code and actionable messages. Raw SSH error lines are drained into bounded private memory for classification, not copied to the page or journal. Cookies, authentication headers, session tokens and raw RPC responses are not logged.

Configuration is `$XDG_CONFIG_HOME/wallaby-agent/config.cfg` (normally `~/.config/wallaby-agent/config.cfg`), mode 0600 in a private directory. Status and control sockets use `$XDG_RUNTIME_DIR`. The UI binds only to `127.0.0.1`. A fresh local page obtains its current Bearer token using a same-origin Fetch Metadata/custom-header handshake; it no longer depends on a fragment token or sessionStorage from the menu launch. Host is restricted to this port’s 127.0.0.1/localhost authority, foreign origins and same-site/cross-site requests are rejected, API access still requires the token, and no CORS access is granted. No session cookie is used because cookies are not isolated by port. All page assets are locally installed.

## Node protocol and RPC

Application V2 retains the **Dashboard V155 Agent v1 protocol on port 56443**. See [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md). Registration, independent heartbeats/long polling, acknowledgements and correlated results carry approved local Core RPC requests. Duplicate commands are not rerun; lost acknowledgements and RPC timeouts are not automatically replayed. Reconcile local state before repeating a write.

The Agent independently enforces a public/read-only RPC allowlist. Wallet creation, descriptor import, address/label changes, scanning actions, private exports, unlocking, signing and broadcasting cannot be called directly by Dashboard. Approved local workflows use separate fixed code paths. See [APPROVAL_PROTOCOL.md](APPROVAL_PROTOCOL.md) for the future Dashboard exchange and immutable Stage 2 PSBT handoff.

## Upgrade and build

Close old configuration tabs before upgrading. V2 startup stops/disables the current user's retired V1 Jellyfin unit and removes its old startup link/status/config switch. DDNS-GO and node settings are preserved; Dashboard browser access starts OFF.

Optional manual refresh after installing Build 6:

```sh
systemctl --user daemon-reload
systemctl --user try-restart wallaby-agent-monitor.service wallaby-agent-ddns.service wallaby-agent-dashboard.service wallaby-agent-node.service wallaby-agent-ui.service
wallaby-agent configure
```

Opening Wallaby Agent Configuration from the menu automatically detects older monitor/UI processes and refreshes the saved enabled services once after an upgrade. Reopening an already-current Build 6 page keeps the SSH master connected. Close old browser tabs after upgrading. The optional commands above only restart units already running. The new Dashboard unit is enabled when its switch is turned on. Package scripts do not control another logged-in user's session.

Source checks:

```sh
python3 -m unittest discover -s tests -v
```

Build using Ubuntu 26.04 with Python 3, `gcc` and `dpkg-dev`:

```sh
python3 packaging/build.py
```

No root or network is needed for building. The DEB includes a compiled native launcher and Python runtime sources; it is not a static standalone executable. Sources include the vendored embit public descriptor parser and its MIT license. RPC policy derives from Dashboard V155. See [VALIDATION.md](VALIDATION.md) for checks and remaining live tests.

## Build 4 RPC corrections

Wallet RPC uses `/wallet/` followed by the encoded exact wallet name, with no extra suffix. Empty default wallet names, literal trailing slashes, spaces, Unicode, percent signs and embedded slashes are preserved. The Dashboard dispatches at most two active RPC commands per Agent; the Agent retains its own two-worker limit and waits for a free worker rather than disconnecting during a completion race. Independent heartbeats remain active. Existing signing, unlock, private-key and broadcast restrictions are unchanged.


## Vault Builder and Authorise

The black sidebar contains **Services** (always available), **Vault Builder** (enabled when local Core RPC is reachable), and **Authorise** (enabled while pending requests or deny records exist). Core connectivity for local Vault Builder does not require a live Dashboard session. Core V31 is the tested wallet target.

Vault Builder selects a funded private-key source wallet with no active vault, a destination wallet containing a derivable public key (including public-descriptor watch wallets), an exact sats/vB fee and an unlock date/timezone. Address-only watch wallets are excluded. It explicitly sweeps every available input, receiving and change outputs included, to one vault output after subtracting the fee. Locked, immature, unsafe or otherwise unavailable funds cause an explanatory failure rather than a partial sweep. Calculate creates a dedicated public Core monitor; it does not sign or broadcast.

The locally bundled timezone boundary map and IANA list retain Dashboard's earlier design and attribution. The target is internally the selected date's local 07:00; the display instead gives the inverse 99% arrival-model time for the selected discrete height, and the most-likely time, both in the selected zone and UTC. The constant 600-second Poisson model is an estimate, not a 99% real-world guarantee. Height restrictions are enforced by Bitcoin consensus, not the date or the Agent. No block explorer is consulted.

Vault Builder creates `wsh(and_v(v:pk(KEY),after(HEIGHT)))` with one public key and no bypass path. The exact descriptor, RPC construction and PSBT are shown; policy and command sections have explanatory hover/focus highlighting. Core independently derives the address and the key is bound to the destination's public descriptor. A dedicated private-key-disabled `Wallaby Vault <hash>` wallet monitors it; the original key wallet signs later withdrawals. The Agent associates monitor balances with that key wallet and can roll a matured vault into a new one. A watch-only destination does not prove possession of its private key. Back up the original key wallet and vault descriptor: the public monitor is not a key backup.

**Send** opens a local passphrase dialog, signs the reviewed transaction through Core, promptly relocks encrypted wallets, checks mempool acceptance and broadcasts. **Send to Transaction Builder** signs but does not broadcast: it queues the signed PSBT for the future Dashboard Stage 2 receiver. Both paths queue public vault data for synchronisation. Existing Dashboard versions report unsupported exchange and queues remain local; this is not a claim of successful server sync. Read-only node RPC and existing tunnels continue to work.

Incoming public vault records and signing proposals can only be staged by the network service. Authorise reconstructs the policy or transaction locally; no Dashboard wallet/owner labels are trusted. Diagrams show inputs, receiving/change outputs, signing-wallet highlight and total fee using exact pipe notation, with addresses in the details. Authorise/Deny decisions are local. Denials persist by content hash and can be deleted to permit a new prompt. New pending requests open the local Authorise page if no Agent page is active. Passwords, Core cookies and private keys never enter the exchange.

The private `approvals.json` beside config.cfg stores public vault records, pending/denied/attempted decisions and queued public/signed exports. A signed PSBT is a spending authorisation and is protected with mode 0600. Reviews expire after ten minutes and are consumed once. Interrupted signing/import operations are marked attempted and never automatically replayed; inspect Core before deliberately retrying. Reconnecting transports only retries data delivery. This build retains one desktop-user permission domain; it is not isolation from a compromised local account, browser or Core cookie.

The Dashboard's former direct watch-wallet creation/import workflows now require its later approval-protocol update. No Dashboard code, server installation, real wallet or installed Agent was changed during this build.


## Build 6 regression coverage

Fresh tab, reload, localhost alias, token refresh, invalid-token/Origin/Host/Fetch Metadata rejection, partial autosaves, external config edits and upgrade-process refresh are tested. Form controls stay disabled until the saved configuration loads, avoiding the false empty/red state seen in Build 5. A live isolated test against the configured server authenticated one IPv6 SSH master, added both DDNS-GO and Dashboard forwards, received their web responses, then removed both forwards while the same master PID stayed connected. Existing installed services and saved config were not changed by that test.
