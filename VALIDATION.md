# V2 Development Build 4 — build validation

Built 27 October 2026. Package version: `2.0.0~dev4`, architecture amd64. GCC compiled the hardened native PIE launcher and dpkg-deb generated the DEB.

All 44 Agent source tests pass. New regressions call the actual Core HTTP client with exact wallet names (including empty default, spaces, slashes, punctuation and Unicode) and exercise eight queued commands without exceeding two Core workers or dropping the session. Existing configuration, transport, diagnostics, RPC policy and Dashboard protocol tests continue to pass.

The matching Dashboard source tests additionally connect the actual Agent process to the real Dashboard hub and a strict simulated Core server with twelve loaded wallets. They check bounded dispatch and fast failure retention on Ownership. The metadata tests do not query real wallets or public blockchain services.

Package inspection confirmed version/architecture, exact runtime/web source parity, all five user services, no Python caches or runtime records, native amd64 PIE launcher, default-OFF tunnel configuration and no automatic tunnel activation in postinst. The package and SHA256 checksum are published on Development; historical packages remain unchanged. Installation, live node loading and user-service startup/upgrade testing remain pending. No server or laptop service was changed. The Dashboard DEB remains unbuilt pending the separate reboot checkpoint.
