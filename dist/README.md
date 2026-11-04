# Wallaby Agent Development installers

Current: **V2 Development Build 52**, Ubuntu 26.04 LTS amd64.

[Download Build 52](wallaby-agent_2.0.0~dev52_amd64.deb). Check its SHA-256 against [SHA256SUMS.txt](SHA256SUMS.txt) before installing.

Build 52 includes the cumulative disc fixes: recognized writer progress, independent burn/verification ETA countdowns, stable wallet and drive selections, bounded disc membership, and verification-only retries. Optical verification reads through the drive interface so Linux's stale 2 KB block capacity cannot truncate a newly written disc. Success still requires the entire intended byte count, a successful reader exit and the original full-track checksum.

Validated with 164 Python regression checks, 21 interface suites and an isolated live three-Agent recovery test. See the [main README](../README.md) and [Build 52 notes](../AGENT_BUILD52_OPTICAL_READBACK.md).

Finish sensitive work and all required backups, wait for Dashboard completion, then close the existing protected workspace normally before installing/restarting. A webpage refresh does not update a worker already running in RAM. Services settings are retained on upgrade; the installer does not forcibly destroy an active protected session.

Tunnel-only clients do not need Bitcoin Core or the optional protected viewer/optical packages. Optical operations additionally require xorriso. Earlier installers remain in this directory. This is a Development build.
