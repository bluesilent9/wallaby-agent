> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Wallaby Agent — Stable

**No Stable application release has been promoted yet.**

The current application is **[Wallaby Agent V2 Development Build 5](https://github.com/bluesilent9/wallaby-agent/tree/Development)**. [Ubuntu 26.04 LTS amd64 DEB](https://github.com/bluesilent9/wallaby-agent/blob/Development/dist/wallaby-agent_2.0.0~dev5_amd64.deb) · [Checksums](https://github.com/bluesilent9/wallaby-agent/blob/Development/dist/SHA256SUMS.txt).

Build 5 provides:

- **Services:** per-user IPv6 SSH tunnels for DDNS-GO Administration, Dashboard browser access and the Bitcoin Core node interface, with independent switches, reconnects and desktop-session startup. Jellyfin administration was removed in V2.
- **Public/read-only node RPC:** direct Dashboard requests cannot change wallets, access private keys, unlock, sign or broadcast.
- **Vault Builder inside the Agent:** full-wallet single-key P2WSH timelock construction, local Core verification, timezone/block-height estimates and matured-vault rollover.
- **Authorise:** independently reconstructed local transaction/policy review, local approval or denial, persistent deny records, local signing/broadcast and signed-PSBT queuing.

Dashboard-side vault exchange and the immutable Transaction Builder Stage 2 receiver remain **pending**. Agent exports queue locally until the Dashboard implements the [protocol](https://github.com/bluesilent9/wallaby-agent/blob/Development/APPROVAL_PROTOCOL.md). Dashboard V1 Build 7 supports ordinary read-only node queries; its earlier direct watch-wallet creation/import workflows cannot bypass Build 5’s local-approval boundary.

These are Development capabilities, not a Stable release or an independent security audit. Use the [Development README](https://github.com/bluesilent9/wallaby-agent/blob/Development/README.md) for installation, trust/key setup, limitations, validation and source-build instructions. The repository retains Stable and Development branches.
