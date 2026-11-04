"""Model Context Protocol (MCP) data models and schema helpers for Nexus MCP."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


def _sanitize_gemini_schema(obj: Any) -> None:
    """Ensure all array types in JSON schema have an 'items' definition for Gemini API compliance."""
    if isinstance(obj, dict):
        if obj.get("type") == "array" and "items" not in obj:
            obj["items"] = {"type": "object"}
        for value in obj.values():
            _sanitize_gemini_schema(value)
    elif isinstance(obj, list):
        for item in obj:
            _sanitize_gemini_schema(item)


@dataclass(frozen=True)
class McpTool:
    """Represents a tool formatted for LLM consumption following MCP specification."""

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
        schema = copy.deepcopy(self.input_schema)
        _sanitize_gemini_schema(schema)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        }
