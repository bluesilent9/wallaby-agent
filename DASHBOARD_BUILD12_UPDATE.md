# Agent V2 Development Build 12 / Dashboard V1 Build 13

No new Dashboard protocol or implementation is required for this build. The Agent implements the six follow-up items in Dashboard Build 13's `docs/AGENT_FOLLOW_UP.md`. Existing setup contributions, physical-role completion proofs, partial-signature results, broadcast requests and persistent sync-denial status keep their formats. Dashboard cannot acknowledge local fees or substitute its wallet labels for Core evidence.

## Local fee review

The diagram labels the verified inputs-minus-outputs fee **Total network fee**. It does not attribute the joint fee to the selected signer. An independent local checkbox is required before signing or broadcasting when the fee is at least 10% of locally identified non-change payments or its conservative rate bound is at least 100 sats/vB. Change is excluded only when Core identifies it as change belonging to a locally known input owner. If no payment is identified, all returned output value is the denominator; a positive fee with no returned value also warns. Core's decoded unsigned transaction size gives a conservative upper-bound rate: signatures may reduce the actual rate, so borderline transactions can warn. This deliberately avoids trusting Dashboard size/change labels. The Agent re-verifies the transaction and unspent inputs before acting. A deliberate local override remains possible. Signature collection and the separate broadcast workflow are unchanged.

## Identity and state

One independently entered full producing-Agent fingerprint is bound to all that producer's roles in the exact wallet ceremony. Each new ceremony must be verified again. Legacy per-role submissions remain accepted only when every full fingerprint matches. Native signing prompts name the actual routed Core wallet and action. Disc decryption/encryption prompts explicitly request the disc-backup passphrase; peer transfer labels request the receiving computer login password.

Awaiting review, attempted/outcome-uncertain and completed states remain distinct. No lost response, restart or uncertain result triggers automatic replay. The retired local whole-wallet Vault Builder entry points, calculation module and obsolete generation tests are removed after a caller audit. Declared immutable vault-intent checks, current wallet policies and conservative recognition of any existing volatile export record remain.

## Multiple physical discs

Disc count defaults to 1 (range 1–99); write speed defaults to slowest supported. Reported numeric speeds are optional. xorriso's minimum-speed request is used even if a drive cannot enumerate numeric choices; the drive selects the actual safe media speed. Every requested separate disc contains repeated checksummed encrypted package copies across its capacity. The package is encrypted once in protected RAM. Each next disc requires local confirmation of fresh blank write-once media; full direct read-back must pass before its counter advances. The existing signed physical-role completion proof is emitted only after the entire selected set verifies. There is no new Dashboard field for disc count/speed and no automatic retry after an uncertain write or completion callback.

Services and the schema-limited wallet-sync Denial list remain the Agent's persistent preferences. Private staging, pending operations and optical settings stay volatile. Existing Core wallets/public monitors and intended optical/signed outputs keep their explicit destinations. No Dashboard files were changed by this Agent implementation.

Physical optical hardware, privileged protected Qt/systemd/AppArmor/Snap lifecycle and actual peer-machine deployment remain unverified here; see VALIDATION.md.
