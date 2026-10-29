> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent V2 — Development Build 8

Ubuntu 26.04 LTS amd64 · Bitcoin Core 31 · **Development**, not a Stable release.

[Download Build 8 DEB](dist/wallaby-agent_2.0.0~dev8_amd64.deb) · [Checksums](dist/SHA256SUMS.txt) · [Validation](VALIDATION.md) · [Dashboard changes to pass on](DASHBOARD_BUILD8_UPDATE.md)

Build 8 adds a locally selectable multi-wallet synchronisation list, genuine public-only transfers (including labelled fixed-address Extinct wallets), vault monitoring records, and locally authorised history recovery. **Dashboard code is unchanged.** Dashboard V1 Build 9 supports the older Build 7 single-wallet preview contract; the new queue, version-2 previews and recovery result states need the changes documented in [DASHBOARD_BUILD8_UPDATE.md](DASHBOARD_BUILD8_UPDATE.md).

## Development downloads

GitHub opens Stable by default. Select [Development](https://github.com/bluesilent9/wallaby-agent/tree/Development) for current source and installers.

| Build | Ubuntu 26.04 LTS amd64 installer | Source |
| --- | --- | --- |
| **V2 Development Build 8 — latest** | [Build 8 DEB](dist/wallaby-agent_2.0.0~dev8_amd64.deb) | Current Development source |
| V2 Development Build 7 | [Build 7 DEB](dist/wallaby-agent_2.0.0~dev7_amd64.deb) | [Matching source](https://github.com/bluesilent9/wallaby-agent/tree/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0) · [ZIP](https://github.com/bluesilent9/wallaby-agent/archive/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0.zip) |
| V2 Development Build 6 | [Build 6 DEB](dist/wallaby-agent_2.0.0~dev6_amd64.deb) | [Matching source](https://github.com/bluesilent9/wallaby-agent/tree/b2b44e7983940e7a758969e4244df5d2e6f4c6dc) · [ZIP](https://github.com/bluesilent9/wallaby-agent/archive/b2b44e7983940e7a758969e4244df5d2e6f4c6dc.zip) |

These are development builds. Historical installers and their checksums remain available.

## Services and settings

The black sidebar provides **Services**, **Vault Builder**, **Synchronisation** and **Authorise**. Synchronisation is available when local Core is connected, a wallet request exists, or recovery is running, so users can inspect This Node without a pending transfer. Synchronisation requests and missing history **never open a browser or change the current page**. Open Utilities → Wallaby Agent Configuration yourself. Existing transaction-signing/standalone vault authorisation notifications retain their separate behaviour.

| Service | Local endpoint | Server destination | Core required |
| --- | --- | --- | --- |
| DDNS-GO Administration | `http://[::1]:9876` | `[::1]:9876` | No |
| Wallaby Dashboard | `http://[::1]:38951` | `[::1]:38951` | No |
| Bitcoin Core Node Dashboard Interface | private ephemeral IPv6 loopback port | `[::1]:56443` | Yes |

Services start OFF for a new user. Upgrades retain saved choices. Enabled services run at user login with bounded reconnection delays; Jellyfin administration remains removed. Enter the server hostname and its SSH account (which may differ from your desktop username). Server IP literals are refused. **Connect** authenticates a strict-host-key-checked IPv6 OpenSSH master; services add/remove forwards on that connection. There are no ping checks.

Settings save as edited to `~/.config/wallaby-agent/config.cfg` or the XDG equivalent and reload externally saved changes. There is no Save button. Set up passwordless server SSH and trust its host key first. Local Core requires RPC enabled. Cookie discovery supports owned processes, custom datadirs, Snap and standard paths; only the cookie path is saved. Cookies rotate and are reread on every call. The browser API uses strict loopback Host, Origin, Fetch Metadata and session-token checks.

## Select and review wallet synchronisation

The list contains **Send**, **Sending Agent**, **Receiving Agent**, **Wallet Name** and **Watch Only**. Rows start unselected. A source without private keys is always watch-only and its mode cannot be changed. Sender names, public descriptors, funded receiving/change addresses, amounts and receipt times/heights are obtained from the sender's own Core. Receiver display names are explicitly labelled as Dashboard-supplied; names never establish wallet identity. Click a row for its review. All participating computer names and IPv6 identities appear below the list.

Public-key descriptor wallets and fixed `addr()` watch wallets are supported. Fixed-address subsets can be identified inside a larger private-key-disabled archive. Addresses and their exact Core labels—including `Wallet name | LOST:DD/MM/YYYY HH:MM:SS UTC` Extinct records—are signed, reviewed and recreated. Zero-balance labelled addresses are included. Source change-address status is preserved; it is not inferred from an imported wallet's initially empty address book. This does not make address-only wallets signing sources or Vault Builder destinations.

Associated public vault policies, block-height conditions, derivation references and monitor history accompany the transfer. Core verifies the policy/key relationship and creates the receiving monitor after local approval. No bypass spending policy is introduced.

Each version-2 preview is signed by a dedicated Ed25519 Agent identity, with the wallet, public metadata, peers, transfer challenge and 15-minute expiry bound together. Independently compare the complete preview hash and sender Agent fingerprint on the two computers. Dashboard is a courier, not a trusted key authority. The live SSH manifest must match the signed public snapshot, including descriptor metadata, labels and vaults; changed funds or metadata require a fresh request.

Dashboard owns list membership. Agents have **no clear, delete or deny control for sync rows**. Uncheck a row to leave it pending. Updated authoritative snapshots withdraw requests when their suggesting sender goes offline. Already attempted operations retain an audit/history record; withdrawal never deletes a restored wallet or staged encrypted file.

## Direct transfers

On receivers, authorise the selected incoming rows after independently comparing each sender fingerprint. On senders, enter each receiving computer's local login username/password and independently verified **system SSH host fingerprint**. These are separate from Agent preview keys and Bitcoin wallet passphrases. Credentials stay in memory and an owner-only one-shot askpass socket; they never reach Dashboard.

Wallets transfer one at a time in alphabetical order across the selected sending rows. Each selected receiver can accept its approved rows from several sending computers. Incoming and outgoing batches are separate locally initiated phases; complete or end receiving authorisation before starting a sending batch on that Agent. Ending authorisation closes the temporary receiving endpoint but leaves all pending requests in the list.

**Watch Only sends public data only.** The receiver creates a blank descriptor wallet with private keys disabled, imports approved public descriptors and restores labels. It rejects a wallet-file payload in this mode. Either peer can require watch-only; the sender must respect the receiving choice before any private file is created or sent.

Full transfer requires an encrypted, locked private-key wallet. Core makes one consistent temporary transfer file; it is sent directly over authenticated IPv6 SSH, never through Dashboard, and removed from sending staging afterward. This is the transport payload, not an additional retained backup. No automatic pre-recovery wallet/configuration backups are created. The receiving Agent never overwrites a wallet and verifies descriptors, encryption, key capability, labels, vault policies and history. Maximum encrypted transfer file size is 256 MiB.

SSH fingerprints are checked before credentials are sent. Ubuntu Desktop normally requires installing OpenSSH server separately on the receiver; the page provides checks and copyable installation/start commands. Optional administrator-approved UFW inspection is read-only. Displayed firewall rules are scoped to the sender's IPv6. The receiver needs inbound TCP 22; senders normally need outbound TCP 22. A modem IPv6 firewall block is only suspected after local checks; the Agent cannot inspect modems reliably. Direct physical LAN routes use the LAN automatically. Routed/VPN paths are labelled cautiously. The Agent does not edit system SSH, enable IPv4, change firewall rules or configure the modem.

Both sides show Success only after a matching wallet has been loaded and verified. If old blocks are missing, the encrypted file or public wallet is retained privately and the result is **recovery_required**, not success. The receiver later reports completion after locally approved recovery; Dashboard must relay that outcome to the sender. A transfer with an uncertain import/restore outcome is never replayed automatically.

## This Node and history recovery

The card shows **Synchronised** (green), **Requires Rescan** (amber), or **Requires Blockchain Download** (red), based on local Core state and approved history requirements. Its refresh button is disabled when green, unavailable or already running. Offline RPC is explicitly described as unassessed, not proof that a new download is needed.

Click refresh to review a local recovery plan, then Authorise. Existing downloads are monitored instead of restarted. Available historical blocks are rescanned locally. If required blocks were pruned, the Agent cleanly shuts down Core and restarts it with a one-shot `-reindex=1`, **preserving its existing pruning setting and limit throughout**. It never adds a pruning override or edits pruning configuration.

Core network activity is briefly paused during preparation. The Agent restores staged encrypted wallets, registers the original public descriptor history timestamps, loads any other previously loaded wallets and installs vault monitors **before historical blocks are downloaded**. It then resumes network activity. Core records wallet/vault transactions as blocks arrive and can discard old blocks according to its existing pruning setting. Wallet history remains in the wallets after those blocks are pruned; an archival copy of the chain is not required. Completion requires the recovered tip, processed wallet/monitor histories and independent transaction/label/policy checks. If Core network activity was originally disabled, it is disabled again after successful recovery.

Native and bitcoin-core Snap launchers are identified locally by the owned Core process holding the selected data-directory lock. Unknown launchers or unsupported service-managed instances are refused before shutdown with manual guidance. Restarted Core runs in a separate user service so Agent lifecycle does not kill it. All work runs as the user, without root, automatic backup copies, manual block-directory deletion or permanent recovery-option edits.

If Agent restarts during preparation, network activity remains paused until the user reviews a fresh local plan. Already attempted wallet restorations are reconciled against loaded wallets rather than blindly repeated. After preparation, Core can continue its existing pruned download independently. The Agent never starts another reindex just because a correctly registered wallet's original blocks have since been pruned. Physical desktop/Snap/systemd operation and a full Internet mainnet download still require deployment testing.

## Vault Builder, authorisation and RPC restrictions

Vault Builder retains the whole-wallet CLTV vault workflow, timezone map and local/UTC modelled 99% block-arrival estimates. Bitcoin enforces the height, not the estimated date. Send signs/broadcasts only after local review. Send to Transaction Builder exports an **unsigned** PSBT; later complete transactions must preserve fixed vault inputs, output, sequences, locktime and fee. The Agent enforces these independently of Dashboard's disabled diagram cards.

Incoming signing reconstructs the transaction from local Core and PSBT data. Approved partial signatures return without broadcasting; broadcast has a separate local review. Direct Dashboard RPC is a positive allowlist of public read-only calls. It cannot unlock/sign/export private keys, create/import/load/backup wallets, change labels or broadcast. Transfers and recovery use fixed locally approved workflows, never remote RPC names, paths or commands. Ordinary Dashboard RPC is temporarily refused during authorised transfer/recovery.

## Install and build

```sh
sudo apt install ./wallaby-agent_2.0.0~dev8_amd64.deb
wallaby-agent configure
```

Installation needs normal administrator permission; enabled Agent services run as the desktop user. Open Utilities → Wallaby Agent Configuration and close older browser tabs.

```sh
python3 -m unittest discover -s tests -v
python3 packaging/build.py
```

Build with Python 3.11+, gcc and dpkg-dev on Ubuntu 26.04; no root is needed. Set `WALLABY_TEST_BITCOIND` to an official Core 31 bitcoind for isolated regtest tests. The DEB contains a compiled native launcher, auditable Python sources, local HTML/CSS/JS/timezone data and vendored MIT embit. See [VALIDATION.md](VALIDATION.md), [DASHBOARD_BUILD8_UPDATE.md](DASHBOARD_BUILD8_UPDATE.md) and the older [DASHBOARD_PREVIEW_UPDATE.md](DASHBOARD_PREVIEW_UPDATE.md).

