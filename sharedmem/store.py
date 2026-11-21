# SPDX-License-Identifier: Apache-2.0
"""Server-side SQLite store for curated, typed, scoped memories (schema v3).

Replaces v2's raw machine/harness file dumps with atomic, mutable topic memories
modeled on Claude Code's memory system:
- Scopes: 'global' or lowercase project slug
- Types: user | feedback | project | reference
- Hard size and per-scope caps prevent log/rollout dumping
- Opening a v1/v2 database saves an automatic pre-v3 backup before migrating
"""

import datetime as dt
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from . import core
from .core import MEMORY_TYPES, now, parse_memory_id, validate_memory_fields

SCHEMA_VERSION = 3
TYPE_ORDER = {t: i for i, t in enumerate(MEMORY_TYPES)}


def _row_to_dict(row):
    return {
        "id": f"{row[0]}/{row[1]}",
        "scope": row[0],
        "slug": row[1],
        "type": row[2],
        "name": row[3],
        "description": row[4],
        "body": row[5],
        "updated_at": row[6],
        "updated_by": row[7],
    }


def sort_memories(items):
    return sorted(
        items,
        key=lambda m: (
            m["scope"] != "global",
            m["scope"],
            TYPE_ORDER.get(m["type"], 99),
            m["slug"],
        ),
    )


def search_items(items, query, *, scope=None, mem_type=None, limit=25):
    """Case-insensitive ranked search over a list of memory dicts."""
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    if not terms:
        raise ValueError("Search query must not be blank")
    filtered = [
        m
        for m in items
        if (scope is None or m["scope"] in ("global", scope))
        and (mem_type is None or m["type"] == mem_type)
    ]

    def score(mem):
        title_text = f"{mem['scope']}/{mem['slug']} {mem['name']}".lower()
        desc_text = mem["description"].lower()
        body_text = mem["body"].lower()
        combined = f"{title_text}\n{desc_text}\n{body_text}"
        matched = [t for t in terms if t in combined]
        if not matched:
            return None
        points = 0
        for t in matched:
            if t in title_text:
                points += 6
            if t in desc_text:
                points += 4
            if t in body_text:
                points += 1
        if scope and mem["scope"] == scope:
            points += 2
        return (len(matched) == len(terms), len(matched), points)

    scored = []
    for mem in filtered:
        s = score(mem)
        if s is not None:
            scored.append((s, mem))
    if not scored:
        return []
    all_match = [pair for pair in scored if pair[0][0]]
    ranked = all_match if all_match else scored
    ranked.sort(key=lambda pair: (-pair[0][1], -pair[0][2], pair[1]["id"]))
    results = []
    for _, mem in ranked[:limit]:
        snippet = _extract_snippet(mem["body"], terms)
        results.append({**mem, "snippet": snippet})
    return results


def _extract_snippet(body, terms):
    for line in body.splitlines():
        low = line.lower()
        if any(t in low for t in terms):
            clean = line.strip()
            return clean[:180] + ("..." if len(clean) > 180 else "")
    return ""


