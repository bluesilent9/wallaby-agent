# Wallaby Agent V2 Development — build validation

Built 27 October 2026 on Ubuntu 26.04.1 LTS amd64 with Python 3.14 and GCC. Package version: `2.0.0~dev1`.

26 automated tests pass (`python3 -m unittest discover -s tests -v`). Coverage includes the Dashboard V155 HTTP/RPC integration over IPv6, exact decimal results and disconnect handling, V1 configuration migration across every combination of the two retained service switches, retired service shutdown and startup-link cleanup, first-install absence of the old unit, service-manager failure reporting, bootstrap cleanup ordering, the two-service HTML page, and API rejection of the removed toggle. Tests use temporary configuration/runtime directories and mocked user-unit controls; they do not alter the installed Agent or connect to the real Bitcoin node.

The DEB builds successfully using `python3 packaging/build.py`. Extracted package checks confirm version/architecture/dependencies, the compiled ELF amd64 PIE launcher, DDNS-GO/node/monitor/UI user units only, the V2 UI and runtime sources, V1 configuration migration, and the included README. The post-install script only refreshes desktop entries; it does not start or enable tunnels. SHA-256 checksums are published beside the installer in `dist/`.

Still pending: live package installation/upgrade, login-session lifecycle checks and wallet-laptop node/Dashboard testing. The local Core endpoint used by integration tests is simulated. The package has not been installed on the build laptop as part of this build, and Stable is unchanged.

## Historical V1 validation

Built on Ubuntu 26.04.1 LTS amd64 with Python 3.14 and GCC.

19 automated tests pass, including real Dashboard V155 HTTP registration over an IPv6 local listener, correlated RPC request delivery, exact decimal results and graceful disconnect. Other tests cover hostname/IP validation, Snap/custom datadir discovery, private atomic config persistence, rootless systemd commands, SSH IPv6 transport, IPv6 local/remote destinations and host-key enforcement, port collisions, bounded retry backoff, resumption of ping after tunnel loss, RPC restrictions, duplicate deliveries, lost acknowledgements, and loopback UI token/Origin/Host protection.

The HTML5 workspace was inspected in a browser. The DEB was built and its metadata/content checked; the package does not start or enable tunnels during installation.

Build 2 was also tested against the live family SSH server using the existing authenticated account: both IPv6 tunnel masters established successfully, Jellyfin /health returned HTTP 200, and DDNS-GO returned its expected HTTP 307 redirect. Temporary test tunnels were closed afterwards. The saved Agent username was corrected through its configuration page; SSH credentials were not changed. The real Bitcoin Core Snap process, desktop session startup, network failure recovery and package upgrade still require a live check. The local Core endpoint in integration tests is simulated.
