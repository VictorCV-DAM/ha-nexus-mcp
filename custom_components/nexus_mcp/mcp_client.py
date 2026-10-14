"""Asynchronous Model Context Protocol (MCP) client for Home Assistant.

Communicates with MCP servers (such as ha-mcp) over SSE/HTTP transport.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class McpError(Exception):
    """Base exception for MCP client errors."""


class McpConnectionError(McpError):
    """Raised when connection to the MCP server fails."""


class McpRpcError(McpError):
    """Raised when the MCP server returns a JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP RPC Error [{code}]: {message}")
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class McpTool:
    """Represents a tool exposed by the MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert MCP tool definition to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_gemini_tool(self) -> dict[str, Any]:
        """Convert MCP tool definition to Gemini function declaration format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }


class McpClient:
    """Client for Model Context Protocol (MCP) servers using SSE transport."""

    def __init__(
        self,
        server_url: str,
        session: aiohttp.ClientSession | None = None,
        client_name: str = "nexus-mcp",
        client_version: str = "0.1.0",
    ) -> None:
        """Initialize the MCP client."""
        self._server_url = server_url.rstrip("/")
        self._session = session
        self._own_session = False
        self._client_name = client_name
        self._client_version = client_version

        self._post_url: str | None = None
        self._sse_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._closing = False

        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._tools: dict[str, McpTool] = {}

    @property
    def is_connected(self) -> bool:
        """Return True if the client is connected and ready."""
        return self._connected.is_set() and not self._closing

    @property
    def tools(self) -> dict[str, McpTool]:
        """Return cached discovered tools."""
        return self._tools

    async def connect(self) -> None:
        """Establish SSE connection and perform MCP initialization handshake."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True

        self._closing = False
        self._connected.clear()
        self._sse_task = asyncio.create_task(self._listen_sse())

        try:
            # Wait for SSE endpoint discovery event (up to 10 seconds)
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError as err:
            await self.disconnect()
            raise McpConnectionError(
                f"Timed out waiting for SSE endpoint event from {self._server_url}"
            ) from err

        # Perform MCP initialization handshake
        await self._initialize_handshake()

        # Cache available tools
        await self.refresh_tools()
        _LOGGER.info(
            "Connected to MCP server %s. Discovered %d tools.",
            self._server_url,
            len(self._tools),
        )

    async def disconnect(self) -> None:
        """Disconnect and clean up resources."""
        self._closing = True
        self._connected.clear()

        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

        # Cancel any pending requests
        for fut in self._pending_requests.values():
            if not fut.done():
                fut.set_exception(McpConnectionError("MCP Client disconnected"))
        self._pending_requests.clear()

        if self._own_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _listen_sse(self) -> None:
        """Background listener for Server-Sent Events (SSE)."""
        if self._session is None:
            return

        try:
            async with self._session.get(
                self._server_url,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "MCP SSE connection failed with HTTP %d", response.status
                    )
                    return

                current_event: str | None = None

                async for raw_line in response.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        current_event = None
                        continue

                    if line.startswith("event:"):
                        current_event = line[len("event:") :].strip()
                        continue

                    if line.startswith("data:"):
                        data_str = line[len("data:") :].strip()

                        if current_event == "endpoint":
                            # The server tells us where to POST JSON-RPC messages
                            endpoint_path = data_str
                            self._post_url = urljoin(
                                f"{self._server_url}/", endpoint_path
                            )
                            _LOGGER.debug(
                                "MCP endpoint discovered: %s", self._post_url
                            )
                            self._connected.set()
                            continue

                        # Handle standard JSON-RPC response
                        try:
                            msg = json.loads(data_str)
                            self._handle_rpc_message(msg)
                        except json.JSONDecodeError:
                            _LOGGER.warning("Invalid JSON from MCP SSE: %s", data_str)

        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.error("Error in MCP SSE stream listener: %s", err)
            if not self._closing:
                self._connected.clear()

    def _handle_rpc_message(self, msg: dict[str, Any]) -> None:
        """Route incoming JSON-RPC response to the awaiting future."""
        msg_id = msg.get("id")
        if msg_id is None:
            # Server-initiated notification or ping
            _LOGGER.debug("MCP Notification received: %s", msg)
            return

        future = self._pending_requests.pop(msg_id, None)
        if future is None or future.done():
            return

        if "error" in msg:
            err = msg["error"]
            future.set_exception(
                McpRpcError(
                    code=err.get("code", -1),
                    message=err.get("message", "Unknown error"),
                    data=err.get("data"),
                )
            )
        else:
            future.set_result(msg.get("result"))

    async def _send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if not self.is_connected or not self._post_url or not self._session:
            raise McpConnectionError("MCP Client is not connected")

        self._request_id += 1
        req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            async with self._session.post(
                self._post_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status not in (200, 202):
                    self._pending_requests.pop(req_id, None)
                    raise McpConnectionError(
                        f"POST to MCP server returned HTTP {response.status}"
                    )

            # Wait for response arriving via SSE stream
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError as err:
            self._pending_requests.pop(req_id, None)
            raise McpRpcError(-32000, f"Request '{method}' timed out after 30s") from err

    async def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.is_connected or not self._post_url or not self._session:
            raise McpConnectionError("MCP Client is not connected")

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        async with self._session.post(
            self._post_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as response:
            if response.status not in (200, 202):
                _LOGGER.warning(
                    "MCP Notification %s returned HTTP %d", method, response.status
                )

    async def _initialize_handshake(self) -> None:
        """Perform MCP initialize protocol handshake."""
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": self._client_name,
                    "version": self._client_version,
                },
            },
        )
        _LOGGER.debug("MCP Initialized: %s", result)
        await self._send_notification("notifications/initialized")

    async def refresh_tools(self) -> dict[str, McpTool]:
        """Fetch available tools from the MCP server (`tools/list`)."""
        result = await self._send_request("tools/list", {})
        raw_tools = result.get("tools", [])

        discovered: dict[str, McpTool] = {}
        for raw in raw_tools:
            name = raw.get("name")
            if not name:
                continue
            tool = McpTool(
                name=name,
                description=raw.get("description", ""),
                input_schema=raw.get("inputSchema", {}),
            )
            discovered[name] = tool

        self._tools = discovered
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool on the MCP server (`tools/call`)."""
        if name not in self._tools:
            # Refresh in case tools were updated
            await self.refresh_tools()
            if name not in self._tools:
                raise McpError(f"Tool '{name}' is not exposed by the MCP server.")

        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        return result