class Store:
    def __init__(self, directory, *, require_mount=None, min_free_bytes=None):
        self.directory = Path(directory).expanduser()
        if self.directory.is_symlink():
            raise ValueError("Refusing symlink store directory")
        if require_mount:
            mount = Path(require_mount).expanduser().resolve()
            if not os.path.ismount(mount):
                raise ValueError(f"Required mount is unavailable: {mount}")
            if not self.directory.resolve().is_relative_to(mount):
                raise ValueError("Store directory must be inside the required mount")
        self.min_free_bytes = (
            core.DEFAULT_MIN_FREE_BYTES if min_free_bytes is None else min_free_bytes
        )
        if self.min_free_bytes < 0:
            raise ValueError("Minimum free bytes must be greater than or equal to zero")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        database = self.directory / "memory.sqlite3"
        self.db = sqlite3.connect(database, timeout=30, isolation_level=None)
        database.chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._migrate()

    def close(self):
        self.db.close()

    def _tables(self):
        rows = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {name for (name,) in rows}

    def _migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        tables = self._tables()
        had_legacy = bool(tables & {"files", "sources", "machines"})
        if had_legacy:
            self._snapshot("pre-v3-migration.sqlite3", keep_existing=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
                self.db.rollback()
                return
            self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    scope TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (scope, slug)
                )
                """
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)"
            )
            for legacy in ("files", "sources", "machines"):
                self.db.execute(f"DROP TABLE IF EXISTS {legacy}")
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if had_legacy:
            self.db.execute("VACUUM")

    def begin(self):
        if shutil.disk_usage(self.directory).free < self.min_free_bytes:
            raise ValueError(
                f"Less than {self.min_free_bytes} bytes free; refusing writes"
            )
        self.db.execute("BEGIN IMMEDIATE")

    def _check_quotas(self, scope):
        scope_count = self.db.execute(
            "SELECT count(*) FROM memories WHERE scope=?", (scope,)
        ).fetchone()[0]
        if scope_count > core.MAX_MEMORIES_PER_SCOPE:
            raise ValueError(
                f"Scope '{scope}' exceeds {core.MAX_MEMORIES_PER_SCOPE} memory limit; "
                "consolidate or forget stale entries first"
            )
        total_count, total_bytes = self.db.execute(
            "SELECT count(*), COALESCE(SUM(length(CAST(body AS BLOB))), 0) "
            "FROM memories"
        ).fetchone()
        if total_count > core.MAX_TOTAL_MEMORIES:
            raise ValueError(
                f"Store exceeds {core.MAX_TOTAL_MEMORIES} total memory limit"
            )
        if total_bytes > core.MAX_STORE:
            raise ValueError(
                f"Store exceeds {core.MAX_STORE // 2**20} MiB quota"
            )

    def all_memories(self):
        rows = self.db.execute(
            "SELECT scope, slug, type, name, description, body, updated_at, updated_by "
            "FROM memories"
        ).fetchall()
        return sort_memories([_row_to_dict(r) for r in rows])

    def get_memories(self, ids):
        found = {}
        for memory_id in ids:
            scope, slug = parse_memory_id(memory_id)
            row = self.db.execute(
                "SELECT scope, slug, type, name, description, body, updated_at, "
                "updated_by FROM memories WHERE scope=? AND slug=?",
                (scope, slug),
            ).fetchone()
            found[f"{scope}/{slug}"] = _row_to_dict(row) if row else None
        return found

    def save_memory(
        self,
        *,
        scope,
        slug,
        type,
        name,
        description,
        content,
        updated_by="",
        updated_at=None,
    ):
        scope, slug, mem_type, name, description, body = validate_memory_fields(
            scope, slug, type, name, description, content
        )
        stamp = updated_at or now()
        actor = str(updated_by or "")[:64]
        self.begin()
        try:
            existed = (
                self.db.execute(
                    "SELECT 1 FROM memories WHERE scope=? AND slug=?", (scope, slug)
                ).fetchone()
                is not None
            )
            self.db.execute(
                """
                INSERT INTO memories
                    (scope, slug, type, name, description, body, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, slug) DO UPDATE SET
                    type=excluded.type,
                    name=excluded.name,
                    description=excluded.description,
                    body=excluded.body,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (scope, slug, mem_type, name, description, body, stamp, actor),
            )
            self._check_quotas(scope)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "status": "updated" if existed else "created",
            "id": f"{scope}/{slug}",
            "scope": scope,
            "slug": slug,
            "bytes": len(body.encode("utf-8")),
            "updated_at": stamp,
        }

    def delete_memory(self, memory_id):
        scope, slug = parse_memory_id(memory_id)
        self.begin()
        try:
            cur = self.db.execute(
                "DELETE FROM memories WHERE scope=? AND slug=?", (scope, slug)
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "status": "deleted" if cur.rowcount else "not_found",
            "id": f"{scope}/{slug}",
        }

    def import_memories(self, items, *, replace=False):
        if not isinstance(items, list):
            raise TypeError("items must be a list")
        prepared = []
        for item in items:
            scope, slug, mem_type, name, description, body = validate_memory_fields(
                item["scope"],
                item["slug"],
                item["type"],
                item["name"],
                item["description"],
                item["content"],
            )
            prepared.append(
                (
                    scope,
                    slug,
                    mem_type,
                    name,
                    description,
                    body,
                    item.get("updated_at") or now(),
                    str(item.get("updated_by") or "import")[:64],
                )
            )
        self.begin()
        try:
            if replace:
                self.db.execute("DELETE FROM memories")
            self.db.executemany(
                """
                INSERT INTO memories
                    (scope, slug, type, name, description, body, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, slug) DO UPDATE SET
                    type=excluded.type,
                    name=excluded.name,
                    description=excluded.description,
                    body=excluded.body,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                prepared,
            )
            for scope in {row[0] for row in prepared}:
                self._check_quotas(scope)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"imported": len(prepared), "replaced": bool(replace)}

    def _snapshot(self, name, *, keep_existing=False):
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True, mode=0o700)
        target = folder / name
        if keep_existing and target.exists():
            return target
        fd, tmp = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3", dir=folder)
        os.close(fd)
        try:
            with closing(sqlite3.connect(tmp)) as db:
                self.db.backup(db)
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed")
            if keep_existing and target.exists():
                return target
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return target

    def backup(self):
        """Refresh today's backup atomically; keep three daily recovery points."""
        name = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d") + ".sqlite3"
        target = self._snapshot(name)
        for old in sorted((self.directory / "backups").glob("????-??-??.sqlite3"))[:-3]:
            old.unlink()
        return {"backup": str(target), "integrity": "ok"}

    def status(self):
        scopes = dict(
            self.db.execute(
                "SELECT scope, count(*) FROM memories GROUP BY scope ORDER BY scope"
            ).fetchall()
        )
        total_bytes = self.db.execute(
            "SELECT COALESCE(SUM(length(CAST(body AS BLOB))), 0) FROM memories"
        ).fetchone()[0]
        return {
            "schema": self.db.execute("PRAGMA user_version").fetchone()[0],
            "integrity": self.db.execute("PRAGMA integrity_check").fetchone()[0],
            "total_memories": sum(scopes.values()),
            "total_bytes": total_bytes,
            "scopes": scopes,
            "free_bytes": shutil.disk_usage(self.directory).free,
        }
