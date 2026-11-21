# SPDX-License-Identifier: Apache-2.0
"""Client side: pull curated memories into a fast local cache, write through on save/forget.

Reads (`recall`, `read`) are served directly from the local JSON cache (<5 ms, works
offline, zero SSH latency per call). Writes (`save`, `forget`) execute atomically on
the canonical server over SSH and refresh the local JSON + Markdown mirror in the same
round-trip.

client.json (v3):
  {"version": 3, "machine": "remote-mac", "cache": "~/.local/share/shared-memory/cache",
   "exchange_command": ["ssh", ..., "pi", "python3 ... exchange ..."]}
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from .core import (
    MAX_WIRE,
    atomic_write,
    has_symlink_part,
    now,
    parse_memory_id,
    render_memory_markdown,
    render_root_index,
    render_scope_index,
    safe_path,
)
from .store import sort_memories

EXCHANGE_TIMEOUT = 30


def load_config(path):
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def exchange(cfg, request, timeout=EXCHANGE_TIMEOUT):
    proc = subprocess.run(
        cfg["exchange_command"],
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(
            "Server exchange failed; existing cache retained. " + proc.stderr[-400:]
        )
    if len(proc.stdout) > MAX_WIRE:
        raise ValueError("Exchange response too large")
    return json.loads(proc.stdout)


def _cache_root(cfg):
    cache = Path(cfg["cache"]).expanduser()
    if cache.is_symlink():
        raise ValueError("Refusing symlink cache root")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    return cache.resolve()


def _render_markdown_tree(memories):
    files = {"INDEX.md": render_root_index(memories)}
    by_scope = {}
    for mem in memories:
        by_scope.setdefault(mem["scope"], []).append(mem)
    for scope, items in by_scope.items():
        prefix = "global" if scope == "global" else f"projects/{scope}"
        files[f"{prefix}/MEMORY.md"] = render_scope_index(scope, items)
        for mem in items:
            files[f"{prefix}/{mem['slug']}.md"] = render_memory_markdown(mem)
    return files


def _write_cache(cache, memories):
    memories = sort_memories(memories)
    files = _render_markdown_tree(memories)
    for path in files:
        safe_path(path)
        if has_symlink_part(cache, path):
            raise ValueError("Cache contains symlink parent")
    manifest = cache / ".manifest.json"
    old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    for path, content in files.items():
        target = cache / path
        if not target.exists() or target.read_bytes() != content.encode("utf-8"):
            atomic_write(target, content)
    for path in set(old) - set(files):
        safe_path(path)
        target = cache / path
        if target.is_file() and not target.is_symlink():
            target.unlink()
    atomic_write(manifest, json.dumps(sorted(files)))
    atomic_write(cache / "memories.json", json.dumps(memories, ensure_ascii=False))
    return memories


def sync(config_path):
    cfg = load_config(config_path)
    cache = _cache_root(cfg)
    lock = sqlite3.connect(cache / ".sync-lock.sqlite3", timeout=2)
    try:
        lock.execute("BEGIN IMMEDIATE")
        response = exchange(cfg, {"protocol": 3, "op": "pull"})
        memories = _write_cache(cache, response["memories"])
        status = {
            "last_success": now(),
            "machine": cfg["machine"],
            "server_version": response.get("server_version", "3"),
            "total_memories": len(memories),
        }
        atomic_write(cache / "status.json", json.dumps(status, indent=2))
        (cache / "error.json").unlink(missing_ok=True)
        return status
    except Exception as error:
        atomic_write(
            cache / "error.json",
            json.dumps({"failed_at": now(), "error": str(error)}, indent=2),
        )
        raise
    finally:
        lock.close()


class CacheBackend:
    """MCP backend: reads from local cache (fast, offline), writes through to server."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.cache = _cache_root(self.cfg)
        self._key = None
        self._memories = []

    def all_memories(self):
        data_file = self.cache / "memories.json"
        if not data_file.exists():
            sync(self.config_path)
        key = os.stat(data_file).st_mtime_ns
        if key != self._key:
            self._memories = sort_memories(
                json.loads(data_file.read_text(encoding="utf-8"))
            )
            self._key = key
        return self._memories

    def get_memories(self, ids):
        by_id = {m["id"]: m for m in self.all_memories()}
        result = {}
        for memory_id in ids:
            scope, slug = parse_memory_id(memory_id)
            canonical = f"{scope}/{slug}"
            result[canonical] = by_id.get(canonical)
        return result

    def save_memory(self, *, scope, slug, type, name, description, content):
        response = exchange(
            self.cfg,
            {
                "protocol": 3,
                "op": "save",
                "machine": self.cfg["machine"],
                "memory": {
                    "scope": scope,
                    "slug": slug,
                    "type": type,
                    "name": name,
                    "description": description,
                    "content": content,
                    "updated_by": self.cfg["machine"],
                },
            },
        )
        self._memories = _write_cache(self.cache, response["memories"])
        self._key = os.stat(self.cache / "memories.json").st_mtime_ns
        return response["result"]

    def delete_memory(self, memory_id):
        response = exchange(
            self.cfg,
            {"protocol": 3, "op": "forget", "machine": self.cfg["machine"], "id": memory_id},
        )
        self._memories = _write_cache(self.cache, response["memories"])
        self._key = os.stat(self.cache / "memories.json").st_mtime_ns
        return response["result"]
