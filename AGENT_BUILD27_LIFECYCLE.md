# Agent V2 Build 27: close contention and late background exchanges

## Supplied log evidence

On 2 November 2026, Dashboard logged empty authoritative lists: treasury-australia revision 6 and wallet-laptop revision 15 both had receiving=0, sending=0. Agent cannot manufacture missing paired requests. Dashboard's chat reproduced expired/stalled previews causing hidden requests and is addressing its scheduler/review workflow separately.

Russia's native close was refused at 05:59:40 UTC and accepted at 06:00:19 UTC. Older diagnostic text records only a busy category, so the exact blocker at that instant cannot be recovered. A real socket/Qt test independently reproduces a short local-status lock causing an immediate native close refusal.

Wallet-laptop accepted close at 06:01:00 UTC, then logged an exchange connection refusal during node shutdown and an unconfirmed cleanup at 06:01:03 UTC. The existing manual guarded recovery succeeded at 06:01:15 UTC without removing private work by force.

## Changes

- Native X admission waits up to ten seconds for the worker lock; it still refuses unresolved private work, loaded/staged archives and undelivered operation results. Legacy deadline admission remains bounded. Closing logs fixed blocker categories.
- Once the close safety gate accepts, the node stop event is set immediately. Node exchanges share session cancellation: a late HTTP reply is not applied or acknowledged, and an intentional stop does not write a spurious connection-failure event.
- A contended public status snapshot has `status_pending=true`. The lifecycle waits for authoritative status rather than declaring that snapshot to be unfinished private work. The service stop helper refuses to act from it.
- Safe cleanup retries transient status/busy/unreachable conditions within a 15-second retry budget. Every retry invokes the same existing guard. Genuine operation/archive/delivery checks stay intact; there is no kill, forced deletion or private-operation replay. Unexpected/permanent failures retain protected RAM and the existing recovery flow.
- Sync logs include authoritative revision and send/receive/disabled/visible counts. Enabling a denial entry logs restored request counts and explains if Dashboard has supplied no current request. No descriptors, addresses, signing keys, credentials or complete requests are added to logs.

## Checks

78 targeted tests, 16 real offscreen Qt/framed-socket tests and ten JavaScript suites pass. A same-wallet private-result fixture still refuses close and does not set the node stop event. Tests simulate status/cleanup contention and late HTTP replies; installed target-machine cleanup still needs confirmation. No production services, wallets or denial preferences were modified.

No new Dashboard message kind/schema is required. The server-side empty/stalled queue correction belongs to Dashboard's concurrent build; upgrading Agent alone cannot repair a request not offered by the server.
