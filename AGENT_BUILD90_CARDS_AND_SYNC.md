# Build 90 — card colours, peer status and sync discovery

## Actual colour failure

The protected page sends `style-src 'self'`. The previous wallet renderer set its hue in an inline style attribute, which the browser refused. A browser fixture without that response header failed to reproduce the production restriction. The renderer now assigns random palette classes, defined entirely in the external stylesheet. Inline hue attributes and the old colour assignment are removed. The security policy remains strict. Each currently displayed wallet or peer receives a distinct randomly allocated colour class, stable during the page session and unrelated to ownership or wallet contents.

## Direct peers

Cards follow the Server Nodes page: coloured fill and top border, device icon, name, connection light/text, Agent or restricted-Mobile role, server/client orientation, and reconnect/delete controls. Green requires both an authenticated ready peer and a ready direct path. Amber denotes active negotiation or local confirmation; disconnected/disabled peers are red. A Server connection alone cannot turn the direct light green.

## Extinct synchronisation

The supplied Agent logs show a successful direct comparison and local Treasury deletion. Enabling receiving then restored zero executable requests. Server Build 7’s log identifies `peer_changed:1`: a stale IPv6-bound request blocks the offered Extinct transfer. The Server chat is preparing Build 8 to issue a fresh unattempted identity-bound direct request while retaining attempted outcomes and receive denials.

The Agent now retains each public offer’s source name and blocker in its table model. Discovery without an executable request displays that source and the actual blocker, including the need for Server renewal, rather than “No Agent Detected”. Receiving controls appear when the fresh direct request arrives. An offer alone never becomes transfer/import authority, and the Agent does not fabricate a request or retry an earlier operation. Discovery exports include status counts without wallet data, keys, addresses or source names.

## Validation

A headless Chromium fixture runs the actual HTML/CSS/JavaScript with the production Content Security Policy. It checks actual background colours, absence of inline wallet colours, peer lights and roles, deletion, transaction history/copying, stale-offer messaging and fresh-request controls. Isolated local tests cover deny/enable/discovery semantics, safe diagnostic counts and release identity. Current UI regressions and direct receiving behaviour are checked. Temporary regtest data and synthetic browser API responses are used; no live wallets, pairing records or Server profile are modified. Package extraction verifies every runtime/web file and document plus protected ownership/modes.
