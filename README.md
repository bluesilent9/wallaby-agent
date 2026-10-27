# Wallaby Agent V2 — Development

Wallaby Agent manages per-user **IPv6 SSH tunnels** from a Linux desktop to your server. Its local HTML5 configuration page uses the Wallaby gear emblem and black sidebar.

**V2 Development build 3 is available for Ubuntu 26.04 LTS (amd64).** It adds independent Dashboard browser access and improved connection diagnostics. [Download the DEB](dist/wallaby-agent_2.0.0~dev3_amd64.deb) and verify [SHA256SUMS.txt](dist/SHA256SUMS.txt). All 42 automated tests and package inspection pass; live installation and startup testing remain pending. Stable has no application release.

## Three independent services

| Configuration switch | Local endpoint | Server destination | Requires Bitcoin Core? |
| --- | --- | --- | --- |
| DDNS-GO Administration | `http://[::1]:9876` | `[::1]:9876` | No |
| Wallaby Dashboard | `http://[::1]:38951` | `[::1]:38951` | No |
| Bitcoin Core Node Dashboard Interface | private ephemeral IPv6 loopback port | `[::1]:56443` | Yes |

**Wallaby Dashboard** supplies browser access. Switch it on, then use **Open Dashboard**. It can be enabled on a computer with no Bitcoin Core installation. The **Node Dashboard Interface** separately connects local Core RPC to the Dashboard's Agent listener; it does not provide browser access on port 38951. Enable either or both according to the computer's role.

All three switches default OFF for a new user. Upgrading an existing V1/V2 configuration preserves DDNS-GO and node choices and adds Dashboard access OFF. ON connects immediately, reconnects automatically and starts at the next user login. OFF stops and disables only that user's corresponding service. Jellyfin administration remains removed.

## Install and configure

Install `dist/wallaby-agent_2.0.0~dev3_amd64.deb`, verifying it against `dist/SHA256SUMS.txt` first:

```sh
sudo apt install ./wallaby-agent_2.0.0~dev3_amd64.deb
```

Installing a DEB uses normal administrator permission. Tunnels, settings and login startup subsequently run as your user, without sudo, system services or lingering. Open **Utilities → Wallaby Agent Configuration**, or run `wallaby-agent configure`.

1. Enter a server hostname/domain and click **Accept server**. IP literals are rejected; the server requires an AAAA record and a working IPv6 route.
2. Enter the **server SSH account**, which can differ from your desktop login. For example, desktop user `dave` on wallet-laptop uses server SSH account `wallet-laptop`. Verify the trusted server fingerprint and key authentication with `ssh -6 -F /dev/null USER@HOSTNAME` before enabling services. Encrypted keys must be unlocked in the desktop SSH agent. An optional absolute private-key path can be selected.
3. Click **Save settings** after editing SSH/RPC fields. Accepting a server name and toggling services do not save those fields. Unsaved edits now display a reminder. Saving connection changes restarts enabled services with those settings.
4. Enable the services needed on this computer. Dashboard browser access and DDNS-GO need no RPC cookie.
5. For the node interface, enable RPC (`server=1`) and restart Bitcoin Core. Agent checks owned Core processes, custom datadir/cookie options, Snap `~/snap/bitcoin-core/common/.bitcoin` and `current/.bitcoin`, then `~/.bitcoin`, with local config/settings hints. Bitcoin Core has no standard datadir environment variable. If needed, select the local `.cookie` with **Choose file**, then save settings. Only its path is saved, and its contents are reread for each RPC call.

## IPv6 and SSH forwarding

SSH always uses `ssh -6`; local listeners and remote forward destinations use IPv6 loopback `[::1]`. The tunnel command ignores `~/.ssh/config` forwarding directives, uses normal `known_hosts` and the SSH agent, and enforces host-key verification. It never stores an SSH password or accepts an unknown server key automatically. The configuration page and local Core RPC use IPv4 loopback independently of SSH.

Server forwarding rules must permit the exact destinations. A restricted key that uses all three services can permit `[::1]:9876`, `[::1]:38951` and `[::1]:56443`, subject to existing account restrictions. An IPv4-only `PermitOpen 127.0.0.1:PORT` rule does not permit `[::1]:PORT`. The installer does not alter server SSH rules or expose public listeners.

