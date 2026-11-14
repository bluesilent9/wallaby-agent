# Current communication protocols

The supported deployment baseline is Build 88 and newer. Protocol version numbers describe individual message/data formats, not Agent release numbers. A version-1 envelope can therefore still be the current format.

Server exchange and public read-only RPC use `agent_exchange.py`, `agent_rpc.py` and `public_policy.py`. The Server discovers wallets and signals work; it does not confer local signing authority or supply trusted wallet-history comparisons.

Local protected UI requests are authenticated through `app.py`, `secure_bridge.py` and `secure_worker.py`. Keys, wallet mutations and approvals stay inside the protected worker. Native prompts handle passphrases. Diagnostic exports contain sanitised operational evidence.

QR pairing accepts the current version-3 scan-connect invitation, with signed typed device identities and the Noise transcript validated in `peer_channels.py`. Saved pairings retain pinned identities. Authenticated heartbeats carry the current device name and supported optional features. Agent and Mobile permissions remain distinct. Old version-1/2 QR workflows are rejected.

Direct SSH transport, identity pinning and reconnection are defined in `direct_protocol.py`, `direct_peers.py` and `direct_ssh.py`. `relay_stream.py` transports bounded streams only over the authenticated direct Agent channel. The Server relay is used to establish/maintain connectivity, never to transport wallet files or blockchain bulk data.

Current extinction requests use version-3 separate preserve/delete phases defined by `retirement_phases.py`. Old combined retirement requests are rejected. Core transaction/address comparisons are local or directly peer-authenticated. An unavailable peer leaves the preservation warning; it cannot grant or prevent deletion by itself.

Direct wallet/history transfers retain current signer-role, policy, private/watch-only and LOST metadata checks. Blockchain downloads and cloning retain source/receiver chain and history checkpoints. Existing physical recovery discs, saved wallet policies and persistent security preferences remain readable; removing old network workflows does not erase or invalidate those data formats.
# Build 95 direct Extinct history snapshots

The receiver advertises `core_history_v3` on the already authenticated, approved Agent-only wallet stream. V3 carries the same bounded, signed native transaction packet as V2 and permits exact stored-history coverage with `basis: trusted_direct_snapshot` when the source has no local whole-scan receipt. This basis is preserved inside Core's public archive and across further transfers. It is an explicitly trusted source assertion, not an independent historical scan or a transaction-discovery proof. V3 is rejected outside the current paired direct transfer protocol. The Server carries no transaction records or authority for this decision.

Coverage checks accept optional `basis` values `local_scan` and `trusted_direct_snapshot`; absence retains the existing local-scan meaning. Both bases remain bound to the exact address/transaction inventory, checksum and locally validated active-chain anchor. All native transaction records and LOST labels must pass normal readback. Previously unknown entries may be imported under this direct approval, while active local owners and recipient-only uncovered entries still block the merge. Pruned full block data is unnecessary when both nodes already validate the relevant chain and the sender retains the native wallet records. Missing chain ranges, missing source transactions and unconfirmed history remain separate failures.

