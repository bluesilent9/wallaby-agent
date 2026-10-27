# Development installers

The latest installer is **V2 Development build 3**: [wallaby-agent_2.0.0~dev3_amd64.deb](wallaby-agent_2.0.0~dev3_amd64.deb), for Ubuntu 26.04 LTS amd64. Verify it with [SHA256SUMS.txt](SHA256SUMS.txt).

Build 3 adds the independent Wallaby Dashboard browser tunnel on port 38951, retains DDNS-GO and the separate node interface on port 56443, and includes specific connection errors and an unsaved-settings reminder. Existing DDNS-GO/node settings are preserved; the new Dashboard switch defaults OFF.

All 42 automated tests and package inspection pass. Installation/upgrade and live login-startup testing remain pending. Older DEBs are historical artifacts and do not include these additions. Stable has no released Agent application.

See the repository README for installation, restarting active user services after upgrade, configuration and legacy Dashboard startup removal.
