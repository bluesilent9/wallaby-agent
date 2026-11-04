# Build 47: disc progress, approval and protected-viewer recovery

The Treasury Australia kernel record at 2026-11-04 04:50:04 UTC identifies a
QtWebEngine renderer using about 2.6 GiB of anonymous memory inside the protected
service's 3 GiB memory limit. xorriso was also running. The service then stopped
with oom-kill and restarted. This lost the volatile ceremony and physical-role
backups; it was not a missing authorisation of the already approved signer jobs.
The logs cannot establish whether that particular disc was physically written.

## Disc Operations

* Each active preparation, burning and verification stage has a wide progress
  bar. Each stage starts from zero. Preparation reports completed tasks; physical
  burning advances from xorriso's written-byte reports, not bytes fed to a pipe.
  Waiting for the writer or disc finalisation is explicitly described.
* Direct full read-back reports Verification Successful or Verification Failed.
  Writer failure reports Burning the disc failed. Preparation and completion
  failures have separate messages. Neither writing nor queuing counts as a
  verified completion. Unselected jobs remain pending.
* Check disc status reads the selected optical drive without writing. It reports
  blank, already written, no disc, or unknown. Written does not prove a valid
  backup, and a failed probe never claims blank. The check is available without
  queued work, and waits while another optical operation is active.
* Wallet Builder signer jobs are immediately selectable after local approval of
  the complete policy; they require no additional archive authorisation.
  Separate Dashboard Wallets archive requests appear as disabled checkboxes,
  labelled Awaiting authorisation. Review and approve staging on Authorise before
  selecting them for a disc. Merely receiving a request captures no private data.
* Disc count repeats the same selected set. Putting the same existing wallet
  beside two DIFFERENT signer discs uses two successive ordinary archive requests. After the first verifies and
  Dashboard records completion, click Archive again and approve that fresh
  request for the other signer disc. No Dashboard protocol update is required.
  See DASHBOARD_BUILD47_DISC_REPEATS.md.

## Memory and recovery

Progress updates mutate existing elements rather than replacing the complete
Disc Operations DOM. Overlapping page polls share one in-flight request. The
protected viewer has a bounded JavaScript heap and a higher OOM selection score.
The secure service uses OOMPolicy=continue so a renderer-only kill does not itself
stop the wallet worker. A stopped renderer offers a presentation reload, without
replaying an authorisation or disc action. A killed wallet worker remains a lost
RAM session; this change cannot reconstruct it. The 3 GiB cap, no-swap settings,
Chromium sandbox, write restrictions and crash-dump blocks remain enabled.

Package preparation checks available cgroup memory with a reserve as well as RAM
filesystem space. An unavailable/insufficient budget refuses preparation; it
never falls back to a persistent temporary file. Writer diagnostics use bounded
redacted tails. Public stage/result events help distinguish preparation from
physical writing and verification.

A policy received after its original RAM session was lost gives an explicit
missing-session explanation. It cannot regenerate signing keys by reapproving an
old participation proposal. Independent archives remain usable.

## Upgrade and current interrupted test

Finish or explicitly cancel and reconcile the current Wallet Builder ceremony on
each Agent, then close the protected workspaces normally before installing this
build. Installing code or refreshing a page does not upgrade an existing worker
in memory. A service that already lost its keys cannot resume that ceremony.
Never force-close a funded or unaccounted-for ceremony.

Use the existing reviewed Builder cancellation workflow. A persistent signer
wallet left by a lost session may require its own reviewed local deletion after
all requests are reconciled and its empty/history checks pass. Do not remove
unrelated old Treasury wallets or David SMSF. This build performs no automatic
cleanup of real wallets by their names.

To inspect the possibly used disc after upgrading: Disc Operations → select the
optical drive → Check disc status. A read-only status cannot establish how much
of an interrupted burn is recoverable; written media is not a fresh blank.

## Validation and limits

The final regression includes three independent Core 31 nodes with a 3-of-5
vault, two physical roles on one Agent, and two real encrypted David SMSF backup
captures. It writes two separate file-backed xorriso images and directly reads
each back. After disc one, only its matching SMSF request completes; the other
signer remains queued. A fresh SMSF archive request is then captured and verified
with the second signer. Replaying an old completed request does not capture again.
No real optical media or production wallets were used.

An accelerated offscreen Qt test runs 30,000 progress updates with no newly
allocated DOM elements. Observed process-tree RSS is about 0.5 GiB. A renderer
kill/reload fixture preserves a dummy worker, and an isolated 80 MiB user-service
OOM test confirms continue policy retains its parent. These checks do not promise
that every possible process kill or prolonged hardware failure preserves RAM.
Physical drive progress parsing uses xorriso report fixtures; physical burner
hardware has not been exercised in development here.

Systemd OOM policy reference:
https://www.freedesktop.org/software/systemd/man/255/systemd.service.html
Qt WebEngine flag reference:
https://doc.qt.io/qt-6.10/qtwebengine-features.html
