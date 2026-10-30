# Dashboard handoff — Agent V2 Development Build 9

Dashboard V1 Build 11 now implements and tests this protocol: Wallet Builder, authenticated contributions/policy/physical-backup completion, per-input signature thresholds, intentional cosigner grouping and retirement inventory refresh. The Agent remains V2 Development Build 9. Its guided encrypted-disc restore/signing screen is not yet implemented; Dashboard routes normal partial-signature requests after a matching account is restored locally. See the [Dashboard guide](https://github.com/bluesilent9/wallaby-dashboard/blob/Development/docs/WALLET_BUILDER.md).

## Existing exchange and retirement

The header is `X-Wallaby-Agent-Version: 2.0.0~dev9`. Keep the existing `/agent/v2/exchange` envelope, content-addressed outbox IDs, complete `wallet_sync_queue` revisions, immutable signed v2 previews, and paired transfer/recovery results. Build 9 advertises the existing supported capability `wallet_retirement` in addition to node_identity, partial_signing, broadcast and wallet_transfer. Do not add unknown capability strings to Dashboard Build 10's strict schema. Dashboard Build 11 schedules the setup messages below only for Agent version 9 or later. No older setup/backup fallback is provided.

The Build 10 `wallet_retire` proposal is accepted exactly as documented there: kind, version=1, request_id, wallet, public_wallet, archive_label, require_zero_balance=true, delete_wallet=false. request_id hashes the object before adding request_id; request_hash hashes the final complete proposal. RPC wallet names are only routing hints; the full public descriptor identity must match Core locally.

Authorise presents confirmed used receiving and change addresses and exact archive labels. Agent checks local history/tip and zero spendable, watch, immature, pending, locked, vault/shared-policy holdings. Existing per-address LOST records are preserved, never fabricated by retirement. It imports public checksummed addr() records into the private-key-disabled `Wallaby Extinct` archive. The original signing wallet is retained and remains loaded. Results remain `wallet_retirement_result` with request_hash and complete/denied/error. Dashboard refreshes actual Core inventory before changing the display; do not treat retirement as a loss declaration or a command to delete keys. Hide/group retired source policies without counting their historical archive as a second balance.

For shared-wallet retirement, Build 9 also accepts a private-key-disabled restricted shared policy only when its exact descriptors have actual matching local private signing accounts. Ordinary address-only archives do not qualify. Dashboard Build 11 also schedules retirement of matching shared-policy monitors through the normal local approval boundary.

If local pruned history cannot be established, the receiving user can record a local recovery requirement, then separately review/authorise This Node recovery. This cannot be initiated by Dashboard. Pruning mode and limit remain unchanged. Retirement needs another independent review afterwards; history recovery does not itself approve retirement.

## Obtain public Agent identities

Send only when supporting this protocol:

```
{kind:"wallet_setup_identity", version:1, challenge:64_LOWERCASE_HEX}
```

Agent replies with outbox kind `wallet_setup_identity`, payload a signed envelope:

```
{message:{version:1,challenge,public_key:"ssh-ed25519 ...",fingerprint:"SHA256:...",hostname},
 public_key:"ssh-ed25519 ...",signature:"BASE64_SSHSIG_ARMOURED_BYTES"}
```

Compare challenge, verify signature and ensure public_key equals message.public_key and fingerprint. Names, self-signed discovery and Dashboard account ownership are not independent authentication. Users compare each full fingerprint directly on the corresponding Agent or through another trusted channel. The Agent shows its own identity in Services. Dashboard stores only public identities; it never gets the Agent identity private key or any Bitcoin key. Agent identities are distinct from server login keys and Bitcoin signing keys.

All setup envelopes below use canonical UTF-8 JSON: sort_keys=True, separators=(",",":"), ensure_ascii=True, allow_nan=False. Signature namespace is **wallaby-wallet-setup-v1**, separate from wallet-preview signatures. Sign/verify using OpenSSH SSHSIG with Ed25519; signature is base64 of the entire armoured SSH signature file. Content-address the *whole outbox kind/payload* using the existing exchange rules. Verify signatures in Dashboard too, but each Agent independently re-verifies everything. Dashboard is only a courier.

## 1. Participation proposal

Deliver this public object to all selected participating Agents (and physical-proposal observers as appropriate):

```
{kind:"wallet_setup",version:1,session_id:64_LOWERCASE_HEX,
 chain:"main"|"test"|"signet"|"regtest",name:"Display name",
 threshold:M,
 cosigners:[{id:"stable-safe-role-id",name:"Display label",
             agent_key:"ssh-ed25519 ...",storage:"node"|"disc"}, ...],
 height:null|BLOCK_HEIGHT,expires_at:UNIX_SECONDS}
```

Use a fresh random session_id. Expiry is a future integer no more than 24 hours away. M and N count **independent keys**, with 1 <= M <= N <= 15, not computers or copies of the same key. IDs are unique, immutable, at most 64 characters; names at most 128 characters. A height is an integer 1..499999999, not a timestamp. The chain is mandatory. No paths, private keys, passwords, RPC commands, spending scripts or arbitrary branches are allowed in this phase.

Each physical role has exactly one explicitly selected producing Agent. Do not generate that physical key on every observer. Multiple roles on one producing Agent still generate distinct keys, but the UI should explain the concentration of signing authority. Each physical cosigner gets its own disc. Never silently combine several independent physical cosigners on one disc.

Agent users review the complete proposal and independently enter every assigned Agent fingerprint, including the full role assignment and threshold. Only then does the local producer generate independent Core-encrypted signing wallets in protected RAM. Passphrases are native local input, never browser or Dashboard fields. Agent uses its own random Core-generated keys; Dashboard cannot choose a seed or private key. Public account material is collected only *after encryption*. A producing Agent generates only roles whose agent_key matches its independently known own identity.

For every locally produced role, outbox kind `wallet_setup_contribution` contains a signed envelope whose message is:

```
{session_id,proposal_hash:SHA256_CANONICAL_COMPLETE_PARTICIPATION_PROPOSAL,
 cosigner_id,receive_key:"[fingerprint/84h/0h/0h]xpub.../0/*",
 change_key:"[fingerprint/84h/0h/0h]xpub.../1/*"}
```

Non-main networks use coin type 1 and tpub. Paths are fixed BIP84 account 0, branches 0/1 with an unhardened wildcard. Receiving and change keys must have the same account xpub. Repeated account keys across roles are rejected. Contributions are signed by that role's exact pinned producing Agent key. A locally approved observer emits a signed `wallet_setup_ack` with message `{version:1,session_id,proposal_hash,status:"participating"}` without generating a secret.

Freeze the proposal and contributions. A repeated unchanged outbox is idempotent. A changed contribution for an existing role/session is not a replacement; stop and reconcile locally. A cancelled/expired/lost setup needs a new session ID and local approvals, never automatic regeneration under the old identity.

## 2. Construct and deliver the complete policy

After every role has a verified contribution, construct receiving and change descriptors. Sort roles by **cosigner ID** and keep that key order. Plain single-signature uses `wpkh(KEY)`. Plain multisig uses `wsh(sortedmulti(M,KEYS...))`. A single-signature height vault uses `wsh(and_v(v:after(H),pk(KEY)))`. A multisig height vault uses `wsh(and_v(v:after(H),multi(M,KEYS...)))`. `sortedmulti` is an output-descriptor expression and cannot be nested as a Miniscript fragment; the vault uses `multi` with the deterministic cosigner order. Include descriptor checksums. No alternate branches, emergency bypass keys or Taproot key-path bypass are accepted by this version.

Deliver:

```
{kind:"wallet_setup_policy",version:1,proposal:EXACT_PHASE_1_PROPOSAL,
 contributions:[EXACT_SIGNED_ENVELOPES_SORTED_BY_COSIGNER_ID],
 receive_descriptor:"...#checksum",change_descriptor:"...#checksum"}
```

Every receiving Agent must already have locally approved phase 1 for that exact proposal. It verifies every contribution signature and producer assignment, checks its own contributions are unchanged, checks distinct accounts/branches/network/height, and independently reconstructs both descriptors. It compares Core's derived addresses with its own derivation at indexes 0, 1 and 10 on both branches. Unsupported policy forms are refused, not displayed as equivalent.

The common policy hash is canonical SHA256 of:

```
{proposal:EXACT_PHASE_1_PROPOSAL,
 receive_descriptor,change_descriptor,
 contributions:EXACT_SIGNED_ENVELOPES_SORTED_BY_COSIGNER_ID}
```

The Agent displays the hash, threshold, complete roles/fingerprints, network, mandatory height and six matching sample addresses. Users compare the complete hash/addresses across Agents and authorise this final policy locally. Reaching a vault height removes only the height restriction: M signatures are still required. Diagram editing restrictions alone are never the security check.

After approval, only node-assigned encrypted signing wallets are restored into the user's existing Core, and a separate public policy monitor is installed there. Disc-only private wallets are never restored into that persistent node. Ordinary encrypted node-wallet storage is an explicitly chosen destination; it is distinct from the physical-only never-staged-on-laptop-drive claim. Agent returns a signed `wallet_setup_ack` message `{version:1,session_id,proposal_hash,policy_hash,status:"policy_approved",backup:"pending"|"not_required"}`.

It also emits signed outbox `wallet_setup_inventory`, message:

```
{version:1,session_id,policy_hash,chain,monitor_wallet,
 signing_wallets:{COSIGNER_ID:EXACT_LOCAL_PRIVATE_ACCOUNT_WALLET_NAME,...},
 receive_descriptor,change_descriptor}
```

These public routing names identify *signing accounts*, not separate balances. Group the policy monitor/watch replicas as one shared wallet. Route signing requests to the associated private account wallet. Verify its actual public key contribution rather than assuming the monitor has private keys. Multiple replicas of the same key count as one cosigner.

## 3. Physical backup completion

Burn Disc remains inaccessible until phase 2 is locally approved for a local disc role. Each physical disc contains one Core-encrypted signing wallet, the complete public proposal and receiving/change descriptors, all authenticated contributions, the policy hash and a generic recovery utility. The whole package is additionally encrypted with AES-256-GCM and scrypt (N=131072,r=8,p=1); its passphrase is entered locally and kept separately. Recovery requires both the package passphrase and the corresponding Core wallet passphrase. Neither is stored on the disc or sent to Dashboard.

Agent only accepts blank write-once DVD-R/BD-R optical media and requires confirmation that it is an M-Disc in a compatible drive. Branding cannot be cryptographically verified by software. xorriso builds and writes from protected RAM. A direct aligned read-back of every ISO byte must match SHA256 before success. A failed/uncertain write or verification never produces success and never triggers a secret operation automatically again.

Each verified physical role emits signed `wallet_setup_ack`:

```
{version:1,session_id,proposal_hash,policy_hash,status:"backup_verified",
 cosigner_file:SHA256_OF_UTF8_COSIGNER_ID,image_sha256:64HEX}
```

Correlate cosigner_file with the corresponding role ID. Collect all required physical-role confirmations, not merely one success from a producing computer. Keep backup status pending until every assigned disc is verified. After every local assigned disc completes, the producing Agent stops its temporary Core and removes temporary key material from its RAM filesystem. A five-second Success display precedes the next physical role or closing the Burn Disc page.

Only mark the overall wallet ready after **all intended participants' matching policy approvals and all required authenticated disc confirmations** have arrived. Do not enable funding before that. Offer the approved receiving address and policy hash for independent Agent comparison. A disc is a backup, not a network signer: restore it into an appropriately protected trusted environment before using that key.

## 3a. Authenticated completion delivery

After collecting the final proofs, send to each Agent which locally approved this policy:

```
{kind:"wallet_setup_complete",version:1,proposal_hash:64HEX,policy_hash:64HEX,
 acknowledgements:[SIGNED_ENVELOPE, ...]}
```

The acknowledgement list is at most 64 envelopes. Include one matching signed `policy_approved` acknowledgement from **every distinct producing Agent key** and a matching signed `backup_verified` acknowledgement for **every disc role**. Every message must bind version=1, session_id, proposal_hash and policy_hash. Physical proofs also bind the SHA256 of the UTF-8 role ID and a 64-hex image_sha256. Reject unrelated signers, proposals, policies, roles and invalid signatures. Participation acknowledgements are insufficient. The Dashboard must not synthesize these signatures or replace missing proofs with a boolean.

The Agent requires an existing matching local approval, independently verifies every envelope and marks only the exact Core public policy monitor ready. This narrowly completes the previously authorised setup; it grants no private-key authority. Signing refuses pending generated policies. Public Core address-zero labels `Wallaby setup pending:HASH` and `Wallaby setup ready:HASH` preserve this state after the volatile Agent session ends; they are local records, not trusted Dashboard assertions. Deliver completion while the local approval record still exists. If that RAM state has been lost before completion, stop and reconcile locally; do not regenerate keys automatically.

## 4. Later transaction signing, broadcasting and monitoring

Retain BIP174 PSBT v0 and compose-before-sign. Every signer reviews the *same complete final transaction* locally, including all sending/receiving outputs, change and absolute fee. Sign only locally controlled inputs with ALL/DEFAULT; reject ANYONECANPAY and changed fixed vault intent. Agent enriches public scripts/origins from its own Core policy monitors and checks that the final locktime and sequence satisfy an approved mandatory height.

Build 9 can rediscover these restricted public policy/signing-account relationships directly from Core after an Agent RAM restart. Names are never ownership proof. Public policy monitors and intentionally retained encrypted signing wallets survive in Core; transient Agent approvals do not.

On Dashboard, count **distinct cryptographically valid cosigner signatures per input** against its actual script/threshold. A returned PSBT may contain only one of M signatures. A wallet card must not go green merely because one Agent returned a PSBT. Verify all signatures, matching unsigned transaction bytes, sighashes, previous outputs, witness scripts/key origins, and required vault conditions. Combine without changing any input/output/sequence/locktime. Duplicate copies of one signature are one cosigner. Use the existing separately approved `broadcast_transaction` flow only when every input is complete and Core independently accepts the exact final transaction.

For wallet cards, parse the actual restricted descriptors (including the mandatory-height multi form), group watch-only/node-key replicas correctly, and show per-policy/per-output vault heights and balances. Never confuse individual cosigner account wallets with separate shared-wallet balances. A plain multisig remains M-of-N after any optional vault height has passed.

## Protected environment and volatile-session semantics

SSH/service configuration and machine SSH identity remain persistent. Bitcoin inbox/outbox, PSBT reviews, temporary files and physical-only wallet material use non-swapping RAM. The dedicated HTML5 viewer and entire Bitcoin/Dashboard client run inside the protected service, not the ordinary browser/user-service process. Native secret dialogues share those protections. The ordinary Services page receives only service-level status and public machine identity. Peer SSH pipes are passed into the protected worker rather than parsed by an ordinary relay. Production Core retains its explicitly chosen encrypted wallets/public policy records and blockchain; existing on-disk material cannot retroactively become never-on-disk.

One local administrator-authorised setup establishes the fixed RAM mount. Subsequent logins can start only that user's fixed unprivileged worker via a narrow policy rule; tunnels remain user services. The worker checks actual no-swap filesystem/process controls, disables dump paths, refuses enabled kernel crash dumping, restricts ordinary filesystem writes/other raw devices, and verifies an ancestor sleep/hibernation inhibitor. The supervisor holds inhibition through temporary-child shutdown and RAM cleanup. No global swap/prune/firewall/SSH settings are changed.

A trusted kernel, administrator, installed dependencies and optical hardware remain assumptions. Do not claim an unconditional guarantee against a compromised OS. Normal persistent Core storage is outside the physical-only workflow and is intentionally retained. Actual desktop/Snap/native startup and real optical media need deployment validation.

Reboot, power loss or explicit cleanup loses unfinished RAM state. A cancelled or lost setup is **not** silently regenerated or considered backed up. Retain public server audit and show unknown/incomplete outcomes; require a deliberate fresh session after local reconciliation. Never repeat a wallet restore, key generation or burn because an acknowledgement was lost. Existing Core wallets/public monitors may already exist. Agent users can explicitly discard only unfinished pre-installation setup keys through a native confirmation; attempted installations require local reconciliation.

## Required integration tests on Dashboard

1. Plain single, plain M-of-N, mandatory-height single and mandatory-height M-of-N public policies, including receive/change samples and no bypass branches.
2. Wrong producer, duplicate account key, changed threshold/path/network/height, replaced local contribution, invalid signature, expired/replayed session and mismatching policy hash.
3. Multiple physical roles on one producer: separate discs and separate matching acknowledgements for every role; no funding before all required confirmations.
4. Different keyholders returning partial PSBTs: per-input signature counts, duplicate-key replicas, signature tampering and unchanged transaction commitments before separately approved broadcast.
5. Make Extinct: complete history, zero funds including associated vaults/shared policies, preserved receive/change/LOST labels, and retained original key wallet.
6. RAM-session loss, failed/uncertain imports or burns, lost replies, disconnected peers and explicit local reconciliation; no automated secret retries.
7. Existing Build 10 queue/preview/recovery remains usable and pruning settings remain unchanged.
