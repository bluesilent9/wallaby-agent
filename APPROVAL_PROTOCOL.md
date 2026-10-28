# Agent approval and public vault exchange — v1 (build 5)

This is the **Agent-side contract for a future Dashboard implementation**. The Dashboard program has not been modified. Existing v1 read-only RPC remains on port 56443 through the same IPv6 SSH tunnel. Browser Dashboard access remains port 38951.

## Independent permissions

Direct Dashboard RPC is a local positive allowlist of public/read-only queries. No wallet creation/import, label/address creation, loading/unloading, rescan, signing, unlock, backup/private export, coin locking or broadcast is advertised or accepted. `listdescriptors` accepts only public exports. Private-looking keys are rejected in both request parameters and results. The Dashboard's old allowlist cannot override the Agent's restrictions.

Approval proposals are data, never method names or arbitrary RPC commands. Only local authenticated browser requests can invoke the fixed wallet workflows in `wallet_ops.py`. The transport's exchange thread cannot approve a proposal. These are application permission boundaries under one desktop user, **not OS isolation from an already compromised local account**. Core's cookie and wallet passphrase stay on that computer.

## Exchange transport

After normal `/agent/v1/register`, Agent sends `POST /agent/v2/exchange` with the existing connection's Bearer token, `X-Wallaby-Agent: 1`, JSON and loopback Host through SSH. Dashboard must authenticate the connection exactly as v1 and bind all data to its authorised user/profile; self-reported MAC/hostname are not authorisation. A server that does not implement the endpoint returns 404/405/501. Agent then retains its queue and disables extension probing until reconnect; ordinary read-only node presence/RPC continues.

Request:

```json
{"version":1,"outbox":[{"id":"<SHA256>","kind":"vault_public","payload":{}}],"known_vaults":["<public-vault SHA256>"]}
```

Response (all fields required; unknown fields rejected):

```json
{"version":1,"accepted":["<sent item SHA256>"],"proposals":[{"kind":"vault_sync","vault":{}}]}
```

IDs are SHA256 of UTF-8 JSON with recursively sorted keys, separators `,`/`:`, ASCII escapes and no NaN/infinity. Outbox ID hashes `{kind,payload}`. Known vault ID hashes the vault object. Proposal ID hashes the entire proposal, excluding any external delivery ID. Dashboard must independently recompute hashes. Public-vault integer fields do not use JSON floats.

At most eight outgoing items and sixteen incoming proposals per exchange; polls every 30 seconds, with no automatic wallet-operation retries. Each PSBT is at most 2 MiB base64 text, local storage 16 MiB, pending/denied/outbox lists 128 entries each. Future server must bound request body to 20 MiB and response to 16 MiB+4 KiB, reject duplicate JSON keys and validate the schema before acknowledging. Acknowledgement means **durably stored**, never merely received in memory. Agent only removes explicitly acknowledged sent items. Use idempotent content-addressed storage. On invalid exchange, retain the queue and retry later.

## Public vault record

```json
{"version":1,"chain":"main","descriptor":"wsh(and_v(v:pk(<compressed-public-key>),after(<height>)))#<checksum>","address":"bc1q...","height":1000000,"source":{"descriptor":"<public Core descriptor with checksum>","index":0},"timestamp":1793200000}
```

Only this single-key P2WSH mandatory CLTV policy is accepted in build 5; no recovery/bypass branch. Address, network, key derivation, descriptor checksums and height are independently recomputed. Source contains no wallet name or private key. `timestamp` is the earliest scan time (creation time minus a two-hour allowance). Nodes on different chains reject the record. Agent's build uses local Core height, never a Dashboard-provided tip or public explorer.

A receiver stages the immutable record and opens **Authorise**. Local review derives all details from the record and its own Core; Dashboard labels never establish ownership. Authorise creates/loads the locally chosen `Wallaby Vault <hash-prefix>` private-key-disabled descriptor monitor and imports this exact public policy. A matching private key stays in the original key wallet. Local BIP32-origin annotation supports later PSBT signing. Historical imports unavailable on a pruned chain fail explicitly. Import completion and known script ownership do not prove current balance, possession of a private key on a watch-only node, or irreversible chain confirmation.

Deny persists the proposal content hash and details; identical advertisements do not reopen the browser. Deleting a deny record permits a subsequent advertisement to ask again. Authorise is enabled while proposals or denial records exist; Services is always available. Pending uncertain operations are marked attempted before execution and are not silently replayed after interruption.

## Signing proposal

```json
{"kind":"sign_psbt","chain":"main","wallet":"Exact local signing wallet name","psbt":"<base64 PSBT>"}
```

The `wallet` identifies which local key wallet is requested; it is not a trusted label. Agent checks it against Core and verifies local control of an input. Every input value/script is checked against a full previous transaction fetched from local Core/history. Output addresses, locally recognised names, change, total fee, sequences and locktime come from Core decoding and wallet ownership, never Dashboard metadata. Non-ALL/non-DEFAULT signature modes are rejected. Authorisation is bound to the immutable PSBT and local review, expires after ten minutes, and is consumed once. Inputs must remain unspent. Any changed interpretation requires another review.

The local **Send** password dialog signs through Core, relocks an encrypted wallet in a finally block, checks the unsigned transaction did not change, requires complete signatures, calls `testmempoolaccept`, then broadcasts through local Core. Failed/uncertain requests remain attempted; reconcile Core before submitting new work. A known failure before any signing RPC (for example an incorrect passphrase) permits a fresh local review. An uncertain attempted request can be explicitly dismissed into the deny list, then its deny record deleted if a new proposal is appropriate. An optional `sign_result` outbox payload carries `{request_hash,txid,message}` after successful broadcast. No signing passphrase or RPC credentials cross the tunnel.

## Signed Vault Builder export to Transaction Builder

Outbox `kind: "transaction_builder_psbt"`, payload:

```json
{"version":1,"chain":"main","psbt":"<signed PSBT>","transaction_hash":"<Agent review tx_hash>","vault":{},"review":{},"stage":2,"immutable":true}
```

`review` is advisory Agent-derived public display data. Dashboard must decode and validate the actual PSBT independently, verify signatures and derive actual transaction identity. `transaction_hash` is the hash of Core's decoded unsigned `tx` object in the local review, not a txid. Do not use it instead of Bitcoin transaction validation. The Agent also queues `vault_public`, whether local broadcast or export was selected.

Dashboard must **only consume into an explicitly open Transaction Builder Stage 2 workspace owned by the same user/profile and expecting the same node/chain**. No global auto-insertion or auto-broadcast. If Stage 2 is not active, retain the item and do not acknowledge it as consumed. On acceptance, replace the diagram with an immutable rendering of the signed transaction: no amount, destination, input, change, fee, sequence or locktime edits. Clear/load another transaction may remove it. The signed transaction can never be silently attached to a different draft. Diagram layout changes are permitted only if they do not alter transaction bytes. Normal explicit broadcast controls apply later.

The current Dashboard does not implement this exchange. Agent shows queued/unsupported status; it must never claim server synchronisation or Stage 2 insertion succeeded until durable acknowledgement arrives.
