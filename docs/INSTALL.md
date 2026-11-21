# Installation

## Requirements

- Python 3.11 or newer on server and clients
- OpenSSH client and server for remote transport
- A private network path (such as Tailscale) or otherwise secured SSH endpoint
- Non-interactive key authentication with strict host-key checking enabled
- CLI binaries for CLI-managed harnesses (`codex`, `claude`); Antigravity, OpenCode, and Cursor are registered through their JSON config files

The runtime uses only the Python standard library.

## 1. Install the server

Clone or copy this repository onto the server, then run:

```sh
python3 install_server.py
```

By default this installs `shared_memory.py` and `sharedmem/` to `~/.local/share/codex-shared-memory/`, initializes `~/.local/share/codex-shared-memory/data/memory.sqlite3`, and schedules daily SQLite backups. The default directory name is kept stable so existing v1/v2 deployments upgrade in place; override with `--install-dir` and `--data-dir` if you prefer another location.

If the store lives on a mounted disk, enable the mount guard and free-space floor:

```sh
python3 install_server.py \
  --data-dir /srv/shared-memory/data \
  --require-mount /srv/shared-memory \
  --min-free-bytes 1073741824
```

Use `--skip-backup-scheduler` if another scheduler manages backups. The installer prints the exact paths and commands and records them in `server.json`.

## 2. Prepare SSH

Create or reuse an SSH host alias on each client, verify the host key out of band, and confirm passwordless batch login works:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes memory-server true
```

Do not disable host-key checking. Any enrolled SSH identity can read, save, and delete shared memories, so enroll only trusted machines.

## 3. Install a client

Clone or copy this repository onto each client machine and pick a stable lowercase machine ID:

```sh
python3 install_client.py --machine laptop --ssh-host memory-server
```

Override server paths explicitly if you installed the server outside the default directory:

```sh
python3 install_client.py \
  --machine laptop \
  --ssh-host memory-server \
  --remote-script /opt/shared-memory-mcp/shared_memory.py \
  --remote-data /srv/shared-memory/data \
  --remote-require-mount /srv/shared-memory \
  --min-free-bytes 1073741824
```

For a single-machine deployment or local testing, pass `--local-data <path>` instead of `--ssh-host`.

The client installer:

1. Copies `shared_memory.py` and `sharedmem/` into `--install-dir` (default `~/.local/share/codex-shared-memory`).
2. Writes `client.json` (`version: 3`, cache path, and `exchange_command`).
3. Runs an initial `sync` to populate the local cache before touching any harness config.
4. Registers the `memory` MCP server with every detected harness (and removes any legacy `shared_memories` entry) unless `--skip-mcp` is passed.
5. Creates a per-user 5-minute sync schedule (`--interval-seconds 300`) unless `--skip-scheduler` is passed.

### Supported harnesses

Use `--harness` (repeatable) to select specific harnesses; by default all detected ones are configured:

| Harness | MCP registration target |
|---|---|
| `codex` | `codex mcp add memory -- ...` (honors `CODEX_HOME`) |
| `claude-code` | `claude mcp add --scope user memory -- ...` |
| `antigravity` | `~/.gemini/config/mcp_config.json` and T3 Code Antigravity provider `config/mcp_config.json` |
| `opencode` | `mcp.memory` in `~/.config/opencode/opencode.json` (or `.jsonc` if plain JSON) |
| `cursor` | `mcpServers.memory` in `~/.cursor/mcp.json` |

By default every harness runs `python3 <install-dir>/shared_memory.py serve --config <client.json>`, serving reads from the local cache and forwarding writes over SSH. Pass `--mcp-mode remote` to run the MCP server directly over SSH instead.

For any other stdio MCP client, register that same `serve --config <client.json>` command under the name `memory`.

### Optional: disable Claude Code local auto-memory

To keep Claude Code from writing separate per-folder local memories alongside `memory`, set `"autoMemoryEnabled": false` in `~/.claude/settings.json`.

### Verify

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py doctor \
  --config ~/.local/share/codex-shared-memory/client.json
```

`doctor` checks live server reachability, local cache freshness and memory count, and every detected harness registration. Then start a fresh agent session and confirm `recall` returns your index.

## Windows notes

Run the installers in PowerShell with Python 3.11+. The client installer creates a per-user Task Scheduler job (`CodexSharedMemorySync`), and the server installer creates `CodexSharedMemoryBackup`. Pass `--skip-scheduler` or `--skip-backup-scheduler` if policy blocks Task Scheduler changes.
