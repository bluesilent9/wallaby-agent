# Build 39: archive an existing wallet during a new vault setup

## Cause

After signing keys were generated, a setup could remain in the contributed phase with a setup_active reservation while waiting for complete-policy approval. Dashboard RPC execution rejected every read based on that reservation, including getblockchaininfo, even though generation had finished and no persistent node wallet was being changed. Dashboard health then became checking and its archive options excluded the node. Build 38's idle-disc read fix did not cover this earlier wait or the separate Dashboard execution path.

## Changes

The protected workspace now supplies one validated public RPC callback for Dashboard execution and the local public bridge. An idle contributed setup, an idle wait for discs and queued archives permit public read-only queries. The original setup reservation remains intact and still blocks closure and unrelated sensitive operations. If another local action holds the workspace lock, public requests return busy immediately rather than waiting behind a passphrase dialogue.

Local review and approval of an archive_wallet request are permitted during an idle contribution wait. The archive handler independently verifies persistent private-key ownership, descriptor identity, scan status and related public policies, and captures only after local consent. Generation, policy installation, failed setup states, unknown reservations, active transfers, history recovery, cancellation, active archive capture and optical work remain guarded. No new Dashboard RPC method or private operation is exposed.

Dashboard also needs to avoid treating a full blockchain-health check as a prerequisite for offering an existing-wallet backup. Its separate archive-eligibility update handles that button. Agent changes alone do not change Dashboard controls.

## Preserve a setup already in progress

Do not close or force-restart a protected workspace holding unfinished disc material just to load this version. A running older worker retains its version and cannot adopt new Python methods by installing files underneath it. On the existing build, review the complete wallet-policy request on each contributing Agent and approve only if correct. This installs the policy without funding the vault or burning a disc. A node producer then finishes; a disc producer waits for discs. These phases already allow reads in Build 38. With Dashboard eligibility corrected, stage the independent archive, finish the intended burns, and upgrade after safe closure.

No production wallet, workspace or installed service was changed by these tests or by building this package.

## Expired complete-policy reviews

The existing ten-minute approval review limit remains enforced. The interface replaces an idle final-policy approval with Review again shortly before expiry. A server refusal for an expired policy review also replaces the stale control. Re-review is explicit and approval is never automatically repeated; a submitted approval cancels its idle UI timer. No key generation is repeated and the setup remains intact.