Remove an old Dashboard startup forward before enabling the Agent's Dashboard switch if it occupies port 38951. Identify the exact legacy unit and inspect its command before retiring it; do not disable the new `wallaby-agent-node.service` or a storage mount. See [LEGACY_DASHBOARD_TUNNEL.md](LEGACY_DASHBOARD_TUNNEL.md).

## Status and diagnostics

Red means off/disconnected, amber means connecting/checking, and green means connected. The switch records desired ON/OFF; the separate dot reports actual state. DDNS-GO and Dashboard browser tunnel green confirms authenticated SSH and its forwarding listener, not the application's HTTP health. Node green requires **SSH, healthy local Core RPC, and successful Dashboard registration/heartbeat**.

Reconnects use 15–300 second exponential backoff with jitter. SSH keepalives detect lost transports. A connected SSH transport suppresses server ping; without one, IPv6 ping runs immediately and every 60 seconds. ICMP blocking can make ping red while SSH works.

Errors distinguish SSH/DNS/IPv6 routing, server-key verification, key authentication, local port conflicts, denied server forwarding, a refused remote target, Core cookie discovery/readability/format, RPC authentication/port/warmup, and Dashboard HTTP/protocol/session failures. RPC/Dashboard errors are no longer overwritten with a generic SSH-key warning. The original failure remains visible during long retry waits and is shown as the previous failure during the next connection attempt.

```sh
journalctl --user -u wallaby-agent-dashboard.service -n 50 --no-pager
journalctl --user -u wallaby-agent-node.service -n 50 --no-pager
```

The journal includes classified stage/code and actionable messages. Raw SSH error lines are drained into bounded private memory for classification, not copied to the page or journal. Cookies, authentication headers, session tokens and raw RPC responses are not logged.

Configuration is `$XDG_CONFIG_HOME/wallaby-agent/config.cfg` (normally `~/.config/wallaby-agent/config.cfg`), mode 0600 in a private directory. Status and launch tokens use `$XDG_RUNTIME_DIR`. The UI binds only to `127.0.0.1`, requires its menu-launch token, checks Host/Origin and loads no third-party assets.

## Node protocol and RPC

Application V2 retains the **Dashboard V155 Agent v1 protocol on port 56443**. See [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md). Registration, independent heartbeats/long polling, acknowledgements and correlated results carry approved local Core RPC requests. Duplicate commands are not rerun; lost acknowledgements and RPC timeouts are not automatically replayed. Reconcile local state before repeating a write.

The Agent independently enforces the Dashboard method/public-descriptor policy, including watch-only wallet setup. Private exports, unlocking, signing, broadcasting and arbitrary methods are excluded. Monetary decimals travel exactly, without binary-float conversion. Core is contacted only on its configured local loopback port; the hub cannot choose credentials or filesystem paths. MAC/hostname values are identity hints; SSH supplies authentication. Exactly-once RPC is not guaranteed across arbitrary network failures.

## Upgrade and build

Close old configuration tabs before upgrading. V2 startup stops/disables the current user's retired V1 Jellyfin unit and removes its old startup link/status/config switch. DDNS-GO and node settings are preserved; Dashboard browser access starts OFF.

After installing build 3:

```sh
systemctl --user daemon-reload
systemctl --user try-restart wallaby-agent-monitor.service wallaby-agent-ddns.service wallaby-agent-dashboard.service wallaby-agent-node.service wallaby-agent-ui.service
wallaby-agent configure
```

This only restarts units already running. The new Dashboard unit is enabled when its switch is turned on. Package scripts do not control another logged-in user's session.

Source checks:

```sh
python3 -m unittest discover -s tests -v
```

Build using Ubuntu 26.04 with Python 3, `gcc` and `dpkg-dev`:

```sh
python3 packaging/build.py
```

No root or network is needed for building. The DEB includes a compiled native launcher and Python runtime sources; it is not a static standalone executable. Sources include the vendored embit public descriptor parser and its MIT license. RPC policy derives from Dashboard V155. See [VALIDATION.md](VALIDATION.md) for checks and remaining live tests.
