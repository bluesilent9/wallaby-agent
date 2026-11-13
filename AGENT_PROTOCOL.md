# Current communication protocols

The supported deployment baseline is Build 88 and newer. Protocol version numbers describe individual message/data formats, not Agent release numbers. A version-1 envelope can therefore still be the current format.

Server exchange and public read-only RPC use `agent_exchange.py`, `agent_rpc.py` and `public_policy.py`. The Server discovers wallets and signals work; it does not confer local signing authority or supply trusted wallet-history comparisons.

Local protected UI requests are authenticated through `app.py`, `secure_bridge.py` and `secure_worker.py`. Keys, wallet mutations and approvals stay inside the protected worker. Native prompts handle passphrases. Diagnostic exports contain sanitised operational evidence.

QR pairing accepts the current version-3 scan-connect invitation, with signed typed device identities and the Noise transcript validated in `peer_channels.py`. Saved pairings retain pinned identities. Authenticated heartbeats carry the current device name and supported optional features. Agent and Mobile permissions remain distinct. Old version-1/2 QR workflows are rejected.

Direct SSH transport, identity pinning and reconnection are defined in `direct_protocol.py`, `direct_peers.py` and `direct_ssh.py`. `relay_stream.py` transports bounded streams only over the authenticated direct Agent channel. The Server relay is used to establish/maintain connectivity, never to transport wallet files or blockchain bulk data.

Current extinction requests use version-3 separate preserve/delete phases defined by `retirement_phases.py`. Old combined retirement requests are rejected. Core transaction/address comparisons are local or directly peer-authenticated. An unavailable peer leaves the preservation warning; it cannot grant or prevent deletion by itself.

Direct wallet/history transfers retain current signer-role, policy, private/watch-only and LOST metadata checks. Blockchain downloads and cloning retain source/receiver chain and history checkpoints. Existing physical recovery discs, saved wallet policies and persistent security preferences remain readable; removing old network workflows does not erase or invalidate those data formats.
