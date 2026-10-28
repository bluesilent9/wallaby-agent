# Development installers

Latest: [V2 Development Build 5 DEB](wallaby-agent_2.0.0~dev5_amd64.deb), Ubuntu 26.04 LTS amd64. Verify [SHA256SUMS.txt](SHA256SUMS.txt).

Build 5 adds local Vault Builder and Authorise pages and restricts direct Dashboard RPC to public/read-only queries. All three existing service toggles remain. It signs only after local review and approval, supports local broadcast or signed PSBT queuing, and persists sync denials. 60 tests pass, including twelve isolated Core 31 regtest tests; package checks pass.

Dashboard exchange and Transaction Builder Stage 2 reception require the later Dashboard implementation in APPROVAL_PROTOCOL.md. Current servers cannot yet receive those queued items. Development only; not installed or independently security-audited. Older packages do not include these features.
