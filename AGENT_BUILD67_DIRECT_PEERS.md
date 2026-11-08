# Build 67 — direct peer connections and local QR reading

9 November 2026. Requires Wallet Server V1 Build 3. Install with APT so Ubuntu installs python3-paramiko, python3-zxing-cpp and python3-pil. The Mobile application is still a separate implementation. Close protected work normally before upgrading; this release does not upgrade a running wallet workspace in place.

## User workflow

Open **Peer Connections** in the protected window. This is the dedicated page for Agent/Mobile pairing, local identity/review QR display, reading a pairing QR from a PNG/JPEG image, signed-text import, direct connection status/expiry, connection renewal and deletion. Image decoding is local. Obtain the QR independently from the other Agent's screen, confirm its source, and compare the authenticated channel code when accepting the requested Agent/Mobile permission. QR-image import is supported; camera capture is not added to the protected viewer.

**Delete direct connection** closes its SSH service/session, releases volatile epoch credentials and disables automatic direct reconnection locally, including after workspace restart. It retains the permanent QR pairing. Use **Connect / renew direct connection** on each endpoint that disabled it to reconnect. **Revoke pairing** also removes the durable trust grant and requires a fresh independent QR. Deleting a connection during a wallet transfer interrupts that operation; inspect/reconcile it before retrying. It never deletes Core wallets or archive/disc material.

Wallet/archive/blockchain stream records **must use direct SSH**. There is no bulk relay fallback, overriding the earlier Build 66 bulk-relay implementation and the optional fallback described in Server Build 3's handoff. Outgoing bulk frame IDs are explicitly excluded from Server delivery, and incoming bulk frames arriving through the relay are refused even if a direct session also exists. Unreachable peers show a waiting state; interrupted streams retain existing recovery-required handling and full-file digest checks. Small encrypted pairing, negotiation and policy controls may use the relay; after cutover application frames use the direct path. Ordinary public Server coordination/RPC traffic remains unchanged.

The application advertises local literal IPv4/IPv6 interface addresses. It detects interface-address changes every 15 seconds. It does not discover a hidden router's public mapping, configure NAT/UPnP/firewalls, guess a peer port or use the machine's administrative SSH service. Firewalled/CGNAT networks may require a reachable LAN or an administrator-provided network path. No claim is made that SSH alone traverses arbitrary mobile NAT.

## Connection and credential security

The Build 66 permanent role/identity/PSK pairing remains the trust root. Each direct epoch creates fresh in-memory Ed25519 client/host keys and a random application login; no OS account, password bootstrap, authorized_keys entry, known_hosts entry or persistent epoch-key file is created. The protected worker's no-swap and read-only filesystem protections remain. The narrow trust helper additionally permits only a Boolean per-peer direct_enabled preference; old Build 66 trust records remain valid.

Paramiko supplies an application-owned SSH listener on a separate ephemeral port, using Ed25519, Curve25519 and AES-GCM. Only one authenticated session channel and the `wallaby-peer-v1` subsystem are allowed. Shell, exec, PTY, SFTP, TCP/agent/X11 forwarding, password and unauthenticated login remain refused. Each listener permits one connection, and four incoming handshakes are admitted globally. At most eight paired devices negotiate direct connections concurrently; each pair has one active and one pending epoch. At most eight candidates on one offered service port are tried. No hostname, unspecified/multicast/broadcast/link-local/loopback production target is accepted.

The client pins the public host key from the Noise-authenticated offer **before authentication**. Both endpoints then perform a fresh inner Noise IKpsk2 handshake, verify signed application identities/roles and bind the exact offer, epoch, SSH session ID and host/client keys. Both confirm the binding inside SSH. A logical-sequence barrier drains preceding relay frames before cutover; direct receipts retain exact outstanding encrypted frames until acknowledged. Direct control packets carry no financial approval authority. Mobile permission remains verification-only and never substitutes for an Agent cosigner or a private synchronisation endpoint.

Credentials expire locally after at most 86,400 monotonic seconds from epoch creation. Renewal begins five minutes before expiry. Interface changes or local renewal negotiate fresh credentials. A valid old session continues while its replacement is being confirmed; retirement occurs only after bilateral authenticated cutover. Closure releases Paramiko's private-key authorisation references as well as the epoch's key references. Private epoch keys remain volatile and never enter profiles, exports, logs or recovery discs. Managed runtime reference release is best effort; physical zeroisation is not guaranteed.

Loss/expiry closes the affected authenticated channel and wallet streams. QR trust and wallets are retained, but attempted wallet actions are never automatically replayed. A Server restart can require reauthentication/reconciliation. An unexpired old connection may carry controls while its replacement is negotiated; expired keys cannot bootstrap another epoch.

## Mobile/client wire handoff

Retain the Server Build 3 DIRECT_PEERS.md and Build 66 SECURE_RELAY/Noise framing. No financial proposal schema changes are needed. A logical encrypted application record uses payload_type `peer.direct`, operation_hash = SHA256(canonical logical Noise prologue), and body exactly:

