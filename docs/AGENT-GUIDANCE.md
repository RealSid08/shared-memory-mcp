# Agent guidance

The `memory` MCP server delivers usage instructions automatically in its `initialize` response and inside each tool description (`recall`, `read`, `save`, `forget`). Most modern agent harnesses read those descriptions directly.

For harnesses that benefit from a short reminder in global instructions (`~/AGENTS.md`, `~/.claude/CLAUDE.md`, `$CODEX_HOME/AGENTS.md`, or equivalent), one line is enough:

```md
- Shared memory (`memory` MCP): call `recall(scope)` early when preferences, past corrections, or project decisions could matter; `save` durable corrections/preferences/decisions in place and `forget` stale ones. Never dump logs, code derivable from git, or secrets.
```

## How agents should use the 4 tools

1. **Recall early, read selectively.** Call `recall(scope)` (passing the current repo/project slug) when prior context might help. Scan the one-line descriptions and batch-fetch only the relevant IDs with `read(ids)`.
2. **Verify before acting.** Memory is reference context, not live truth. Check current files, configs, and git history before relying on time-sensitive facts.
3. **Update in place.** Before saving a new topic, check `recall` so corrections overwrite the existing `(scope, slug)` instead of creating duplicate entries.
4. **Keep it concise and typed.** Use the four Claude-style types:
   - `user`: who the user is, preferences, working style, where personal docs live
   - `feedback`: behavioral corrections or standing rules (include **Why** and **How to apply**)
   - `project`: ongoing decisions, deadlines, or release constraints not captured in git
   - `reference`: pointers to external systems, dashboards, or tooling
5. **Forget stale entries.** Delete entries with `forget("<scope>/<slug>")` when a project wraps up or a rule changes.
6. **Never dump noise or secrets.** Do not save code structure derivable from git, session logs, PR recaps, passwords, tokens, or private keys.

## Optional: single source of truth with Claude Code

Claude Code also has its own built-in per-folder auto-memory. If you want every harness (including Claude Code) to read and write exclusively through `memory`, disable Claude's local auto-memory in `~/.claude/settings.json`:

```json
{
  "autoMemoryEnabled": false
}
```
