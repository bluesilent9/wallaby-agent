# Build 10 optical layout and recovery

A small ISO-9660 recovery filesystem contains recovery.wallaby (one encrypted package), policy-independent recovery instructions, the protected recovery utility and redundancy.py. The encrypted package contains exactly policy.json and one Core-encrypted role wallet. AES-256-GCM authenticates the package; scrypt N=131072/r=8/p=1 derives its key. Public header checksums do not replace GCM or trusted-policy review.

At the next 1 MiB boundary, a raw data track contains complete repeated packages. Every copy starts with a 4096-byte independently SHA256-protected JSON header: magic WALLABY-REDUNDANT-DISC-2, little-endian JSON length, canonical JSON, its SHA256 and zero padding. Fields are version, package_bytes, package_sha256, start, stride, copies, total_bytes, index, offset. Copy slots are rounded to 4096 bytes. The remaining tail is padding; the detected writable capacity reserves 2 MiB for drive overhead. Build 23 package limit is 512 MiB; supported medium capacity is at most 1 TiB. Streaming write timeout is 48 hours plus bounded finalisation.

The writer streams one encrypted package repeatedly through xorriso; it does not allocate a full-medium image or a directory entry for each copy. A complete direct-I/O track digest must match before success. Reading discovers a valid layout header, then jumps among exact slots, checking each complete ciphertext digest. Unreadable headers, short reads and corrupt payloads are skipped. Only a complete intact copy is decrypted, authenticated, policy-verified and offered for local review. Build 9's single-file layout remains readable through the ISO recovery file fallback.

This supplies complete-copy redundancy and integrity detection, alongside the medium's native error correction. It does not add parity able to reconstruct a package when every copy is damaged. Copies on the same disc do not protect against losing or destroying that disc. If all copies fail, try another disc or drive. Recovery passphrases cannot be replaced by knowing the block height or policy code.

Build 10 asked for 1x; current builds default to the drive’s slowest supported speed. Blu-ray 1x is 36 Mbit/s (4.5 MB/s), so a nominal 25 GB takes about 92.6 minutes of writing; lead-in/finalisation and full read-back are additional. DVD 1x is approximately 1.385 MB/s. Capacity is queried from the drive, not hardcoded as 25 GB. [Manufacturer optical-media brochure](https://docs.rs-online.com/a827/0900766b812db220.pdf).

No physical optical burn has been performed during development validation. Inspect this format and protection implementation before relying on archival recovery.

## Build 12: separate discs and speed selection

Choose 1–99 separate physical discs, default **1**, for each authorised physical role. Each disc retains the capacity-filling repeated-copy format above. The default **Slowest supported** requests xorriso minimum speed (`speed=-1`); it does not assume that 1× is supported. A read-only media query supplies optional numeric choices, which are revalidated before writing. The hardware controls the actual speed. Nominal 25 GB / 4.5 MB per second is about 93 minutes at 1×, excluding finalisation/read-back; minimum supported speed can be faster.

One encrypted package and small base ISO remain in protected RAM for the set. Every new disc requires explicit fresh-blank confirmation, and the complete written track is verified before advancing. Options are fixed once the set starts. No disc is automatically retried. A write/read-back failure is uncertain and requires a fresh blank disc and deliberate confirmation. If all discs verify but completion acknowledgement fails, reconcile completion; do not reburn automatically. Existing completion proof is sent only after the selected count verifies. RAM staging is removed after successful set completion.

## Build 23 multi-wallet container

The encryption and raw redundancy framing remain unchanged. A decrypted version-2 `wallaby-archive-set` ZIP contains `policy.json` and exactly one `wallets/<64-hex-entry-id>.dat` per entry. The manifest has `version`, `format`, `policy_hash` (canonical digest of all other fields), `entries` and `replaces` (old encrypted-package archive IDs). Each entry binds its ID, kind (`setup_role` or `node_wallet`), display name and complete recovery metadata. Version-1 single-role packages remain supported.

The bound is 15 entries, 256 MiB per wallet and 480 MiB total wallet bytes; encrypted packages cannot exceed 512 MiB. The writer streams repeated copies of that one package, so disc capacity does not multiply RAM usage or directory entries. It rejects insufficient protected RAM. No HDD/SSD fallback exists.

Generic node-wallet entries retain their public account, related public monitoring policies, address labels and approved same-key policy extensions. Setup-role entries retain signed original policy contributions plus the complete ordered extension chain. Independent cosigners of the same setup policy cannot be combined accidentally on one disc. The outer `ARCHIVE-ID.txt` labels the SHA-256 of the encrypted recovery package, not the physical image; identical separately burned copies share that archive ID.

Replacement coverage requires every old member and preserves its policy/label history. Only full selected-disc readback qualifies a replacement for the old-disc destruction checklist. Neither queueing a backup nor encryption alone qualifies it. All previous policies remain useful for detecting or spending earlier deposits after a renewal.
