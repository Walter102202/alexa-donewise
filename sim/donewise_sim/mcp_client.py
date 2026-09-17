"""Official MCP client, owned by one task for the lifetime of its AnyIO contexts."""

import asyncio
from urllib.parse import urlsplit, urlunsplit

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MCPClient:
    def __init__(self, settings, run_id):
        self.settings, self.run_id = settings, run_id
        self.protocol_version = self.mcp_session_id = None
        self._task = None
        self._queue = asyncio.Queue()
        self._ready = None

    async def start(self):
        if self._task is None or self._task.done():
            self._ready = asyncio.get_running_loop().create_future()
            self._task = asyncio.create_task(self._serve())
        await asyncio.shield(self._ready)

    async def _serve(self):
        current = None
        try:

            async def headers(response):
                if sid := response.headers.get("mcp-session-id"):
                    self.mcp_session_id = sid

            auth = {"X-DoneWise-Run-Id": self.run_id}
            if self.settings.mcp_bearer_token:
                auth["Authorization"] = "Bearer " + self.settings.mcp_bearer_token
            async with httpx2.AsyncClient(
                headers=auth, event_hooks={"response": [headers]}
            ) as http:
                async with streamable_http_client(
                    self.settings.mcp_url, http_client=http
                ) as streams:
                    async with ClientSession(*streams) as session:
                        initialized = await session.initialize()
                        self.protocol_version = initialized.protocol_version
                        if self.protocol_version != "2025-11-25":
                            raise RuntimeError("Unexpected MCP protocol version")
                        self._ready.set_result(None)
                        while True:
                            command = await self._queue.get()
                            if command is None:
                                break
                            method, args, current = command
                            result = await getattr(session, method)(*args)
                            if not current.done():
                                current.set_result(result)
                            current = None
        except Exception:
            # Never expose HTTP headers, tokens or provider exception dumps.
            error = RuntimeError("MCP connection unavailable; no write was automatically retried")
            if not self._ready.done():
                self._ready.set_exception(error)
            if current is not None and not current.done():
                current.set_exception(error)
        finally:
            while not self._queue.empty():
                command = self._queue.get_nowait()
                if command is not None and not command[2].done():
                    command[2].set_exception(RuntimeError("MCP connection closed"))

    async def _request(self, method, *args):
        # A later request reconnects with the original run, never replays a write.
        await self.start()
        future = asyncio.get_running_loop().create_future()
        await self._queue.put((method, args, future))
        return await future

    async def tools(self):
        result = await self._request("list_tools")
        return [tool for tool in result.tools if tool.name != "approval_grant"]

    async def call(self, name, args):
        result = await self._request("call_tool", name, args)
        text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
        return result.structured_content, result.is_error, text

    async def admin(self, path, payload=None):
        if not self.settings.demo_admin_token:
            raise RuntimeError("Demo admin capability is not configured")
        parts = urlsplit(self.settings.mcp_url)
        url = urlunsplit((parts.scheme, parts.netloc, "/admin/" + path, "", ""))
        async with httpx2.AsyncClient(
            headers={"X-Demo-Admin-Token": self.settings.demo_admin_token}
        ) as client:
            if payload is None:
                response = await client.get(url, params={"run_id": self.run_id})
            else:
                response = await client.post(url, json={"run_id": self.run_id, **payload})
            if response.status_code != 200:
                raise RuntimeError("Demo admin request failed")
            return response.json()

    async def close(self):
        if self._task and not self._task.done():
            await self._queue.put(None)
            await self._task
