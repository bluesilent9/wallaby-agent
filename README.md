> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent V2 — Development Build 14

Ubuntu 26.04 LTS amd64 · Bitcoin Core 31 · **Development**, not a Stable release.

[Build 14 DEB](dist/wallaby-agent_2.0.0~dev14_amd64.deb) · [Checksums](dist/SHA256SUMS.txt) · [Validation](VALIDATION.md) · [Build 12 integration notes](DASHBOARD_BUILD12_UPDATE.md)

Build 14 separates missing-component instructions from the install command, which appears in a selectable code box with a **Copy command** button and copy confirmation. Command generation uses only the fixed optional-package list; it never includes cookie contents or passwords. Protected-worker failures now preserve their original local Core/Dashboard stage, category and safe explanation instead of being mislabelled as incompatible Dashboard data. Node protocol failures also distinguish invalid JSON endpoints, command fields, identifiers, deadlines and refused read-only RPC scope without displaying raw server data. Tunnel-only installation remains supported.

An Agent diagnostic bug has been confirmed and fixed: its protected-node proxy converted every worker failure into ValueError and the runtime then labelled that as invalid Dashboard data. The underlying cause of the reported node disconnect has **not been reproduced** in isolated registration/poll/ack/result tests against Dashboard Build 13. The supplied Dashboard log records a server-side `NoneType` error; the Dashboard chat is correcting an absent-version exception separately. That exception alone does not establish the cause of the Agent disconnect. See [connection investigation](DASHBOARD_BUILD14_DIAGNOSTICS.md). No Dashboard source is modified here.

Build 13 fixes tunnel-only installation on Ubuntu 26.04. The unavailable legacy `policykit-1` dependency is removed. Bitcoin Core, PyQt6 WebEngine, optical writing tools and administrator-authorisation tools are **optional** and are not automatically installed with the Agent. DDNS-GO and Dashboard browser-access tunnels work without Bitcoin Core. A missing Bitcoin prerequisite leaves the node switch off and greyed; clicking it explains what is missing without enabling its service or changing other tunnels. Existing node services report prerequisite problems before creating their tunnel; login does not launch an unavailable Bitcoin workspace.

Build 12 incorporates the Agent follow-up for **Dashboard V1 Build 13**. Transaction diagrams show the verified **Total network fee**, with a separate local acknowledgement for unusually high fees. Native prompts identify the exact Core signing wallet and action; disc-backup and computer-login passwords are explicitly distinguished. Wallet creation verifies one full fingerprint per distinct producing Agent, binding all its roles to that identity. Retired local Vault Builder generation helpers are removed; current wallet-policy creation, archive restoration, vault checks and signing remain.

Disc Operations now supports **1–99 separate discs** and reported numeric burn speeds. Defaults are **one disc** and **slowest supported speed**. Each disc is still filled with redundant encrypted recovery copies, then completely read back. Subsequent discs reuse one protected-RAM encrypted package and require a fresh local blank-disc confirmation. The full requested set must be verified before its completion proof is sent. Failed writes and uncertain completion are never repeated automatically. See [disc format](DISC_FORMAT.md).

Build 11 makes the **wallet synchronisation Denial list persistent on the Agent**. Disable an incoming wallet policy once; it remains disabled after closing the protected workspace or rebooting. Enable it on Authorise to remove its entry and allow the current or next sync offer. Disabled entries never count as unfinished work or light notification dots. One-off declined signing/setup requests remain session-only; there is no persistent request history.

The Agent owns this list. Dashboard cannot restore, clear or override it. Dashboard code does not need changing for local enforcement or reboot persistence. A small optional [permission-status query](DASHBOARD_BUILD11_UPDATE.md) lets Dashboard display “disabled on this Agent” and suppress its own missing-wallet alerts; it creates no second control list. This supersedes Build 10's proposal for server-retained preference snapshots.

Disc Operations, archived-key signing, redundant optical backups, BIP-322 messages and the multi-request Authorise queue remain. Dashboard V1 Build 13 already supports wallet setup, completion proofs and restored-cosigner transaction routing. Remote RPC remains public/read-only; local wallet/signing/broadcast approval boundaries are unchanged. No Dashboard code is changed in this build.

