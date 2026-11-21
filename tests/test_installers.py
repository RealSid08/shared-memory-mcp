import json
import plistlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_client
import install_server
from sharedmem import harnesses, install, scheduler


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_remote_command_is_portable_and_quoted(self):
        args = install_client.parse_args(
            [
                "--machine",
                "test-node",
                "--ssh-host",
                "memory-server",
                "--remote-data",
                "~/memory data",
                "--skip-mcp",
            ]
        )
        with patch.object(install.shutil, "which", return_value="/usr/bin/ssh"):
            exchange, serve = install.build_commands(
                args, "/usr/bin/python3", self.root / "shared_memory.py"
            )
        self.assertEqual(exchange[-2], "memory-server")
        self.assertIn('"$HOME"/', exchange[-1])
        self.assertIn("exchange", exchange[-1])
        self.assertIn("serve", serve[-1])

    def test_local_client_install_end_to_end(self):
        install_dir = self.root / "client"
        args = install_client.parse_args(
            [
                "--machine",
                "test-node",
                "--local-data",
                str(self.root / "server-data"),
                "--install-dir",
                str(install_dir),
                "--min-free-bytes",
                "0",
                "--skip-mcp",
                "--skip-scheduler",
            ]
        )
        with redirect_stdout(StringIO()):
            result = install.install_client(args)
        config = json.loads((install_dir / "client.json").read_text())
        self.assertEqual(config["version"], 3)
        self.assertFalse(result["mcp_registered"])
        self.assertEqual(
            result["mcp_command"][-3:],
            ["serve", "--config", str(install_dir / "client.json")],
        )
        self.assertTrue((install_dir / "cache/INDEX.md").is_file())
        self.assertTrue((install_dir / "cache/memories.json").is_file())

    def test_server_install_without_scheduler(self):
        install_dir, data = self.root / "server", self.root / "data"
        args = install_server.parse_args(
            [
                "--install-dir",
                str(install_dir),
                "--data-dir",
                str(data),
                "--min-free-bytes",
                "0",
                "--skip-backup-scheduler",
            ]
        )
        with redirect_stdout(StringIO()):
            result = install.install_server(args)
        self.assertTrue((data / "memory.sqlite3").is_file())
        self.assertIsNone(result["backup_scheduler"])
        self.assertEqual(
            json.loads((install_dir / "server.json").read_text())["data"], str(data)
        )

    def test_harness_registrations_including_antigravity(self):
        home = self.root / "home"
        with (
            patch.object(harnesses, "run") as run,
            patch.object(harnesses.subprocess, "run"),
        ):
            harnesses.Codex(home, "/opt/codex", home / "alt-codex").register(
                ["py", "serve"]
            )
            command, env = run.call_args.args[0], run.call_args.kwargs["env"]
            self.assertEqual(command[:4], ["/opt/codex", "mcp", "add", "memory"])
            self.assertEqual(env["CODEX_HOME"], str(home / "alt-codex"))

            harnesses.ClaudeCode(home, "/opt/claude").register(["py", "serve"])
            self.assertEqual(
                run.call_args.args[0][:6],
                ["/opt/claude", "mcp", "add", "--scope", "user", "memory"],
            )

        # Antigravity (both ~/.gemini/config and T3 provider config)
        (home / ".gemini/config").mkdir(parents=True)
        (home / ".gemini/config/mcp_config.json").write_text("")
        t3_cfg = home / ".t3/userdata/providers/antigravity/abc123/config"
        t3_cfg.mkdir(parents=True)
        harnesses.Antigravity(home).register(["py", "serve", "--config", "c.json"])
        for p in (
            home / ".gemini/config/mcp_config.json",
            t3_cfg / "mcp_config.json",
        ):
            data = json.loads(p.read_text())
            self.assertEqual(
                data["mcpServers"]["memory"],
                {"command": "py", "args": ["serve", "--config", "c.json"]},
            )

        opencode = home / ".config/opencode/opencode.json"
        opencode.parent.mkdir(parents=True)
        opencode.write_text(json.dumps({"mcp": {"other": {"type": "local"}}}))
        harnesses.OpenCode(home).register(["py", "serve"])
        data = json.loads(opencode.read_text())
        self.assertEqual(data["mcp"]["memory"]["command"], ["py", "serve"])
        self.assertIn("other", data["mcp"])

        harnesses.Cursor(home).register(["py", "serve", "--config", "c.json"])
        cursor = json.loads((home / ".cursor/mcp.json").read_text())
        self.assertEqual(
            cursor["mcpServers"]["memory"],
            {"command": "py", "args": ["serve", "--config", "c.json"]},
        )

    def test_scheduler_definitions(self):
        command = ["python3", "shared_memory.py", "sync"]
        with (
            patch.object(scheduler.platform, "system", return_value="Darwin"),
            patch.object(scheduler.os, "getuid", return_value=501, create=True),
            patch.object(scheduler, "run"),
            patch.object(scheduler.subprocess, "run"),
        ):
            plist = Path(scheduler.schedule("sync", command, self.root, 300))
        definition = plistlib.loads(plist.read_bytes())
        self.assertEqual(definition["Label"], "codex-shared-memory.sync")
        self.assertEqual(definition["ProgramArguments"], command)


if __name__ == "__main__":
    unittest.main()
