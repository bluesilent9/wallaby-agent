# Agent V2 Build 10: Dashboard integration

Dashboard V1 Build 11 already supports wallet setup, public cosigner accounts and partial-sign-result routing. Disc Operations restores its physical role into a separate protected RAM Core; ordinary public listwallets/listwalletdir, wallet descriptors and wallet information expose that local signing account. Existing Build 11 policy matching can target it. No encrypted/private archive is uploaded. Message signing is local and requires no Dashboard change.

## Required: per-Agent synchronisation preferences

Build 11 must be updated to retain and honour incoming wallet-policy exclusions. The Agent deliberately emits no unknown outbox kind unless Dashboard explicitly requests this protocol, preserving existing connections.

Send an inbox proposal with exactly:

```json
{"kind":"wallet_sync_preferences","version":1,"challenge":"64 lowercase hex characters","previous":null}
```

On a later connection, previous is the latest authenticated snapshot for that same Agent identity. The challenge is fresh and request-specific. The reply outbox kind is wallet_sync_preferences; payload is `{version:1, challenge:<same challenge>, snapshot:<signed envelope>}`. Envelope structure is the existing setup_messages SSH signature envelope; verify with namespace **wallaby-sync-preferences-v1** and that registered Agent's key. The signed message has exactly:

```json
{"version":1,"purpose":"wallet_sync_preferences","agent_key":"ssh-ed25519 ...","revision":1,"policies":["64 lowercase hex policy ID"]}
```

Policy ID is SHA256 of canonical compact sorted-key JSON for the sorted public descriptors produced by build8_policy.descriptors. Use this exact canonicalisation from the Agent source: descriptor checksums/origins/hardened spelling are normalised there. Names are not identity. At most 128 distinct policy IDs are accepted. No private descriptors are allowed.

Persist the verified envelope per registered Agent identity. Bind its reply to the outstanding challenge. Reject conflicting contents at the same revision, rollback/replayed updates and signatures belonging to another Agent. Restore the latest snapshot **before generating missing-wallet queue rows or notifications**. Agent independently verifies its own signature before restoring the RAM list. A malicious relay can withhold an old/new snapshot; signing is never authorised by these preferences.

For that receiving Agent only, suppress automatic sync offers and missing-wallet warnings for excluded exact policies. Preserve normal node inventories, other Agents' requirements and all signing authorisations. Re-enabling removes the policy from the next signed revision. Do not infer an exclusion from an unsigned user label or a missing wallet. A cancelled request alone is not an exclusion.

Until Dashboard implements this, exclusions suppress incoming rows only in the current protected workspace, and Dashboard may continue its own notifications. Show this limitation plainly. No new unrestricted RPC permission is needed.

## Disc-loaded transaction signing

Use existing public account inventory and exact policy-key matching, not display names. A restored physical role exposes a `Disc ...` account plus a public policy monitor. The persistent Core never receives its private backup. An Agent workspace restart unloads the archive, so ask the user to reload the disc before routing a signing request. Multiple loaded distinct archived roles can contribute to the same PSBT; duplicate copies of the same key are not additional signers.

The fixed inputs, output policy, amounts and fee commitments remain enforced by Agent transaction review. Diagram edit locks alone are not the security check.
