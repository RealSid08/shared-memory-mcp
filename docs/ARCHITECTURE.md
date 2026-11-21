# Architecture

## Components

1. **Core validation & rendering** (`sharedmem/core.py`). Enforces memory types (`user`, `feedback`, `project`, `reference`), scope and slug format, 8 KiB body cap, secret detection, atomic file writes, and Claude-style YAML-frontmatter Markdown rendering.
2. **Store** (`sharedmem/store.py`). One SQLite database (schema v3, WAL mode, `synchronous=FULL`) on the server with primary key `(scope, slug)`. Handles atomic upserts, deletes, bulk imports, quota checks, daily integrity-checked backups, and automatic backed-up migration from v1/v2 stores.
3. **Client sync & local cache** (`sharedmem/client.py`). Pulls the curated snapshot from the server on a schedule (default every 5 minutes) and on every write. Writes `memories.json` for fast reads plus a human-readable Markdown mirror (`INDEX.md`, `global/`, `projects/<scope>/`).
4. **MCP server & tools** (`sharedmem/mcp.py`, `sharedmem/tools.py`). A stdio JSON-RPC 2.0 server registered as `memory` with four tools: `recall`, `read`, `save`, and `forget`. Runs over either backend:
   - cache-backed (`serve --config client.json`, default on clients): reads directly from local `memories.json` (`< 5 ms`, offline-capable); `save` and `forget` forward over SSH to the server and refresh the local cache in one round-trip;
   - store-backed (`serve --data ...`, direct server mode).
5. **Exchange handler** (`sharedmem/server.py`). Invoked by clients over local stdio or authenticated SSH (`exchange_command`). Speaks exchange protocol v3 (`pull`, `save`, `forget`, `import`, `status`).
6. **Harness integrations** (`sharedmem/harnesses.py`). Registers `memory` (and cleans up legacy `shared_memories`) across Codex, Claude Code, Antigravity (CLI + T3 Code provider configs), OpenCode, and Cursor.
7. **Scheduler** (`sharedmem/scheduler.py`). Configures per-user periodic sync and server backups via launchd (macOS), systemd user timers (Linux), or Task Scheduler (Windows).

There is no long-running HTTP listener. Over SSH, each write or sync runs as a short-lived authenticated SSH command.

## Data flow

```text
Any harness (Claude Code / Antigravity / Codex / OpenCode / Cursor)
  |
  | stdio MCP
  v
local serve --config client.json
  |-- recall() / read() ------> local cache/memories.json (< 5 ms, offline)
  |-- save() / forget() ------> SSH exchange (v3) -> server SQLite -> fresh snapshot -> local cache
  
background timer (every 5 min) -> SSH exchange (pull) -> atomic refresh of cache/
```

## Exchange protocol (v3)

Requests arrive as one JSON object on stdin and return one JSON object on stdout:

- `{"protocol": 3, "op": "pull"}`: returns all curated memories sorted by scope, type, and slug.
- `{"protocol": 3, "op": "save", "memory": {...}, "machine": "..."}`: validates, upserts in one transaction, and returns the result plus the refreshed full memory list.
- `{"protocol": 3, "op": "forget", "id": "<scope>/<slug>"}`: deletes the entry and returns the result plus the refreshed full memory list.
- `{"protocol": 3, "op": "import", "items": [...], "replace": bool}`: bulk-imports curated memories atomically.
- `{"protocol": 3, "op": "status"}`: read-only store health, scope counts, byte totals, and disk free space for `doctor`.

## Local cache layout

```text
cache/
  memories.json               # authoritative local read cache (atomic replace)
  INDEX.md                    # global index + links to project scopes
  global/
    MEMORY.md                 # global scope index
    <slug>.md                 # YAML frontmatter + Markdown body
  projects/
    <scope>/
      MEMORY.md               # project scope index
      <slug>.md               # YAML frontmatter + Markdown body
  status.json                 # last_success, total_memories, scopes
  error.json                  # present only after a failed sync; cleared on next success
```

## Schema and upgrades

The store records its schema in `PRAGMA user_version` (`3`). Opening a legacy v1 or v2 database (containing `files`, `sources`, or `machines` tables) automatically saves `<data>/backups/pre-v3-migration.sqlite3`, creates the `memories` table, drops the legacy dump tables, vacuums the database, and sets `user_version = 3`.

## Consistency and limits

- Server writes use `BEGIN IMMEDIATE` SQLite transactions and verify free space before committing.
- Client sync uses an OS-released SQLite lock (`sync.lock`) so overlapping timer ticks do not collide.
- Offline reads always work from the last good `memories.json`. Offline writes are not queued and return an explicit error to the agent.
- Hard limits:
  - 80 characters max for `name`, 180 characters max for `description`
  - 8 KiB max per memory body
  - 200 memories max per scope
  - 2,000 memories max total
  - 16 MiB max total stored body text
  - 32 MiB max exchange payload
  - 1 to 10 memory IDs per `read` call, 25 max search hits per `recall(query=...)`
