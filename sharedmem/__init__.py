# SPDX-License-Identifier: Apache-2.0
"""Self-hosted, harness-agnostic curated Markdown memory (Claude-style).

Python 3.11+, standard library only. Modules:

- core: limits, validation, redaction, Markdown rendering, atomic writes
- store: server-side SQLite store (schema v3), CRUD, search, backups
- tools: MCP tool schemas and recall/read/save/forget behavior
- mcp: newline-delimited JSON-RPC stdio transport
- server: exchange protocol handler (protocol v3)
- client: client pull sync, local Markdown + JSON cache, cache-backed MCP backend
- harnesses: MCP registration for Codex, Claude Code, Antigravity, OpenCode, Cursor
- scheduler: launchd, systemd and Task Scheduler definitions
- install: client and server installers
- cli: command-line entry point
"""

VERSION = "3.0.0"
