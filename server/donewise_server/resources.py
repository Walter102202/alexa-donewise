"""Read-only receipt resources; never expose credentials or request metadata."""

import json

import anyio
from donewise_harness.registry import Registry
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError


def register_resources(server: MCPServer, registry: Registry):
    @server.resource("receipts://run/{run_id}")
    async def run_receipts(run_id: str) -> str:
        rows = await anyio.to_thread.run_sync(registry.latest_receipts_for_run, run_id)
        keys = ("operation_id", "action", "outcome", "observed_at")
        return json.dumps([{k: json.loads(row["receipt_json"])[k] for k in keys} for row in rows])

    @server.resource("receipts://operation/{operation_id}")
    async def operation_receipt(operation_id: str) -> str:
        row = await anyio.to_thread.run_sync(registry.latest_receipt, operation_id)
        if row is None:
            raise ResourceError("Receipt not found")
        return row["receipt_json"]
