# Build 48: recognise the actual optical writer's progress

## Cause and current session

Build 47 required a `Track 01:` prefix on every progress line. The installed
xorriso instead emits lines such as:

    xorriso : UPDATE :    8 of   32 MB written (fifo  0%) [buf  50%]   7.6x.

A throttled file-backed invocation with the same cdrecord arguments reproduced
this exact output on stderr. The old parser returned no progress even though the
writer completed and the output read back correctly. The local installed xorriso
manual also documents the prefix-free `X of Y MB written` form.

Treasury Australia's read-only samples show writer input rising from 7,145,173,352
to 7,235,678,568 bytes over ten seconds: about 9.05 MB/s, well beyond the 16 MiB
writer FIFO. Output counters also rise. This is strong evidence of sustained
writer activity, not proof of a successfully recorded disc. The running Build 47
session should be left to finish writing and direct verification. Do not restart
it just to install this display correction.

## Changes

* Accept real xorriso UPDATE lines, prefix-free MB reports, and legacy Track
  prefixes. Preserve exact decimal conversion, clamping, and final successful
  writer-exit confirmation. Warnings and unrelated messages cannot advance bars.
* Display elapsed writing time and reported MB/GB alongside the stage bar. If no
  physical progress has been recognised, distinguish starting from input being
  accepted. Never turn pipe input byte counts into physical writing percentages.
* Show the age of the last progress report when it is at least 30 seconds old.
  An old report describes missing information; it does not automatically label
  the drive stalled or restart it.
* Record fixed public writer-launch, recognised progress, completed input and
  writer-exit diagnostics. Progress logging uses ten-percent buckets, rather
  than logging each line or embedding raw writer output. Existing bounded,
  redacted failure diagnostics remain in place. Counters stay in the protected
  job; no keys, passphrases or image contents are exposed.
* Progress poll updates still mutate existing elements. New counters do not enter
  the structural render signature, preserving Build 47's DOM/memory safeguards.

Writer byte reports describe the writer's progress; only direct read-back proves
that the disc matches the prepared image. Completion, cancellation, backup counts,
archive formats, policy-refresh history and local approval rules are unchanged.
No Dashboard protocol update is needed.

## Validation

Three new checks cover actual and legacy report formats, refusal to confuse pipe
acceptance with physical progress, and a real throttled file-backed xorriso stream
which must emit intermediate progress BEFORE it exits. Its output passes direct
read-back. The focused 21-check writer/disc run passes, including the three-Agent
repeat-archive case. All 20 JavaScript suites pass, including elapsed time, byte
counts, stale reports and the existing approval guards. Full regression results
are distributed with the build; they include vault policy refresh and archive
load/refresh/signing flows. All wallets/media in development are disposable test
fixtures. No physical burner hardware was used here.

## Installing for the next refresh tests

Finish verification and every remaining required physical backup, or explicitly
cancel/reconcile unfinished work, then close each protected workspace normally.
Install Build 48 after that. Refreshing the webpage alone cannot replace an old
worker already running in RAM. This build does not hot-patch the ongoing burn.

Reference: GNU xorriso's -pacifier and cdrecord emulation documentation:
https://www.gnu.org/software/xorriso/man_1_xorriso.html
