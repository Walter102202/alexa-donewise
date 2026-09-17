"""In-memory demo sessions, receipt-derived events and out-of-model consent."""

import asyncio
import json
from uuid import uuid4

from .mcp_client import MCPClient


class ToolCallError(RuntimeError):
    """A deliberate MCP tool error, already sanitized by the server."""


class Session:
    def __init__(self, settings, llm):
        self.id = uuid4().hex
        self.run_id = "run_" + uuid4().hex
        self.settings, self.llm = settings, llm
        self.client = MCPClient(settings, self.run_id)
        self.consent_token = None
        self.messages = []
        self.pending_approval = None
        self.receipts = {}
        self.events = []
        self.changed = asyncio.Condition()
        self.lock = asyncio.Lock()
        self.task = None
        self.tools = []
        self.step = 0
        self.script_args = {}
        self.turn_spoken = {}
        self._seen_receipts = set()

    async def start(self):
        try:
            await self.client.start()
            self.tools = [
                dict(name=t.name, description=t.description, input_schema=t.input_schema)
                for t in await self.client.tools()
            ]
            if self.settings.demo_admin_token:
                token = await self.client.admin("consent-token", {})
                self.consent_token = token["consent_token"]
        except BaseException:
            await self.client.close()
            raise

    def metadata(self):
        return {
            "session_id": self.id,
            "run_id": self.run_id,
            "mode": self.settings.mode,
            "tools": [t["name"] for t in self.tools],
            "protocol_version": self.client.protocol_version,
            "mcp_session_id": self.client.mcp_session_id,
            "admin_enabled": bool(self.settings.demo_admin_token),
        }

    async def emit(self, kind, data):
        async with self.changed:
            self.events.append({"id": len(self.events) + 1, "event": kind, "data": data})
            self.changed.notify_all()

    async def stream(self, after=0):
        while True:
            async with self.changed:
                if len(self.events) <= after:
                    try:
                        await asyncio.wait_for(self.changed.wait(), 15)
                    except TimeoutError:
                        pass
                batch = self.events[after:]
            if not batch:
                yield ": heartbeat\n\n"
            for event in batch:
                after = event["id"]
                yield f"id: {after}\nevent: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    async def record(self, tool, result):
        identity = result.get("receipt_id") or json.dumps(result, sort_keys=True)
        key = result.get("operation_id") or identity
        self.turn_spoken[key] = result
        if identity in self._seen_receipts:
            return
        self._seen_receipts.add(identity)
        if op_id := result.get("operation_id"):
            self.receipts[op_id] = {"tool": tool, "result": result}
        await self.emit("receipt", {"tool": tool, "result": result})
        if result.get("outcome") == "PENDING":
            await self.emit("assistant", {"text": result["spoken"], "source": "spoken"})
        if fault := result.get("fault_injected"):
            await self.emit("fault", {"kind": fault, "fired": True})

    async def execute(self, tool, arguments):
        if tool not in {t["name"] for t in self.tools}:
            raise RuntimeError("Tool is not available to the agent")
        await self.emit("status", {"status": "calling " + tool})
        result, is_error, text = await self.client.call(tool, arguments)
        if is_error:
            raise ToolCallError(text)
        if result is None:
            raise RuntimeError("MCP tool failed: " + tool)
        await self.record(tool, result)
        if result.get("approval_request"):
            self.pending_approval = {
                "request": result["approval_request"],
                "arguments": dict(arguments),
            }
        deadline = asyncio.get_running_loop().time() + 15
        while result.get("outcome") == "PENDING":
            await self.emit("status", {"status": "pending"})
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(1)
            result, is_error, _ = await self.client.call(
                "operation_get", {"operation_id": result["operation_id"]}
            )
            if is_error or result is None:
                raise RuntimeError("Unable to check operation; no write was retried")
            await self.record("operation_get", result)
        return result

    async def approve(self):
        if not self.pending_approval or not self.consent_token:
            raise RuntimeError("No approvable payment or consent capability")
        pending = self.pending_approval
        grant, is_error, _ = await self.client.call(
            "approval_grant",
            {
                "approval_request_id": pending["request"]["approval_request_id"],
                "consent_token": self.consent_token,
            },
        )
        if is_error or grant is None:
            raise RuntimeError("Approval was not granted")
        result = await self.execute(
            "payment_charge_verified", {**pending["arguments"], "approval_id": grant["approval_id"]}
        )
        self.pending_approval = None
        return result

    async def arm(self, kind, uses=1):
        await self.client.admin("faults", {"kind": kind, "uses": uses})
        await self.emit("fault", {"kind": kind, "armed": True})

    async def speak_receipts(self):
        spoken = [r["spoken"] for r in self.turn_spoken.values() if r.get("outcome") != "PENDING"]
        if spoken:
            await self.emit("assistant", {"text": " ".join(spoken), "source": "spoken"})

    def launch(self, action):
        if self.task and not self.task.done():
            return False

        async def run():
            async with self.lock:
                self.turn_spoken = {}
                try:
                    await action()
                except Exception:
                    await self.emit(
                        "error",
                        {
                            "message": "Turn could not complete. Check the audit; "
                            "no write was automatically retried."
                        },
                    )
                    await self.speak_receipts()
                finally:
                    await self.emit("status", {"status": "idle", "step": self.step})

        self.task = asyncio.create_task(run())
        return True

    async def close(self):
        if self.task:
            await self.task
        await self.client.close()
