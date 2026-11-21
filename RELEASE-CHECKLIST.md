# Release checklist

## Owner decisions

- [x] License under Apache-2.0.
- [x] Publish as `shared-memory-mcp` (renamed from `codex-shared-memory`) with an unofficial-project disclaimer.
- [x] Use GitHub private vulnerability reporting.
- [x] Use the repository owner's real email in public Git metadata.

## Technical gates

- [x] Portable server and client paths, commands, schedules, mount guard, and free-space threshold.
- [x] No runtime dependency outside Python 3.11+ and OpenSSH for remote transport.
- [x] Unit, integration, installer, and local end-to-end tests.
- [x] Repository privacy and secret-pattern scan (`scripts/release_check.py --public-release`).
- [x] Runtime databases, caches, client configuration, logs, and memory snapshots ignored.
- [x] License notice and package metadata finalized.
- [x] Repository owner explicitly approved publication.
