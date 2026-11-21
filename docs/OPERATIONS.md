# Operations

## Health checks

On the server:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py status \
  --data ~/.local/share/codex-shared-memory/data
```

This reports schema version (`3`), SQLite `integrity_check`, total memories, stored body bytes, per-scope counts, and disk free space.

On a client, pull immediately or run `doctor`:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py sync \
  --config ~/.local/share/codex-shared-memory/client.json

python3 ~/.local/share/codex-shared-memory/shared_memory.py doctor \
  --config ~/.local/share/codex-shared-memory/client.json
```

Inspect `<cache>/status.json` for `last_success`, `total_memories`, and `scopes`. A failed sync leaves the existing cache intact and writes `<cache>/error.json`; the next successful sync removes `error.json`.

## Bulk import

Seed or migrate curated memories from a JSON array (`[{scope, slug, type, name, description, content, updated_at?, updated_by?}, ...]`) via stdin on the server:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py import \
  --data ~/.local/share/codex-shared-memory/data < curated.json
```

Pass `--replace` to replace the store contents atomically. All validation rules (types, 8 KiB body cap, scope caps, secret rejection) run before the transaction commits.

## Upgrade from 1.x or 2.x

1. Upgrade the server first: rerun `install_server.py` from this checkout. Opening a v1/v2 database automatically writes `<data>/backups/pre-v3-migration.sqlite3` before migrating to schema v3 and vacuuming the file.
2. Seed any curated memories you want to preserve with `import` (or let agents save fresh ones).
3. Rerun `install_client.py` on each client machine. It updates `client.json` to v3, pulls the curated snapshot, switches harness registrations from `shared_memories` to `memory`, and updates the background sync schedule in place.

## Backups

Run a manual backup on the server:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py backup \
  --data ~/.local/share/codex-shared-memory/data
```

Backups use SQLite's online backup API, run `PRAGMA integrity_check` on the copy, and keep three rolling daily snapshots under `<data>/backups/`. Copy backups off-device if disk failure is in scope.

## Restore

1. Pause client sync schedules and close active agent sessions using `memory`.
2. Pause the server backup schedule.
3. Preserve the current `memory.sqlite3` (and any `-wal` / `-shm` files) for inspection.
4. Copy a verified backup to `memory.sqlite3` with `0600` permissions and remove any stale `-wal` / `-shm` files.
5. Run `status`, re-enable schedules, and trigger a client `sync`.

## Deleting memories

For normal cleanup, agents or users can call `forget("<scope>/<slug>")`, which deletes the row in SQLite and prunes the local Markdown mirror on every machine at the next sync.

If you need complete historical erasure (for example, after an accidental sensitive paste):

1. Call `forget("<scope>/<slug>")` (or delete the row in SQLite and run `VACUUM`).
2. Delete any dated backups under `<data>/backups/` that predated the removal and run a fresh `backup`.
3. Run `sync` on every enrolled client so local `memories.json` and Markdown files are refreshed.

## Disconnect a client

1. Disable its OS sync schedule.
2. Remove the `memory` MCP server from each harness.
3. Remove any shared-memory cue from your global `AGENTS.md` / `CLAUDE.md`.
4. Delete `~/.local/share/codex-shared-memory` (or your custom `--install-dir`).

Default OS schedule identifiers (kept stable from v1 for in-place upgrades):

- macOS client: `codex-shared-memory.sync`
- macOS server backup: `codex-shared-memory.backup`
- Linux client: `codex-shared-memory-sync.timer`
- Linux server backup: `codex-shared-memory-backup.timer`
- Windows client: `CodexSharedMemorySync`
- Windows server backup: `CodexSharedMemoryBackup`
