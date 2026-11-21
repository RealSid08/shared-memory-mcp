# Provenance and licensing notes

This project started in v1/v2 as `codex-shared-memory`, an independent Python service whose early tool surface was evaluated for compatibility with the OpenAI Codex memory extension (`d6489472f3c15e87d2d7763a5fde033545c530f8`).

In v3 it was renamed to `shared-memory-mcp` and rebuilt around curated, typed topic memories (`user`, `feedback`, `project`, `reference`) accessible across Claude Code, Codex, Antigravity, OpenCode, Cursor, and any stdio MCP client.

No third-party source files, tests, private snapshots, credentials, databases, or logs are included in this repository. The MCP transport follows the public [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-11-25).

This repository is licensed under the Apache License 2.0. It is an independent community project and is not affiliated with or endorsed by Anthropic, OpenAI, Google, or Anysphere.

This note records engineering provenance and is not legal advice.
