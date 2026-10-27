# V2 Development Build 4 — pre-build validation

Source prepared 27 October 2026. Package version: `2.0.0~dev4`, architecture amd64. No Build 4 DEB or native launcher build has run at this checkpoint.

All 44 Agent source tests pass. New regressions call the actual Core HTTP client with exact wallet names (including empty default, spaces, slashes, punctuation and Unicode) and exercise eight queued commands without exceeding two Core workers or dropping the session. Existing configuration, transport, diagnostics, RPC policy and Dashboard protocol tests continue to pass.

The matching Dashboard source tests additionally connect the actual Agent process to the real Dashboard hub and a strict simulated Core server with twelve loaded wallets. They check bounded dispatch and fast failure retention on Ownership. The metadata tests do not query real wallets or public blockchain services.

Pending after the requested reboot: native launcher/DEB build, package inspection, checksums and release upload. Installation, live node loading and user-service startup/upgrade testing remain pending. Historical Build 3 artifacts remain unchanged in the repository. No server service or laptop service was changed during source preparation.
