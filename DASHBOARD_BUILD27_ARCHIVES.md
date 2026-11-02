# Agent Build 23 / Dashboard Build 27 integration

Implementation source: `work/wallaby-agent-v2-build23/src/archive_requests.py`, `archive_operations.py`, `policy_refresh.py`, `archive_format.py`. Isolated Core, UI and cross-program protocol checks are documented in VALIDATION.md. Physical optical hardware has not been tested. Dashboard source is being developed in its own chat; no Dashboard code is changed here.

## Queue contract already matched to Dashboard archive_queue.py

Capability `wallet_archive_queue_v1`. Proposal exactly `{kind:"wallet_archive_queue",version:1,queue_id:64HEX,revision:NONNEGATIVE_INT,requests:[TASKS]}`. It is a **full snapshot**, including explicit empty requests. Repeated unchanged revisions may reoffer a locally deleted task; changed content at an unchanged revision or backwards revisions fail validation. Failed fetch/disconnect is not withdrawal. Active private captures remain protected when their Dashboard request is withdrawn.

`archive_wallet` exactly `{kind,version:1,nonce:64HEX,request_id:64HEX,wallet:LOCAL_NAME,public_wallet,related_policies:[PUBLIC_WALLET],require_local_authorisation:true}`. request_id is the canonical SHA-256 of all other fields. Public wallet rows use the existing strict public descriptor format. Agent independently checks a persistent private wallet and every proposed related policy against local Core; disc-only/watch-only/extinct accounts cannot become Dashboard archive sources. Local approval stages an encrypted Core backup only in protected RAM. An unencrypted source is encrypted in a separate protected temporary Core; the source wallet is unchanged.

Deleting a task locally removes only its pending row: Dashboard may offer it again. Disabling an archive wallet writes only a policy identifier, display name and inert archive-purpose tag to the existing persistent Denial service. It is separate from wallet-sync denial. The user may enable it again on Authorise; Dashboard remains the sole request lifetime owner.

Outbox `archive_queue_result` is a **plain public object** `{version:1,queue_id,request_id,status:"queued"|"disabled"|"complete"|"error",...evidence,signed_receipt}`. The optional extra `signed_receipt` is the Agent's existing `setup_messages` envelope over the same object before adding the envelope. Completion is generated only by the verified-burn callback, never queueing/receipt. Evidence contains `readback_verified:true,image_sha256:64HEX,archive_members:[64HEX],replacements:[{archive_id,image_sha256,members:[64HEX],old_policies_retained:true,readback_verified:true}]`. Each included Dashboard task receives its own correlated result after all requested discs verify.

## Destruction tasks

`destroy_disc` exactly `{kind,version:1,nonce,request_id,archive_id:64HEX,label:TEXT,replacement_image_sha256:64HEX,replacement_receipt?:ENVELOPE}` with the same request_id binding. `archive_id` is SHA-256 of the **old encrypted recovery.wallaby package**, not the physical disc image hash. The Agent refuses destruction without a local verified full-coverage replacement record or its own previously signed replacement receipt. This covers every member of a multi-wallet disc and retains previous policies/labels. Dashboard must copy the Agent's signed receipt when it needs the proof to survive a workspace restart.

Only the local physical-confirmation control sends `archive_queue_result` with `status:"complete",destruction_confirmed_locally:true,archive_id,image_sha256`. Dashboard may withdraw the request, but cannot assert physical destruction. Disconnects retain pending tasks in protected RAM; reconnected full snapshots quietly remove withdrawn unattempted tasks. Tasks may be deleted locally and reoffered.

Locally initiating refresh of loaded archives (rather than a Dashboard archive-wallet task) emits signed `archive_inventory` with `{version:1,event:"replacement_verified",readback_verified,image_sha256,archive_members,replacements}`. Dashboard should use its verified public evidence to create the appropriate destruction requests. Receipt is not destruction.

## Multi-wallet archives / provenance

Disc Operations allows 1–15 approved wallet rows in one encrypted package. Separate disc count defaults to 1; speed defaults to slowest supported. Every physical disc is filled with repeated recovery copies and fully read back. More than one independent cosigner for the **same setup policy** cannot accidentally share one disc. Existing Build 9–22 single-role discs remain readable. All old disc members must be selected for a replacement before it qualifies for destruction.

