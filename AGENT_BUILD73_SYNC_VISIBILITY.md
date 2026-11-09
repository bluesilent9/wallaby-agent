# Build 73 — synchronization opportunities, not local inventory

Supersedes Build 71/72's inclusion of standalone local inventory in the sync table.
A local wallet without a usable recipient is not a synchronization row. Outgoing
pending requests require both a current matching receiver-enabled public offer and
a live independently paired direct connection. When the last recipient goes
away, the outgoing row and its badge count disappear without deleting the wallet.
Public outgoing advertisements alone cannot keep an empty send row on screen.

Incoming missing-wallet discoveries remain listed while waiting for their sender.
A locally denied policy always remains listed as denied, even if the sender and
its Server offer disappear. Denied incoming work contributes no badge count. When
a policy is re-enabled and rediscovered, it returns as ordinary pending receiving
work. All visible rows retain alphabetical sorting, multisig grouping and the
separate Signer column. Actual attempted transfers remain inspectable even after
a disconnection; they are never silently erased or replayed.

This is a read-only presentation change. Current wallet files, key roles, proofs,
selection/approval safeguards, persistent local denials and optical/archive data
are retained. The Services Wallet icon/title/description fixes from Build 72 remain.
No Wallet Server update beyond existing Build 6 is required.

Tests explicitly cover local-only/no-other-Agent emptiness, live-to-offline outgoing
visibility, incoming offline discovery, denied entries without any sender/offer,
re-enabling receiving, per-recipient filtering and retained attempted outcomes.
Existing sender-denial/reenable, multisig signer grouping, public offer validation,
queue/preference, worker startup, real direct-SSH single-signature and Server 6
cross-process checks pass. Browser tests check the empty table, zero sidebar count,
visible incoming rows and a denial-only table with no sender; JavaScript suites
exercise the rest of the GUI. Real user wallets and running services are untouched.