```
{type:"peer.direct.KIND",negotiation_id:HEX64,epoch_id:HEX64,
 endpoints:[{endpoint_id:HEX64,role:"agent"|"mobile"}, ...],
 created_utc:INTEGER,expires_utc:INTEGER,body:KIND_BODY}
```

Sort the two endpoint objects by endpoint_id. Records expire within 120 seconds; reject future skew >15 seconds, expired/reordered/replayed frames, contradictory contents, role/key substitution or the wrong logical channel. Public SSH keys use canonical `ssh-ed25519 BASE64` strings. IDs use 32 random bytes encoded as lowercase hex.

Each endpoint first sends `client-key` with `{client_public_key}` under its own random negotiation ID. Both elect the smaller ID; epoch_id is that elected ID. Subsequent offer/accept/ready/selection/retirement records use the elected negotiation/epoch IDs. Each permitted server orientation installs its offered client public key before emitting its `offer` (the exact Server Build 3 body). Agent–Mobile has only the Agent-server orientation. Agent–Agent probes both offered orientations; only connections that complete SSH and the inner Noise binding count as reachable. The elected initiator chooses cryptographically randomly among the proved reachable sessions, waiting up to 12 seconds to allow both orientations to succeed. With one reachable orientation it uses that one; with none it waits and retries boundedly, never relaying bulk bytes.

`accept` body is `{offer_hash}`. `ready` body is `{offer_hash,ssh_session_binding}` and is emitted over the authenticated control channel only after the direct handshake. The elected initiator adds `select` with `{offer_hash}`; the other replies `selected` with `{offer_hash}`. These two selection records refine the Server's election rule; neither is a plaintext Server API field.

The restricted SSH subsystem carries 4-byte unsigned big-endian lengths and at most 65,536 bytes per packet. Its fresh Noise prologue and both signed handshake payloads equal:

```
{protocol:"wallaby-wallet-direct",version:1,offer_hash,epoch_id,
 endpoints:SORTED_ROLE_BOUND_ENDPOINTS,host_public_key,client_public_key,
 ssh_session_id:LOWERCASE_HEX_SSH_SESSION_IDENTIFIER}
```

SSHSIG namespace: `wallaby-wallet-direct-handshake-v1`. The SSH client is the fresh Noise initiator, independent of the permanent pairing's initiator. It pins the paired responder's Noise static key; the responder checks the decrypted initiator static key against its locally paired identity. Both use the permanent pair PSK, not an SSH key, for IKpsk2. Both exchange `{type:"peer.direct.ready",offer_hash,ssh_session_binding}` inside fresh Noise, where binding is SHA256(canonical(prologue plus noise_handshake_hash: lowercase hex)).

Following handshake, every length-prefixed packet is encrypted under this fresh Noise session. Packet types are `{type:"selected",offer_hash}`, `{type:"barrier",tx:logical_tx_counter,rx:logical_rx_counter}`, `{type:"active",offer_hash}`, `{type:"frame",frame:UNCHANGED_LOGICAL_NOISE_FRAME}` and `{type:"receipt",id:EXACT_FRAME_ID}`. A peer may activate only when it has the same selected proof and remote barrier equals `(local_rx,local_tx)`. Exchange active confirmations before forwarding application data. Selected sessions exchange barriers at least once a second, including during negotiation, so a one-direction-only network does not time out before election. Counters and duplicate-ID rules remain those of the logical Noise channel. Direct dispatch wakes on new frames rather than polling each chunk. At most eight direct frame receipts and four application chunks may be outstanding; bulk streams retain their four-chunk bounds and exact operation/offset/file hashes.

`retire` and `retired` use the Server handoff `{old_epoch_id,new_epoch_id,reason}` body after bilateral new-session activation. `disconnect` has `{}` and is a peer request to close this volatile direct connection, not permission to revoke trust/delete a wallet. Local deletion disables auto-reconnection until local re-enable. One active and one pending epoch are retained; superseded credentials are released. The optional signed Server `path` report contains only endpoint/channel/epoch/transport/state and no address, login or key. Server path reports never activate a local connection.

## Validation and boundaries

Tests exercise real Paramiko SSH and fresh Noise, simultaneous negotiation/renewal, one reachable orientation, Agent-server/Mobile-client roles, full private/watch-only/multisig original-role Core 31 transfers, live expiry, deletion without pairing/key loss, bounded eight-megabyte streaming without relay delivery, QR-image round-trip, altered/replayed/expired/key-substituted offers, inherited replay/role/downgrade guards and actual Wallet Server Build 3 relay dispatch. Bulk frame IDs are checked absent from the Server path. Browser checks cover the dedicated page, local QR import, independent-source confirmation, connection deletion/renewal and pairing revocation. Existing signing/extinction/disc UI regressions remain.

No installed service, live wallet, real SSH account, firewall or disc was modified. Tests use isolated Core regtest data, local fixture networks and invented keys. Actual Android background/CGNAT, installed Qt image-file selection and systemd deployment still need device testing. Test fixtures do not establish Internet reachability. Source/DEB parity and retained previous installers are audited separately.
