# Agent V2 Build 29 synchronisation recovery

The supplied 2 November logs show two separate causes. Before clearing the Dashboard profile, Dashboard records `peer_changed:22` for the sender and `peer_changed:11` for recipients: frozen IPv6 endpoints no longer match the same nodes' currently advertised addresses. Dashboard Build 33 handles safe fresh endpoint-bound requests. After clearing the profile, all three Dashboard queues restart at revision zero, while Agents repeatedly reject `exchange_sync_revision`. Wallet-laptop had retained revision 15; its local exclusions were zero. This is not an Ownership prerequisite or a local denial.

## Agent corrections

Exchange associates a sync-list baseline with a hash of the authenticated connection token, never the token itself. Fully schema-validated queue responses from a fresh authenticated session can rebase the revision counter. Existing pending, attempted, active, completed, signed-review, outbox and denial data are retained and reconciled by the normal authoritative snapshot rules. Only unattempted withdrawn offers can be removed. Already attempted operations stay for reconciliation. Repeated same-session rewinds or changed contents at the same number are refused; recent retired session hashes prevent a delayed old exchange from switching the baseline back (bounded to 128, in RAM only). Production Dashboard invalidates old tokens on reset.

Identical snapshots are reapplied idempotently so that local dismissal of an unattempted offer does not hide active remote work indefinitely. Local receiving-policy exclusions remain authoritative and do not apply to other peers. Completed and attempted operations are never recreated or reauthorised. Rejection diagnostics now distinguish previous/incoming numeric revisions; successful snapshots report session rebasing without tokens, wallet contents or endpoints.

A batch whose selected requests are withdrawn reports its partial completion count instead of returning without an explanation. Credentials are cleared in all cases; withdrawn operations are not transmitted or replayed. Dashboard Build 33 also retains already-offered requests across a routine permission-refresh delay, while the Agent continues enforcing its live local exclusions.

No changes grant Dashboard mutating Core RPC. Local fingerprint comparison, exact signed-review/challenge/endpoint binding and live sender/receiver Core checks remain required. An IPv6 change needs a newly bound review; existing local authority cannot silently migrate to another address. Only Dashboard source is responsible for scheduling absent-wallet offers and Ownership navigation; Agent never invents a missing peer request.

## Testing

`tests/test_build29.py` reproduces the exact revision-15 -> new session revision-zero lifecycle and unchanged-list dismissal. Both tests fail against Build 28. It also covers same-session rollback/content rejection, delayed retired sessions, malformed-response rollback, retained active/completed/outbox/denial state, receive-policy isolation and token exclusion.

`tests/integration_sync_cluster.py` uses three independent Agents, three real isolated Core 31 regtest nodes and production Dashboard HTTP/RPC/queue/signature/permission handlers. The profile-reset case uses production `ProfileArchive.replace()` plus `NodeRegistry.reset()` while all three Agent processes remain alive, with no Ownership assignments and no local denial list. Discovery must rebuild 22 sending rows and 11 rows per recipient. It also checks policy disable/re-enable isolation, receiver reconnects, long-lived previews, Dashboard restart, matching independent review codes and actual wallet transfers/receipts.

Test adapters are limited to regtest network constants/health, synthetic machine identities, SSH readiness and a same-user relay replacing authenticated SSH transport. This does not test real IPv6 routing, SSH passwords, host/modem firewalls, installed systemd/Polkit/AppArmor or protected RAM evidence. No production wallets, coins, services or settings are touched.

## Final results

392 full regression tests passed, then 50 focused tests passed after the last partial-batch reporting refinement. Sixteen Qt/socket checks and ten JavaScript suites passed. The final three-Agent/three-Core run passed all 22 deliveries (11 per receiving node), all 22 independent review-code comparisons, empty final queues and cleared credentials, following live profile reset, same-node IPv6 rotation, preview ageing and Dashboard restart. Runtime fixture hashes match Dashboard Build 33. Earlier diagnostic runs are retained locally; the exported integration result and validation log identify the final passing run.
