# Repeat an existing-wallet archive beside another signer disc

No Dashboard protocol change is needed. Dashboard Build 55 deduplicates active
same-wallet requests on one Agent, but a verified completed request does not block
a fresh archive request. Each new request has a fresh nonce and request_id.

1. Request David SMSF from Dashboard Wallets and approve its staging on Authorise.
2. Select David SMSF and the first Wallet Builder signer job in Disc Operations.
3. Burn and verify. Wait until Dashboard reports that archive as verified.
4. Click Archive again in Dashboard Wallets and choose the same producing Agent.
5. Approve this NEW archive request on Authorise, then select it with the remaining
   signer job and burn/verify the second disc.

Wallet Builder signer jobs need no extra authorisation after complete-policy
approval. Each separately requested existing-wallet archive does need approval.
The remaining signer stays queued after the first burn. Completed captures are
removed only after read-back; the original persistent wallet is unchanged. Replays
of the first completed task or receipt cannot capture again or complete the new
request. No automatic requeue, target extension or new receipt type is introduced.

Disc count repeats the SAME selected set on several discs. The sequential process
above is for different signer sets. Selecting two physical roles of one multisig
policy on the same disc remains refused. A completed archive record is proof of
a backup: do not use cancellation of that completed record just to request another
copy, because cancellation initiates reviewed physical-disc cleanup.

Validation: tests/test_build47.py::RepeatedArchiveDiscs uses three real isolated
Core nodes, two physical roles and two fresh archive requests. Each request is
captured, written through real file-backed xorriso and directly read back with its
own signer. After the first, the other signer remains; after the second the setup
finishes. Both archive identities differ. The existing Dashboard Build 55 queue
was separately exercised through signed completion, fresh-request creation and
old-receipt replay. No Dashboard source, real wallet, installed service or physical
optical medium was changed by these tests.