Routed `getwalletinfo` replies add public fields `wallaby_storage:"disc",wallaby_archive_id:64HEX,wallaby_policy_hash:64HEX`. Existing signing-only routing aliases, walletname/raw wallet-name agreement and no persistent-history classification remain. This metadata is provenance, never private-key authority.

## Additive policy refresh (matched to Dashboard wallet_policy_updates.py)

Capability `wallet_policy_refresh_v1`. Proposal currently exactly `{kind:"wallet_policy_refresh",version:1,request_id:64HEX,chain,wallet:LOCAL_NAME,previous_descriptors:[RECEIVE,CHANGE],receive_descriptor,change_descriptor,timestamp:UNIX_INT,expires_at:UNIX_INT}`. Agent checks old policy locally, unchanged exact account keys/quorum/branches, and strictly later mandatory height. Local review displays independently derived addresses plus a local Core UTXO scan for indices 0–999. Local approval imports public descriptors **additively**, preserving all old policies, and can update the public monitor of a loaded archive without replacing its private account. Missing pruned history is explicitly scheduled for existing history recovery; pruning is unchanged and incomplete balances are not marked synchronised.

Signed outbox `wallet_policy_refresh_result` (existing setup-message envelope) carries `{version:1,request_hash,request_id,status:"approved"|"history_required",wallet,monitor_wallet,policy_hash,receive_descriptor,change_descriptor,previous_descriptors}`. No funding or signature happens here. Dashboard must require relevant approval evidence before funding the reserved new vault output, then submit the actual PSBT for separate local transaction review/signing. GUI locks alone never authorise altered scripts, keys, height or PSBT.

Public policy extensions are encrypted into replacement archives and validated as a continuous same-key/same-quorum history on restoration. Old discs still hold useful signing keys, but missing new public policies must be locally approved before use. The isolated Core 31 test exercises a 3-of-5 vault through two renewals with one archived key and two additional signing accounts. It checks pre-expiry rejection, post-expiry acceptance, balances on the new monitor and encrypted re-archival/restoration of both policy revisions.


### Required PSBT output bindings for renewed vault funding

Both `sign_psbt_partial` and `broadcast_transaction` accept optional `output_policies:[{policy_hash,descriptor,index,address,amount_sats:STRING}]` (at most 16). This is part of `wallet_policy_refresh_v1`; no additional capability name is advertised. Dashboard Build 27 attaches this evidence to signing and broadcast requests for renewed destinations known on that signer; other signers review an external output address without a claimed local ownership binding. `policy_hash` is the Agent-approved `digest(transition)` returned by the refresh acknowledgement; descriptor is exactly its receive/change policy; index is currently within the independently scanned/imported 0–999 range. Agent verifies its own earlier approval or a trusted local Core/loaded-archive marker, independently derives the address and script, and requires exactly the declared amount in the PSBT output. It rechecks before wallet unlock and before broadcast. No GUI edit flag grants signing authority. Unknown, altered, removed or duplicated bindings are refused. The local review explicitly marks verified vault outputs with height and threshold.

The public refresh monitor is **new and additive**, with a new public route alias for a disc-loaded node, so Dashboard must use the returned `monitor_wallet`, not assume the old source name. Original monitors/history remain untouched. This lets exact two-descriptor readiness checks coexist with retaining all previous policies.

## Upgrade and resource bounds

The new denial helper uses `wallaby-agent-denials-v2@UID.service` and its own runtime socket while retaining the existing fixed persistent preference directory. Package installation reloads unit definitions and does not restart an active protected worker or denial helper. Older unfinished workers must finish their guarded cleanup before replacement.

A set is limited to 15 entries, 256 MiB per Core backup and 480 MiB combined backup bytes; ciphertext is limited to 512 MiB. Protected RAM free space is checked before packing/decryption/loading. A larger set must be split; no persistent-disk staging fallback exists. Public UTXO verification and vault destination indices currently cover 0–999. These bounds are intentional and do not establish that an arbitrary wallet outside the scanned range has complete history.

A valid full queue snapshot withdraws unattempted requests; disconnect alone does not. An authorised private capture cannot be silently discarded by Dashboard withdrawal. No remote message proves that a physical disc was destroyed; the explicit local checkbox records the user's confirmation.
