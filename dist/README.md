# Wallaby Agent Development installers

Current: **V2 Development Build 11**, Ubuntu 26.04 LTS amd64.

Install `wallaby-agent_2.0.0~dev11_amd64.deb` with your normal package manager. Finish sensitive work and close the existing protected workspace before restarting it with this build; the installer does not forcibly destroy an active RAM session. Services settings are retained. New installations start with all tunnels off.

Build 11 persists only the local wallet-sync Denial list in addition to existing Services settings. Ordinary signing/setup declines and Bitcoin working data remain volatile. No Dashboard update is needed for the Agent to enforce its list across reboots.

Verify SHA256SUMS.txt before installation. Earlier installers remain here; matching source commits are linked in the main README. Development only. See VALIDATION.md for deployment limits.
