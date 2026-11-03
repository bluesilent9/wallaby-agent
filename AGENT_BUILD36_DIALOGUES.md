# Build 36: retain desktop context for protected passphrase dialogues

The protected HTTP service sends background/status and approval calls using its system-service environment. That environment may omit the display and authority settings supplied when the protected viewer opened. Replacing the saved environment on each call discarded those settings before a later native passphrase dialogue. A regression reproduces the resulting pre-prompt refusal, then passes with the fix.

The worker now preserves previously supplied, authenticated local display settings when background requests omit them or send empty values. Valid nonempty updates replace them. The same fixed environment allowlist, value limits and validation remain in place; no arbitrary loader, executable or process variables are accepted. Existing setup/cancellation and message-signing dialogues share the retained context. This does not weaken storage, swap, signing-consent or close guards.

Protected logs now include exact known local error explanations, safe local RPC method/error codes, operating-system error numbers and the setup failure stage. Arbitrary exception strings and raw RPC data remain withheld. Offline Core startup output is drained into a bounded 32 KiB RAM buffer, discarded after readiness, and converted only to fixed public failure categories if startup fails. Raw output, passphrases, keys and proposals are not exported to the activity log.

The supplied empty-node probe confirmed successful offline Core startup under filesystem restrictions, with a native dialogue tool available. Its empty-node disk-space and missing-mempool warnings did not prevent readiness. Earlier logs lacked the exact original error, so they cannot prove its historical text; the reproduced display-context defect explains a dialogue refusal without a visible passphrase prompt. Fresh installed-user testing of Build 36 remains necessary.

Dashboard Build 42 separately fixes busy-node polling and stale network-error notices. Agent retains its intentional busy guards. No Dashboard protocol change is introduced here. This is V2 Development Build 36, not a Stable release.
