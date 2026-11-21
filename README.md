# Shared Memory MCP

[![test](https://github.com/RealSid08/shared-memory-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/RealSid08/shared-memory-mcp/actions/workflows/test.yml)

Shared Memory MCP is a small, self-hosted MCP server that gives every coding agent harness the same curated, Claude-style memory across trusted machines. Works with Claude Code, Codex, Antigravity, OpenCode, Cursor, or any stdio MCP client.

One SQLite store on a server you control holds typed, scoped topic memories. Each client machine keeps a local JSON + Markdown cache for sub-5ms offline reads and writes through to the server over SSH.

This is an unofficial community project. It is not affiliated with or endorsed by Anthropic, OpenAI, Google, or Anysphere.

## How it works

```text
Remote Mac / Laptop (any harness)
  Claude Code / Antigravity / Codex / OpenCode / Cursor
        |
        | stdio MCP (recall, read, save, forget)
        v
  local memory MCP server + cache/ (memories.json + INDEX.md + scopes)
        |  ^
        |  |  save() / forget() -> 1 SSH round-trip + instant cache refresh
        |  |  5-min background pull -> keeps all machines in sync
        v  |
  Central Server (e.g. Raspberry Pi) over Tailscale SSH
        SQLite v3 (WAL, secret filter, 8 KiB cap, daily rolling backups)
```

- **Curated, not scraped**: no raw conversation dumps, rollout logs, or per-machine folders. Agents curate typed memories in place, modeled on Claude Code's memory design.
- **Four memory types**: `user`, `feedback`, `project`, and `reference`.
- **Scoped**: `global` (always included in `recall`) plus lowercase kebab-case project slugs (`web-app`, `api`, `career`, etc.).
- **Local-first reads**: `recall` and `read` hit the local cache on disk (`< 5 ms`, works offline, 0 SSH hops).
- **Atomic write-through**: `save` and `forget` forward over SSH to SQLite and return a fresh snapshot to the local cache in one round-trip.
- **Zero runtime dependencies**: Python 3.11+ standard library and OpenSSH only. No public HTTP listener.

## MCP tools

Registered under the MCP server name `memory`:

| Tool | Runs on | What it does |
|---|---|---|
| `recall(scope?, query?, type?)` | Local cache | Returns the scannable one-line index (`global` + optional project `scope`) or runs ranked keyword search. |
| `read(ids)` | Local cache | Batch-fetches full Markdown content for 1 to 10 memories (`<scope>/<slug>`). |
| `save(scope, slug, type, name, description, content)` | Server -> cache | Creates or updates a topic memory in place. Blocks secrets, bodies over 8 KiB, and scopes over 200 items. |
| `forget(id)` | Server -> cache | Deletes a stale, wrong, or superseded memory from the server and refreshes the local cache. |

The server speaks newline-delimited JSON-RPC over stdio and MCP protocol revisions `2024-11-05` through `2025-11-25`, returning clean Markdown text (not escaped JSON blobs) so agents spend fewer tokens reading memory.

## Guardrails

- **Types**: only `user`, `feedback`, `project`, or `reference`.
- **Size cap**: 8 KiB max per memory body (prevents log dumps and session transcripts).
- **Index cap**: 200 memories per scope, 2,000 total, 16 MiB store quota.
- **Secret filter**: rejects private key blocks, common API tokens, and credential assignment lines on `save`. Best-effort hygiene, not a substitute for keeping secrets out of memory.

## Quick start

On the server:

```sh
python3 install_server.py
```

Confirm non-interactive SSH with strict host-key checking from each client, then install on each client machine:

```sh
python3 install_client.py --machine laptop --ssh-host memory-server
```

The client installer copies the runtime, runs an initial pull, registers `memory` with every detected harness (Codex, Claude Code, Antigravity, OpenCode, Cursor; override with `--harness`), removes any legacy `shared_memories` registration, and schedules a 5-minute background sync on macOS, Linux, or Windows.

Verify end to end at any time:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py doctor \
  --config ~/.local/share/codex-shared-memory/client.json
```

(The default runtime directory remains `~/.local/share/codex-shared-memory` so v1/v2 deployments upgrade in place without breaking existing paths or schedules. Pass `--install-dir` and `--data-dir` to choose another path.)

See [docs/INSTALL.md](docs/INSTALL.md) for full setup and [docs/OPERATIONS.md](docs/OPERATIONS.md) for upgrades, imports, backups, restore, and removal.

## Agent guidance

The MCP server sends concise usage instructions in its `initialize` response, and each tool schema explains when to call it. For harnesses that work best with an explicit prompt cue, add one line to your global `AGENTS.md` or `CLAUDE.md` (see [docs/AGENT-GUIDANCE.md](docs/AGENT-GUIDANCE.md)). If you use Claude Code, you can also set `"autoMemoryEnabled": false` in `~/.claude/settings.json` so all memory flows through `memory` instead of per-folder local files.

## Layout

`shared_memory.py` is the stable launcher. The implementation lives in `sharedmem/`: `core`, `store`, `tools`, `mcp`, `server`, `client`, `harnesses`, `scheduler`, `install`, and `cli`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development and verification

```sh
uv sync --locked
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv run python scripts/release_check.py --public-release
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md), [docs/PROVENANCE.md](docs/PROVENANCE.md), and [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

Licensed under the [Apache License 2.0](LICENSE).
