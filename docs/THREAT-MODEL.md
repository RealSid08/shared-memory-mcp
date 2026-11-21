# Threat model

## Intended use

One person operates the server and enrolls only trusted machines. The service shares concise, curated Markdown memories over local stdio or authenticated SSH. The server is not exposed as a public HTTP service.

## Trust boundaries

- SSH authenticates transport peers and encrypts traffic in transit.
- Every enrolled SSH identity has full read, write (`save`), and delete (`forget`) access to the shared memory store.
- Any connected MCP client and model can call all four tools (`recall`, `read`, `save`, `forget`).
- Stored memories are reference content, not executable instructions; agents should treat retrieved text as untrusted data and verify consequential facts against the live repo or system.

## Safeguards

- Strict schema validation for scopes, slugs, memory types, single-line names/descriptions, and UTF-8 bodies
- Hard quotas enforced inside SQLite write transactions: 8 KiB per body, 200 memories per scope, 2,000 memories total, 16 MiB store cap, 32 MiB wire cap
- Best-effort secret filter that rejects private key blocks, common API tokens, and credential assignment lines on `save` and `import` (fails closed rather than silently rewriting)
- Symlink refusal for install roots, store roots, cache directories, and cache file targets
- Optional required-mount guard and configurable minimum free-space threshold before writes
- Private file creation (`umask 0077`) and `0600` permissions on SQLite database files
- Destructive tool annotation (`destructiveHint: true`) on `forget`, and `readOnlyHint: true` on `recall` and `read`
- No offline write queue (failed writes fail explicitly instead of replaying stale mutations later)

## Important limitations

- Secret detection is best-effort and can miss credentials written in prose or unusual formats. Store pointers to where credentials live, never the credentials themselves.
- A compromised enrolled client or SSH key can read, overwrite, or delete all shared memories.
- This is not multi-tenant. There are no per-user ACLs, per-scope permissions, or cryptographic audit logs.
- SSH hardening, key rotation, disk encryption, and off-device backups are outside this repository.
- Local cache files (`cache/memories.json` and Markdown mirror) live unencrypted in the user's home directory; protect the machine accordingly.
- SQLite backups on the same disk do not protect against hardware failure.

Do not expose the stdio process through an unauthenticated network wrapper. If multiple untrusted users or teams need shared memory, use a multi-tenant service with explicit authentication, authorization, and audit controls.
