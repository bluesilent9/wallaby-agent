# Build 76 — connect the running worker to its peer service

Build 75's scanned QR was accepted in Treasury Australia's log, but there was no peer-service attachment or authenticated-handshake event on either Agent. The QR-generating Agent therefore had nothing to display. This was an Agent startup integration defect.

## Cause and repair

The protected Workspace owns a live Store object, and its optional asynchronous peer initializer attaches the Peers service to that object. Workspace.start_node previously constructed a NodeClient without supplying that Store. NodeClient then constructed Exchange without it. Exchange reopened a Store from disk, which can read persistent approval data but cannot recover the other object's volatile peer-service reference. Consequently the production exchange never called Peers.connect, and the QR's outgoing handshake stayed local indefinitely.

Workspace now supplies its exact Store object to every NodeClient session. NodeClient passes it to Exchange, including replacement sessions after recovery. If optional peer initialization finishes after the first exchange, the next exchange sees the service on the same object and starts its authenticated background connection. An authored diagnostic records that attachment. The optional peer helper still cannot block ordinary Core access.

No QR trust, typed roles, signatures, expiry, one-use controls, Mobile restrictions, wallet approvals, private-data rules or direct-only bulk requirements are relaxed. The Build 75 scan-to-connect workflow is unchanged. Existing saved pairings are retained. Both Agents should install Build 76, reopen their node interfaces and use a fresh QR. No Wallet Server update is required; tests use existing Build 6.

## Reproduction and validation

The new integration test starts two actual protected Workspace objects in separate processes, each with an isolated real Core regtest node. Each Workspace starts its production NodeClient, normal IPv6 HTTP registration and background Exchange against the actual Wallet Server HTTP handler and registry. Server identities are established through the ordinary signed-identity challenge, not injected into relay storage. The test then generates and scans a QR through the peer-action path and waits for automatic pairing and real restricted direct SSH, followed by a direct-only fixture payload. A test-only payload consumer receives this fixture before wallet-stream handlers; separate real-Core transfer regressions validate wallet handling.

No test manually attaches a peer RPC callback, invokes Peers.connect/tick, constructs Exchange or supplies a fake NodeClient to this integration path. Optional peer-storage initialization is deliberately delayed until after node startup, exercising the asynchronous ordering. Only isolated helper storage, protected-memory attestation, fixture identities, regtest health and loopback direct-address discovery are adapted. Camera reading was already tested in Build 75 and was not changed here.

The same startup test was run against the original Build 75 source and failed as expected: both node connections were green, but both peer RPC attachments and background threads were absent. It passes against Build 76. Existing unit/dispatcher tests had manually attached or driven the peer service and missed this integration boundary.

Release evidence includes the complete 55-test regression run and 26 JavaScript suites. Checks cover normal worker startup, late peer initialization, Agent-to-Agent scan-to-direct setup, Mobile restriction regressions, one-use and tampering, optional helper failure, public control traffic during slow wallet work, signed-result delivery, session-token rotation, original multisig/vault role restoration and real Core single-signature/private multisig/watch-vault transfers over direct SSH. Tests use no real funds, laptop services, physical cameras or discs. Installed hardware/network testing remains separate.
