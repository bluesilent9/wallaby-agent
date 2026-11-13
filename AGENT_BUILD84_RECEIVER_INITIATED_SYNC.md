# Build 84: the receiving Agent starts trusted direct transfers

Install Build 84 on both Agents, closing their protected workspaces normally before updating. Keep the source protected workspace running and its trusted direct SSH connection available. The existing Wallet Server discovery/signalling protocol is sufficient; no Server update is required for this change.

## Behaviour

* **Blockchain clone:** review and approve the exact source on the receiver. The paired source serves it automatically when idle. There is no sender arming checkbox or one-use source approval. Core on the source briefly stops and restarts independently as part of the cold snapshot. Receiver-side review, chain/wallet compatibility, disk-space checks, recovery handover and separate old-wallet deletion approval remain.
* **Direct block download:** prepare and start receiving on the receiver. The paired source supplies its available blocks automatically, even while catching up itself. The receiver retains valid newer blocks if the source is behind. A pruned source still cannot supply blocks it no longer holds. Internet fallback stays disabled unless the receiver explicitly resumes it.
* **Wallet transfer:** select the source and private/watch-only choice on the receiver, review its signed public preview and authorise receiving. A direct authenticated request starts the exact matching source transfer automatically. The sender does not need to select the wallet or click Send. Multi-wallet batches request one wallet at a time and preserve each receiving choice independently. Sending rows describe the receiver-controlled operation instead of displaying sender approval controls.

Sources may refuse work that conflicts with active operations, withdrawn requests or changed wallet evidence. Such refusals are displayed on the receiver; they are not requests for sender approval and are not silently retried. Legacy transfers without the independently paired direct connection retain their credential-based workflow; pairing is not inferred from Server discovery.

## Authority and data checks

The existing independently approved permanent Agent pairing now authorises automatic service of these receiver requests while the protected worker is running. Removing that pairing revokes the device's access. The receiver still approves each clone, starts its block session, or approves its exact wallet batch locally. Server signalling, an arbitrary destination address, a mere wallet listing and Mobile pairing cannot initiate an export.

The new direct-only wallet request binds the pinned channel, exact transfer operation, wallet/challenge/destination, signed preview hash, unique request token and receiver's watch-only choice. The source needs the matching current pending offer and verifies its live Core facts through the existing transfer path. Watch-only replies cannot be upgraded to private exports. Private-wallet backups still require a locked encrypted source and the existing signer/restoration rules. No wallet is unlocked automatically and managed vault signer restrictions are retained.

The request and response use the direct-only stream message family. Relay-delivered bulk/control requests of this family are refused. Closed or mismatched operations, malformed choices, duplicate tokens and substituted identities do not authorise a send. Pending jobs and lifecycle denials retain their existing meaning. A late response for an already finished wallet does not change the next receiving operation.

## Validation and scope

Isolated actual Bitcoin Core 31 wallets and real paired SSH cover receiver-only single-signature transfers, multisig/original-role restoration, watch-only choices, public vault watch sources, two-wallet batches, busy/withdrawn/changed-preview refusal and refusal of unlocked private sources. Clone tests remove sender arming and cover pending/running recovery, a genuinely reindexed receiver, retained signing, interrupted handover and failed history verification. Block tests remove sender serving switches and cover both SSH orientations, a behind source, real three-Agent daisy chaining, pruning gaps and Internet isolation.

Additional regression suites retain native Extinct history/LOST handling, wallet scan-checkpoint protection, startup, pairing attacks, Mobile restrictions, release labels and UI approval/deletion checks. Desktop systemd launch is replaced with independent isolated Core processes in clone fixtures. Installed Snap/service behaviour, real Wi-Fi throughput and production laptop wallets were not exercised or changed by these tests.
