# SPDX-License-Identifier: Apache-2.0
"""Exchange protocol v3 handler run on the server (locally or over SSH).

Requests arrive as one JSON object on stdin:
- {"protocol": 3, "op": "pull"} -> full curated memories list
- {"protocol": 3, "op": "save", "memory": {...}} -> upsert + updated memories list
- {"protocol": 3, "op": "forget", "id": "<scope>/<slug>"} -> delete + updated list
- {"protocol": 3, "op": "import", "items": [...], "replace": bool} -> bulk import
- {"protocol": 3, "op": "status"} -> store health and scope counts
"""

from . import VERSION


def handle(store, request):
    if not isinstance(request, dict):
        raise TypeError("Exchange request must be a JSON object")
    protocol = request.get("protocol")
    if protocol != 3:
        raise ValueError(f"Unsupported exchange protocol {protocol}; expected 3")
    op = request.get("op")
    if op == "status":
        return {"protocol": 3, "server_version": VERSION, **store.status()}
    if op == "pull":
        return {
            "protocol": 3,
            "server_version": VERSION,
            "memories": store.all_memories(),
        }
    if op == "save":
        mem = request.get("memory")
        if not isinstance(mem, dict):
            raise TypeError("memory must be an object")
        result = store.save_memory(
            scope=mem["scope"],
            slug=mem["slug"],
            type=mem["type"],
            name=mem["name"],
            description=mem["description"],
            content=mem["content"],
            updated_by=mem.get("updated_by") or request.get("machine") or "",
        )
        return {
            "protocol": 3,
            "server_version": VERSION,
            "result": result,
            "memories": store.all_memories(),
        }
    if op == "forget":
        result = store.delete_memory(request["id"])
        return {
            "protocol": 3,
            "server_version": VERSION,
            "result": result,
            "memories": store.all_memories(),
        }
    if op == "import":
        result = store.import_memories(
            request.get("items", []), replace=bool(request.get("replace", False))
        )
        return {
            "protocol": 3,
            "server_version": VERSION,
            "result": result,
            "memories": store.all_memories(),
        }
    raise ValueError(f"Unknown exchange operation: {op}")
