> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent V2 — Development Build 7

Ubuntu 26.04 LTS amd64 · Bitcoin Core 31 · **Development**, not a Stable release.

[Download the DEB](dist/wallaby-agent_2.0.0~dev7_amd64.deb) · [Checksums](dist/SHA256SUMS.txt) · [Validation](VALIDATION.md) · [Dashboard integration changes to pass on](DASHBOARD_PREVIEW_UPDATE.md)

Build 7 keeps Build 6’s live settings and authenticated shared IPv6 SSH connection. It adds unsigned vault composition, separately approved signature-return/broadcast operations and a direct wallet synchronisation workflow with signed initial previews.

**Dashboard V1 Build 9 now implements the signed initial preview relay and paired transfer scheduling required by Agent Build 7, alongside unsigned vault composition, partial signing and separate broadcast approval.** Use [Dashboard Build 9](https://github.com/bluesilent9/wallaby-dashboard/tree/Development). Actual Agent sender/receiver preview interoperability is tested; physical two-laptop SSH/firewall/user-approval checks remain live deployment work. Build 8 still lacks the signed-preview extension.

## Build 6 and Build 7 downloads and source

**These builds are published on the [Development branch](https://github.com/bluesilent9/wallaby-agent/tree/Development). GitHub opens Stable by default; select Development to see the current source and installers.** Neither build is a Stable release.

| Build | Ubuntu 26.04 LTS amd64 installer | Matching source |
| --- | --- | --- |
| **V2 Development Build 7 — latest** | [Download Build 7 DEB](https://github.com/bluesilent9/wallaby-agent/raw/refs/heads/Development/dist/wallaby-agent_2.0.0~dev7_amd64.deb) | [Browse Build 7 source](https://github.com/bluesilent9/wallaby-agent/tree/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0) · [Download source ZIP](https://github.com/bluesilent9/wallaby-agent/archive/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0.zip) |
| V2 Development Build 6 | [Download Build 6 DEB](https://github.com/bluesilent9/wallaby-agent/raw/refs/heads/Development/dist/wallaby-agent_2.0.0~dev6_amd64.deb) | [Browse Build 6 source](https://github.com/bluesilent9/wallaby-agent/tree/b2b44e7983940e7a758969e4244df5d2e6f4c6dc) · [Download source ZIP](https://github.com/bluesilent9/wallaby-agent/archive/b2b44e7983940e7a758969e4244df5d2e6f4c6dc.zip) |

Verify installers against [SHA256SUMS.txt](https://github.com/bluesilent9/wallaby-agent/blob/Development/dist/SHA256SUMS.txt). Both installers are in [Development/dist](https://github.com/bluesilent9/wallaby-agent/tree/Development/dist). The repository root contains the current Build 7 source; Build 6's matching source is retained in the linked Git history.

Build 6 introduced live settings and one authenticated IPv6 SSH connection shared by the services, replacing ping checks. Build 7 adds unsigned vault proposals, separately authorised signing/broadcast and verified wallet-sync previews. **Build 7 wallet-file synchronisation is supported by Dashboard V1 Build 9; the shared contract is in [DASHBOARD_PREVIEW_UPDATE.md](DASHBOARD_PREVIEW_UPDATE.md).** See [validation and remaining live tests](VALIDATION.md).

## Services and local settings

The black sidebar has **Services**, **Vault Builder**, **Synchronisation** and **Authorise**. Services remains available. Vault Builder needs a local Core connection; Synchronisation is enabled only for an active paired request or its brief success screen. Authorise holds local transaction/public-vault approvals and persistent deny records. New requests switch the current Agent page or open its local page in the default browser if no Agent page is active.

| Service switch | Local browser endpoint | Server destination | Core required |
| --- | --- | --- | --- |
| DDNS-GO Administration | `http://[::1]:9876` | `[::1]:9876` | No |
| Wallaby Dashboard | `http://[::1]:38951` | `[::1]:38951` | No |
| Bitcoin Core Node Dashboard Interface | private ephemeral IPv6 loopback port | `[::1]:56443` | Yes |

All switches start **OFF** for a new user. Upgrades preserve selected DDNS-GO, Dashboard and node services; retired Jellyfin administration remains removed. Enabled services reconnect with bounded backoff and start at desktop login as that user. Dashboard browser access and node reporting are independent switches.

Enter the server hostname/domain and the **server’s SSH account**, not necessarily your desktop username. IP literals are rejected for this server field; all SSH uses IPv6. Verify its SSH host fingerprint and set up passwordless SSH beforehand (`ssh -6 -F /dev/null USER@HOSTNAME`). Explicit private-key paths are optional; otherwise desktop SSH agent/default keys are used.

Valid edits save automatically after a short debounce into `~/.config/wallaby-agent/config.cfg`, or its XDG equivalent. External file edits appear on the page. There is no Save button. **Connect** immediately retries saved settings. The server dot reflects an authenticated SSH master, not ping. Services add/cancel IPv6 loopback forwards on that same login without reconnecting it. Red/amber/green indicate disconnected/connecting/connected; the node service additionally requires local RPC and Dashboard registration. There are no ping checks.

Enable Core RPC (`server=1`) and restart Core. Cookie discovery checks owned Core processes/custom datadirs, Snap data roots and `~/.bitcoin`; use Choose file if necessary. Core has no standard datadir environment variable. Cookie contents stay local and are reread for each RPC call. Local page APIs require the private session token and strict loopback Host/Origin/Fetch Metadata checks.

## Vault Builder and signing

Select a funded private-key-enabled source with no active vault, a destination with public spending keys (including public descriptor watch wallets), a sats/vB fee, timezone and date. Address-only watch wallets are excluded. The Agent constructs `wsh(and_v(v:pk(KEY),after(HEIGHT)))`, a mandatory-height single-key vault with no bypass. Every available receiving/change input is explicitly selected; locked, immature, unsafe or unavailable funds prevent an incomplete sweep. A matured vault can be rolled over. Core independently checks the address and key derivation and creates a public monitor. Preserve the original key wallet and public vault descriptor backups.

The timezone map, local/UTC modelled 99% arrival time and most-likely time remain. The constant ten-minute Poisson model is an estimate, not a guaranteed calendar unlock; Bitcoin enforces height. Review the exact descriptor, RPC construction, PSBT and locally reconstructed transaction diagram in pipe notation.

- **Send** locally unlocks/signs through Core, relocks, checks mempool policy and broadcasts after user approval.
- **Send to Transaction Builder** now exports an **unsigned** PSBT with public signing metadata. It does not unlock, sign or broadcast and no longer asks for a password. Dashboard Stage 2 preserves that fixed component and appends ordinary transactions before signing.
- **Incoming signing** independently verifies all previous outputs and the complete final transaction. Local vault exports cannot be omitted or changed in a signing request. Fixed inputs, sequences, vault output, amounts, version, locktime and fee are checked, independently of disabled Dashboard cards. Locally approved signatures return through `partial_sign_result`; no broadcast occurs. A separate locally reviewed broadcast request independently finalises and checks TXID before broadcasting.
- Direct Dashboard RPC remains a positive allowlist of **public read-only** calls. It cannot unlock/sign/export keys, create/import/load/backup wallets, change labels/addresses or broadcast. Network proposals never authorise these operations; fixed local workflows require local approval. Legacy immediate-broadcast `sign_psbt` requests are rejected. Old signed exports are retained privately under `legacy_exports`, not uploaded into the new unsigned proposal contract.

## Initial wallet verification and direct synchronisation

The sender queries its own Core for public descriptors and currently unspent funded receiving/change outputs, including locked/immature outputs visible in wallet history. Amounts, receipt times and receipt heights come from that local node. It signs a frozen initial preview with a dedicated local Ed25519 **Agent identity**, not a Bitcoin signing key. The updated Dashboard relays public data/signature only. The receiver independently checks the signature, wallet, challenge, peers and expiry before displaying it.

Users compare the preview’s complete SHA256 code directly between Agent screens. The receiving user must enter the **sender Agent identity fingerprint copied from the sender itself**, outside Dashboard. The screen supplies public `bitcoin-cli gettxout` checks. A fingerprint supplied only by Dashboard is not trusted; independent comparison is necessary to detect substitution. Preview lifetime is 15 minutes; changed funds or peer addresses require a fresh reviewed request.

Receiving **Authorise** opens a private temporary Agent receiving endpoint, not an automatic system SSH configuration change. On the sending Agent, **Send** asks for the receiving computer’s local username/login password and its **system SSH host fingerprint**, which must be compared with the receiving screen. This is separate from the sender’s preview identity fingerprint. Login passwords are held only in memory and an owner-only one-shot askpass socket, never saved or sent through Dashboard. The live direct manifest is compared with the initial approved preview; the receiver checks that live manifest before accepting the file.

Only an already encrypted and locked private-key wallet can be transferred; an unencrypted private wallet is refused. Core makes a consistent backup. The file travels directly over IPv6 SSH on port 22 and is staged privately beside the Core cookie/data root for Snap compatibility. Maximum wallet file size is 256 MiB. Receiver restores under a new generated `Wallaby Sync <id>` name, never overwrites an existing wallet, checks descriptors, private-key capability, encryption, completed scan and the reported funded outputs, and confirms loaded status directly to the sender. Both display **Success!** for about five seconds, close their transfer connection, return to Services and report public completion. Restored names may differ; public descriptors, not names, establish wallet identity.

Only one wallet is active per Agent. Initial batches are sorted alphabetically. While active, new Dashboard RPC and approvals are rejected; heartbeats/results continue. The sole inbound exception fills the same frozen request’s signed initial preview. Cancel/deny records persist. Attempted or uncertain restoration/signing is never replayed automatically: inspect Core before deliberately starting a fresh request. Public preview/outbox records contain no wallet file, passphrase or private key.

## SSH, firewall and modem help

Ubuntu Desktop/flavours do not include an SSH server by default. The receiving screen checks installation and a local IPv6 port-22 listener and offers copyable installation/start commands. Installing OpenSSH can enable a general system SSH listener; review its host authentication and IPv6 configuration. The Agent itself does not edit the system daemon, enable IPv4 listening, change your modem, or open firewall rules. Closing a transfer stops its Agent receiving endpoint/direct connection; an existing system SSH service remains under your control.

The optional **Check receiving firewall** button asks for normal OS administrator approval to read `ufw status verbose`; it does not change rules. Unknown/complex/localised rule output stays unverified. Commands show how to allow this **specific sender IPv6** into the receiver’s TCP 22 and remove that rule afterwards. IPv6 support in UFW must be enabled. Other firewall software is not checked.

The receiver needs **incoming IPv6 TCP 22**; sender normally needs **outgoing TCP 22**. If the receiver’s local UFW check permits it but the sender cannot connect, the sender/receiver help identifies the receiving modem’s IPv6 firewall as a suspected cause, not a proven one. Allow an inbound modem exception to the receiver, preferably scoped to the sender. IPv6 normally uses a firewall exception rather than IPv4 NAT port forwarding. VPNs, stale/rotated IPv6 addresses and routing failures can also explain failure. The Agent cannot reliably inspect modem settings. The page shows the current kernel-selected route: a direct physical interface route keeps the wallet file on that LAN, even using public IPv6 addresses. Router/virtual/VPN routes are labelled cautiously. There is no separate LAN button. Public preview/coordination still passes through Dashboard. For a direct LAN route, connection help highlights receiving SSH/UFW and Wi-Fi client isolation rather than Internet port forwarding. Sender errors distinguish unreachable SSH, host-key mismatch, wrong login/password, missing receiving authorisation, preview mismatch and failed/uncertain Core restoration.

## Install, upgrade and build

```sh
sudo apt install ./wallaby-agent_2.0.0~dev7_amd64.deb
wallaby-agent configure
```

Open **Utilities → Wallaby Agent Configuration**. Opening it detects older monitor/UI processes and refreshes the saved enabled user services once. Close old browser tabs. Package scripts do not start tunnels or edit another logged-in user’s session. Installing the DEB needs normal administrator permission; routine Agent services remain per-user. Incoming SSH prerequisites and an optional UFW read are separate OS operations, explicitly described on screen.

```sh
python3 -m unittest discover -s tests -v
python3 packaging/build.py
```

Build on Ubuntu 26.04 using Python 3.11+, gcc and dpkg-dev, without root. Tests use isolated official Core 31 regtest data/coins; set `WALLABY_TEST_BITCOIND` to its path. The DEB contains a compiled native launcher, auditable Python sources, local web assets/timezone data and vendored MIT-licensed embit. It is not a static executable. Historical DEBs/checksums remain in `dist`; use Build 7 for this protocol. See [APPROVAL_PROTOCOL.md](APPROVAL_PROTOCOL.md) and [DASHBOARD_PREVIEW_UPDATE.md](DASHBOARD_PREVIEW_UPDATE.md) for the exact server handoff and remaining live-integration requirements.
