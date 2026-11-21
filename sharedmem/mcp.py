# SPDX-License-Identifier: Apache-2.0
"""Newline-delimited JSON-RPC 2.0 MCP server over stdio."""

import json
import sys

from . import VERSION
from .core import MAX_WIRE
from .tools import TOOLS, call

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCTIONS = (
    "Curated cross-machine, cross-harness memory (Claude-style typed topic files: "
    "user, feedback, project, reference).\n"
    "- Call `recall(scope)` early when user preferences, past corrections, ongoing "
    "project decisions, or external pointers could help (pass the repo/project name "
    "when working in one; global memories are always included).\n"
    "- Call `read(ids)` only for the specific entries whose description looks relevant.\n"
    "- Call `save` proactively when the user corrects you or shares a lasting "
    "preference, personal fact, project decision, or external reference. Check `recall` "
    "first so you update an existing topic in place rather than creating duplicates.\n"
    "- Call `forget` when a memory becomes stale, wrong, or superseded.\n"
    "- Never save code or file structure derivable from git, ephemeral task/PR logs, "
    "session recaps, or secrets/passwords/tokens. Verify time-sensitive facts against "
    "current files and git before acting."
)


def serve(backend, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout

    def reply(payload):
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdout.flush()

    for line in stdin:
        message = None
        try:
            if len(line) > MAX_WIRE:
                raise ValueError("Request too large")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise TypeError("Invalid JSON-RPC request")
            if "id" not in message:
                continue
            method, params = message.get("method"), message.get("params", {})
            if method == "initialize":
                requested = params.get("protocolVersion")
                result = {
                    "protocolVersion": requested
                    if requested in PROTOCOLS
                    else PROTOCOLS[-1],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "memory", "version": VERSION},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    value = call(backend, params["name"], params.get("arguments", {}))
                    text = (
                        value
                        if isinstance(value, str)
                        else json.dumps(value, ensure_ascii=False)
                    )
                    result = {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    }
                except (ValueError, KeyError, TypeError, RuntimeError) as e:
                    result = {
                        "content": [{"type": "text", "text": str(e)}],
                        "isError": True,
                    }
            else:
                reply(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                )
                continue
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception:  # noqa: BLE001 - never crash the long-running MCP loop
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(message, dict) else None,
                "error": {
                    "code": -32603,
                    "message": "Invalid request or store unavailable",
                },
            }
        reply(response)
