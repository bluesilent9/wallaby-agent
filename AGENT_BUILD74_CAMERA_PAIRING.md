# Build 74 — camera pairing and connection management

Peer Connections has two primary controls: **Read QR code** opens the camera; **Generate QR code** shows a short-lived invitation for another device. The page detects Agent/Mobile identity from the authenticated exchange and requires local confirmation on the invitation issuer. No role is accepted from the Server directory. Mobile permissions remain verification-only: no wallet approvals, private wallet sync or Agent signer participation. Existing operation-specific Mobile review QR codes remain available on their review pages.

QR dialogs no longer display raw invitation text or the local identity-key line. Saved connection cards show the authenticated device name, device type, direct status and server/client orientation. Names are display metadata, never authority. Delete connection revokes local saved trust and closes the channel; reconnecting after deletion requires fresh QR pairing. Offline Agent orientation is assigned at connection time; Mobiles always use the client role.

## Camera boundary

Only the exact protected IPv6 loopback origin can request video capture, with a native local confirmation each time. Audio, combined audio/video and screen capture requests are denied. No camera grant is persisted. Frames are resized to at most 1,280 pixels wide and decoded locally by the existing bounded QR reader; no frames are saved or sent to the Wallet Server. Only one decode runs at a time. Tracks stop on recognition, close, navigation, hidden window and protected-workspace loss. Permission refusal and missing cameras have visible feedback.

The protected service retains its closed device policy and adds only the video4linux camera device class and video supplementary group. Chromium sandboxing and all wallet protections remain enabled. Headless tests use test-only fake cameras and sandbox flags that are not installed in production.

## Version 2 pairing / Mobile handoff

Both new Agents should use Build 74. Existing saved pairs remain valid and the Agent can still read version 1 invitations. A Mobile application needs matching version 2 support before it can use the new automatic pairing controls; the Agent's Python Mobile-role fixture is not a shipped Mobile application.

The signed envelope remains the existing SSHSIG envelope, signature namespace `wallaby-wallet-peer-invitation-v1`, protocol `wallaby-wallet-peer-pair` and kind `agent_invitation`. Version 2 has exactly the version 1 message fields plus signed `issuer_name`. Existing cipher suite `Noise_IKpsk2_25519_ChaChaPoly_SHA256`, secret generation, 120-second expiry, independent pinned Server route and one-use rules are unchanged. The issuer uses its actual `issuer_role`, `issuer_identity_key`, `issuer_noise_public_key` and role-derived `issuer_endpoint_id`. An Agent issues `allowed_peer_role: auto`; a Mobile issues `allowed_peer_role: agent`. A Mobile may never accept another Mobile or upgrade its identity to Agent.

The scanner pins the typed issuer identity and starts the existing signed Noise handshake using its own typed identity. The issuer verifies the role-derived endpoint, signed transcript and invitation permission, then shows Confirm Agent or Confirm Mobile locally. No automatic role approval occurs. Existing per-operation checks apply after pairing. The encrypted connection `ping` body may include `device_name` (nonempty, <=128 characters, no control characters); receivers update only the matching saved pair's display name. Omission is compatible with older peers. Do not copy names from pong echoes.

No Wallet Server protocol or capability change is required; Wallet Server Build 6 already forwards the opaque control exchange. Bulk wallet/archive/block transfers remain direct-only.

## Validation

35 pairing, real restricted SSH, bounded direct bulk, typed Mobile restrictions and QR decoder tests passed. A further 21 regression tests cover wallet-list visibility, optional peer startup, alphabetical navigation and real Core single-signature/private original multisig/watch-only vault transfers over direct SSH. All 26 JavaScript suites passed.

A real Chromium fake-camera stream was captured with getUserMedia and decoded with the actual local zxing reader. Tests cover camera shutdown on success/close/navigation, two primary buttons, no raw QR text, role confirmation, device names/orientation and connection deletion. A native Qt 6.10.2 WebEngine test independently exercised the real video permission signal at IPv6 loopback, local confirmation and stopped video-only capture. The page screenshot was visually inspected.

Physical laptop cameras and installed systemd camera permissions still require device testing. No user wallet, live service, physical camera or optical disc was changed by these tests.
