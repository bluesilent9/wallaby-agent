# Build 92 — Wallets and stable receiving reviews

Wallet cards, transaction history and local deletion controls now live on the protected Wallets page, after Synchronisation in the alphabetical sidebar. The unprotected window disables this page. Entering Wallets reloads local Core wallets; mutations still trigger a refresh.

The fresh protected status response previously cached raw wallet_transfer approvals before projecting local grouped receive requests. Busy polling returned that old cache and replaced an open review with a different request. The cache now stores the displayed approval projection, and the browser does not treat a status_pending cached list as an authoritative withdrawal. Real request changes still invalidate the review and its single-use approval token.

Receive checkboxes have accessible labels without visible Receive text. Denied rows are red, enabled rows green. The extra disabled paragraph is removed. Denied discovery notices retain their advertised source while receiving remains blocked. When the Server has omitted a source, the UI says availability was not reported rather than claiming no Agent was detected. Server Build 11 must be updated to provide denied receiving offers while continuing to suppress denied sends.

Concurrent sender preview preparation now keeps the first immutable signed snapshot instead of sending a second timestamp/signature for the same request. A changed/expired Server preview is surfaced in the local receiving review before approval. Restarted RAM workspaces still require the Server to renew an obsolete frozen preview; no Agent bypasses that binding.

Checks cover real worker fresh/busy status projection, browser review survival and temporary disabling during busy polls, denial/source visibility without transfer authority, concurrent preview creation, protected/unprotected navigation, alphabetical sidebar, row colours, wallet history/deletion, and complete Extinct history plus grouped transfers over real Core/direct SSH.
