# Wallaby Agent V1 Development — validation

Built on Ubuntu 26.04.1 LTS amd64 with Python 3.14 and GCC.

19 automated tests pass, including real Dashboard V155 HTTP registration, correlated RPC request delivery, exact decimal results and graceful disconnect. Other tests cover hostname/IP validation, Snap/custom datadir discovery, private atomic config persistence, rootless systemd commands, SSH IPv6 transport and IPv6 remote destination/host-key enforcement, port collisions, bounded retry backoff, resumption of ping after tunnel loss, RPC restrictions, duplicate deliveries, lost acknowledgements, and loopback UI token/Origin/Host protection.

The HTML5 workspace was inspected in a browser. The DEB was built and its metadata/content checked; the package does not start or enable tunnels during installation.

Not tested against the family's live SSH server or a real Bitcoin Core Snap process. Real server key trust/key authentication, forwarding permissions, desktop session startup, actual network failure recovery and install/remove on the target computer still need a live check. The local Core endpoint in integration tests is simulated. No changes were made to the host user's service settings or SSH credentials.