## Install and start

Install the DEB with your normal package manager. Mandatory runtime dependencies are Python 3, OpenSSH client, systemd, xdg-utils, iproute2, Python cryptography and util-linux. All connection services remain off on a fresh install. Existing saved service choices are retained on upgrade.

**Tunnel-only computer:** no Bitcoin, Qt WebEngine, xorriso or polkit installation is needed. Ignore the unavailable node-interface explanation and use DDNS-GO or Dashboard normally.

**Bitcoin computer:** install optional protected-desktop components with `sudo apt install pkexec polkitd python3-pyqt6 python3-pyqt6.qtwebengine kdialog` (an existing zenity can replace kdialog). Qt WebEngine is in Ubuntu Universe; if apt cannot find it, check that repository and the machine’s package configuration. Install Bitcoin Core separately using your chosen supported distribution, including Snap, enable its RPC server and choose/discover its readable cookie. There is no dependency or recommendation on an apt package named `bitcoind`. Prerequisite detection uses the configured cookie and optional viewer/dialogue tools; actual Core RPC and Dashboard readiness are checked when connecting. An installed but stopped/misconfigured Core is not declared connected.

**Optical operations:** additionally install `xorriso` when needed: `sudo apt install xorriso`. Its absence produces a specific message when media is checked and does not block node reporting or SSH tunnels.

On upgrade, finish sensitive work, switch off the node interface and close the existing protected workspace before restarting it with this build. The installer does not forcibly terminate a running RAM signing/setup session. A reboot after finishing that work also starts the new installed code.

Open **Utilities → Wallaby Agent Configuration**. **Services** uses the ordinary HTML5 configuration page. Hostname, SSH username/port/key and enabled services save live. A hostname/domain is required; literal IP addresses are refused. Connect authenticates an IPv6-only shared SSH master, never pings. Green means authenticated connection, amber means connecting and red means failed/disconnected. DDNS-GO, Dashboard browser access and the node interface share its forwarding connection. Tunnels remain user services and start at login when enabled.

For Bitcoin functions, click **Start protected workspace** on Services. A one-time native administrator authorisation establishes the non-swapping RAM mount. Later logins can start only that user's fixed unprivileged protected worker without repeating the administrator prompt. If the node interface is enabled, login bootstrap starts that worker automatically. This does not grant root to wallet operations or enable other users' services.

Bitcoin pages open in a dedicated protected HTML5 window. The ordinary browser/service process receives only service-level status and public machine identity, not wallet/PSBT payloads. Read-only service settings are visible in the protected window; use the Utilities shortcut to edit them. Wallet/backup passphrases are requested through protected native dialogues, never ordinary browser forms, URLs, command arguments, logs or Dashboard.

After switching off the node interface and finishing sensitive work, **Close workspace** shuts down temporary processes and clears its RAM state. Sleep/hibernation remains inhibited while sensitive work is active. Do not shut down an unfinished setup: temporary keys and uncompleted payloads are volatile. No setup is automatically regenerated after a loss or uncertain outcome.

## Authorise: wallet creation

The Agent accepts one active wallet setup at a time, with 1–15 independent cosigners and a threshold between 1 and N. Each local role produces a different key. Copies of one key are not additional cosigners.

1. Review the full public proposal: name, network, M-of-N threshold, every assigned Agent identity, node/disc storage roles and optional block height. Independently compare and enter one complete fingerprint per distinct producing Agent, for this ceremony; Dashboard names are only display hints.
2. After participation approval, Core creates encrypted signing wallets in the protected temporary node. Passphrases are local. Only assigned roles are generated; physical-only keys are not duplicated on observers or other Agents. Signed public account contributions go to Dashboard.
3. Review the complete policy. The Agent verifies every contribution signature, producer assignment, its own unchanged keys, distinct accounts, network and receiving/change derivations. It independently constructs the exact supported policy and compares six sample addresses with Core. Compare the complete policy code and sample addresses directly across Agents.
4. Locally approve the exact policy. Only node-assigned encrypted wallets are retained in your chosen existing Core, together with a public policy monitor. Physical-only private wallets stay in protected RAM for disc preparation. The complete public recovery policy accompanies every physical backup.

