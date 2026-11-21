# SPDX-License-Identifier: Apache-2.0
"""MCP tool schemas and behavior for curated, Claude-style cross-harness memory.

Four crisp tools designed around how agents actually recall and update memory:
- recall: load the scannable one-line index (global + optional project scope) or search
- read:   fetch full Markdown content of 1-10 memories by ID in one call
- save:   create or update a typed memory in place (enforces anti-slop guardrails)
- forget: delete a stale, wrong, or superseded memory cleanly
"""

import re

from .core import (
    MAX_DESCRIPTION_LEN,
    MAX_MEMORY_BYTES,
    MAX_NAME_LEN,
    MAX_WIRE,
    MEMORY_TYPES,
    SCOPE_RE,
    SLUG_RE,
    parse_memory_id,
    short_date,
    validate_scope,
)
from .store import search_items


def optional(schema):
    return {"anyOf": [schema, {"type": "null"}]}


STR = {"type": "string"}
TYPE_ENUM = {"type": "string", "enum": list(MEMORY_TYPES)}


def _tool(name, description, properties, required=(), *, read_only=False, destructive=False):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
        },
    }


TOOLS = [
    _tool(
        "recall",
        "Load the curated memory index and/or search memories by keywords. Call early "
        "in a task whenever user preferences, past corrections, ongoing project "
        "decisions, or external pointers could help. Always includes `global` memories; "
        "pass `scope` (a short lowercase repo/project name like `web-app`, `api`, "
        "`mobile-app`, or `career`) to include that project's memories too. Returns "
        "compact one-line summaries so you can pick only the few relevant IDs to `read`.",
        {
            "scope": optional(
                {
                    "type": "string",
                    "description": (
                        "Optional lowercase project/repo slug (e.g. 'web-app', "
                        "'api', 'career'). Global memories are always included."
                    ),
                }
            ),
            "query": optional(
                {
                    "type": "string",
                    "description": (
                        "Optional space-separated keywords to search across titles, "
                        "descriptions, and bodies."
                    ),
                }
            ),
            "type": optional(
                {
                    **TYPE_ENUM,
                    "description": "Optional filter: user, feedback, project, or reference.",
                }
            ),
        },
        read_only=True,
    ),
    _tool(
        "read",
        "Read the full Markdown content of one or more memories by ID (`<scope>/<slug>`, "
        "e.g. `global/writing-voice` or `web-app/release-flow`). Batch multiple IDs "
        "in one call when several entries from `recall` look relevant.",
        {
            "ids": {
                "type": "array",
                "items": STR,
                "minItems": 1,
                "maxItems": 10,
                "description": "Memory IDs in '<scope>/<slug>' form.",
            }
        },
        ["ids"],
        read_only=True,
    ),
    _tool(
        "save",
        "Create or update a durable memory in place (same `scope` + `slug` replaces "
        "the existing entry). Save proactively when the user corrects your behavior, "
        "states a lasting preference, shares a durable personal fact, makes an ongoing "
        "project decision, or gives an external pointer. Check `recall` first so you "
        "update an existing topic instead of creating duplicates. NEVER save code or "
        "architecture derivable from git, ephemeral task/PR logs, session recaps, or "
        "secrets/passwords/tokens.",
        {
            "scope": {
                "type": "string",
                "pattern": f"^{SCOPE_RE}$",
                "description": (
                    "'global' for user/cross-project memories, or a short lowercase "
                    "project slug (e.g. 'web-app', 'api', 'career')."
                ),
            },
            "slug": {
                "type": "string",
                "pattern": f"^{SLUG_RE}$",
                "description": (
                    "Stable kebab-case topic ID (e.g. 'writing-voice', 'no-prod-dry-run'). "
                    "Reuse an existing slug to update it in place."
                ),
            },
            "type": {
                **TYPE_ENUM,
                "description": (
                    "user (who the user is/goals/personal facts), feedback (behavioral "
                    "rule/correction with Why + How to apply), project (ongoing work/"
                    "decisions/deadlines not in git), or reference (external tool/doc pointer)."
                ),
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_NAME_LEN,
                "description": "Short display title.",
            },
            "description": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_DESCRIPTION_LEN,
                "description": (
                    "Single-line hook shown in the index so future sessions know when "
                    "this memory is relevant."
                ),
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_MEMORY_BYTES,
                "description": (
                    "Concise Markdown body (max 8 KiB). For feedback/project memories, "
                    "include the rule/fact, Why, and How to apply."
                ),
            },
        },
        ["scope", "slug", "type", "name", "description", "content"],
    ),
    _tool(
        "forget",
        "Delete an outdated, wrong, or superseded memory by ID (`<scope>/<slug>`). "
        "Use when a project finishes, a preference changes, or duplicates are merged.",
        {
            "id": {
                "type": "string",
                "description": "Memory ID to delete in '<scope>/<slug>' form.",
            }
        },
        ["id"],
        destructive=True,
    ),
]


