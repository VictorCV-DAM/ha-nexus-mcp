import asyncio
import json
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Provide lightweight stub for homeassistant when running tests outside HA environment
if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock
    sys.modules["homeassistant.exceptions"] = ha_mock
    sys.modules["homeassistant.helpers"] = ha_mock
    sys.modules["homeassistant.helpers.config_validation"] = ha_mock

from custom_components.nexus_mcp.mcp_client import (
    McpClient,
    McpConnectionError,
    McpError,
    McpRpcError,
    McpTool,
)



class TestMcpTool(unittest.TestCase):
    """Test McpTool data model and schema transformations."""

    def test_schema_conversions(self) -> None:
        """Verify conversion to OpenAI and Gemini tool formats."""
        tool = McpTool(
            name="create_automation",
            description="Create a new automation in Home Assistant",
            input_schema={
                "type": "object",
                "properties": {
                    "alias": {"type": "string"},
                    "trigger": {"type": "array"},
                },
                "required": ["alias", "trigger"],
            },
        )

        # OpenAI format check
        openai_fmt = tool.to_openai_tool()
        self.assertEqual(openai_fmt["type"], "function")
        self.assertEqual(openai_fmt["function"]["name"], "create_automation")
        self.assertEqual(openai_fmt["function"]["parameters"], tool.input_schema)

        # Gemini format check (verifies automatic array sanitization with items: {type: object})
        gemini_fmt = tool.to_gemini_tool()
        self.assertEqual(gemini_fmt["name"], "create_automation")
        self.assertEqual(
            gemini_fmt["parameters"]["properties"]["trigger"]["items"],
            {"type": "object"},
        )


class TestMcpClient(unittest.IsolatedAsyncioTestCase):
    """Test McpClient SSE streaming, handshake, tool discovery and tool calling."""

    async def test_rpc_message_handling(self) -> None:
        """Test incoming JSON-RPC response routing and error handling."""
        client = McpClient("http://localhost:8000/sse")
        client._connected.set()
        client._post_url = "http://localhost:8000/messages"

        # Create simulated pending request
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending_requests[1] = fut

        # Simulate success response arriving via SSE
        client._handle_rpc_message({"id": 1, "result": {"status": "ok"}})
        self.assertEqual(await fut, {"status": "ok"})

        # Simulate error response
        fut_err = loop.create_future()
        client._pending_requests[2] = fut_err
        client._handle_rpc_message(
            {
                "id": 2,
                "error": {"code": -32601, "message": "Method not found"},
            }
        )
        with self.assertRaises(McpRpcError) as ctx:
            await fut_err
        self.assertEqual(ctx.exception.code, -32601)

    async def test_tool_refresh_and_calling(self) -> None:
        """Test discovery caching and tool call validation."""
        client = McpClient("http://localhost:8000/sse")
        client._connected.set()
        client._post_url = "http://localhost:8000/messages"
        client._session = MagicMock()

        # Mock _send_request for tools/list
        mock_tools_response = {
            "tools": [
                {
                    "name": "search_entities",
                    "description": "Search entities by name or domain",
                    "inputSchema": {"type": "object"},
                }
            ]
        }

        async def fake_send_request(method: str, params: dict) -> dict:
            if method == "tools/list":
                return mock_tools_response
            if method == "tools/call":
                return {"content": [{"type": "text", "text": "entity_id: light.living_room"}]}
            return {}

        client._send_request = AsyncMock(side_effect=fake_send_request)

        # Refresh tools
        tools = await client.refresh_tools()
        self.assertIn("search_entities", tools)
        self.assertEqual(tools["search_entities"].name, "search_entities")

        # Call tool
        result = await client.call_tool("search_entities", {"query": "living room"})
        self.assertIn("content", result)

        # Call non-existent tool
        with self.assertRaises(McpError):
            await client.call_tool("non_existent_tool", {})


if __name__ == "__main__":
    unittest.main()
