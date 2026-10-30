# Wallaby Agent Development installers

Current: **V2 Development Build 13**, Ubuntu 26.04 LTS amd64.

Install `wallaby-agent_2.0.0~dev13_amd64.deb` using your normal package manager. Tunnel-only clients do not need Bitcoin Core, PyQt6 WebEngine, xorriso or pkexec/polkitd. These are optional suggestions, not dependencies or automatically installed recommendations. The unavailable policykit-1 dependency and bitcoind recommendation are removed.

DDNS-GO and Dashboard browser-access tunnels remain usable. An unavailable node switch stays off and explains its prerequisites. Bitcoin clients can install pkexec, polkitd, PyQt6/WebEngine and a native passphrase dialogue separately, then install/start Core with RPC and configure its cookie. Snap/manual Core installations do not require an apt package named bitcoind. Optical work additionally needs xorriso.

Services settings are retained on upgrade. Fresh installations have all tunnels off. Finish sensitive Bitcoin work and close an existing protected workspace before upgrading/restarting it; the installer does not destroy active RAM sessions.

Verify SHA256SUMS.txt before installation. Earlier installers remain here. Development only. See the main README and VALIDATION.md for tests and deployment limits.
