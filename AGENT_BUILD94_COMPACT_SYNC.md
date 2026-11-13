# Development Build 94

The Synchronisation Signer column says `Single Signature Wallet` for single-signature policies, independently of watch-only storage. Multisig rows list available local signer labels and the selected source account name from its signed preview, without placeholder review text. An unavailable signer or an address-only Extinct archive is shown as an em dash; no signer identity is invented.

Routine waiting/availability notes no longer add lines under Enable/Deny receiving. Source menus retain the relevant explanation as a tooltip. Real attempted-transfer results and inspection controls remain visible. The actions column shrinks to its buttons and aligns at the right edge. Other columns keep natural table sizing; source menus can expand into freed space without the old 250px cap. Horizontal scrolling remains available on smaller windows.

The prior SSH diagnostic gap is also fixed: per-channel forwarding failures are logged even when the authenticated master stays alive. Logs distinguish a denied destination, refused listener, unreachable target, or other channel failure, without recording the raw SSH message or pretending an unattributed shared-channel error belongs to a particular service. HTTP diagnostics distinguish a close before status, invalid status line, truncated body and socket reset without logging response contents or request bodies. Transport restrictions and IPv4 Internet/IPv6 loopback routing are unchanged.

Checks include production-CSP browser screenshots and assertions for signer labels, tooltips, absence of row status paragraphs, source-menu width/action placement, preserved receiving selections, history views and normal cleanup; diagnostic category/redaction tests; release identity and existing Core/direct-transfer regressions. Packaging verifies source parity and root ownership/permissions.

The separate new-node discovery and signed-identity bugs identified in Wallet Server Build 14 still require the Server companion fix. This Agent release does not manufacture discovery offers or bypass identity checks.
