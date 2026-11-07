# Build 65 — restore original signer roles over direct SSH

Build 64 correctly blocked ordinary managed-signer replication, but also blocked restoration of an original managed role. Build 65 adds a narrowly scoped path rather than removing the cloning prohibition.

## What is checked

Before a separate, locally approved extinction deletion, the Agent records each local wallet's full public-policy identity and the identities of its private-key records. These are public identifiers hashed with the Core descriptor identity; private record VALUES, wallet passwords and transaction history are never stored in the preference ledger. The reader works with encrypted Core 31 descriptor-wallet backups without unlocking them. It includes inactive/historical vault policies, HD accounts and static keys. Two wallets with identical public descriptors but different private keys have different role bindings.

A fresh paired v2 SSH invitation must carry `restoration={version:1,policy_id:<existing normalized public policy digest>}`. The signed initial preview must contain the identical object. Dashboard cannot add this purpose to an old ordinary-sync review. Both peers require Build 65, and the independently pinned SSH host identity and sender Agent preview fingerprint remain mandatory.

The receiver checks its own durable original assignment before authorising receipt. Over the authenticated SSH stream it offers a fresh, transfer-bound original-role permit. Immediately before transmission, the sender checks the exact encrypted Core backup against that permit. Before loading it, the receiver repeats the key-ownership check. Different, extra, missing or plaintext private keys are refused. Core then independently checks the complete public policy, encryption, historical data and current-chain checkpoint. Wallet names do not confer authority. Unknown legacy assignments are blocked, not filled in from Dashboard assertions.

The complete original public descriptor set is required, including previous vault heights. Updating a role's password or address index does not change its identity; adding another private signer does. The transfer keeps the original key set rather than collecting a signing quorum on the recipient. Each original role is independent. A successful role immediately restores local active status; other missing roles remain pending and do not block it. This does not claim that the remaining signers can satisfy the wallet's spending threshold.

Temporary physical-only disc signers retain their existing protected-RAM and physical-recovery restrictions. This exception does not convert them into permanent node wallets or copy all cosigners to every node. Existing active managed accounts continue to be blocked from ordinary replication.

## Watch copies

After Dashboard has observed a qualifying private source, other Agents may receive watch-only copies. For an explicitly chosen watch restoration, Build 65 constructs a NEW public-only SQLite snapshot from a consistent Core backup. It copies only an explicit Core 31 public-record allowlist and disables private keys. Private/encrypted/master-key records never enter the new database, including deleted/free pages. The receiver verifies that allowlist and the private-key-disabled flag before Core loads the snapshot. Current and older policies, transaction history, address labels and LOST metadata remain inside Core. A watch snapshot cannot recreate private keys and never qualifies as the first private restoration source.

## Extinction with lost signers

Extinction does NOT require every signer, a signing quorum, wallet unlocking or Bitcoin signatures. The existing v3 preservation receipt and separate zero-balance deletion safeguards remain. Role capture inspects only available local wallets; missing/offline/lost signers are not requested. A watch-only node with no Bitcoin private keys can preserve complete history and delete its own empty old copy. Signed Agent receipts use the Agent identity, not Bitcoin spending keys.

After recording the local role information, the Agent repeats cancellation, funding, history and deletion-target checks before unloading wallets. A Restore/cancellation arriving during that step cannot silently lose its protection.

## Compatibility and evidence

Dashboard Build 90 implements the matching restoration proposal/preview fields and preserves per-node assignments across the lifecycle. Its desired Active/Extinct classification remains separate from the actual locally approved work. Agent 64 cannot consume the new invitation fields. Build 65 accepts older preference records, but a pre-65 deletion that retained no role evidence cannot safely be treated as proof of which private signer used to belong to that Agent. Original local assignment/recovery evidence is needed; the program will not guess. Persistent role records add fields older builds do not understand; keep the matching new Agent build when using them.

Core 31 format references: [descriptor key records](https://github.com/bitcoin/bitcoin/blob/v31.0/src/wallet/walletdb.cpp), [wallet flags and descriptor serialization](https://github.com/bitcoin/bitcoin/blob/v31.0/src/wallet/walletutil.h). Only offline backup files in protected non-swapping RAM are inspected/constructed; no open wallet database is modified.

The distribution test log covers HD and static single-signature/multisig/old-and-current-vault restoration, real partial signing by only the original role, receiver and production-sender rejection of a different role, independent missing roles, public snapshots, durable metadata and extinction with no local private signers. Core fixtures and passwords are invented regtest data; no live wallet, service or physical disc was changed.
