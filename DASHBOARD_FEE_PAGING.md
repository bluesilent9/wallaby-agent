# Dashboard follow-up for Agent V2 Build 20

## Confirmed cause from the supplied logs

At 31 October 2026 21:32:40 UTC, Dashboard requested `getrawmempool [true]` for 37,963 transactions. Agent returned `local_rpc_response_limit`. The same occurred for 38,108 transactions at 21:33:41 UTC. The local HTTP/result envelope exceeded the Agent's 16 MiB boundary. Recent blocks, Core fee priorities and BTC/AUD quotes succeeded. This is not an SSH or unsynchronised-node failure. The preceding 401/re-registration followed Dashboard's logged profile replacement and is separate.

Agent Build 20 supplies a new bounded read-only paging method. **Dashboard must adopt it before this fixes the projection on the installed system.** No Dashboard source was changed in this Agent build. Ordinary `getrawmempool` retains its exact Core response shape and existing 16 MiB envelope; it is never silently truncated or reinterpreted.

## Required Dashboard change

Add `wallaby_mempool_snapshot` to Dashboard's public node RPC method allowlist (`agent_rpc.NODE_METHODS`), so capability negotiation and RPCBroker accept it. It is an Agent adapter method, not a Bitcoin Core RPC or wallet operation. Agent advertises it in the existing v1 registration methods list. On the selected node, replace the Fee Estimates verbose-mempool request with:

```
wallaby_mempool_snapshot {}   # or []
```

The reply is:

```json
{
  "version": 1,
  "snapshot": "32 lowercase hex characters",
  "created_at": 1793480000,
  "expires_at": 1793480300,
  "total": 38000,
  "offset": 0,
  "next_offset": 1000,
  "entries": {
    "64-character transaction id": {
      "vsize": 150,
      "fees": {"modified": "0.00001234"},
      "depends": []
    }
  }
}
```

Continue on the **same node and connection** with:

```
wallaby_mempool_snapshot {"snapshot": "<same id>", "offset": 1000}
```

Offsets advance by 1,000; the last `next_offset` is JSON null. Each page has at most 1,000 entries, ordered lexically by txid. All pages refer to one immutable complete Core mempool capture. Fees are exact BTC decimal strings; dependency IDs, vsize and modified fee are precisely the fields consumed by current `fees.project`. This is fee-planning data, not a replacement generic verbose RPC response.

Validate the version, ID, timestamps, total and contiguous offsets on every reply; reject duplicate txids, out-of-order/mismatched pages, unexpected offsets and changed totals. Collect every page before calling `fees.project`. Require the final unique entry count to equal total and all dependency IDs to be present. Empty mempools have total 0, empty entries, offset 0 and next_offset null. Never draw an unfinished capture as a complete projection.

Keep any existing bounded projection complexity limit explicit (current Dashboard is 50,000 transactions); do not truncate a capture to fit it. Keep recent blocks and fee recommendations available independently. If a capture expires or is replaced, discard its incomplete assembly and start a fresh capture under bounded retry/backoff; do not mix captures or nodes. An earlier complete projection may remain visibly labelled with its capture age while refreshing.

There is one cached snapshot per Agent Core connection, valid for 300 seconds; a new capture replaces it. Agent limits the local-only verbose HTTP read to 64 MiB and 100,000 entries. Remote page responses still pass the normal 16 MiB/private-material checks. An over-capacity or invalid capture fails explicitly; no partial graph is supplied. Snapshots stay only in protected process memory. No new signing, private-key access or wallet mutation is enabled.

Error categories include `local_rpc_mempool_busy`, `local_rpc_mempool_expired`, `local_rpc_mempool_limit`, `local_rpc_mempool_offset`, `local_rpc_mempool_core`, and the existing response limit/validation categories. In a response-limit error, `error.data` now identifies the boundary and byte limit; `observed_bytes_at_least` is a lower bound, not an asserted full response size. Existing read-only RPC acknowledgement/no-replay behavior is unchanged. Each page request needs its own RPC job ID; do not replay an already acknowledged command.

## Suggested Dashboard logging improvements

- Record selected node, method, safe parameters (verbose mode or page offset only), RPC/job correlation ID, elapsed milliseconds, returned/expected entry counts and a final complete/incomplete status.
- For paging, record capture identity, page count, capture age and validation/retry category. Prefer a short diagnostic identifier rather than printing transaction IDs or payloads.
- Preserve Agent `error.data.boundary`, `limit_bytes`, `observed_bytes` or `observed_bytes_at_least`. Distinguish a local Core HTTP cap, sanitized public-result cap and Dashboard receive/validation cap. Do not describe a lower bound as the full reply size.
- Keep authentication/profile-reset recovery separate from projection errors, as the supplied log already largely does. Log when the previous projection is being retained and its age, or when projection is unavailable; never imply a successful refresh includes a failed projection.

Do not log cookies, authentication tokens, full mempool responses, descriptors, addresses or key material. Dashboard's current error entry correctly exposed the immediate 16 MiB cause; correlation, elapsed time and byte-boundary measurements would make the next investigation faster.
