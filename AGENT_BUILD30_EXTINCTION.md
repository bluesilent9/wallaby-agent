# Agent Build 30 / Dashboard Build 34 extinction integration

Agent implements `wallet_retirement_v3`: version-3 `wallet_retire` preserve/delete phases, local Core checks, exact manifest binding, signed preservation receipts and separate local deletion approval. It no longer advertises the combined v2 action. Legacy combined requests are blocked at exchange and protected GUI entry points. Historical tests still exercise the old implementation, which is not a supported production entry point.

Deletion requires independently entering the preserving Agent's SHA256 identity fingerprint in addition to reviewing the exact manifest, local zero balances, paths, original copies, watch copies, dedicated/shared signers and confirmed transaction history. Dashboard must not alter the receipt. Preservation uses an already loaded, private-key-disabled, address-only archive only. No existing archive means no import and no archive creation. Canonical empty archives are exposed with a locally verified wallaby_extinct flag after checking their private-key-disabled, address-only policy. Missing retained blocks require explicit local history preparation/recovery, with pruning unchanged; incomplete history can never produce a preservation-complete receipt. No extra private backup is created. Attempted or uncertain operations cannot be relabelled as an unstarted denial. Public outcomes remain in the protected-RAM outbox until delivered to Dashboard; this does not add another local Bitcoin-data persistence file.

## Old discs discovered later: matching Dashboard Build 34 protocol

A freshly burned archive with a full physical read-back remains `event:"archive_verified", readback_verified:true`. An old encrypted disc successfully read/authenticated now sends an Agent-signed `archive_inventory` envelope with message:

```
{version:1,event:"archive_observed",archive_id:SHA256_OF_ENCRYPTED_PACKAGE,
 payload_sha256:SAME_HASH,payload_verified:true,readback_verified:false,
 replacements:[],members:[EXISTING_PUBLIC_MEMBER_SCHEMA]}
```

This is authenticated package/membership evidence, not proof that all redundant copies on the old medium are readable and never proof of replacement or destruction. Dashboard Build 34 accepts it for later extinction discovery and store its envelope like the verified inventory; it must not satisfy burn/readback or replacement requirements. No secret contents leave protected RAM. The existing `archive_inventory_v1` capability carries it in the matching build. Old Dashboard versions are not supported for new phased extinction.

Version-2 `destroy_disc` uses the fields in Dashboard Build 34's archive queue: operation_id, archive_inventory, retired_wallet, retired_member_ids, manifest_hash, preservation and the three required local/readback flags. Agent verifies its own original inventory signature and the actually read disc catalog, validates the preserving Agent signature and requires independent fingerprint comparison. A mixed disc offers local staging of only the remaining current accounts (retaining a shared signer if another live policy needs it). No destruction confirmation is allowed until every remaining member is covered by a locally read-back-verified replacement. Its `archive_queue_result` completes only after physical destruction confirmation and includes `replacement_readback_verified:true` and `replacement_image_sha256` when a replacement is needed. A disc containing only retired members needs no replacement, but still needs the locally checked signed preservation proof and physical confirmation. Replacement does not claim the old disc's retired private wallets were copied.

Dashboard must refresh and verify at least one connected existing Extinct holder before queueing/delivering later wallet/disc cleanup; an old cached receipt alone does not prove that archive is still available. New/current funds, changed history, uncertain attempts, cancellation or missing proof must block deletion and must not trigger automatic destructive retries.

## Archive request queue and local controls

Dashboard archive requests may arrive at different times. Review and authorise each local source on Authorise; its encrypted Core backup is staged only in protected RAM. In Disc Operations select 1–15 approved independent wallets for a disc set. Unselected rows remain staged for a later burn, and new requests can join the waiting queue. A selected set becomes fixed when preparation starts. All requested physical discs must pass full read-back before any selected request is completed. A failed/uncertain write never removes those requests.

Authorise also offers **Review staged archive**, with **Delete request locally** for unused captures. Disc Operations links directly to the same review, including a staged request withdrawn by Dashboard. Deletion removes only the chosen RAM capture and burner queue member, then reports a signed `archive_queue_result` with status `deleted`. The same request is terminal in RAM and cannot reappear while awaiting acknowledgement. A fresh Dashboard request for the same wallet remains possible. Archiving has no Disable option or persistent denial list. Legacy archive-disable entries are removed without changing synchronisation preferences. Active writing/verification, partially written disc sets and uncertain outcomes cannot be discarded through these controls. Physical disc destruction requires its own explicit local checklist.

Dashboard Build 34 and later (including Build 36) support accumulating and completing the existing archive queue. The new signed `deleted` outcome and requested Notifications/Wallets behavior require the Dashboard changes documented in **DASHBOARD_ARCHIVE_RESULTS_BUILD30.md**. Do not mistake deleting a reminder for physically destroying a disc. Archive staging and per-request terminal records remain volatile; the Dashboard must acknowledge and retain terminal outcomes. No private captures are persisted.

## Disc Operations: accumulated RAM accounts

The five numbered sections are Read a Disc; Review and Load Wallets; Burn Discs; Wallets Loaded in RAM; Create a Replacement Disc. Reading another disc does not replace previously loaded accounts. Local policy comparison and explicit Load this signing account approval remain required for each account. The list includes the verified wallet/policy, cosigner name and stable ID, ordinal among all policy signers, threshold, source archive ID and public Dashboard routes. Multiple different signing roles for the same multisig wallet can be loaded simultaneously and contribute to one message or transaction. Exact duplicate key loads remain refused.

Selecting a row enables Delete selected load. It stops only that temporary Core process and removes that account's RAM directory; other loaded accounts and physical discs remain. Accounts referenced by an unfinished replacement cannot be unloaded until that work is finished. The session has a 64-account bound with existing free-RAM checks; each disc package is still limited to 15 independent entries.

Native X close now allows idle loaded/staged archive accounts, once active operations and required signed deliveries finish. The closing marker permits the existing supervisor to stop only protected child processes and remove RAM data; no persistent Core wallet is stopped or deleted. A failed/refused close retains the accounts.

Dashboard Build 37 implements signed deleted results and red/green outcome notices; the accompanying handoff explains the wire fields. The Dashboard source was not changed by this Agent work.
