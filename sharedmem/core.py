# SPDX-License-Identifier: Apache-2.0
"""Limits, validation, secret redaction, Markdown rendering, and atomic writes."""

import datetime as dt
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

MEMORY_TYPES = ("user", "feedback", "project", "reference")
SCOPE_RE = r"[a-z0-9][a-z0-9-]{0,63}"
SLUG_RE = r"[a-z0-9][a-z0-9-]{0,79}"
MACHINE_RE = r"[a-z0-9][a-z0-9-]{0,63}"

MAX_NAME_LEN = 80
MAX_DESCRIPTION_LEN = 180
MAX_MEMORY_BYTES = 8 * 1024
MAX_MEMORIES_PER_SCOPE = 200
MAX_TOTAL_MEMORIES = 2000
MAX_STORE = 16 * 1024 * 1024
MAX_WIRE = 32 * 1024 * 1024
DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024
DEFAULT_DATA = "~/.local/share/codex-shared-memory/data"


def now():
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def short_date(iso_stamp):
    return (iso_stamp or "")[:10] or "unknown"


def safe_path(path, root_ok=False):
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        raise ValueError("Invalid relative path")
    if path in ("", ".") and root_ok:
        return ""
    parts = path.split("/")
    if any(not p or p.startswith(".") or ":" in p for p in parts):
        raise ValueError("Only visible relative paths are allowed")
    return str(PurePosixPath(path))


def validate_scope(scope):
    if not isinstance(scope, str) or not re.fullmatch(SCOPE_RE, scope):
        raise ValueError(
            "Scope must be 'global' or a lowercase kebab-case project slug "
            "(1-64 chars, a-z, 0-9, hyphens)"
        )
    return scope


def validate_slug(slug):
    if not isinstance(slug, str) or not re.fullmatch(SLUG_RE, slug):
        raise ValueError(
            "Slug must be lowercase kebab-case (1-80 chars, a-z, 0-9, hyphens)"
        )
    return slug


def parse_memory_id(memory_id):
    if not isinstance(memory_id, str) or memory_id.count("/") != 1:
        raise ValueError("Memory ID must be '<scope>/<slug>'")
    scope, slug = memory_id.split("/", 1)
    return validate_scope(scope), validate_slug(slug)


def validate_memory_fields(scope, slug, mem_type, name, description, body):
    validate_scope(scope)
    validate_slug(slug)
    if mem_type not in MEMORY_TYPES:
        raise ValueError(f"Type must be one of: {', '.join(MEMORY_TYPES)}")
    if not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name:
        raise ValueError("Name must be a non-empty single line")
    name = name.strip()
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"Name exceeds {MAX_NAME_LEN} characters")
    if (
        not isinstance(description, str)
        or not description.strip()
        or "\n" in description
        or "\r" in description
    ):
        raise ValueError("Description must be a non-empty single line")
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LEN:
        raise ValueError(f"Description exceeds {MAX_DESCRIPTION_LEN} characters")
    if not isinstance(body, str) or "\x00" in body or not body.strip():
        raise ValueError("Content must be non-empty UTF-8 text without NUL")
    body = body.strip()
    if len(body.encode("utf-8")) > MAX_MEMORY_BYTES:
        raise ValueError(
            f"Memory content exceeds {MAX_MEMORY_BYTES // 1024} KiB limit; "
            "keep memories concise and distilled, never dump raw logs"
        )
    for field_name, text in (
        ("name", name),
        ("description", description),
        ("content", body),
    ):
        if redact(text) != text:
            raise ValueError(
                f"Refusing to save {field_name}: looks like it contains a secret or "
                "credential; store pointers, never secrets"
            )
    return scope, slug, mem_type, name, description, body


def redact(content):
    """Best-effort hygiene for refusing secrets/credentials in saved memories."""
    content = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b",
        "[REDACTED TOKEN]",
        content,
    )
    content = re.sub(
        r"(?im)^.*(?<![A-Za-z0-9_-])(?:password|passwd|passcode|api[_ -]?key"
        r"|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*(?!<)\S.*$",
        "[REDACTED CREDENTIAL LINE]",
        content,
    )
    return content


def render_memory_markdown(mem):
    """Render one memory as Claude-style Markdown with YAML frontmatter."""
    name_q = mem["name"].replace('"', '\\"')
    desc_q = mem["description"].replace('"', '\\"')
    lines = [
        "---",
        f'name: "{name_q}"',
        f'description: "{desc_q}"',
        f"type: {mem['type']}",
        f"scope: {mem['scope']}",
        f"updated_at: {mem['updated_at']}",
    ]
    if mem.get("updated_by"):
        lines.append(f"updated_by: {mem['updated_by']}")
    lines.extend(["---", "", mem["body"], ""])
    return "\n".join(lines)


def render_scope_index(scope, memories):
    """Render a compact Claude-style MEMORY.md index for one scope."""
    heading = "# Global Memory" if scope == "global" else f"# Project Memory: {scope}"
    lines = [heading, ""]
    for mem in memories:
        lines.append(
            f"- [{mem['name']}]({mem['slug']}.md) [{mem['type']}, "
            f"{short_date(mem['updated_at'])}] — {mem['description']}"
        )
    lines.append("")
    return "\n".join(lines)


def render_root_index(memories):
    """Render the root INDEX.md overview across global and project scopes."""
    by_scope = {}
    for mem in memories:
        by_scope.setdefault(mem["scope"], []).append(mem)
    lines = ["# Shared Curated Memory", ""]
    global_items = by_scope.get("global", [])
    lines.append(f"## Global ({len(global_items)})")
    if global_items:
        for mem in global_items:
            lines.append(
                f"- [{mem['name']}](global/{mem['slug']}.md) "
                f"[{mem['type']}, {short_date(mem['updated_at'])}] — "
                f"{mem['description']}"
            )
    else:
        lines.append("- (empty)")
    projects = sorted(s for s in by_scope if s != "global")
    if projects:
        lines.extend(["", "## Projects"])
        for scope in projects:
            lines.append(
                f"- [{scope}](projects/{scope}/MEMORY.md) ({len(by_scope[scope])})"
            )
    lines.append("")
    return "\n".join(lines)


def has_symlink_part(root, relative):
    """True if any component from root down to root/relative is a symlink."""
    parts = Path(relative).parts
    return any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1))


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlink destination")
    fd, tmp = tempfile.mkstemp(prefix=".memory-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
