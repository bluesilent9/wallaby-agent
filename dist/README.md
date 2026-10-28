> [!CAUTION]
> **TRANSACTION SIGNING EXPOSES YOUR KEYS TO THE SIGNING ENVIRONMENT.**
> If you use Wallaby Agent for transaction signing, the Agent handles your wallet passphrase locally and temporarily unlocks Bitcoin Core to request signatures. This gives the locally installed Agent signing authority and puts your wallet keys and funds at risk if the Agent, its dependencies or the computer are compromised. **Independently audit the source code and its dependencies before compiling or using the Agent for transaction signing.** The intended workflow keeps private keys in Core and does not export them to the Dashboard; that does not remove the risk of an unlocked wallet or a compromised signing computer.

# Development installers

Latest: [V2 Development Build 6 DEB](wallaby-agent_2.0.0~dev6_amd64.deb), Ubuntu 26.04 LTS amd64. Verify [SHA256SUMS.txt](SHA256SUMS.txt).

Build 6 fixes fresh-tab local page authentication, removes all ping checks, uses one authenticated IPv6 SSH connection shared by every service, changes Accept Server to Connect, and automatically saves/reloads valid configuration edits. It also refreshes older running Agent services when opened after an upgrade. Existing settings and service choices persist.

77 tests pass, including twelve isolated Core 31 vault/signing regtest cases. A live isolated shared-SSH test passed against the configured server, adding/removing DDNS-GO and Dashboard forwards without replacing the login. Browser live-saving/reload tests and package checks pass.

Close old tabs after installing and open Wallaby Agent Configuration from the desktop menu. Build 5 vault/authorisation features and read-only Dashboard RPC remain. The future Dashboard exchange and Stage 2 receiver are still pending; those exports remain queued locally. Development only. See the main README and validation report for details.
