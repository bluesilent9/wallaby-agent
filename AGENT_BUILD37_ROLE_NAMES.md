# Build 37: named signing roles in native passphrase dialogues

The native wallet-creation passphrase prompt now uses the proposed role name already shown in the protected approval page, together with the wallet name. A separate Signer ID line disambiguates similarly named roles. The opaque internal wallet filename is no longer the prompt heading. Both passphrase entry and confirmation use the same named prompt.

Role IDs, internal wallet filenames, signed contributions, descriptors and signing policy are unchanged. Role and wallet names are display labels from the locally reviewed immutable setup proposal; independent Agent-fingerprint verification remains required. Multiple local roles receive their own assigned names.

The real-Core three-Agent 3-of-5 regression checks all five custom role names, wallet name, signer IDs, confirmation requests and absence of opaque filename headings while completing initial/final public-policy approval and queueing both disc signers. Display-context retention and refusal/error-event tests also pass. No native GUI or physical burner was used by automated tests. This is V2 Development Build 37; no Dashboard update is required.
