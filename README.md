# Wallaby Agent — Development Build 97

Ubuntu 26.04 LTS amd64 · Bitcoin Core 31 · Development release.

The Agent connects your local Core wallets to Wallaby Wallet while keeping wallet keys and local authorisation on this computer. Peer pairing uses authenticated scan-connect QR codes; wallet and blockchain data use direct paired SSH, with the Server providing signalling only.

Build 97 loads the local wallets needed for Extinct ownership inspection automatically and restores their previous loaded state afterward. Source archives can also be temporarily loaded for export. Active-wallet conflicts and import checks remain enforced.

[Build 97 changes and validation](AGENT_BUILD97_TEMPORARY_WALLET_LOADING.md).

The source tree now contains maintained code, current feature tests, protocol/data documentation and Build 88's reference notes. Historical releases are available in Git history rather than accumulated in the current distribution. New packaging builds only the current version and reuses an installer only after verifying its source-input and artifact hashes.

- Build: `python3 packaging/build.py`
- Focused tests: `python3 packaging/checks.py` (set `WALLABY_TEST_BITCOIND` to an isolated-test Core binary; optional Python dependencies must be installed).
- Select additional current feature checks by passing their unittest names. Production-worker integration also needs `WALLABY_SERVER_SOURCE` pointing to the Wallet Server source.
- Export verified current artifacts: `python3 packaging/release.py --output /path/to/output`.

[Build 89 changes and validation](AGENT_BUILD89_CURRENT_RELEASE.md) · [Build 88 reference](AGENT_BUILD88_WALLET_HISTORY.md) · [Current protocols](AGENT_PROTOCOL.md) · [Local approval boundaries](APPROVAL_PROTOCOL.md) · [Disc data format](DISC_FORMAT.md).

Transaction signing temporarily unlocks the selected local Core wallet and gives the installed Agent signing authority. Audit the Agent and dependencies before use. Passphrases and private keys are not sent to the Wallet Server. Compromise of the signing computer can compromise funds.
