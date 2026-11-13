# Optional source origin for current direct wallet sync

Agent Build 93 supports optional `source_storage`, with the closed enum `node` / `disc`:

* Inside the **signed version-3 wallet preview**, this is populated by the sending Agent from its local Core/disc router's `getwalletinfo.wallaby_storage`. Only `disc` is emitted; normal node previews are unchanged. It is covered by the existing canonical signature/hash and immutable preview binding. The Server must accept this optional member and forward the exact signed envelope unchanged. It must never insert or rewrite the member inside a signed preview.
* On a `wallet_sync_offers` version-1 offer, the Server may forward the same `source_storage` as a discovery hint. Use the sender's reported inventory `wallaby_storage` when a preview does not yet exist; prefer the signed preview once available. This hint affects the disc icon only. It does not create a selectable route, approve receiving or relax direct-pairing checks.
* Fields absent on existing node previews/offers are accepted. Unknown origin values are refused. Private data and paths are never included.

No `vault` or `multisig` flag is needed from the Server: receiving Agents parse the public descriptors. Extinct uses the existing public grouped-archive policy. SMSF is solely a case-insensitive substring check of the displayed wallet name.

Server regression cases: accept and preserve an authentic v3 preview with `source_storage: "disc"`; reject unknown values and any signature-changing mutation; preserve it through preview renewal, queued send/receive and discovery offers (including disabled offers). Existing node previews without the field must work unchanged. The Server cannot manufacture authority from origin hints.
