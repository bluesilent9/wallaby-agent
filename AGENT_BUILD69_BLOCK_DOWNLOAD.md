# Build 69 — progressive blockchain download over direct SSH

## Local workflow

Install Build 69 on both paired Agents. On the source, open Synchronisation and enable **Allow paired Agents to download this node’s blocks**. This local grant lasts only for the protected workspace; it exposes public blocks, never wallets or private keys.

On the receiver, choose that Agent under **Blockchain over direct SSH** and select **Prepare receiver — pause Internet peers**. This disables Core P2P networking and records SSH-only intent. Preparation does not reindex, invalidate, delete or rewind blocks. A disconnected, independently pinned source may be selected before it comes online.

If an operation requires historical replay, separately review/authorise recovery on **This Node**. Its plan binds the SSH-only choice, retains the highest previously known target height and uses the existing guarded `-reindex=1 -networkactive=0` restart when actually required. Wallets/vault monitors are registered before incoming replay blocks can be pruned. The plan cannot silently enable Internet peers after preparation. If the selected source mode changes after review, the plan must be reviewed again.

Select **Start receiving blocks** when ready. The receiver waits for a usable paired direct connection and the source’s local serving grant, then requests successive snapshots of its available validated blocks. It can start while the source is behind, at genesis, or still downloading/reindexing. Existing receiver blocks remain intact. When a behind source has nothing new to provide, reception waits; it does not force a shorter chain or initiate a reindex. Core’s own validation and chain selection remain authoritative.

The source may be the SSH client or server. An Agent may simultaneously receive from one source and serve onward to another Agent. Internet peers stay paused on SSH receivers, allowing a daisy chain. Reconnection/retry applies only to this explicitly started public-block session, not wallet operations. Stop receiving retains validated blocks and leaves Internet peers paused. **Resume Core Internet connections** is a separate local action, disabled during reception and refused before replay wallets are registered.

## Transport and validation

The existing QR-pinned Agent channel and restricted direct SSH subsystem carry `stream_open` with an exact random `block_request` token, bound to `digest({chain_download_v2: token})`. The source accepts at most one concurrent serving stream, only with its local serving grant. Mobile roles cannot serve/request blocks. Every `stream_*` record remains forbidden on the Wallet Server relay; there is no bulk relay fallback or arbitrary remote RPC execution.

A block-only round uses the existing bounded common-ancestor locator and validated block protocol, with hello version 2 additionally carrying `source_syncing` and `source_headers`. The source freezes its current validated tip for that round. Blocks are bounded to 4 MiB; direct reads are bounded to 1 MiB and stream acknowledgements use the existing four-chunk window. The receiver checks header hashes, uses Core `submitblock`, checks heights and the final active-chain hash, then waits for the next round. It records only current progress, not per-block history lists. Source reorgs, unavailable/pruned blocks, failed validation and disconnections cannot enable Internet fallback. A confirmed missing pruned range stops receiving with an explicit local message. Retired stream identities keep bounded channel/operation bindings for 60 seconds so late close/acknowledgement frames cannot tear down the direct connection. Wallet transfer retains its complete-source requirement; incomplete sources use the separate public-block controls.

No Wallet Server or Dashboard protocol update is required. Both Agents need Build 69 for the new standalone block request. Existing wallet/direct transfer protocols and saved pairing identities are retained.

## Limits and device testing

A pruned source cannot supply an already missing range. It must retain the needed range as replay progresses, or another suitable source is required. This release does not change pruning limits or promise that a slow receiver can recover a range already pruned by the sender. “Available source blocks checked” does not mean the source has reached the current global network tip. Synchronisation status remains relative to locally known chain evidence.

SSH-only intent and serving permission are scoped to the protected workspace. Core is started with networking disabled during a reviewed replay; an active guard also keeps networking paused while that workspace is open. Stopping reception or closing an idle workspace does not silently restore Internet networking. A new workspace requires fresh receiving/serving actions.

Tests use isolated Core 31 regtest directories and loopback SSH, never production wallets/services or Bitcoin mainnet downloads. They cover shorter/genesis/IBD sources, retaining an ahead receiver’s chain, source pruning gaps, wrong hashes, interruptions, explicit Internet resumption, bound recovery plans and real replay-wallet registration while offline. Real Paramiko tests cover progressive rounds in both SSH orientations and three-Agent daisy chaining. Existing single-signature, original multisig signer and watch-only vault direct transfers remain tested. Browser tests cover Prepare/Start/Stop, local serving, disabled Internet resume, formatted heights and source selection. Actual long-running mainnet/mobile-data use still requires laptop testing.
