# Agent V2 Build 11 — the Agent owns its Denial list

This supersedes the Build 10 server-retained preference-snapshot proposal. No Dashboard code is changed here.

## Enforcement needs no Dashboard update

The Agent persistently owns its incoming wallet synchronisation Denial list. Its schema-limited local file contains exact public policy IDs and display names only. Disabled wallets stay blocked across workspace shutdown/reboot. Enabling a wallet on Authorise removes that one local entry; a current queue row or later offer can then proceed. No remote cleanup or second exclusion switch is needed.

Individual signing/setup declines, request bodies, queues, completed results, PSBTs and history jobs are not part of this persistent list. They remain in protected volatile storage. Disabled entries do not count as unfinished work. A separate real node-history issue may still produce a Synchronisation notification.

## Optional read-only status query for Dashboard display

Dashboard can learn the Agent's current policy decisions using the previously reserved exchange kind. It must not maintain an independent inhibition list or restore its own cached decisions onto an Agent.

Send an inbox proposal:

```json
{"kind":"wallet_sync_preferences","version":1,"challenge":"64 lowercase hex characters","previous":null}
```

The reply outbox kind is wallet_sync_preferences; payload is `{version:1, challenge:<same challenge>, snapshot:<signed envelope>}`. The envelope uses existing setup_messages SSH signatures with namespace **wallaby-sync-preferences-v1**. Verify against that registered Agent's identity. Its signed message is exactly `{version:1, purpose:"wallet_sync_preferences", agent_key:<Agent public key>, revision:<local list revision>, policies:[<sorted disabled public policy IDs>]}`.

Policy ID remains SHA256 of the canonical compact sorted-key JSON encoding of sorted public descriptor identities from Agent build8_policy.descriptors: strip checksums/key origins, normalise hardened spelling, preserve actual scripts/keys; names do not establish identity. Use the implementation for exact matching. At most 128 policies are returned.

After a valid response, show disabled policies as “Synchronisation disabled on this Agent” and omit their missing-wallet alerts or automatic sync offers for that receiving Agent. Refresh on later exchanges so enabling locally is reflected promptly. A cached snapshot is display information only, never another user-controlled rule. If status becomes unavailable, show status unknown/offline; do not claim an absent wallet is synchronised. Actual inventories, other Agents' needs and all signing permissions remain independent.

The fresh challenge ties replies to the current query. Persisting an authenticated display cache is optional; its contents must never override a fresh Agent response. The Agent continues to enforce its local list even if Dashboard ignores or withholds the status.

For compatibility, a non-null previous envelope is signature/schema checked but **never restores or changes the local list**, even if this Agent once signed it. The user may have re-enabled that wallet since that snapshot. Send previous:null in new Dashboard code.

Agent sends no new outbox kind unless Dashboard explicitly requests it, preserving the current strict Dashboard exchange. Until this optional status feature is implemented, the Agent blocks locally but Dashboard may continue showing its own missing-wallet notification.
