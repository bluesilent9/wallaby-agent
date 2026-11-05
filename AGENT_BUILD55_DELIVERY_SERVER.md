# Build 55: signing delivery, disc countdown and server fallback

## Investigation and limits

The supplied Agent log records review at 20:52:13 UTC and wallet.sign completion at 20:52:39 UTC on 4 November 2026. This was within the review period. That older completion log did not prove either that Core added a signature or that Dashboard acknowledged it. The supplied Dashboard log does not identify a signature receipt or refusal for that attempt. The user subsequently cancelled the transaction and closed the workspace. Its original result is not available for inspection.

Neither chat reproduced the live failure. Interoperability checks exercise the real Agent signing code, disposable Bitcoin Core keys, HTTP exchange and Dashboard’s cryptographic result validator for single signature, multiple recipients and two distinct multisig signers. All become signed on Dashboard. A lost HTTP acknowledgement is simulated after Dashboard stores the result: resending the identical result succeeds without asking Core to sign again. Fixtures use invented transactions with injected previous-output history and test-only keys; no live funds, wallet files, node services or pending requests are touched. These successful tests do not establish the exact cause of the original failure. Dashboard Build 62 adds complementary request/receipt/rejection diagnostics.

## Agent changes

Core must return a new nonempty signature field for a locally matched signing input. Otherwise the Agent gives an authored transaction_no_signature error, retains the request for explicit review and sends no signing result. Core is relocked. Existing transaction, input, output, fee and review-expiry checks remain enforced; Dashboard still cryptographically validates the returned signatures.

Publishing the immutable signing result and its completed local record now occurs in one locked store transaction. This prevents acknowledgement from racing the creation of the local delivery record. Signing results are prioritised over background outbox notices. Valid acknowledgement is recorded before applying unrelated new proposals, so a bad proposal cannot obscure a valid delivery receipt. Unexpected local failures outside the usual exchange error handler no longer silently terminate the delivery thread; only data delivery is retried. Signing and broadcasting operations are not automatically replayed.

The protected Authorise page shows Signed — waiting for Dashboard until the exact result is acknowledged, then Dashboard acknowledged signed transaction. It does not navigate away to the unavailable protected Services page. Native signing success now says queued, never returned before acknowledgement. Bounded logs identify signature queueing, first send and acknowledgement using only a request reference and field count; no PSBT, private key, passphrase, address, amount or transaction content is logged. Per-session send logging memory is bounded; UI receipt history is limited to 16 entries. Acknowledgement means receipt of the result, not a broadcast or confirmation.

## Disc ETA

Once a measured estimate exists, its remaining seconds decrease between physical progress reports, including reports older than 30 seconds. A small browser timer also advances the display between status polls. New reports replace that estimate using the updated rate. Each stage resets separately. No estimate is invented before measured progress exists. At estimated zero the display says finishing; only the actual writer/read-back outcome establishes completion. Percentage bars remain based on reported bytes, never elapsed time.

## Initial server SSH only

A dedicated server_connector resolves and tries IPv6 first, reserving part of a bounded ten-second connection attempt for IPv4 fallback. Both address families use Ubuntu systemd-resolved over local IPC. IPv4 is tried only if an IPv6 TCP connection is unavailable; authentication/host-key refusal does not trigger another route. The connected socket is passed to OpenSSH, which still authenticates the original configured hostname with StrictHostKeyChecking, BatchMode, no forwarded SSH agent, and no remote shell.

Only wallaby-agent-monitor.service receives AF_INET permission because it owns the single server SSH master. Every other user and protected service retains its existing address-family restrictions. Dashboard/DDNS/node tunnel listeners and destinations remain explicit [::1]; Bitcoin Core RPC and local HTTP are unchanged. Multiplexed forwards attach to the same authenticated master. Peer discovery and synchronisation continue using the IPv6-only resolver. Server status reports the address family actually used. The server hostname must of course have an accessible address/listener in the family selected.

## Validation and upgrade

Checks cover IPv6 preference without even resolving IPv4 on success, unavailable/missing IPv6 fallback to a real IPv4 socket, native resolver family filtering, both-family failure, actual IPv4 socket handoff, host-key/hostname preservation, existing IPv6 listeners and peer routing, signing acknowledgement/retry/prioritisation, recovery from a stopped delivery worker, rejection of Core returning an unsigned PSBT, and ETA corrections. Generated service permissions are inspected to ensure AF_INET is granted only to the server monitor.

Finish active protected work and close normally before installing. For further signing tests, use Dashboard Build 62 alongside Agent Build 55 so both sides record the handoff. If delivery stays queued, keep the workspace open and export both logs; do not sign the same request repeatedly. This build does not modify or revive the previously cancelled transaction.
