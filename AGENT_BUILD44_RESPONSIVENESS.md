# Build 44: control traffic and session stability

Dashboard logs and all three Agent logs show HTTP delays followed by replacement
sessions. Dashboard is addressing its login/profile locking and background-work
scheduling separately. This build addresses related Agent behaviour.

## Agent changes

- Heartbeat/poll command admission never waits for a free Core worker. When both
  slots are occupied, the command remains unacknowledged and unseen; Dashboard's
  existing broker offers the delivered command again. The two-worker bound stays.
- Brief heartbeat/poll HTTP timeout or transport failures retry using the existing
  authenticated token. A fixed 15-second retry window begins at the detected
  failure. The protected workspace becomes amber/paused and returns to green when
  healthy heartbeat traffic resumes. The existing independent recovery watchdog
  enforces the original deadline; retries do not extend it. Expired authentication,
  invalid protocol and session limits still follow guarded session recovery.
- An uncertain RPC acknowledgement/result delivery does not itself discard the
  session. No Core call, ACK or result is automatically replayed. The request
  remains in the session's seen set. Diagnostics identify the delivery phase and
  uncertainty; Dashboard may expire that individual request.
- Runtime exchanges perform at most one sender public-preview verification in a
  separate background worker. A slow Core preview cannot hold up identity replies
  and control exchanges. Failed previews have a per-request 30-second backoff so
  one failing wallet does not repeatedly block the rest. Public preview work
  never authorises a transfer or creates private-key operations.
- Direct peer IPv6 literals bypass hostname-only DNS validation during route
  discovery; named hosts still use native resolver IPC. This repairs the Build 43
  route regression affecting public wallet previews.
- Pending signed identity replies are sent ahead of ordinary outbox items and
  trigger a prompt next exchange. Own-address discovery is cached in RAM for at
  most 30 seconds per connection, avoiding a new DNS/route lookup on every poll.
- Transient exchange failures start with a one-second retry, increasing to a
  bounded 30-second delay. Invalid proposals retain the conservative 30-second
  retry. Logs state the actual endpoint/category and retry interval without
  logging tokens, descriptors, keys, addresses or request contents.

No wire-format or capability change is required. The Dashboard chat is preparing Build 54 with
complementary responsiveness changes; Agent Build 44 cannot fix a
Dashboard profile writer blocking Login. IPv6-only interfaces, native resolver
IPC, local approval requirements and protected RAM handling remain unchanged.

## Tests

Three independent real test Core nodes and Agent clients communicate with an
isolated IPv6 HTTP Dashboard-protocol fixture. Three signed identities arrive
while preview workers are held, despite one deliberately dropped poll per Agent.
There is no replacement registration. Signatures are verified. Additional tests
cover full RPC capacity, fixed recovery windows, rejected authentication,
non-replay of uncertain delivery, and the protected workspace's amber/green
transition with the same client. The fixture isolates scheduling/transport; it is
not a claim that the complete live Dashboard/UI has been reproduced there.

A separate multi-process integration run also passed against a frozen copy of
Dashboard Build 54's current source: three real Agent processes, three isolated
Core nodes, and the production Dashboard HTTP/RPC/Wallet Builder handlers. After
all nodes became eligible, Dashboard accepted all three signed identity replies
in 2.277 seconds in this local fixture. The same three authenticated sessions
remained present. Regtest network/health and synthetic network identities were
the adapters; OS services, real wallets and internet routing were not involved.
`tests/integration_identity_dashboard.py` takes Agent source, Dashboard source and
an output directory; select a dummy Core executable with `WALLABY_TEST_BITCOIND`.
