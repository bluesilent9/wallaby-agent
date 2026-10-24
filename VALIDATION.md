# Wallaby Agent V1 Development build 2 — validation

Built on Ubuntu 26.04.1 LTS amd64 with Python 3.14 and GCC.

19 automated tests pass, including real Dashboard V155 HTTP registration over an IPv6 local listener, correlated RPC request delivery, exact decimal results and graceful disconnect. Other tests cover hostname/IP validation, Snap/custom datadir discovery, private atomic config persistence, rootless systemd commands, SSH IPv6 transport, IPv6 local/remote destinations and host-key enforcement, port collisions, bounded retry backoff, resumption of ping after tunnel loss, RPC restrictions, duplicate deliveries, lost acknowledgements, and loopback UI token/Origin/Host protection.

The HTML5 workspace was inspected in a browser. The DEB was built and its metadata/content checked; the package does not start or enable tunnels during installation.

Build 2 was also tested against the live family SSH server using the existing authenticated account: both IPv6 tunnel masters established successfully, Jellyfin /health returned HTTP 200, and DDNS-GO returned its expected HTTP 307 redirect. Temporary test tunnels were closed afterwards. The saved Agent username was corrected through its configuration page; SSH credentials were not changed. The real Bitcoin Core Snap process, desktop session startup, network failure recovery and package upgrade still require a live check. The local Core endpoint in integration tests is simulated.