Supported policies are native SegWit `wpkh` for plain single-signature, `wsh(sortedmulti(...))` for plain M-of-N, and mandatory-height `wsh(and_v(v:after(H),pk(...)))` or `wsh(and_v(v:after(H),multi(...)))`. Vault keys use deterministic cosigner-ID order. No bypass branches, arbitrary scripts or Taproot key-path alternatives are accepted. Height reached removes only the height restriction; the required signatures remain necessary.

Signed completion proofs are required from every producing Agent and every assigned physical role. A server label alone cannot declare a wallet ready. The local Core monitor records the public ready/pending state. Later signing independently identifies the restricted policy and its actual local private accounts from Core, including after Agent RAM metadata is lost. Transaction reviews show the complete final transaction; signatures return through the existing PSBT workflow and broadcast requires a separate local approval.

## Disc Operations

This page is available whenever the node interface is connected. Read an existing archival disc or prepare a locally authorised physical-role backup. Each physical cosigner has its own disc. A duplicate copy of one key never becomes another cosigner.

For writing, choose blank write-once DVD-R or BD-R M-Disc media. Used/rewritable media are rejected. A separate passphrase encrypts the complete package with AES-256-GCM and scrypt (N=131072,r=8,p=1), including its Core-encrypted role wallet, full public policy, network/height, authenticated contributions and recovery instructions. Keep both package and Core passphrases separately from the disc.

The small recovery filesystem is followed by as many independently checksummed copies of that encrypted package as fit the detected writable capacity. Copies stream from one RAM package: a 100 GB disc does not require a 100 GB RAM image or millions of filesystem entries. Every recorded byte is read back directly before a signed success acknowledgement is issued. The default asks the drive for its slowest supported speed (`xorriso speed=-1`). An optional numeric selection must be reported by the current drive/media. The drive governs actual write speed; slowest need not mean 1×. A nominal 25 GB Blu-ray at 1× takes roughly 93 minutes to write, with finalisation and full read-back taking additional time. See [disc format and recovery limits](DISC_FORMAT.md).

For reading, enter the backup passphrase in the native dialogue. The Agent skips unreadable or checksum-invalid copies until it finds an intact authenticated package. Review its complete policy code, cosigner role, threshold, network, height and sample addresses against a trusted record. Explicitly confirm before loading. Archived creation-request expiry does not invalidate a historical backup.

The encrypted role wallet is loaded into a separate temporary Core in protected RAM, never restored into the persistent node. Its public account is visible to Dashboard for normal transaction routing. Select the request on Authorise and sign locally; the resulting public PSBT follows the existing Dashboard protocol. Core wallet passphrases are requested locally and wallets are relocked. The chainless temporary archive accounts are excluded from persistent-node rescan/download requirements. Unload the archive when finished. Multiple distinct physical roles can remain loaded while you swap discs, so two archived keys can sign one message or transaction without two drives.

## Sign Message

Choose one or more private signing accounts from the node or loaded optical archives, enter the exact message and its Bitcoin address, then review and sign. The Agent builds only BIP-322 synthetic transactions: it never selects real funds or broadcasts a message proof. Native SegWit, wrapped SegWit, Taproot key-path and the supported M-of-N/height policies are checked locally.

Multisig contributors can sign together or continue an exact matching partial message-proof PSBT. Fewer than the required distinct keys produces a clearly labelled partial PSBT, not a completed signature. A repeated signature from the same account does not increase the count. The final proof requires a compatible BIP-322 verifier; height-constrained proofs retain their height condition. This replaces the standalone Wallaby Signer interface.

## Authorise queue and notifications

All pending requests are listed together. Select an item to review its locally reconstructed details; signing and wallet-creation reviews have different layouts. Completed requests close their details. Cancel only an unattempted request; uncertain attempted operations require local reconciliation. Authorise remains available while the node interface is connected, including when the queue is empty.

