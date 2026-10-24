# Wallaby Agent V1 — Development

Wallaby Agent connects a Linux desktop to the family's server with **IPv6-only SSH tunnels**. The HTML5 configuration page has the Wallaby gear emblem and a black sidebar. There is one workspace label rather than a redundant navigation button.

**This is V1 Development. Stable contains no released application yet.** Source and the built Ubuntu 26.04 LTS amd64 installer are in this branch. The DEB contains a compiled native launcher and the Python service runtime; it is not a self-contained static executable.

## Install and configure

Download `dist/wallaby-agent_1.0.0~dev1_amd64.deb`, then:

```sh
sudo apt install ./wallaby-agent_1.0.0~dev1_amd64.deb
```

Package installation uses the usual administrator permission. Configuration, toggles, tunnels, and login startup subsequently use **your user account**, with no sudo, system services, or lingering required. Open **Utilities → Wallaby Agent Configuration** (or Settings on desktops that group applications differently). `wallaby-agent configure` opens the same page.

1. Enter and accept your server hostname/domain. IP literals are rejected. An AAAA record and working IPv6 route are required.
2. Enter your SSH username and optional private-key path. Before enabling a tunnel, use a terminal to verify the server's fingerprint against a trusted source and establish key authentication: `ssh -6 -p 22 USER@HOSTNAME`. Encrypted keys should be unlocked in your desktop's SSH agent. Agent never accepts an unverified host key automatically, stores an SSH password, or opens password prompts in the background. Its explicit forwarding configuration ignores `~/.ssh/config`; it uses your normal `known_hosts` and SSH agent.
3. Save settings and enable only the services you want. All three switches start OFF on a new user account. ON persists across reboot and starts at your next login. OFF stops and disables that user's service immediately.
4. For the node service, enable RPC (`server=1`) in Bitcoin Core and restart Core. Agent searches owned Core processes (`-datadir`/`-rpccookiefile`), Snap `~/snap/bitcoin-core/common/.bitcoin` and `current/.bitcoin`, and `~/.bitcoin`, including local config/settings datadir hints. Bitcoin Core has no standard datadir environment variable; invented environment variables are not used. A native **Choose file** dialog selects `.cookie` if discovery fails. Save settings after selecting it. Non-mainnet cookies/custom RPC ports can be selected explicitly.

## Services and status

| Service | Local endpoint | Server destination |
| --- | --- | --- |
| Jellyfin SSH Administration | `http://127.0.0.1:8096` | server [::1]:8096 |
| DDNS-GO Administration | `http://127.0.0.1:9876` | server [::1]:9876 |
| Bitcoin Core Node Dashboard Interface | private ephemeral loopback port | server [::1]:56443 |

Every SSH transport uses `ssh -6`, and every remote forwarded destination is IPv6 loopback `[::1]`. Local HTTP and RPC listeners use loopback IPv4 deliberately; this does not permit IPv4 SSH connections. Tunnel listeners never bind all network interfaces. Your SSH server must permit these exact forward destinations. For example, a dedicated SSH key can use `restrict,port-forwarding,permitopen="[::1]:8096",permitopen="[::1]:9876",permitopen="[::1]:56443"` in `authorized_keys`, subject to your existing server account restrictions. The server must listen on IPv6 loopback and permit these exact IPv6 destinations. Existing SSH rules permitting only `127.0.0.1` must be updated to `[::1]` by the server administrator; an IPv4-only rule does not authorize an IPv6 destination. No server configuration is modified by the installer.

Red means off/disconnected, amber connecting/checking, green connected. A toggle's colour records the requested ON/OFF setting; the separate dot records actual connection state. Tunnel green confirms an authenticated OpenSSH transport with its forwarding listener installed; it does not promise the Jellyfin/DDNS application behind it is healthy. Node green requires **SSH + successful local Core RPC + Dashboard registration/heartbeat**. A failure produces red before retry, then amber during the next attempt. Reconnects use 15–300 second exponential backoff with jitter. SSH keepalives detect dead transports. When any SSH tunnel exists, server ping stops. Without tunnels, `ping -6` checks immediately and every 60 seconds, including after a failed check. Servers blocking ICMP can show red while SSH still works.

Desired settings: `$XDG_CONFIG_HOME/wallaby-agent/config.cfg` (normally `~/.config/wallaby-agent/config.cfg`), mode 0600 in a 0700 directory. Cookie location is saved, never cookie contents. Runtime tokens and status use a private directory under `$XDG_RUNTIME_DIR`. The config page binds only `127.0.0.1`, uses a short-lived launch token, checks Host/Origin and uses no third-party assets. Browser access without the menu-launch token is rejected.

## Dashboard compatibility and RPC

Implements the Dashboard V155 Agent v1 contract on **56443**; see [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md). Register → heartbeat + long poll → acknowledge → local JSON-RPC → correlated result. Heartbeats continue independently during slow Core operations. Credentials remain local and the cookie is reread for every call so Core restarts work. Duplicate commands are not executed again. Acknowledgement loss and RPC timeouts are not automatically replayed. Reconcile actual Core state before manually repeating a write.

The Agent independently uses the Dashboard's method and public descriptor policy, including watch-only wallet creation/import. Signing, unlocking, private exports, broadcasting and arbitrary RPC methods are excluded. Decimal monetary values travel as exact decimal strings, with integer counts unchanged. Core always uses the locally configured loopback port; the hub cannot select a host, credentials or filesystem path. The self-reported adapter MAC and hostname are identity hints; SSH provides authentication. No software can make RPC exactly-once across arbitrary network failures.

## Build and test

On Ubuntu 26.04 with `gcc`, `dpkg-dev` and Python 3:

```sh
python3 -m unittest discover -s tests -v
python3 packaging/build.py
```

Build needs no root or network. Sources include the vendored embit public descriptor parser and its MIT license. `src/agent_rpc.py` and `descriptor_policy.py` derive from the companion Dashboard V155 source. Build output is `dist/*.deb`.

Inspect: `systemctl --user status wallaby-agent-{monitor,jellyfin,ddns,node}.service` and `journalctl --user -u wallaby-agent-node.service`. To stop all enabled connections before uninstalling: switch them off, then `systemctl --user disable --now wallaby-agent-monitor.service; systemctl --user stop wallaby-agent-ui.service`. Uninstall with `sudo apt remove wallaby-agent`. Your private configuration is retained. Users already logged in should stop their own services before removal; package scripts do not manipulate another user's session.

Development validation uses mock SSH/Core/hub endpoints and the real Dashboard protocol. Live server authentication, your Snap installation, and reconnects on your network still require a check on the target computer. This version has not been promoted to Stable.

Reference defaults and discovery: [Jellyfin networking](https://jellyfin.org/docs/general/post-install/networking/), [DDNS-GO](https://github.com/jeessy2/ddns-go), [Bitcoin Core file locations](https://github.com/bitcoin/bitcoin/blob/master/doc/files.md), [official Core Snap packaging](https://github.com/bitcoin-core/packaging/blob/main/snap/snapcraft.yaml).
