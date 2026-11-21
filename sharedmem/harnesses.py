# SPDX-License-Identifier: Apache-2.0
"""Register the `memory` MCP server across all supported agent harnesses.

Supported harnesses:
- codex:       `codex mcp add memory -- ...`
- claude-code: `claude mcp add --scope user memory -- ...`
- antigravity: `~/.gemini/config/mcp_config.json` + T3 Code Antigravity provider dirs
- opencode:    `~/.config/opencode/opencode.json` (or `.jsonc` if plain JSON)
- cursor:      `~/.cursor/mcp.json`
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .core import atomic_write

NAME = "memory"
LEGACY_NAMES = ("shared_memories",)


def run(command, **kwargs):
    return subprocess.run(command, check=True, stdout=sys.stderr, **kwargs)


def _merge_json(path, update):
    path = Path(path)
    data = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    f"{path} is not plain JSON; update it manually"
                ) from error
    update(data)
    atomic_write(path, json.dumps(data, indent=2) + "\n")


class Codex:
    name = "codex"

    def __init__(self, home, executable=None, codex_home=None):
        self.home = Path(home)
        self.executable = executable or shutil.which("codex")
        self.codex_home = Path(
            codex_home or os.environ.get("CODEX_HOME", self.home / ".codex")
        ).expanduser()

    def detected(self):
        return bool(self.executable)

    def register(self, command):
        if not self.executable:
            raise SystemExit("Codex CLI is unavailable; pass --codex")
        self.codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        for old in (*LEGACY_NAMES, NAME):
            subprocess.run(
                [self.executable, "mcp", "remove", old],
                env=env,
                capture_output=True,
                check=False,
            )
        run([self.executable, "mcp", "add", NAME, "--", *command], env=env)


class ClaudeCode:
    name = "claude-code"

    def __init__(self, home, executable=None):
        self.home = Path(home)
        self.executable = executable or shutil.which("claude")

    def detected(self):
        return bool(self.executable)

    def register(self, command):
        if not self.executable:
            raise SystemExit("Claude Code CLI is unavailable")
        for old in (*LEGACY_NAMES, NAME):
            subprocess.run(
                [self.executable, "mcp", "remove", "--scope", "user", old],
                capture_output=True,
                check=False,
            )
        run([self.executable, "mcp", "add", "--scope", "user", NAME, "--", *command])


class Antigravity:
    name = "antigravity"

    def __init__(self, home):
        self.home = Path(home)

    def _config_paths(self):
        paths = []
        gemini_cfg = self.home / ".gemini/config"
        if gemini_cfg.is_dir():
            paths.append(gemini_cfg / "mcp_config.json")
        t3_root = self.home / ".t3/userdata/providers/antigravity"
        if t3_root.is_dir():
            for child in sorted(t3_root.iterdir()):
                cfg = child / "config"
                if cfg.is_dir():
                    paths.append(cfg / "mcp_config.json")
        return paths

    def detected(self):
        return bool(self._config_paths())

    def register(self, command):
        paths = self._config_paths()
        if not paths:
            paths = [self.home / ".gemini/config/mcp_config.json"]

        def update(data):
            servers = data.setdefault("mcpServers", {})
            for old in LEGACY_NAMES:
                servers.pop(old, None)
            servers[NAME] = {"command": command[0], "args": command[1:]}

        for path in paths:
            _merge_json(path, update)


class OpenCode:
    name = "opencode"

    def __init__(self, home):
        self.home = Path(home)
        cfg_dir = self.home / ".config/opencode"
        jsonc = cfg_dir / "opencode.jsonc"
        plain = cfg_dir / "opencode.json"
        self.config = jsonc if jsonc.exists() and not plain.exists() else plain

    def detected(self):
        return self.config.parent.is_dir() or bool(shutil.which("opencode"))

    def register(self, command):
        def update(data):
            mcp = data.setdefault("mcp", {})
            for old in LEGACY_NAMES:
                mcp.pop(old, None)
            mcp[NAME] = {"type": "local", "command": command, "enabled": True}

        _merge_json(self.config, update)


class Cursor:
    name = "cursor"

    def __init__(self, home):
        self.home = Path(home)
        self.config = self.home / ".cursor/mcp.json"

    def detected(self):
        return self.config.parent.is_dir()

    def register(self, command):
        def update(data):
            servers = data.setdefault("mcpServers", {})
            for old in LEGACY_NAMES:
                servers.pop(old, None)
            servers[NAME] = {"command": command[0], "args": command[1:]}

        _merge_json(self.config, update)


def all_harnesses(home, codex=None, codex_home=None, claude=None):
    return [
        Codex(home, codex, codex_home),
        ClaudeCode(home, claude),
        Antigravity(home),
        OpenCode(home),
        Cursor(home),
    ]


def apply(harnesses, command, *, register=True):
    report = {}
    for harness in harnesses:
        entry = {}
        if register:
            harness.register(command)
            entry["mcp"] = "registered"
        report[harness.name] = entry
    return report