For an incoming wallet synchronisation request, **Disable synchronisation** excludes that exact public descriptor policy on this Agent. It never applies to signing or outgoing transfers. Re-enable it from the exclusions list. An intentionally disabled policy is not unfinished work and does not light either sidebar dot, including when Dashboard repeats the request. Cancelling a row alone may allow a later Dashboard revision to offer it again. The list is persisted locally and needs no Dashboard support. Dashboard may continue its own missing-wallet alerts until it implements the read-only status query; it must never keep another user-controlled exclusion setting.

Authorise and Synchronisation have red sidebar dots while unresolved work exists and the user is on another page. A node history download also counts as unresolved synchronisation. Opening the relevant page hides its dot; leaving with unfinished work restores it. Requests never automatically open a browser or switch pages.

A native Core executable is needed for temporary wallet generation. The Agent checks normal native installation paths and direct native ELF executables inside an existing bitcoin-core Snap; it never silently invokes a Snap launcher with uncontrolled temporary storage. If that binary cannot run inside the protected service, install an appropriate native Core executable. Unknown startup/storage failures stop the workflow; there is no laptop-drive fallback.

For an existing Snap Core's encrypted file transfers/restoration, a small privileged setup helper exposes the **same RAM filesystem** inside its allowed common data directory. It uses directory file descriptors with no symlink traversal, not arbitrary Dashboard paths. The Agent verifies that the alias is the same non-swapping RAM inode. If Snap confinement still prevents access, it refuses the operation rather than staging on disk. Actual Snap namespace behaviour must be checked on the deployment machine.

## Make Extinct

Dashboard Build 11's request is handled locally on Authorise. The Agent verifies public descriptor identity against the exact private Core wallet or a restricted shared policy with matching local private signing accounts, complete confirmed history and zero funds, including pending/immature/watch balances, locked outputs and associated vault/shared-policy monitors. It reconstructs used receiving and change addresses for review. Existing exact address-specific `LOST` labels are preserved; retirement never invents a loss declaration.

Approval imports public `addr()` records into a private-key-disabled historical archive. The original private wallet is **never deleted or unloaded**. If history cannot be established on a pruned node, the user can prepare a local history requirement and separately authorise recovery on Synchronisation. Retirement still requires a fresh review afterwards. An uncertain import is not replayed automatically.

## Synchronisation and This Node

The multi-wallet request list, independently signed funded-address/label/vault previews, watch-only mode and alphabetical selected batches remain. Watch-only sources force watch-only receipt. Exact receiving/change labels and fixed-address Extinct groups, including zero-balance labels, are preserved. Dashboard controls authoritative row membership/withdrawal; Locally cancelled unattempted rows may return in a later queue revision; incoming policy exclusions suppress them on this Agent. Agent SSH pipes are handed into the protected worker, and encrypted private wallet files travel directly between peers, never through Dashboard. Matching names never establish wallet identity.

Missing history is **recovery required**, not successful completion. This Node shows Synchronised / Requires Rescan / Requires Blockchain Download from local evidence. The user reviews and authorises recovery locally. If old blocks are missing, Core can be cleanly restarted/reindexed with **the same pruning mode and limit throughout**. Wallets, original descriptor timestamps and vault monitors are loaded before historical download resumes, so Core records their history before pruning. No archival chain allocation, pruning override, automatic safety backups or remote restart authority is introduced. Synchronisation/history requests never open a window or switch the user's page automatically.

## Persistent Denial list

The only new persistent Agent Bitcoin preference is a list of disabled incoming wallet-policy hashes and their display names, plus a format version and update counter. It lives in `/var/lib/wallaby-agent-denials/<UID>/denials.json`, private to that desktop user (directory 0700, file 0600). No request bodies/hashes for individual declined operations, PSBTs, descriptors, addresses, balances, wallet files, private keys, passphrases, history jobs or approval/outbox payloads enter this file.

