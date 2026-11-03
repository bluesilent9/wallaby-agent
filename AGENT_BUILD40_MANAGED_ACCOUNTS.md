# Build 40: logical wallets and managed signing accounts

## What is stored

A proposed logical wallet such as Treasury has one complete public spending policy. Each node producer keeps its assigned encrypted signing account locally; physical-only roles remain in protected RAM until verified disc backup. Each participating node installs a public policy monitor so it can derive the same addresses and observe the shared outputs. Internal Core accounts have stable generated identifiers. These are not extra owner assets and do not require key-wallet replication to complete the ceremony. They do not automatically rename or disappear at completion.

Core account identifiers remain unchanged for compatibility with pending setups, recovery records and existing discs. Where a live locally approved policy matches its descriptors, Agent cards display the proposed logical name and signer role, and retain the exact Core account name as a secondary detail. After RAM metadata has gone, reserved legacy names are conservatively labelled as managed accounts without guessing the logical wallet or role. Dashboard retains the signed public setup inventory needed to group these accounts and label Ownership correctly.

## Local transfer refusal

Queue snapshots recognise signer public descriptors from locally approved contributions and the reserved legacy signing-account namespace. Unattempted signer offers are not made actionable, are removed from the local pending transfer list, and return the existing wallet_transfer_result with status error and a fixed public explanation. This is not a persistent user denial. An operation already attempted or active remains visible for reconciliation; its state is never silently erased.

The same guard runs when reviewing or authorising transfers, validating batches, matching the sending wallet, immediately before private backup, and on receiving a peer manifest before staging or import. An exact descriptor match protects against a Dashboard changing display names. Persisted Core policy descriptors protect recognised signers even after RAM setup metadata has gone. Existing public-only policy replication and ordinary unrelated wallet transfers remain supported. This does not authorise a remote operation, expose private RPC or erase any account.

## Optional public RPC metadata

A successful protected getwalletinfo response can include wallaby_managed. This does not change the RPC method allowlist. All fields are public and locally constructed:

- version: 1; kind: signer or policy; display_name.
- For a descriptor-matched local setup: setup_id (proposal digest), policy_hash, logical_name, threshold, total.
- For a signer: role_id and role_name.
- For a policy: ready (local verified completion state).
- A conservative name-only legacy result contains legacy: true and omits unverified logical names, role assignments and policy IDs.

Dashboard should prefer its existing authenticated wallet_setup_inventory and proposal/contribution records for asset grouping and ownership. Optional metadata is an additional hint with explicit legacy limitations. It must not use an Agent-supplied display label as permission to spend, authorise synchronisation or discard history. Internal accounts with real transaction history must not be hidden as if their balances did not exist. No additional outbox kind or capability is required.

## Abandon an unfinished setup

Cancel the exact ceremony in Dashboard Wallet Builder first. Keep its cancellation record until every participating Agent has reviewed the locally listed artifacts and explicitly chosen Delete and Cancel (or encrypted Backup and Cancel if desired). Delete only the abandoned setup's listed accounts; never delete existing unrelated wallets or approve its generated-signer sync offers. Any failed or uncertain cleanup must be reconciled instead of relabelled as successful. Then let Dashboard withdraw the obsolete offers and remove stale empty setup resources before reconnecting. The Agent cannot silently erase Dashboard profile state.

No force-stop or blind reset is part of this workflow. Existing unfinished disc material is volatile, so complete cancellation before upgrading a busy older worker. Reaching a vault unlock height is distinct from deleting a wallet or invalidating its keys; cleanup remains an explicit local decision.
