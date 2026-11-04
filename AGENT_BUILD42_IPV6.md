# Build 42: IPv6-only Agent

The Services webpage and protected webpage bind exclusively to `::1`, use
`IPV6_V6ONLY`, and open `http://[::1]:PORT/`. Host and origin checks require the
exact bracketed loopback authority; hostname aliases are refused. The protected
viewer checks parsed origins, including port, before navigating or supplying its
private view header.

All local Dashboard-forward and Core HTTP clients explicitly create IPv6 sockets.
There is no selectable address family or fallback. The offline Core process also
receives `-rpcbind=[::1] -rpcallowip=::1 -onlynet=ipv6`; its RPC port is selected
on IPv6 loopback. Protected and ordinary Agent systemd services exclude IPv4
socket creation. SSH already uses `-6` and bracketed IPv6 forwards.

The package desktop launcher continues to run `wallaby-agent configure`, which
now generates the IPv6 URL. Existing application shortcuts follow that change.
At bootstrap, recognised user-owned Wallaby URL shortcuts in the applications or
configured Desktop folder are replaced with that application launcher, preserving
permissions. Other shortcuts, symlinks and browser profiles are left alone.
Old open browser tabs retain their old URL; reopen the Agent from its shortcut
following the upgrade. An IPv4 URL will no longer connect.

Your normal Bitcoin Core must expose RPC on `::1` at the configured port. If its
configuration explicitly restricts RPC, review its `rpcbind=[::1]` and
`rpcallowip=::1` settings and restart Core. The Agent does not change your node's
configuration, pruning settings or existing wallet storage. IPv6 must remain
enabled on the machine; failure does not activate an alternative transport.

No Dashboard protocol change is required. Build 41 combined-role wallets,
managed signer-transfer restrictions and archival workflows remain in place.
Tests exercise real IPv6 HTTP requests, denied alternate Host/origin values,
refused IPv4 connections, offline Core RPC, shortcut migration and independent
three-Agent multisig wallet creation. Installed systemd/Qt/network behaviour
still needs validation on the target Ubuntu machines; automated fixtures do not
claim to test a physical optical drive or the actual modem/firewall.