A separate fixed unprivileged service, `wallaby-agent-denials@<UID>.service`, owns this schema-limited atomic store. It is started as a dependency of the protected workspace. The Bitcoin worker retains read-only ordinary filesystems; it has no writable persistent mount. Its local socket can read the list or commit a validated list revision only. It cannot request arbitrary file paths, RPC operations or commands. Failed/corrupt/unavailable storage blocks Bitcoin work until it can read the list, rather than silently forgetting exclusions. Services remain independent.

Services configuration and its machine/SSH identity retain their existing persistent locations. Other Agent Bitcoin working data stays in the protected volatile workspace and is cleared on shutdown. Existing Bitcoin Core wallets/blockchain and deliberately produced optical backups/signed Dashboard outputs retain their selected destinations; this does not retroactively erase files created by older versions. Build 11 no longer reloads legacy on-disk `approvals.json` into a new workspace.

## Protection boundary

The dedicated worker and HTML5 viewer use a non-swapping RAM filesystem and process cgroup, zero core limits/non-dumpable children, checked read-only ordinary filesystems, RAM-only temporary/shared-memory paths, restricted raw devices and verified sleep/hibernation inhibition. Enabled kernel crash dumping causes refusal. The supervisor keeps inhibition through temporary-child shutdown and RAM cleanup, including worker failure. The protected process checks its actual controls before sensitive work; merely setting a temporary-folder path or environment flag is insufficient.

The installer adds a fixed per-user protected service, a narrow permission to start/stop only that user's worker, a RAM helper for existing Core Snap access, and a per-service AppArmor user-namespace profile so the HTML5 engine can retain its own sandbox. It does not disable global AppArmor, browser sandboxing, swap, pruning, SSH restrictions or firewalls. The preparation helpers handle mount/account metadata only; wallet operations execute as the desktop user.

The physical-only claim covers **new private wallet material and backup staging through this controlled workflow**. Existing on-disk wallets cannot retroactively become never-on-disk. Intentionally retained encrypted node wallets, Core's blockchain/public policy records, server-relayed public information, service configuration and machine SSH identity have their explicitly selected persistent destinations. Public information deliberately copied or captured by the user and other applications is outside this storage boundary. A trusted OS, administrator, dependencies and hardware remain assumptions; this is not an unconditional guarantee against their compromise or an independent security audit.

Bitcoin Agent inbox/outbox/reviews and temporary jobs are volatile. Keep the workspace alive through completion; on restart reconcile existing Core wallets, pending history and server audit before a deliberate fresh request. No private key, encrypted wallet payload or passphrase is accepted by Dashboard. No automatic wallet/configuration backup copies are created; temporary encrypted transfer/optical payloads are the necessary transport, not extra retained backups.

## Source and historical builds

The source and compiled Ubuntu 26.04 amd64 DEB are on **Development**. The GitHub default is Stable; open [Development explicitly](https://github.com/bluesilent9/wallaby-agent/tree/Development). Stable is unchanged.

- [Build 12 installer](dist/wallaby-agent_2.0.0~dev12_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/8aaa31b823c898260162a0dc28329ccf43f40fae)
- [Build 11 installer](dist/wallaby-agent_2.0.0~dev11_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/e8fbfbaa916532681b3f4344737ef254bf76ae5b)
- [Build 10 installer](dist/wallaby-agent_2.0.0~dev10_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/51e483e8559dec9a6f5855c5fa7d68736201354f)
- [Build 9 installer](dist/wallaby-agent_2.0.0~dev9_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/0be3e95c236ebc8ffd57e4bf7f675d82cdfb0916)
- [Build 8 installer](dist/wallaby-agent_2.0.0~dev8_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/4f6c168f8faa646452bbbba14b3f4f5619e2e785)
- [Build 7 installer](dist/wallaby-agent_2.0.0~dev7_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0)
- [Build 6 installer](dist/wallaby-agent_2.0.0~dev6_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/b2b44e7983940e7a758969e4244df5d2e6f4c6dc)

Build without root: `python3 packaging/build.py`. See [VALIDATION.md](VALIDATION.md) for exact tests and deployment limits. Privileged startup, desktop/Snap confinement and real optical-media operation require machine/hardware validation; passing isolated Core/crypto tests does not prove those integration controls.
