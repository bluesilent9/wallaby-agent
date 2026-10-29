# Signed initial wallet preview — implemented in Dashboard Build 9

**Agent V2 Build 7 and Dashboard V1 Build 9 implement this contract.** Dashboard verifies and relays the signed snapshot, freezes both requests and serialises paired transfers. Unsigned vault composition, partial signing and separate broadcast remain supported. The requirements below document the implemented protocol. Direct RPC remains public/read-only; no private wallet upload endpoint is added.

## Implemented Dashboard requirements

The sending Agent must verify descriptors, current funded outputs, amounts, receipt times and receipt block heights using its own Core connection **during the initial request**. Both users must review the same initial snapshot before SSH transfer authorisation. A Dashboard-rendered balance is insufficient. Dashboard must courier the signed public snapshot below. Agent identity fingerprints must be compared directly between the computers; neither a fingerprint delivered by Dashboard nor a hash displayed only on Dashboard is trusted.

1. Keep the existing `wallet_transfer` request fields. Add **both** `preview_challenge` (fresh cryptographically random 64 lowercase hex characters, shared by the pair) and `node_ipv6` (this request's own node IPv6). Bind the request to the exact peer, direction, public wallet and both addresses. The new fields change its proposal hash, intentionally requiring a fresh review. Do not reuse an old denial/result for a new challenge.
2. Dispatch only one wallet pair at a time when both peers are free. Sort the available wallet list alphabetically (`wallet_name.casefold()`, then descriptor identity/transfer ID). Avoid handing opposite nodes different active requests, which would deadlock their per-node request locks. Other sessions wait; don't replace a request while it is being reviewed.
3. Accept the new outbox kind **`wallet_transfer_preview`** only from the paired **sending** connection. Payload has exactly `{request_hash,preview,public_key,signature}`. `request_hash` is SHA256 of the entire sending request, including the new fields, using the existing canonical JSON rules. Verify correlation before storing/acknowledging; never let another node replace it. Duplicate identical content is idempotent. A different preview requires cancelling the pair and issuing a fresh challenge, not editing the old request.
4. Relay a proposal with exactly `{kind:"wallet_transfer_preview",preview,public_key,signature}` to the paired receiver. The receiver's base request must already be staged, or precede this delivery by an exchange; the current Agent deliberately rejects an unsolicited preview without an active receiving request. Keep retrying the identical preview while the receiver request is pending. Agent pins it once and ignores identical retries. Do not modify, reserialize internally signed facts, round amounts, rename wallets or insert fields. JSON property order is irrelevant because signing uses canonical JSON.
5. Retain authenticated heartbeats, outbox/result delivery and completion handling during a transfer. Agents **reject all new Dashboard RPC/approval work** while a transfer is active. The only inbound exception is the single signed preview fulfilling the already frozen receiving request. This is not permission to change the peer, wallet, request or nonce. Do not disconnect or mark a node permanently failed for the temporary `synchronisation_busy` RPC response. Wait until completion before refreshing its wallet inventory.
6. Continue existing `wallet_transfer_result` handling (`complete`, `denied`, `error`). On completion refresh public wallet inventory. An encrypted private-key wallet and its watch-only equivalent still count as the same public wallet. Failed/uncertain wallet imports or file sends are never automatically retried. Provide a deliberate new-attempt action with a fresh challenge after users reconcile Core. Respect denial records and cancellation.

## Signed payload

```json
{
  "request_hash":"64hex sending request hash",
  "preview":{
    "version":1,
    "transfer_id":"64hex shared transfer id",
    "challenge":"64hex shared preview challenge",
    "sender_ipv6":"2001:db8::1",
    "receiver_ipv6":"2001:db8::2",
    "public_wallet":{"wallet_name":"Wallet","descriptors":[{"desc":"PUBLIC_DESCRIPTOR#checksum","timestamp":0,"active":true,"internal":false,"range":[0,999],"next_index":1}]},
    "chain":"main",
    "funded_outputs":[{"address":"bc1...","txid":"64hex","vout":0,"amount_sats":"123456","time_received":1793200000,"blockheight":970000,"confirmations":5}],
    "node_tip":{"height":970004,"hash":"64hex"},
    "generated_at":1793200000
  },
  "public_key":"ssh-ed25519 BASE64_SSH_PUBLIC_KEY",
  "signature":"BASE64_OF_ARMORED_SSH_SIGNATURE_FILE"
}
```

`funded_outputs` includes current unspent receiving/change/locked/immature outputs found in the source wallet history and checked through local Core `gettxout`. Pending outputs have null `blockheight`; `time_received` can be null if Core has no timestamp. Amounts are exact integer-satoshi decimal strings, never floats. The initial snapshot remains frozen. A later tip can increase confirmations without changing the reviewed amounts/outpoints/time/height. Changed funds or a confirmation transition require a fresh preview/request. Limit 10,000 outputs, 256 public descriptors, bounded original exchange body limits. No private descriptor, file, RPC cookie or password is ever included.

Signature input is UTF-8 `json.dumps(preview,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)`. SSHSIG namespace is **`wallaby-wallet-preview-v1`**. The Agent creates a local, dedicated Ed25519 identity, not a Bitcoin key or an SSH login key. Signature is made with `ssh-keygen -Y sign`; the base64 wrapper contains the entire ASCII armored signature file. Public key has exactly the algorithm and base64 key, no comment. Dashboard can additionally check the signature and all request bindings before relaying, but the receiving Agent independently repeats verification. It will not authorise receipt until the user enters the fingerprint copied directly from the sending Agent's screen. Fingerprint is standard OpenSSH SHA256 of the decoded SSH key blob.

Both Agents display SHA256 of the canonical `preview`, and the sender displays its own locally generated identity fingerprint. Users compare these directly, outside Dashboard. This detects Dashboard substitutions **when the independent comparison is performed**; a key supplied solely by Dashboard is not an identity authority. Previews expire after 15 minutes (up to two minutes future clock tolerance); never renew silently. Clock errors require fixing local clocks or a deliberate new request. Persist the same snapshot and signature for retry/restart. The receiving Agent rejects changed previews and replay across transfer/challenge/IPv6/wallet bindings.

## Compatibility and private transfer

Use Dashboard Build 9 for the implemented relay. Agent Build 7 still recognises older Build 8 paired requests but disables Authorise/Send because they lack preview negotiation. It does **not** send an unsupported new outbox item to Build 8. Do not claim that initial wallet sync works against an unchanged Build 8 server. Add both negotiation fields only after this new relay path is implemented; no new capability string is needed (Build 8 rejects unknown capabilities).

After initial review, receiving Authorise verifies the sender identity fingerprint and opens a temporary owner-only Agent receiving socket for 15 minutes. System OpenSSH on IPv6 port 22 authenticates the receiving machine username/password. Sender separately pins the receiver's **system SSH host** fingerprint from the receiving screen before sending credentials. These are two distinct identities; label them clearly. Wallet file travels directly via IPv6 SSH, never Dashboard. The live peer manifest must match the already approved initial snapshot; the receiver verifies the live manifest before file transmission. Private-key wallets must already be encrypted and locked in Core. Core creates the backup; receiver restores under a new generated name, verifies exact public descriptors/encryption/scanning and reported funded outputs, and sends direct loaded confirmation. Both queue public completion, display Success for about five seconds, close the direct connection and return to Services. No automatic mempool broadcast or signing occurs during sync.

The Agent supplies optional OS-approved **read-only** UFW checking and copyable SSH/UFW commands. It does not install or reconfigure the system SSH server, alter firewall/modem rules, enable IPv4 listening or open general shell access on its own. The receiving computer needs inbound IPv6 TCP 22; sender normally needs outgoing TCP 22 only. A successful local UFW check does not prove modem/router reachability. Sender diagnostics distinguish fingerprint mismatch, SSH reachability, login rejection, receiving authorisation and restoration failure.
