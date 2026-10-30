# Wallaby Agent Development installers

Current: **V2 Development Build 12**, Ubuntu 26.04 LTS amd64.

Install `wallaby-agent_2.0.0~dev12_amd64.deb` with your normal package manager. Finish sensitive work and close the existing protected workspace before restarting it with this build; the installer does not forcibly destroy an active RAM session. Services settings are retained. New installations start with all tunnels off.

Build 12 adds Dashboard Build 13's local fee/prompt/identity follow-up and separate-disc count/speed controls. Burning defaults to one disc at the slowest supported drive/media speed; every disc still holds repeated recovery copies and is fully verified. Later discs require new local confirmation.

Build 11's storage boundary remains: it persists only the local wallet-sync Denial list in addition to existing Services settings. Ordinary signing/setup declines and Bitcoin working data remain volatile. No Dashboard update is needed for the Agent to enforce its list across reboots.

Verify SHA256SUMS.txt before installation. Earlier installers remain here; matching source commits are linked in the main README. Development only. See VALIDATION.md for deployment limits.
