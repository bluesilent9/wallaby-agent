# V2 Development Build 5 validation

Validated 29 October 2026. Target: Ubuntu 26.04 LTS amd64, Bitcoin Core V31. **60 tests pass**, including twelve real-Core vault tests. Official Bitcoin Core 31.0 Linux binaries were downloaded to a temporary test location and matched against the vendor's HTTPS SHA256SUMS. They are not bundled in the Agent.

Tests use isolated regtest data directories, separate loopback RPC ports and newly mined test coins, with P2P listening, discovery and external connections disabled. No real wallet, installed Agent, wallet-laptop or server configuration was accessed or modified.

Verified against real Core:

- Whole-wallet explicit-input funding, single vault output, fee subtraction and no ordinary change.
- Calculate does not sign or broadcast. A public monitor is registered locally and independent Core derivation/key binding is shown.
- Local encrypted-wallet signing, immediate relock and successful broadcast.
- Signed Stage 2 PSBT export is complete and immutable; it is queued without broadcast.
- A changed input set requires recalculation; locked/unavailable funds cannot be silently omitted.
- Vault policy/address/height tampering, forged PSBT input amounts and weak sighash modes are rejected.
- Address-only watch wallets are excluded; inactive public-key descriptor watch wallets are accepted as destinations.
- A matured vault withdrawal is reviewed from local information, signed by the original key wallet and broadcast. The monitor retains public descriptor/BIP32-origin metadata. Matured monitor balances can be swept into a new vault by Vault Builder.
- Wrong passphrases before any signing call permit a fresh local review, with the wallet relocked; uncertain signing attempts are never replayed.
- Public import approval, denial persistence across Store restart, deletion/re-prompt and completed-request suppression.

Other checks cover read-only RPC enforcement, rejection of private exports and direct wallet/chain mutations, exact satoshi values and the inverse Poisson 99% time, DST/timezone handling inherited from Dashboard, legacy Dashboard extension fallback with queues retained, cookie rotation and RPC wallet endpoint routing, SSH IPv6 enforcement, retry diagnostics and migration.

Browser testing used an isolated real-Core regtest UI. Verified the sidebar, wallet lists, timezone/date selection, generated descriptor/RPC/PSBT, local and UTC model times, independently derived address/key wallet, pipe notation and signing-wallet highlight. A local passphrase dialog signed and queued a PSBT without broadcast. A separate public vault proposal was reviewed/imported; the page returned to Services and Authorise disabled once the queue cleared. Screenshot capture was unavailable in the browser tool; browser DOM observations and test logs are retained locally. The production auto-open command is wired through the per-user monitor; live desktop notification/login-startup testing is pending.

The future Dashboard exchange is documented and Agent-side implemented, with bounded queues and durable local data retries. **Dashboard Stage 2 consumption and cross-machine live synchronisation cannot be tested end-to-end until Dashboard implements APPROVAL_PROTOCOL.md.** Current Dashboard versions retain normal read-only node connections while the Agent reports exchange unsupported and keeps data queued. Its old direct watch-wallet import/create flows are intentionally no longer permitted.

Package verification checks native amd64 PIE launcher, version, the five user services, complete runtime/web source parity, locally bundled timezone data/licenses, no caches/test keys/configs, default tunnels OFF, and no tunnel activation in package scripts. Development only; no Stable release or installation was performed. This is functional/security regression coverage, not an independent security audit.
