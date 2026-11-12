# Build 83: switch required history recovery to a direct clone

Install Build 83 on both Agents after closing their protected workspaces normally. Both nodes must use the same Bitcoin Core 31 release. Existing Wallet Server discovery/signalling is sufficient; this build does not require a new Server protocol. Bulk blocks and public wallet history travel only over the locally paired authenticated direct SSH connection.

## Requested Australia workflow

1. Finish extinction and the whole legacy Extinct upgrade on wallet-laptop. Keep its complete Extinct wallet loaded and enable its one-use trusted clone source permission.
2. Receive that Extinct wallet on Treasury Australia through normal approved direct wallet sync. If the Agent requires complete history recovery, that request is supported; recovery may already have started.
3. On Synchronisation → Blockchain, choose **Switch pending/running recovery to a trusted clone**. This pauses the existing recovery at a safe boundary and disconnects Internet peers. It does not authorise a clone or clear pending work. Wait for the paused state.
4. Select wallet-laptop, review the exact source, chain checkpoint and public history counts, and approve the clone. The receiver keeps its own signing wallets and receives the source's cold blockchain state plus the exact required public Extinct history.
5. Completion requires Core to open the clone, retain original wallet records, catch up all loaded wallets, and validate the required Extinct records, labels and coverage. Existing local preservation consent continues automatically. Deleting an old wallet remains a separate local approval with evidence and samples. Receiver Internet peers remain paused until explicitly resumed.

A cloned current tip alone never completes an extinction/history request. Missing source archive coverage, conflicting LOST labels, withdrawn requests, changed jobs or failed history checks leave the affected jobs pending. A chain clone may have succeeded even when subsequent history verification failed; the page reports failure rather than certifying incomplete history. No automatic full-download fallback or wallet deletion is authorised.

## Reindex and retained local wallets

Before a Build 83-authorised recovery resets the chain, the Agent captures public evidence for each current original wallet: public descriptor identity, signing capability, existing raw transaction hashes and Core scan locators. Temporary RAM wallet backups used to read that evidence are removed. No signing key is sent to the source or stored in the public checkpoint.

If reindex has reset the receiver's chain progress below the source's pruned range, a clone is allowed only when this prior local evidence still matches, the source proves the same original chain anchor and the original transactions remain present. The local cold helper may restore only Core's exact `bestblock` and `bestblock_nomerkle` records from that evidence. It verifies the original wallet policy/capability again with Core stopped and hashes every other database record before and after: keys, descriptors, labels and transactions are not replaced. Core may subsequently extend its own keypool normally, but descriptor replacement, range shrinkage and address-index rewind are refused.

A recovery started by an older Agent or manually before this checkpoint existed cannot be assigned invented scan evidence. If a safe pruned handover cannot be established, the operation refuses and keeps recovery pending. Pending recovery before the reset can still use the ordinary current-chain anchor.

Local retirement can queue both the public Extinct job and original private/watch signer jobs. Build 83 accepts the latter only when they belong to that exact locally approved preservation request. Their existing public policy, signing capability and original transaction records are verified; remote private keys are never imported and participation by every multisig signer is not required. General private/ranged incoming-wallet recovery is not silently converted into public archive recovery.

## Failure and operational limits

The pre-existing full/pruned compatibility, chain/network, supported native/Snap layout, index and disk-space checks remain. A receiver ahead of its source is not rolled back. A pruned source cannot supply absent blocks for an unproved historical replay. Source archive export is bounded and requires complete history evidence for all requested addresses; unknown local addresses, changed labels or missing records must be resolved rather than overwritten.

The source and receiver use independent Core restarts; the source restores its previous network setting, while the receiver remains isolated from Internet peers. Cancelled/disconnected operations retain recovery jobs, original wallets and the old blockchain backup where reconciliation is necessary. A process kill or power failure at an uncertain commit still requires local inspection; automatic replay is not promised.

## Validation

Tests use actual isolated Bitcoin Core 31 wallets, genuine source pruning, genuine receiver reindex and paired direct SSH. They verify handover before recovery starts, during recovery, after chain reset, retained original-key signing, public transaction/LOST merges, automatic preservation continuation, separate deletion, connection failure and failed history verification. Additional tests cover exact locator updates/undo, policy/capability refusal, descriptor range growth without rewind, relay/Mobile restrictions, job cancellation and the UI's explicit two-step pause then clone approval.

Desktop systemd launch is replaced with independent isolated Core child processes in these fixtures. Production wallet files, installed user services, Snap confinement, real Wi-Fi throughput and power-loss recovery have not been exercised on the user's laptops. Package checks verify the installed source/UI/document bytes, matching Build 83 versions and root-owned non-writable runtime files.