def validate(value, schema):
    alternatives = schema.get("oneOf", schema.get("anyOf"))
    if alternatives:
        for variant in alternatives:
            try:
                validate(value, variant)
                return
            except ValueError:
                pass
        raise ValueError("Argument does not match allowed schema")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Value must be one of: {', '.join(schema['enum'])}")
    kind = schema.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if kind and type(value) is not types[kind]:
        raise ValueError("Invalid argument type")
    if kind == "object":
        props = schema["properties"]
        unknown = set(value) - set(props)
        missing = set(schema.get("required", [])) - set(value)
        if unknown or missing:
            raise ValueError("Unknown or missing argument")
        for key, val in value.items():
            validate(val, props[key])
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            raise ValueError("List has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"List exceeds {schema['maxItems']} item limit")
        for val in value:
            validate(val, schema["items"])
    elif kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_WIRE):
            raise ValueError("Invalid string length")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError("String does not match required pattern")


def _format_index_line(mem):
    return (
        f"- `{mem['id']}` [{mem['type']}, {short_date(mem['updated_at'])}] — "
        f"{mem['description']}"
    )


def _recall(backend, args):
    scope = args.get("scope")
    if scope is not None:
        scope = scope.strip().lower()
        if scope:
            validate_scope(scope)
        else:
            scope = None
    query = (args.get("query") or "").strip() or None
    mem_type = args.get("type") or None
    all_items = backend.all_memories()

    if query:
        hits = search_items(all_items, query, scope=scope, mem_type=mem_type, limit=25)
        if not hits:
            scope_hint = f" in global + {scope}" if scope and scope != "global" else ""
            return f"No memories matched `{query}`{scope_hint}."
        lines = [f"# Memory Search: `{query}` ({len(hits)} matches)", ""]
        for mem in hits:
            lines.append(_format_index_line(mem))
            if mem.get("snippet"):
                lines.append(f"  > {mem['snippet']}")
        return "\n".join(lines)

    by_scope = {}
    for mem in all_items:
        if mem_type and mem["type"] != mem_type:
            continue
        by_scope.setdefault(mem["scope"], []).append(mem)

    global_items = by_scope.get("global", [])
    other_scopes = sorted(s for s in by_scope if s != "global")

    lines = ["# Memory Index", ""]
    lines.append(f"## Global ({len(global_items)})")
    if global_items:
        lines.extend(_format_index_line(m) for m in global_items)
    else:
        lines.append("- (no global memories)")

    if scope and scope != "global":
        proj_items = by_scope.get(scope, [])
        lines.extend(["", f"## Project: {scope} ({len(proj_items)})"])
        if proj_items:
            lines.extend(_format_index_line(m) for m in proj_items)
        else:
            lines.append(f"- (no memories yet for `{scope}`)")
        remaining = [s for s in other_scopes if s != scope]
        if remaining:
            summary = ", ".join(f"`{s}` ({len(by_scope[s])})" for s in remaining)
            lines.extend(["", f"Other scopes: {summary}"])
    elif other_scopes:
        lines.extend(["", "## Project Scopes (pass `scope` to list)"])
        summary = ", ".join(f"`{s}` ({len(by_scope[s])})" for s in other_scopes)
        lines.append(summary)

    return "\n".join(lines)


def _read(backend, args):
    ids = args["ids"]
    parsed = [f"{s}/{k}" for s, k in (parse_memory_id(i) for i in ids)]
    fetched = backend.get_memories(parsed)
    blocks = []
    missing = []
    for memory_id in parsed:
        mem = fetched.get(memory_id)
        if mem is None:
            missing.append(memory_id)
            continue
        meta = f"`{mem['id']}` · type: {mem['type']} · updated: {short_date(mem['updated_at'])}"
        if mem.get("updated_by"):
            meta += f" · by: {mem['updated_by']}"
        blocks.append(
            f"## {mem['name']}\n{meta}\n_{mem['description']}_\n\n{mem['body']}"
        )
    if missing:
        blocks.append("Not found: " + ", ".join(f"`{m}`" for m in missing))
    if not blocks:
        raise ValueError("No requested memories found")
    return "\n\n---\n\n".join(blocks)


def _save(backend, args):
    res = backend.save_memory(
        scope=args["scope"],
        slug=args["slug"],
        type=args["type"],
        name=args["name"],
        description=args["description"],
        content=args["content"],
    )
    return (
        f"{res['status'].capitalize()} `{res['id']}` "
        f"({res['bytes']} B, updated {short_date(res['updated_at'])})."
    )


def _forget(backend, args):
    res = backend.delete_memory(args["id"])
    if res["status"] == "not_found":
        return f"Not found: `{res['id']}`."
    return f"Deleted `{res['id']}`."


def call(backend, name, args):
    spec = next((t for t in TOOLS if t["name"] == name), None)
    if spec is None:
        raise ValueError(f"Unknown tool: {name}")
    validate(args, spec["inputSchema"])
    if name == "recall":
        return _recall(backend, args)
    if name == "read":
        return _read(backend, args)
    if name == "save":
        return _save(backend, args)
    return _forget(backend, args)
