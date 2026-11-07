# Build 62 — extinction preparation and Bitcoin Pipe formatting

## Confirmed failure path

Diagnostics showed repeated authorise.history attempts lasting approximately nine to eleven minutes, including a Core importdescriptors refusal, with no completed preservation receipt. History preparation imported fixed public addresses with timestamp zero before creating its recovery job. On a pruned node this starts a doomed historical rescan; import failure prevents the recovery job from being queued. Repeating the button repeats the same rescan. No deletion phase is reached.

Preparation now validates the proposal, active chain and address ownership, stages only missing public addresses using the existing non-rescanning timestamp mechanism, and creates an explicit local recovery job. Repeated preparation retains the exact pending job instead of importing again. Existing identical addresses retain their labels; conflicting labels block rather than being overwritten. Original historical timestamps and labels remain in the recovery plan. Matching original source wallets join the same locally authorised recovery so their later deletion checks can establish coverage too. Private keys are not exported or copied.

The review now distinguishes a prepared recovery and offers Open prepared history recovery, leading to This Node on Synchronisation without another preparation call. Download/replay/rescan still requires its separate local approval and preserves pruning settings. Preparation itself never silently starts a blockchain download or reindex.

A complete Extinct wallet is checked before asking an older source wallet to establish broader pruned history coverage. Every required address and label, transaction identity, confirmed active-chain block and relationship to the public source descriptors must verify. Retained Core wallet transaction data can prove the exact preserved manifest even when the original blocks are pruned. Already verified history does not need another descriptor import/rescan. Preservation then produces its existing signed receipt; Dashboard must independently verify it before offering separate zero-balance deletion. All original source deletion, funded-wallet, independent identity, shared-signer and external-history-confirmation safeguards remain.

If the archive still lacks old transactions outside retained blocks, explicit history recovery is genuinely required. The fix exposes and queues that step instead of repeating an impossible import or claiming success. Existing requests and installed partial public imports can be reviewed again after upgrading; no new extinction operation is required solely for this fix.

## Repetition and duplicates

Real Core regression checks import the same manifest repeatedly and compare transaction counts, descriptor records and labels. Counts and records remain unchanged: the same transaction is not appended as another independent transaction. Readback is still required; a failed or cancelled scan is not preservation success. Existing This Node recovery jobs are not overwritten or replayed automatically.

## Bitcoin Pipe notation

Match Dashboard Wallets formatting exactly using integer satoshis:

- 1.00000001 BTC -> `₿1.00 | 1 sats`
- 0.00123456 BTC -> `₿0.00 | 123,456 sats`
- 1234567.89123456 BTC -> `₿1,234,567.89 | 123,456 sats`

Keep two decimal places on the Bitcoin side, group whole Bitcoins and the satoshi remainder with commas, and do not zero-pad the remainder. Zero and negative values follow Dashboard's existing convention. Transaction amounts themselves are unchanged.

No Dashboard protocol update is required. Existing retirement version 3 proposals, results, hashes and signatures are preserved. Tests and packaging never modify real wallets or install/restart user services.
