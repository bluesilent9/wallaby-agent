> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent V2 — Development Build 9

Ubuntu 26.04 LTS amd64 · Bitcoin Core 31 · **Development**, not a Stable release.

[Build 9 DEB](dist/wallaby-agent_2.0.0~dev9_amd64.deb) · [Checksums](dist/SHA256SUMS.txt) · [Validation](VALIDATION.md) · [Dashboard integration handoff](DASHBOARD_BUILD9_UPDATE.md)

Build 9 adds locally approved wallet retirement, authenticated single-signature/M-of-N wallet setup, mandatory-height variants, and encrypted M-Disc preparation/verification in a protected RAM workflow. The local Vault Builder page is removed; proposals originate from Dashboard V1 Build 11’s Wallet Builder and are independently verified on **Authorise**. **Burn Disc** unlocks only after the exact local policy is authorised for a physical role.

**Dashboard V1 Build 11 implements Wallet Builder and this setup protocol.** [Dashboard Development](https://github.com/bluesilent9/wallaby-dashboard/tree/Development) verifies signed setup contributions, policy approvals and every required physical-backup proof, then relays authenticated completion. It collects distinct cosigner signatures per input and avoids synchronizing intentional signing accounts as missing wallets. Agent Build 9 still lacks a guided disc-restore signing UI; restore an encrypted cosigner locally before Dashboard routes a signing request to its matching account. No private recovery package or passphrase goes to Dashboard. Existing RPC remains a positive public/read-only allowlist; Dashboard cannot directly create/unlock/import/delete wallets, export keys, sign, broadcast or restart Core.

## Install and start

Install the DEB with your normal package manager so its dependencies are installed: Python/cryptography, PyQt6 WebEngine, OpenSSH client, systemd, policykit, xorriso and a native password dialogue (kdialog or zenity). All connection services remain off on a fresh install. Existing saved service choices are retained on upgrade.

Open **Utilities → Wallaby Agent Configuration**. **Services** uses the ordinary HTML5 configuration page. Hostname, SSH username/port/key and enabled services save live. A hostname/domain is required; literal IP addresses are refused. Connect authenticates an IPv6-only shared SSH master, never pings. Green means authenticated connection, amber means connecting and red means failed/disconnected. DDNS-GO, Dashboard browser access and the node interface share its forwarding connection. Tunnels remain user services and start at login when enabled.

For Bitcoin functions, click **Start protected workspace** on Services. A one-time native administrator authorisation establishes the non-swapping RAM mount. Later logins can start only that user's fixed unprivileged protected worker without repeating the administrator prompt. If the node interface is enabled, login bootstrap starts that worker automatically. This does not grant root to wallet operations or enable other users' services.

Bitcoin pages open in a dedicated protected HTML5 window. The ordinary browser/service process receives only service-level status and public machine identity, not wallet/PSBT payloads. Read-only service settings are visible in the protected window; use the Utilities shortcut to edit them. Wallet/backup passphrases are requested through protected native dialogues, never ordinary browser forms, URLs, command arguments, logs or Dashboard.

After switching off the node interface and finishing sensitive work, **Close workspace** shuts down temporary processes and clears its RAM state. Sleep/hibernation remains inhibited while sensitive work is active. Do not shut down an unfinished setup: temporary keys and uncompleted payloads are volatile. No setup is automatically regenerated after a loss or uncertain outcome.

## Authorise: wallet creation

The Agent accepts one active wallet setup at a time, with 1–15 independent cosigners and a threshold between 1 and N. Each local role produces a different key. Copies of one key are not additional cosigners.

1. Review the full public proposal: name, network, M-of-N threshold, every assigned Agent identity, node/disc storage roles and optional block height. Independently compare and enter every complete Agent fingerprint; Dashboard names are only display hints.
2. After participation approval, Core creates encrypted signing wallets in the protected temporary node. Passphrases are local. Only assigned roles are generated; physical-only keys are not duplicated on observers or other Agents. Signed public account contributions go to Dashboard.
3. Review the complete policy. The Agent verifies every contribution signature, producer assignment, its own unchanged keys, distinct accounts, network and receiving/change derivations. It independently constructs the exact supported policy and compares six sample addresses with Core. Compare the complete policy code and sample addresses directly across Agents.
4. Locally approve the exact policy. Only node-assigned encrypted wallets are retained in your chosen existing Core, together with a public policy monitor. Physical-only private wallets stay in protected RAM for disc preparation. The complete public recovery policy accompanies every physical backup.

Supported policies are native SegWit `wpkh` for plain single-signature, `wsh(sortedmulti(...))` for plain M-of-N, and mandatory-height `wsh(and_v(v:after(H),pk(...)))` or `wsh(and_v(v:after(H),multi(...)))`. Vault keys use deterministic cosigner-ID order. No bypass branches, arbitrary scripts or Taproot key-path alternatives are accepted. Height reached removes only the height restriction; the required signatures remain necessary.

Signed completion proofs are required from every producing Agent and every assigned physical role. A server label alone cannot declare a wallet ready. The local Core monitor records the public ready/pending state. Later signing independently identifies the restricted policy and its actual local private accounts from Core, including after Agent RAM metadata is lost. Transaction reviews show the complete final transaction; signatures return through the existing PSBT workflow and broadcast requires a separate local approval.

## Burn Disc

Each physical cosigner has a separate disc, even when one Agent produces several roles. Choose an optical drive, insert blank write-once DVD-R or BD-R M-Disc media, check it, and confirm media/drive compatibility. Software cannot authenticate an M-Disc's branding. Used or rewritable media are rejected; the Agent never erases or silently appends to them.

A separate local backup passphrase encrypts the entire recovery package with AES-256-GCM and scrypt (N=131072,r=8,p=1). It contains the Core-encrypted signing wallet, full receiving/change descriptors, threshold/network/height, all authenticated public contributions and recovery instructions. Keep the package and Core wallet passphrases separately from the disc. Neither passphrase is placed on the disc or sent to Dashboard.

The ISO and package are prepared in protected RAM. xorriso writes the optical medium, then direct aligned reads check every image byte against SHA256. Only verified equality produces Success and a signed completion acknowledgement. Failed or uncertain writes remain incomplete. After the final assigned disc is verified, temporary Core/key files are removed; Success remains visible for five seconds before Burn Disc becomes unavailable. A generic inspectable recovery utility on the disc requires a protected, locked-memory, non-swapping, sleep-inhibited environment before decryption.

A native Core executable is needed for temporary wallet generation. The Agent checks normal native installation paths and direct native ELF executables inside an existing bitcoin-core Snap; it never silently invokes a Snap launcher with uncontrolled temporary storage. If that binary cannot run inside the protected service, install an appropriate native Core executable. Unknown startup/storage failures stop the workflow; there is no laptop-drive fallback.

For an existing Snap Core's encrypted file transfers/restoration, a small privileged setup helper exposes the **same RAM filesystem** inside its allowed common data directory. It uses directory file descriptors with no symlink traversal, not arbitrary Dashboard paths. The Agent verifies that the alias is the same non-swapping RAM inode. If Snap confinement still prevents access, it refuses the operation rather than staging on disk. Actual Snap namespace behaviour must be checked on the deployment machine.

## Make Extinct

Dashboard Build 11's request is handled locally on Authorise. The Agent verifies public descriptor identity against the exact private Core wallet or a restricted shared policy with matching local private signing accounts, complete confirmed history and zero funds, including pending/immature/watch balances, locked outputs and associated vault/shared-policy monitors. It reconstructs used receiving and change addresses for review. Existing exact address-specific `LOST` labels are preserved; retirement never invents a loss declaration.

Approval imports public `addr()` records into a private-key-disabled historical archive. The original private wallet is **never deleted or unloaded**. If history cannot be established on a pruned node, the user can prepare a local history requirement and separately authorise recovery on Synchronisation. Retirement still requires a fresh review afterwards. An uncertain import is not replayed automatically.

## Synchronisation and This Node

The multi-wallet request list, independently signed funded-address/label/vault previews, watch-only mode and alphabetical selected batches remain. Watch-only sources force watch-only receipt. Exact receiving/change labels and fixed-address Extinct groups, including zero-balance labels, are preserved. Dashboard controls authoritative row membership/withdrawal; Agent cannot clear the list. Agent SSH pipes are handed into the protected worker, and encrypted private wallet files travel directly between peers, never through Dashboard. Matching names never establish wallet identity.

Missing history is **recovery required**, not successful completion. This Node shows Synchronised / Requires Rescan / Requires Blockchain Download from local evidence. The user reviews and authorises recovery locally. If old blocks are missing, Core can be cleanly restarted/reindexed with **the same pruning mode and limit throughout**. Wallets, original descriptor timestamps and vault monitors are loaded before historical download resumes, so Core records their history before pruning. No archival chain allocation, pruning override, automatic safety backups or remote restart authority is introduced. Synchronisation/history requests never open a window or switch the user's page automatically.

## Protection boundary

The dedicated worker and HTML5 viewer use a non-swapping RAM filesystem and process cgroup, zero core limits/non-dumpable children, checked read-only ordinary filesystems, RAM-only temporary/shared-memory paths, restricted raw devices and verified sleep/hibernation inhibition. Enabled kernel crash dumping causes refusal. The supervisor keeps inhibition through temporary-child shutdown and RAM cleanup, including worker failure. The protected process checks its actual controls before sensitive work; merely setting a temporary-folder path or environment flag is insufficient.

The installer adds a fixed per-user protected service, a narrow permission to start/stop only that user's worker, a RAM helper for existing Core Snap access, and a per-service AppArmor user-namespace profile so the HTML5 engine can retain its own sandbox. It does not disable global AppArmor, browser sandboxing, swap, pruning, SSH restrictions or firewalls. The preparation helpers handle mount/account metadata only; wallet operations execute as the desktop user.

The physical-only claim covers **new private wallet material and backup staging through this controlled workflow**. Existing on-disk wallets cannot retroactively become never-on-disk. Intentionally retained encrypted node wallets, Core's blockchain/public policy records, server-relayed public information, service configuration and machine SSH identity have their explicitly selected persistent destinations. Public information deliberately copied or captured by the user and other applications is outside this storage boundary. A trusted OS, administrator, dependencies and hardware remain assumptions; this is not an unconditional guarantee against their compromise or an independent security audit.

Bitcoin Agent inbox/outbox/reviews and temporary jobs are volatile. Keep the workspace alive through completion; on restart reconcile existing Core wallets, pending history and server audit before a deliberate fresh request. No private key, encrypted wallet payload or passphrase is accepted by Dashboard. No automatic wallet/configuration backup copies are created; temporary encrypted transfer/optical payloads are the necessary transport, not extra retained backups.

## Source and historical builds

The source and compiled Ubuntu 26.04 amd64 DEB are on **Development**. The GitHub default is Stable; open [Development explicitly](https://github.com/bluesilent9/wallaby-agent/tree/Development). Stable is unchanged.

- [Build 8 installer](dist/wallaby-agent_2.0.0~dev8_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/4f6c168f8faa646452bbbba14b3f4f5619e2e785)
- [Build 7 installer](dist/wallaby-agent_2.0.0~dev7_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/8731a90f4adc24f0ac0345b1ab7f70aed5ffdee0)
- [Build 6 installer](dist/wallaby-agent_2.0.0~dev6_amd64.deb) · [matching source](https://github.com/bluesilent9/wallaby-agent/tree/b2b44e7983940e7a758969e4244df5d2e6f4c6dc)

Build without root: `python3 packaging/build.py`. See [VALIDATION.md](VALIDATION.md) for exact tests and deployment limits. Privileged startup, desktop/Snap confinement and real optical-media operation require machine/hardware validation; passing isolated Core/crypto tests does not prove those integration controls.
