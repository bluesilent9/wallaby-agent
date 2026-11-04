# Build 52: verify the drive rather than stale Linux block capacity

## Confirmed fault

On Treasury Australia's ASUS SBW-06D5H-U, the second writer reported progress through all 25,023,217,664 intended bytes and exited successfully. The next O_DIRECT read returned one 2048-byte sector, then EOF. Verification stopped at byte 2048; it never reached a checksum comparison.

The diagnostic taken before ejecting showed Linux sysfs size 4 sectors of 512 bytes and BLKGETSIZE64 capacity 2048 bytes. A direct read returned only 2048 bytes, with an offset-one-MiB read failing EINVAL. In contrast, xorriso queried the drive successfully and reported a written, closed disc with 12,218,528 readable optical blocks, approximately 25 GB. Linux still reported only 2048 bytes after that query. This establishes stale kernel block capacity as the immediate cause of the read failure. It does not by itself prove that every recorded byte is correct.

The first Australia + SMSF disc had previously passed its complete 25,023,217,664-byte checksum after physical reload. The second disc requires its own complete check; the earlier disc's result is never reused.

## Fix

For optical block devices, verification now uses xorriso/libburn's drive-level reading path. It requests the entire intended raw track with an explicit inclusive LBA limit, including repeated recovery bundles beyond the small ISO filesystem. `-check_media what=disc data_to=-` sends raw read data through a pipe into a bounded one-MiB hashing buffer. It never writes the disc, creates an on-disk image, extracts keys or changes pruning/node settings. The old kernel capacity is observed for diagnostics but cannot truncate this check.

The command uses only an input drive, no output drive or cdrecord emulation. `patch_lba0=off` preserves the exact recorded bytes. Recovery retries are enabled at the drive's optical cluster level; unreadable/partial media reports produce a failing reader status. Quality-report storage is bounded by item_limit=1024 and stderr retains only eight bounded diagnostic lines. No list of physical recovery copies is constructed.

Success requires all three: exactly the original intended byte count, reader exit zero, and SHA-256 equality with the original protected RAM stream. Short or excess output, reader failure even with matching bytes, and checksum differences are refused. Ordinary file-based test tracks retain the aligned direct-read path. A rejected non-sector partial read is no longer fed into the hash before retrying.

The GUI says verification could not finish for read interruptions, rather than implying that a complete comparison found corrupted data. A checksum mismatch still reports Verification Failed. Protected material remains available for deliberate verification-only retry.

## Current session recovery

`Wallaby_Agent_Resume_Russia_Disc.py` is restricted to the diagnosed Build 47 session and its exact second disc job. It preserves the already-verified Australia disc, the original ciphertext and the pending Russia + SMSF members. CPython's supported in-process execution patches the reader without restarting the service, then invokes the ordinary verification-only completion path. It never forges a receipt from writer status, capacity, samples or the first disc. Only this second disc's complete matching checksum can finish its remaining physical backup and archive request. Keep the workspace open until success and Dashboard delivery finish.

## Validation

A real xorriso file-track check reads and hashes data beyond a small ISO filesystem. A mocked kernel capacity of 2048 bytes does not constrain that reader. Tests refuse an oversized requested range, a complete checksum mismatch, and a reader that returns the expected bytes but exits with error. The live three-Agent recovery test completes the first signer disc, creates a fresh independent archive request, deliberately interrupts the second verification, then runs the delivered recovery payload in the live worker process: only the second disc's actual members complete and the final setup role finishes.

The normal regression retains Build 51's independent ETAs, stable checkbox selection, exact-job burn admission and all earlier vault/refresh/archive safeguards. No physical drive or production wallet was touched by development tools. Actual media validity is determined by the read-back on the user's burner.

Install after completing the current protected setup and closing it normally. The recovery tool can be used while the old worker remains open; installing this package or refreshing a webpage alone does not replace that worker.

Reference: GNU xorriso manual, -check_media and data_to standard-output mode:
https://www.gnu.org/software/xorriso/man_1_xorriso.html
