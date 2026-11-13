# Current validation

Use `packaging/checks.py` to run current feature checks or specific unittest names. The runner isolates Core/config/runtime paths, refuses real desktop password prompts and confines test wallet deletion/archive swaps to temporary fixtures. It never builds old releases.

`tests/wallet_history_browser.cjs` exercises actual current HTML/CSS/scripts using headless Chromium and synthetic local API responses. Python tests use isolated Bitcoin Core 31 and real paired direct SSH. Additional integration fixtures can exercise real protected-worker and Wallet Server processes when their source/binaries are supplied.

`packaging/release.py` checks that installed runtime source, web assets and documentation exactly match this source tree, and that package contents are root-owned and not group/world-writable. The release version guard checks visible and process metadata.

See `AGENT_BUILD89_CURRENT_RELEASE.md` for scope and limitations, and the exported current test log for results.
