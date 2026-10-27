# V2 Development build 3 — build validation

Built 27 October 2026. Package version: `2.0.0~dev3`, architecture amd64. GCC compiled the native PIE launcher; dpkg-deb generated the Ubuntu 26.04 installer.

Source retains the staged dev2 diagnostics work and adds the independent Dashboard browser tunnel: local [::1]:38951 to server [::1]:38951. The node RPC interface remains on server port 56443. Upgrades preserve DDNS-GO/node choices and add Dashboard OFF. Fresh installs default all three switches OFF. Dashboard access does not load a cookie or start a node RPC client.

All 42 automated tests pass. Tests cover V1/V2 configuration migration, persistence and user-unit enable/disable commands; separate Dashboard/node IPv6 targets; browser/API controls; a Dashboard worker with no Core dependency; diagnostics/redaction and retry retention; and the real V155 HTTP/RPC protocol with a simulated Core endpoint. Temporary config/runtime directories and mocked service controls protect the installed Agent.

Live read-only server inspection confirmed both browser port 38951 and Agent port 56443 listen on IPv4 and IPv6 loopback. The user's earlier wallet-laptop issue was resolved by saving SSH username wallet-laptop. The user confirmed that Dashboard then detects the node. No new wallet-laptop or server configuration was changed during this preparation.

An isolated browser preview verified all three controls, Dashboard toggle persistence with node OFF, the Open Dashboard IPv6 link, and the unsaved-settings reminder. JavaScript syntax was checked with Node. Preview configuration was isolated from the installed Agent.

Package inspection verified version, architecture, all five user services including Dashboard, runtime/web source parity, no Python caches, native amd64 PIE launcher, default-OFF configuration and no automatic tunnel activation in postinst. SHA256SUMS.txt includes the new installer and previously published packages only.

Pending: installation/upgrade; live Dashboard browser tunnel and login-startup testing on the two laptops. The legacy wallet-laptop unit was identified as ~/.config/systemd/user/ssh-tunnels.service from the user-provided unit listing and contents; exact retirement commands are documented in LEGACY_DASHBOARD_TUNNEL.md. No cleanup command was executed remotely.
