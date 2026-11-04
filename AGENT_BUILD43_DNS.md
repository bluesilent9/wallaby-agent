# Build 43: repair DNS inside the IPv6-only services

## Confirmed cause

Build 42 added `RestrictAddressFamilies=AF_UNIX AF_INET6 AF_NETLINK` to the ordinary
Agent services. On the affected Ubuntu laptop, the NSS configuration routes name
lookup through the DNS stub. An IPv6-only `getaddrinfo` request still needs access
to that OS resolver path, which the new service restriction prevented. This caused
SSH to report name resolution failure even though terminal lookups succeeded.
The server's IPv6 address and SSH service were working.

A diagnostic on the affected laptop reproduced successful normal IPv6 lookup,
failed lookup with IPv4 sockets denied, and successful native resolver IPC under
the same restriction. No DNS server settings need changing for this fix.

## New connection path

The Agent asks `systemd-resolved` for IPv6 addresses through its local Unix socket
`/run/systemd/resolve/io.systemd.Resolve`, using the documented
`io.systemd.Resolve.ResolveHostname` method with family `AF_INET6`. Replies and
query time are bounded. IPv4, mapped addresses, malformed byte arrays, unspecified
and multicast addresses are rejected; link-local results retain their interface
scope. No libc DNS fallback or extra address-family permission is introduced.

A fixed OpenSSH proxy helper connects an `AF_INET6` socket and passes that socket
to OpenSSH through `SCM_RIGHTS` with `ProxyUseFdpass=yes`. The original hostname,
port, `StrictHostKeyChecking=yes`, known-hosts handling and normal SSH key or
agent authentication remain in OpenSSH. There is no `Hostname` override,
`HostKeyAlias` rewrite or disabled fingerprint check. The helper never receives
an SSH private key, password or Bitcoin data. Multiple returned IPv6 addresses
are tried within a bounded connection deadline.

Local public IPv6 route discovery uses the same native resolver. Resolver absence,
lookup timeout, missing IPv6 data and invalid/unavailable IPC replies receive
separate safe diagnostic categories. Standard IPv6 connection failure categories
are retained. An unavailable `systemd-resolved` produces a helpful error; the
Agent does not weaken its socket restrictions or change OS DNS configuration.
The OS resolver uses the machine's own DNS configuration; the Agent itself only
uses Unix IPC and IPv6 sockets.

## Validation

Tests reproduce the restricted helper using a real seccomp filter and a local
native resolver fixture, receive the passed descriptor, and exchange data over
its IPv6 connection. Live testing on the affected laptop also authenticated to
its configured server and received Dashboard HTTP 200 over an IPv6 SSH forward,
while IPv4 sockets remained denied. This used a separate temporary master and
forward which were removed afterwards; existing services/settings were unchanged.
No Bitcoin Core or node interface was required for that test. No Dashboard
protocol update is required.

References: [systemd resolver protocol](https://github.com/systemd/systemd/blob/main/src/shared/varlink-io.systemd.Resolve.c),
[OpenSSH connection and descriptor handoff](https://github.com/openssh/openssh-portable/blob/master/sshconnect.c),
[OpenSSH proxy options](https://man.openbsd.org/ssh_config).
