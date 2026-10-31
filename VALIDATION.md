# Agent V2 Development Build 20 validation

The accompanying Build 20 test log records the final regression/focused runs and JavaScript checks. The package-verification receipt records source/document comparisons and SHA-256. No production Core, installed Agent services, SSH/firewall rules, physical discs or pruning settings were changed.

## Build 20 checks

- Reproduced the native-close failure using an admitted four-second request followed by eight seconds of simulated mandatory OS checks. Closing now succeeds after those checks. Stale requests, active private work, lock contention and unfinished delivery/archive guards remain in force. Only the exact old-worker expiry uses its older guarded close action; other refusals never trigger that fallback.
- Shipped ordinary-window JavaScript hides the normal close button, keeps configuration inert while a viewer is open/cleanup is pending, and exposes recovery only after confirmed viewer loss and failed cleanup. Authenticated API tests independently refuse an open/unknown viewer and absence of a cleanup failure. Successful recovery disables only the node, preserves DDNS-GO/Dashboard settings and invokes safe stop; failed stop never reports success or clears recovery evidence.
- A real HTTP fixture returns more than 17 MiB of Core JSON. Ordinary verbose RPC still refuses its existing bound with safe byte-boundary measurements. The new local-only capture accepts the bounded larger input, extracts the explicit public fee-planning fields and returns a small page. Response handles are closed on refusal as well as success.
- A 38,000-entry graph is captured once and delivered without missing/duplicate transactions across 38 immutable 1,000-entry pages. Exact modified fees and parent dependencies survive. Expired/replaced snapshots, invalid offsets/parameters, incomplete graphs, malformed/non-satoshi fees and overlapping capture are refused without partial projection data.
- The current Dashboard Build 20 projection function produces identical output from normal entries and assembled snapshot fields. Real Bitcoin Core 31 regtest verifies snapshot transaction identities, virtual sizes and modified fees against ordinary getrawmempool output. Ordinary RPC shape stays unchanged.
- New RPC is strictly public/read-only and takes no wallet endpoint. Existing private/signing/mutating direct RPC prohibitions continue. Log tests retain typed redaction, environment origins, seven UTC days/1 MiB per day, private file modes and safe handoff. New diagnostics record known local refusal categories, action/cleanup durations, capture counts and response-boundary measurements rather than payloads or raw exception text.

## Existing coverage

The regression includes guarded mixed-worker upgrades, optional tunnel-only installation, native/private viewer boundaries, real-Core multisig/vault signing, archive restoration and BIP-322 messages, local cancellation backup/restoration, private/watch/multisig retirement, persistent sync denials, loss labels, and genuine missing-block replay with pruning unchanged.

## Deployment limits and required Dashboard work

Native Qt/systemd/Polkit lifecycle is exercised with controlled substitutes, not a real privileged installation on wallet-laptop. The native X, log handoff and emergency cleanup still need on-device verification. No physical optical disc was written, and no production coins or wallets were used.

**Dashboard must adopt the new allowlisted paging adapter before the reported large-mempool projection will succeed.** Its source was not edited. Required changes, validation rules, limits and suggested Dashboard log improvements are in DASHBOARD_FEE_PAGING.md. The 64 MiB local capture / 100,000-entry bounds and Dashboard's independent existing projection complexity limit fail explicitly; this is not an unbounded mempool implementation.

Unknown/unreachable worker state is never proof that its viewer or private work is gone. Recovery does not bypass protection, unfinished-work or delivery checks, and does not force-discard RAM. Logs/working Bitcoin data preserve the existing protected-RAM and explicitly authorised persistence boundaries documented in the README.
