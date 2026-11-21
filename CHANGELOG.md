# Changelog

## 3.0.0 - 2026-11-21

- Rename the project from `codex-shared-memory` to `shared-memory-mcp` to reflect its harness-agnostic design.
- Rewrite the store, exchange protocol, and MCP surface as curated Claude-style typed topic memories (`user`, `feedback`, `project`, `reference`) organized into `global` and per-project scopes.
- Replace raw per-machine/harness file scraping (`sharedmem/sources.py`) and append-only ad-hoc notes with four focused MCP tools registered as `memory`: `recall`, `read`, `save` (upsert in place), and `forget`.
- Return compact Markdown text from MCP tools instead of escaped JSON, and include behavioral guidance in MCP `initialize` `instructions`.
- Enforce anti-slop guardrails: 8 KiB max body size, 200 memories per scope, 2,000 total memories, 16 MiB store quota, and secret rejection on `save`.
- Add Antigravity harness registration (`~/.gemini/config/mcp_config.json` and T3 Code Antigravity provider configs) alongside Codex, Claude Code, OpenCode, and Cursor, and clean up legacy `shared_memories` entries.
- Add `import` CLI command and automatic `pre-v3-migration.sqlite3` backup when migrating v1/v2 stores.
- Keep default runtime paths (`~/.local/share/codex-shared-memory`) and OS scheduler identifiers stable so existing deployments upgrade in place.

## 2.0.0 - 2026-10-29

- Split the single script into the `sharedmem/` package (core, sources, store, tools, mcp, server, client, harnesses, scheduler, install, cli); `shared_memory.py` stays as the launcher at the same path.
- Add pluggable memory sources: `codex`, `claude-code`, and generic `markdown` directories, each with a server-enforced allowlist and its own namespace under `machines/<machine>/<source>/`.
- Register with Codex, Claude Code, OpenCode, and Cursor, and write guidance once per real instruction file, skipping files that already carry a shared-memory policy.
- Serve MCP reads from the local cache by default (`serve --config`); note writes go to the server and refresh the cache.
- Skip and report oversized or unreadable files and missing sources instead of failing the whole sync; raise the per-file limit to 2 MiB.
- Add store schema versioning with an automatic, backed-up v1 migration, v1 exchange compatibility, a status operation, and a `doctor` command.

## Unreleased (1.x)

- Document the recommended `AGENTS.md` guidance, placement options, safety boundaries, and lookup workflow for agents using shared memory.

## 1.0.0 - 2026-09-12

- Extract the proven single-user service into a portable repository.
- Replace hard-coded host, username, data path, mount, and scheduler identifiers with options and safe defaults.
- Add server and client installers for local or SSH-backed deployments.
- Preserve the allowlisted snapshot model, append-only notes, offline cache, quotas, redaction, backups, and stdio MCP interface.
- Add cross-platform CI, installer coverage, release checks, architecture, operations, installation, and threat-model documentation.
- Exclude all private snapshots, runtime configuration, databases, credentials, network details, and logs.
