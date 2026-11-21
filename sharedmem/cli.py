# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point.

Server side (--data):         serve, exchange, backup, status, import
Client side (--config):       sync, serve (cache-backed MCP), doctor
"""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import VERSION, client, mcp, server
from .core import DEFAULT_DATA, DEFAULT_MIN_FREE_BYTES, MAX_WIRE
from .harnesses import NAME as MCP_NAME
from .store import Store


def open_store(args):
    return Store(
        args.data, require_mount=args.require_mount, min_free_bytes=args.min_free_bytes
    )


def doctor(config_path):
    """Check server reachability, local cache freshness, and harness registrations."""
    checks, ok = {}, True
    cfg = client.load_config(config_path)
    try:
        checks["server"] = client.exchange(
            cfg, {"protocol": 3, "op": "status"}, timeout=30
        )
    except Exception as error:  # noqa: BLE001
        checks["server"] = {"error": str(error)[-300:]}
        ok = False
    cache = Path(cfg["cache"]).expanduser()
    status = cache / "status.json"
    if status.exists():
        data = json.loads(status.read_text(encoding="utf-8"))
        last = data["last_success"]
        age = dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(last)
        checks["cache"] = {
            "last_success": last,
            "age_seconds": int(age.total_seconds()),
            "total_memories": data.get("total_memories", 0),
        }
        ok &= age.total_seconds() < 1200
    else:
        checks["cache"] = {"error": "never synced"}
        ok = False
    if (cache / "error.json").exists():
        checks["cache"]["last_error"] = json.loads(
            (cache / "error.json").read_text(encoding="utf-8")
        )
    config = str(Path(config_path).expanduser().resolve())
    checks["harnesses"] = registrations(config)
    print(json.dumps({"version": VERSION, "ok": bool(ok), "checks": checks}, indent=2))
    return 0 if ok else 1


def registrations(config):
    home, found = Path.home(), {}

    def show(command):
        try:
            out = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout if out.returncode == 0 else ""

    for name, exe in (("codex", "codex"), ("claude-code", "claude")):
        path = shutil.which(exe)
        if path:
            text = show([path, "mcp", "get", MCP_NAME])
            found[name] = (
                "unknown"
                if text is None
                else "local cache"
                if config in (text or "")
                else "other"
                if text
                else "missing"
            )
    json_targets = [
        ("opencode", home / ".config/opencode/opencode.json", "mcp"),
        ("opencode-jsonc", home / ".config/opencode/opencode.jsonc", "mcp"),
        ("cursor", home / ".cursor/mcp.json", "mcpServers"),
        ("antigravity-cli", home / ".gemini/config/mcp_config.json", "mcpServers"),
    ]
    t3_agy = home / ".t3/userdata/providers/antigravity"
    if t3_agy.is_dir():
        for child in sorted(t3_agy.iterdir()):
            cfg_file = child / "config/mcp_config.json"
            if cfg_file.parent.is_dir():
                json_targets.append(("antigravity-t3", cfg_file, "mcpServers"))
    for name, file, key in json_targets:
        if file.exists():
            raw = file.read_text(encoding="utf-8").strip()
            if not raw:
                found[name] = "missing"
                continue
            try:
                entry = json.loads(raw).get(key, {}).get(MCP_NAME)
            except json.JSONDecodeError:
                found[name] = "unreadable config"
                continue
            found[name] = (
                "missing"
                if not entry
                else "local cache"
                if config in json.dumps(entry)
                else "other"
            )
    return found


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="shared_memory.py")
    parser.add_argument(
        "command",
        choices=["serve", "exchange", "backup", "status", "sync", "doctor", "import"],
    )
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--require-mount")
    parser.add_argument(
        "--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES
    )
    parser.add_argument("--config", help="client.json for sync, doctor, or serve")
    parser.add_argument("--replace", action="store_true", help="replace on import")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if args.command == "sync":
        print(json.dumps(client.sync(args.config)))
        return 0
    if args.command == "doctor":
        return doctor(args.config)
    if args.command == "serve" and args.config:
        mcp.serve(client.CacheBackend(args.config))
        return 0
    store = open_store(args)
    try:
        if args.command == "serve":
            mcp.serve(store)
        elif args.command == "exchange":
            body = sys.stdin.read(MAX_WIRE + 1)
            if len(body) > MAX_WIRE:
                raise ValueError("Exchange too large")
            request = json.loads(body)
            print(json.dumps(server.handle(store, request), ensure_ascii=False))
        elif args.command == "import":
            items = json.loads(sys.stdin.read())
            print(json.dumps(store.import_memories(items, replace=args.replace)))
        elif args.command == "backup":
            print(json.dumps(store.backup()))
        else:
            print(json.dumps(store.status(), indent=2))
    finally:
        store.close()
    return 0


def entry():
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print(f"shared-memory: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
