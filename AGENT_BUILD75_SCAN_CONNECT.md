# Build 75 — scan, pair and connect

Generate a fresh QR on one updated device and scan it on the other. A successful authenticated scan now completes pairing and starts direct SSH setup automatically. No second approval click is required. Install Build 75 on both Agents for this workflow. Both devices must be connected to Wallaby Wallet and have a reachable direct network path. Direct setup still takes a short handshake; the interface does not claim it is connected merely because a QR was decoded.

The QR dialog explains the scan-to-connect action and automatically dismisses when pairing starts or a new pair appears, revealing connection progress. The scanning device shows authentication progress and then the saved device's direct-connection status. Incompatible/expired/used QR errors, failed discovery, interruptions, busy service and unfinished-pairing expiry have fixed, sanitised feedback. Error messages persist long enough to read. Ordinary camera frames with no valid pairing QR are not logged as failed actions.

## Findings and limits of supplied logs

Build 74 always instructed the scanner to check the other screen before the handshake completed. Its issuer confirmation could remain behind the QR modal. Peer-action logs did not distinguish scanning, importing and polling, and the peer loop could clear its own error immediately after a tick. The supplied logs therefore do not prove which transport/handshake stage prevented the attempted connection. Build 75 adds explicit safe pairing-stage diagnostics; it never logs invitation secrets, ciphertext, keys or raw remote errors.

A separate code defect also dropped in-progress handshakes when relay backpressure occurred during discovery, receive or channel reporting (only send previously retained state). Busy responses now pause and retain exact messages/channel state throughout the loop. No wallet operation is retried by this change.

## Trust and versioning

The user's new instruction makes generating and directly scanning the short-lived QR the two local pairing actions. This supersedes the separate role-confirmation requirement for new scan-to-connect invitations. The change is explicitly identified by signed version **3**, adding exactly `pairing_mode: scan-connect` to the version 2 message. Other fields, kind `agent_invitation`, signature namespace, cipher suite, typed identities, 120-second expiry and independently pinned Server route are unchanged. Version 1 and 2 invitations retain their original confirmation behavior; their semantics are not silently upgraded.

The issuer grants only after the scanner proves possession of the QR secret, the expected Noise static key and the signing identity bound to its typed endpoint and signed handshake transcript. One valid handshake reserves the invitation to one channel; a competing channel cannot reuse it before persistence. Invalid proofs cannot create saved trust. A Server directory alone never grants permission. Saved trust and subsequent reconnects keep their existing identity pins. Revocation still requires a fresh QR.

A Mobile remains a Mobile regardless of which device generates the QR. It is always the direct client and cannot approve wallets, receive private Agent wallet sync or participate as an Agent signer. Mobile-to-Mobile pairing is refused. Pairing does not approve any wallet operation. Bulk streams remain direct-only. No Server update is required beyond existing Wallet Server Build 6. A Mobile application needs matching version 3 support for this automatic workflow; Python Mobile fixtures do not mean the shipped Mobile application was updated.

## Validation

63 regression executions passed, including unpaired-to-paired routing through the real Wallet Server Build 6 dispatcher, real restricted direct SSH and direct-only bulk, both Agent and Mobile roles, temporary transport interruption, one-use reservation, invalid proofs/tampering, legacy confirmation, existing direct renewal/revocation/role restrictions, wallet-table visibility and real Core single-signature/private original multisig/watch-vault transfers. Nine additional feedback/legacy executions passed, including backpressure without channel loss, persistent errors, explicit timeout and ordinary empty camera frames.

All 26 JavaScript suites passed. The browser camera test uses actual getUserMedia fake-camera video and the real local QR decoder: it checks automatic pairing progress without an extra Agent confirmation, QR-modal dismissal, camera shutdown, legacy confirmation, named cards and deletion. The page screenshot was visually inspected. No real user wallet, running laptop service, physical camera or physical disc was changed. Physical device/network testing remains necessary.
