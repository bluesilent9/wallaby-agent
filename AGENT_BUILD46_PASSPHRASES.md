# Build 46: correct password confirmation without losing progress

All wallet passphrase prompts now use one native Qt dialogue in a separate
protected child process. Creation/backup prompts contain both passphrase fields.
A mismatch explains the error, clears only the confirmation and leaves the
original entry and operation waiting. Empty, overlong or creation passwords below
12 characters can also be corrected in the same dialogue. Existing wallet unlocks
retain their original password-length compatibility. Cancel remains an explicit
request to stop local secret entry; it does not automatically retry an operation.
The existing five-minute dialogue timeout remains.

Computer-login password inputs on Synchronisation also have a Show/Hide button.
They are cleared and re-masked on submission even when visible at that moment.

Every field starts masked and has an independent Show/Hide button. Visibility
can be switched without submitting the dialogue or requesting the password again.
The wallet and role name remain visible, interpreted as plain text. Mismatch
warnings contain no password or other secret. There is no mismatch event exported
to Dashboard and no wallet/key generation is started until confirmation succeeds.

The helper checks the same protected service, non-swapping RAM and no-dump
requirements before loading Qt or asking for a secret. Qt storage paths point
inside protected RAM. Only public prompt settings enter stdin; passwords never
enter process arguments/environment. A private stdout pipe returns the accepted
password with JSON framing, preserving actual Unicode/newline characters. Stderr
is never copied into logs or UI. Fields are cleared and visibility reset on exit.
There is no browser or persistent-file fallback. python3-pyqt6 is already a
prerequisite of the protected viewer, while SSH-only installations remain valid.

The reviewed builder-cancellation screen no longer requires an extra checkbox.
The red Delete and Cancel button directly submits the selected cleanup. Backend
review expiry, changed-artifact, empty/history and active-writer checks remain.

## Archive availability investigation

A real three-Agent 3-of-5 fixture reaches awaiting_disc with two physical roles.
The burn Agent answers its public inventory RPC and can locally approve and stage
an unrelated private David SMSF wallet. Those real public responses also produce
a usable archive destination through Dashboard Build 54 inventory processing
(test adapter selects regtest key versions; production remains mainnet-only).

Adding one unrelated unloaded wallet-directory entry reproduces Dashboard's
"Waiting for wallet inventory" message. AgentHub.refresh_inventory rejects the
entire inventory before querying any loaded wallet. The user's Treasury Australia
output has precisely this condition: david_smsf is loaded, but two old generated
wallet directories are unloaded. Dashboard is fixing the distinction between
loaded archive sources and complete inventories required for missing-wallet sync.
No Agent wallet folder is hidden, loaded, renamed or deleted to work around this.
No production wallet or current ceremony was changed by our isolated tests.

## Verification

Actual Qt widget tests run offscreen with invented passphrases: a mismatched
confirmation keeps the dialogue open and emits no accepted signal; correcting it
succeeds. Both visibility controls, clearing, short/empty/oversized retry,
existing short wallet-password compatibility, Unicode/newline pipe framing and
safe failure when the helper cannot open are checked. Parent invocation tests
check that password data is absent from arguments/environment and desktop display
context survives background requests. No real desktop password prompt is opened
by the tests. Full vault installation, signing, cancellation, archive, IPv6 and
interface regressions are also run before packaging.
