# Build 64: Core-native Extinct history and direct SSH catch-up

This development build requires Bitcoin Core 31. It never edits an open wallet database. Every test uses isolated regtest data, not a real wallet or running desktop service.

## Historical records and LOST

An active source wallet is accepted as the authoritative history it has processed through the current node tip, as requested. Before preservation, the Agent checks its exact public policy, active-chain confirmations, zero funds and locked outputs, and every known address/transaction against the approved manifest. Being at the current tip alone is not a cryptographic proof that an arbitrary imported wallet has complete past history.

Core's ordinary address-import/rescan path needs historical blocks, and `importprunedfunds` alone omits an outgoing transaction with no owned output. Build 64 instead takes a consistent Core backup into protected non-swapping RAM, extracts only transaction records from that offline backup, and adds them to a separate offline backup of the public-only Extinct wallet. It does not copy private-key records or the original wallet's ranged descriptors. The destination keeps its fixed historical addresses, existing unrelated children, labels, comments and Core transaction records, including outgoing final spends. Fixed-address birth times in the replacement are set to zero for a later full replay.

Core restores and reads back the staged public wallet before a narrow helper atomically exchanges two unloaded wallet directories. The Agent reloads and verifies the final archive before reporting preservation. The original active wallet remains until a separate deletion approval, supported by the existing signed v3 preservation receipt. Existing current history is reused; repeated preservation does not duplicate transactions. If the original source is missing and the archive lacks its history, the explicit older-block recovery path remains available, with Build 63's planned-restart protections. A timestamp is never used as evidence of completeness.

`LOST:dd/mm/yyyy hh:mm:ss UTC` text is retained exactly inside Core labels. Conflicting existing labels, including loss dates, stop the merge. New transfer data cannot overwrite another loss date. Historical transaction data is stored in Core, not a separate Agent history database.

The offline reader is pinned to Core 31 SQLite/CWalletTx serialization and refuses other major versions. It verifies SQLite integrity, transaction IDs and exact active-chain references. Signed peer historical records retain the trust boundary of an authenticated wallet backup: source Core's stored confirmation history is not a newly generated Merkle proof when old blocks are pruned.

An interrupted exchange leaves the original source and public archive directories available for reconciliation; no completion receipt is sent before readback. If only cleanup of the previous public copy fails after successful final readback, the verified archive stays installed and the previous public copy is retained under `.wallaby-history-*`. Do not delete uncertain staged directories without local inspection.

## Synchronisation and block catch-up

Both peers advertise `chain_sync_v1` and `core_history_v1` inside the already authorised direct SSH channel. No new Dashboard capability or outbox kind is required for history and block transfer. A source/receiver pair still uses the existing signed public preview, independently compared Agent identity, SSH host fingerprint and local receiving approval.

After the direct connection is authorised, the receiver disables Core P2P connections with `setnetworkactive(false)`. The peers locate a common ancestor, stream bounded raw blocks, and use Core's own consensus validation to reach the frozen sender tip before importing the selected wallets. Loaded wallets must process that tip. This is part of a selected wallet synchronisation, not an independent background Internet download. A receiver can subsequently send its validated retained blocks onward to another receiver.

A pruned sender cannot supply blocks it no longer retains. Missing ranges, invalid blocks, changed chains and interrupted connections stop the transfer; there is no silent Internet fallback. Verified blocks are retained. The receiver's previous P2P setting is restored after a successful transfer, including a safely deferred historical import; otherwise its Synchronisation page offers an explicit Resume Core Internet connections action after receiving authorisation ends. Core RPC and the Agent connection remain available while P2P is disabled. Active transfers have a bounded 24-hour lifetime; idle receiving authorisation remains 15 minutes.

The sender signs a bounded historical-record packet against the exact transfer, live preview and checksum. The receiver checks the pinned Agent signature, policy, labels and active-chain references before asking Core to load it. No signing keys cross this history channel.

## Local lifecycle state and persistent Deny

Completed local deletion records only inert policy/address hashes, original wallet names, request/operation hashes and its state in the existing narrow persistent preference service. It does not persist wallet contents or signing authority. An incoming Extinct archive is deferred unless every incoming address has completed extinction locally. A recreated original wallet or another loaded active wallet owning those addresses also blocks import. Unknown/pre-Build-64 completion evidence is not inferred from a missing filename. A grouped archive currently defers as a whole if any child is ineligible; eligible children are not silently imported as a partial success.

Cancel dismisses an unattempted request without a persistent denial. Dashboard may send it again. Deny adds a separate, persistent extinction or restoration policy entry; the two purposes and ordinary wallet synchronisation are independent. The Authorisation deny list can remove these entries. Attempted/uncertain operations cannot be hidden by Deny or Cancel.

## Dashboard coordination and restoration

The history redesign uses the existing `wallet_retire` v3 preserve/delete messages and existing `wallet_transfer` v2 paired requests, previews and result messages. Dashboard 89 can use those history operations unchanged.

The user's subsequent immediate Dashboard extinction / Restore button requirement DOES require Dashboard changes: Dashboard may move its own presentation to Extinct immediately, but must keep local preservation/deletion progress separate. A presentation change is not authority to delete a wallet or claim history verified.

For restoration, Dashboard must withdraw outstanding extinction requests and arrange a fresh normal paired direct SSH transfer of the exact active original public policy from a holder that still has that active wallet. Agent 64 recognises an exact locally retired policy as restoration, displays that fact in Synchronisation, and only clears its local extinct state after the received original passes Core policy, encryption, history and current-chain checks over the new direct SSH path. A Dashboard request alone, an Extinct fixed-address import or a failed transfer cannot clear it. Existing Extinct history and LOST labels remain for tax/history reporting. A private original is required to regain private signing capability; a watch-only copy does not recreate keys. Existing managed-signer cloning restrictions remain enforced: use their established role/policy recovery flow rather than ordinary wallet replication.

Dashboard must not claim restoration complete merely because a request was issued or a signature/preview received. It should independently inspect the resulting active wallet capability after the transfer result. Pending local restoration Deny is tied to the exact public policy, not an operation ID/name, and survives a new transfer ID. Source and receiver need Build 64 for this restoration completion path.
