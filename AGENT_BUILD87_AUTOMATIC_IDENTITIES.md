# Build 87 — automatic identity verification through direct Agent connections

Manual Agent and SSH fingerprint entry is removed from approval screens. QR pairing establishes local peer trust; subsequent remote identity checks use the authenticated paired Agent and its live direct SSH connection. Wallet Server names, keys and matching text entered by a user cannot establish that trust. Local approvals for wallet deletion, policy installation, receiving wallets and physical disc destruction remain separate.

## Wallet deletion

The deletion screen retains the exact wallet list, independently checked transaction/address samples, LOST labels, zero-balance checks, shared-signer retention and explicit deletion approval. It displays neither the preserving identity fingerprint nor a manifest code for the user to transcribe. The deletion API accepts the reviewed request ID without a fingerprint field.

The Agent rechecks the signed receipt, actual local wallet, policy, balances, history and filesystem targets. When complete preservation is verified in a local Extinct wallet, deletion does not require another Agent to be online. Otherwise, the preserving identity is verified through its paired direct connection, and the existing warning says the history should already have been preserved in another node's Extinct wallet. No extra checkbox is added. Other missing multisig signers are not required to retire an empty wallet.

## Other operations

- Producing Agents agree on the exact setup/policy through their authenticated direct channels. Older saved setup proposals also use this agreement instead of manual pins; local-only producers are checked locally. Server relay traffic cannot supply a policy agreement. Missing, mismatched or changed channels stop approval before key generation or installation.
- Foreign archive cancellation, replacement and extinction-disc cleanup verify the original disc author and preserving identity through local pairing and a live direct Agent channel. Original-disc reads, complete membership, replacement read-back and physical destruction confirmation remain required. A typed hash cannot bypass an unavailable peer or an unread disc.
- Current receiver-initiated wallet transfers already bind the signed preview to the paired sender. Receive approval now has no fingerprint fields. Legacy username/password/fingerprint sending is removed; old requests without the authenticated direct transport must be refreshed through the current direct-sync flow. Actual wallet data never falls back to the Server relay.
- Identity confirmation is Agent-only. Pairing a Mobile does not grant Agent policy, wallet transfer or disc-author authority. Revoked pairings and unavailable direct links do not gain a manual override.

Install Build 87 on the Agents participating in these operations. Existing QR pairings are retained; reconnect them in Peer Connections if necessary. No new Wallet Server protocol is introduced, and no Wallet Server update is required for current direct-sync requests. Bitcoin addresses and optional public policy detail remain visible for review; cryptographic verification is retained internally.

## Validation

Tests use real isolated Core 31 wallets and a real Wallet Server HTTP listener with two QR-paired Agent processes and direct SSH. They confirm exact policy agreement, disagreement refusal and refusal after direct disconnection. Separate tests cover local self-identity, paired Mobile restrictions, substituted/revoked peers, direct-only policy records, no manual bypass before key generation, disc-read retention, fingerprint-free API fields and invalid receipt signatures.

An actual empty private wallet is deleted without a fingerprint only after local Extinct history comparison, and the archive transaction count remains unchanged. Changed raw transaction data, missing records/labels and absent local archive evidence are still rejected. Multisig extinction with missing private signers and cancellation during original-role capture are rerun. Existing receiver-initiated private/watch, multisig, old vault policy and batch transfer tests, clone/history recovery and UI checks are retained. Logs list the exact checks and outcomes.

Fixture limits: test Core data is isolated, native prompts are rejected or explicitly mocked, and independent fixture Core processes stand in for desktop systemd restart services. The user's host systemd/cgroup/mount/inhibitor configuration is not recreated. Identity unit tests use real paired Noise identities with controlled direct availability; the process integration test exercises actual direct SSH. No production wallet or attached log is uploaded.
