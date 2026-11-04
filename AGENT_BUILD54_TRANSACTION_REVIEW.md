# Build 54: transaction review timer and local wallet icons

## Signing expiry

The transaction review has a ten-minute authorisation lifetime. The Dashboard investigation found a review at 19:11:42 UTC followed by a failed attempt at 19:28:34 UTC. Earlier builds requested the wallet passphrase before checking expiry and their sanitised diagnostic log did not include the expiry explanation. The elapsed time strongly indicated expiry, but the old log did not conclusively identify that error.

Build 54 checks review validity before requesting a passphrase, again when password entry returns, after transaction revalidation, and immediately before requesting signatures or broadcasting. Expiry raises an authored transaction_review_expired diagnostic with instructions to review again; the message is visible to the user and retained in sanitised logs. The signing request remains pending when nothing was signed. An expired review cannot unlock or sign through a fresh attempt; if a review expires during a preparatory unlock, the wallet is relocked and no signature request is made. Existing uncertain-operation and no-replay rules remain enforced.

The review shows a sticky Transaction countdown in minutes and seconds, including on broadcast reviews. It uses the protected worker’s remaining allowance and a browser monotonic clock, deducting request transit/processing time conservatively. It does not start an independent extra ten-minute allowance on arrival. Backend enforcement also uses monotonic elapsed time so rolling the wall clock backwards cannot extend a review. The timer does not pause during native password entry. At zero, the action is disabled and Review again is offered. The transaction details remain visible. A fresh review independently recalculates the transaction and restores the allowance; no transaction rebuild or automatic signing is performed.

## Card icons and trust

The icon order is Wallet, Vault, Multisig, Watch, Disc. Wallet is always first on transaction input/output and local-wallet cards, including an unknown output; Network Fee has none. Optional icons are only shown when supported by local evidence. Their accessible labels/tooltips explain what they mean. The artwork follows the Dashboard’s existing wallet, safe, keys, eye and disc symbols.

Wallet names continue to come from local ownership matching. Vault and Multisig reflect parsed public descriptors obtained from local Core; only the restricted mandatory-height policy establishes the Vault icon. A separately declared vault output must pass existing independent policy-approval, address-derivation, script and amount checks before it gains policy markers. Watch means the matched local accounts have no private signing account; Disc means a matched local account is routed from an archive loaded in this protected workspace. These facts describe this Agent, not keys or archives on other machines. Unknown outputs receive no unproven policy/storage icons. No exchange identity or Dashboard-supplied display flag is used. No icon establishes a funded balance or says a vault is still locked.

The underlying PSBT review, exact output comparison, fee acknowledgement, transaction hash and input checks are unchanged. Icon metadata does not authorise a different transaction.

## Validation and installation

Regression coverage includes the exact 600-second boundary, wall-clock rollback, expiry before password entry, expiry during password entry, safe diagnostic output, an expired request followed by successful explicit re-review and signing on isolated Bitcoin Core, descriptor threshold and storage traits, countdown cleanup and server-side expiry recovery. Interface checks cover icon ordering, unknown outputs and absence of fee-card icons. Existing wallet/disc/startup checks are retained.

No Dashboard update is required for this change. Finish active protected work and close its workspace normally before installing. This update does not modify a pending transaction or bypass its review.
