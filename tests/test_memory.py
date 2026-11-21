import concurrent.futures
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sharedmem import client, core, server
from sharedmem.store import Store
from sharedmem.tools import call

LAUNCHER = str(ROOT / "shared_memory.py")


class CuratedMemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "store", min_free_bytes=0)
        self.store.save_memory(
            scope="global",
            slug="writing-voice",
            type="feedback",
            name="Writing voice",
            description="Write emails and messages in plain human voice with no filler",
            content="Use plain sentences, contractions, and concrete specifics.",
            updated_by="workstation-a",
        )
        self.store.save_memory(
            scope="acme-app",
            slug="billing-display",
            type="project",
            name="Billing display",
            description="Annual plan shows monthly equivalent beneath the billed total",
            content="Billed amount stays most prominent on paywall.",
            updated_by="workstation-a",
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def call(self, tool_name, **args):
        return call(self.store, tool_name, args)

    def exchange_command(self):
        return [
            sys.executable,
            LAUNCHER,
            "exchange",
            "--data",
            str(self.root / "store"),
            "--min-free-bytes",
            "0",
        ]

    def test_recall_index_and_scoping(self):
        root_view = self.call("recall")
        self.assertIn("global/writing-voice", root_view)
        self.assertIn("`acme-app` (1)", root_view)
        self.assertNotIn("acme-app/billing-display", root_view)

        scoped = self.call("recall", scope="acme-app")
        self.assertIn("global/writing-voice", scoped)
        self.assertIn("acme-app/billing-display", scoped)

        by_type = self.call("recall", scope="acme-app", type="feedback")
        self.assertIn("global/writing-voice", by_type)
        self.assertNotIn("acme-app/billing-display", by_type)

    def test_recall_search_ranking_and_snippets(self):
        hit = self.call("recall", query="paywall")
        self.assertIn("acme-app/billing-display", hit)
        self.assertIn("Billed amount stays most prominent", hit)

        miss = self.call("recall", query="nonexistent-xyz-token")
        self.assertIn("No memories matched", miss)

    def test_read_batch_and_missing(self):
        out = self.call("read", ids=["global/writing-voice", "acme-app/missing-one"])
        self.assertIn("## Writing voice", out)
        self.assertIn("Use plain sentences", out)
        self.assertIn("Not found: `acme-app/missing-one`", out)

    def test_save_upsert_and_forget(self):
        created = self.call(
            "save",
            scope="global",
            slug="no-ai-attribution",
            type="feedback",
            name="No AI attribution",
            description="Never add Co-Authored-By or AI attribution in commits or PRs",
            content="Keep commits and comments in the owner's own voice.",
        )
        self.assertIn("Created `global/no-ai-attribution`", created)

        updated = self.call(
            "save",
            scope="global",
            slug="no-ai-attribution",
            type="feedback",
            name="No AI attribution",
            description="Never add Co-Authored-By or AI attribution anywhere",
            content="Updated rule body.",
        )
        self.assertIn("Updated `global/no-ai-attribution`", updated)
        self.assertEqual(
            self.store.get_memories(["global/no-ai-attribution"])[
                "global/no-ai-attribution"
            ]["body"],
            "Updated rule body.",
        )

        deleted = self.call("forget", id="global/no-ai-attribution")
        self.assertIn("Deleted `global/no-ai-attribution`", deleted)
        self.assertIn("Not found", self.call("forget", id="global/no-ai-attribution"))

    def test_validation_caps_and_secret_rejection(self):
        with self.assertRaises(ValueError):
            self.call(
                "save",
                scope="global",
                slug="bad-secret",
                type="reference",
                name="API Key",
                description="Do not save this",
                content="api_key: super-secret-value",
            )
        with self.assertRaises(ValueError):
            self.call(
                "save",
                scope="global",
                slug="too-big",
                type="project",
                name="Too big",
                description="Oversized dump",
                content="x" * (core.MAX_MEMORY_BYTES + 1),
            )
        with self.assertRaises(ValueError):
            self.call(
                "save",
                scope="Bad Scope",
                slug="ok",
                type="user",
                name="x",
                description="x",
                content="x",
            )
        with self.assertRaises(ValueError):
            self.call("read", ids=["../etc/passwd"])
        with self.assertRaises(ValueError):
            self.call("read", ids=[])

        with (
            patch.object(core, "MAX_MEMORIES_PER_SCOPE", 1),
            self.assertRaises(ValueError),
        ):
            self.call(
                "save",
                scope="global",
                slug="second-item",
                type="user",
                name="Second",
                description="Exceeds scope cap",
                content="body",
            )

    def test_concurrent_saves(self):
        def write(i):
            store = Store(self.root / "store", min_free_bytes=0)
            try:
                return store.save_memory(
                    scope="global",
                    slug=f"item-{i}",
                    type="user",
                    name=f"Item {i}",
                    description=f"Desc {i}",
                    content=f"Body {i}",
                )["status"]
            finally:
                store.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(6)))
        self.assertEqual(results.count("created"), 6)

    def test_v2_store_migrates_with_backup_and_drops_dumps(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / "memory.sqlite3")) as db:
            db.executescript(
                "CREATE TABLE files(path TEXT PRIMARY KEY, content TEXT NOT NULL, owner TEXT NOT NULL, source TEXT NOT NULL DEFAULT '');"
                "CREATE TABLE sources(machine TEXT NOT NULL, source TEXT NOT NULL, type TEXT NOT NULL, updated_at TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(machine, source));"
                "INSERT INTO files VALUES('machines/mac/codex/MEMORY.md','800kb dump','mac','codex');"
                "PRAGMA user_version=2;"
            )
            db.commit()
        store = Store(legacy, min_free_bytes=0)
        try:
            self.assertEqual(store.status()["schema"], 3)
            self.assertEqual(store.status()["total_memories"], 0)
            self.assertTrue((legacy / "backups/pre-v3-migration.sqlite3").is_file())
            tables = store._tables()
            self.assertNotIn("files", tables)
            self.assertNotIn("sources", tables)
        finally:
            store.close()

    def test_client_sync_markdown_mirror_and_write_through(self):
        config = self.root / "client.json"
        cache_dir = self.root / "cache"
        config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "machine": "laptop-b",
                    "cache": str(cache_dir),
                    "exchange_command": self.exchange_command(),
                }
            )
        )
        status = client.sync(config)
        self.assertEqual(status["total_memories"], 2)
        self.assertTrue((cache_dir / "INDEX.md").is_file())
        self.assertTrue((cache_dir / "global/writing-voice.md").is_file())
        self.assertTrue((cache_dir / "projects/acme-app/MEMORY.md").is_file())

        backend = client.CacheBackend(config)
        res = call(
            backend,
            "save",
            {
                "scope": "ops",
                "slug": "deploy-window",
                "type": "project",
                "name": "Deploy window",
                "description": "Production deploy freeze schedule",
                "content": "Avoid production schema deploys on Fridays.",
            },
        )
        self.assertIn("Created `ops/deploy-window`", res)
        self.assertTrue((cache_dir / "projects/ops/deploy-window.md").is_file())
        self.assertIn("ops/deploy-window", call(backend, "recall", {"scope": "ops"}))

        del_res = call(backend, "forget", {"id": "ops/deploy-window"})
        self.assertIn("Deleted `ops/deploy-window`", del_res)
        self.assertFalse((cache_dir / "projects/ops/deploy-window.md").exists())

    def test_mcp_stdio_transport_store_and_cache(self):
        config = self.root / "client.json"
        config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "machine": "workstation-a",
                    "cache": str(self.root / "cache"),
                    "exchange_command": self.exchange_command(),
                }
            )
        )
        client.sync(config)
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "recall", "arguments": {"scope": "acme-app"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "read", "arguments": {"ids": ["global/writing-voice"]}},
            },
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "save",
                    "arguments": {
                        "scope": "global",
                        "slug": "mcp-test",
                        "type": "user",
                        "name": "MCP test",
                        "description": "Round-trip save test",
                        "content": "Saved over stdio MCP.",
                    },
                },
            },
        ]
        proc = subprocess.run(
            [sys.executable, LAUNCHER, "serve", "--config", str(config)],
            input="\n".join(json.dumps(r) for r in requests) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(replies), 5)
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "memory")
        self.assertEqual(
            [t["name"] for t in replies[1]["result"]["tools"]],
            ["recall", "read", "save", "forget"],
        )
        self.assertIn("acme-app/billing-display", replies[2]["result"]["content"][0]["text"])
        self.assertIn("Writing voice", replies[3]["result"]["content"][0]["text"])
        self.assertIn("Created `global/mcp-test`", replies[4]["result"]["content"][0]["text"])
        self.assertIsNotNone(self.store.get_memories(["global/mcp-test"])["global/mcp-test"])

    def test_backup_and_status(self):
        b = self.store.backup()
        self.assertEqual(b["integrity"], "ok")
        self.assertEqual(self.store.status()["total_memories"], 2)
        with self.assertRaises(ValueError):
            server.handle(self.store, {"protocol": 2, "op": "sync"})


if __name__ == "__main__":
    unittest.main()
