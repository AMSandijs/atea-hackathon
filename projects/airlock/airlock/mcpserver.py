"""Local stdio MCP front door: only approved sanitized case text is exposed."""

from __future__ import annotations

from mcp.server import MCPServer

from .cases import read_case as _read_case

mcp = MCPServer("Local AI Airlock")


@mcp.tool()
def read_case(case_id: str) -> str:
    """Read an operator-approved, sanitized Azure investigation by opaque case ID."""

    return _read_case(case_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
