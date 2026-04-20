"""
Regulation MCP server.

Exposes one tool: `fetch_regulations(track, query)` → list[Rule]

Run it:
    python mcp_server/server.py

Then in .env:
    MCP_SERVER_URL=http://localhost:8000/sse

The agent will call this instead of the local fixture.

This is an SSE-transport MCP server using the official Anthropic MCP SDK.
In production you would back this with a vector store, a regulation database,
or an external API. Here it returns from the same fixture used in agent/tools.py
so you can see the full round-trip working without a database dependency.

Why a separate server instead of just calling the fixture directly:
- Demonstrates the actual MCP protocol handshake (initialize → call_tool)
- The server can be versioned, audited, and deployed independently of the agent
- Any MCP-compatible client (Claude Desktop, another agent, a Slack bot) can
  call the same server — regulation retrieval becomes a shared service, not
  copied logic
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("regulation-store")

# ---------------------------------------------------------------------------
# Regulation fixture
# Same data as agent/tools.py — the server owns this in production.
# ---------------------------------------------------------------------------
_RULES: dict[str, list[dict[str, Any]]] = {
    "title_iv": [
        {
            "id": "34_CFR_668.32(a)",
            "track": "title_iv",
            "text": (
                "A student is eligible if they are a U.S. citizen, national, "
                "or eligible non-citizen."
            ),
            "gates": ["citizenship"],
        },
        {
            "id": "34_CFR_668.32(c)",
            "track": "title_iv",
            "text": (
                "A student must be enrolled or accepted for enrollment as a "
                "regular student in an eligible program."
            ),
            "gates": ["enrollment_status", "program_type"],
        },
        {
            "id": "34_CFR_668.34",
            "track": "title_iv",
            "text": (
                "A student must maintain satisfactory academic progress (SAP) "
                "as defined by the institution."
            ),
            "gates": ["sap_status"],
        },
        {
            "id": "34_CFR_668.35",
            "track": "title_iv",
            "text": (
                "A student in default on a Title IV loan is ineligible until "
                "the default is resolved."
            ),
            "gates": ["prior_default"],
        },
    ],
    "state_aid": [
        {
            "id": "STATE_GEN_01",
            "track": "state_aid",
            "text": (
                "State residency and enrollment at an in-state institution "
                "are typically required."
            ),
            "gates": ["enrollment_status"],
        },
    ],
    "institutional": [
        {
            "id": "INST_GEN_01",
            "track": "institutional",
            "text": (
                "Institutional aid eligibility is governed by school policy "
                "and the specific award terms."
            ),
            "gates": [],
        },
    ],
    "unknown": [],
}


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------
@mcp.tool()
def fetch_regulations(track: str, query: str) -> str:
    """
    Return applicable regulations for the given regulatory track.

    Args:
        track: One of 'title_iv', 'state_aid', 'institutional', 'unknown'.
        query: The natural-language eligibility question (used for logging
               and future semantic routing — not filtered on here).

    Returns:
        JSON-encoded list of Rule objects, each with id, track, text, gates.
    """
    rules = _RULES.get(track, [])
    return json.dumps(rules)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Regulation MCP server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="localhost")
    args = parser.parse_args()

    print(f"Starting regulation MCP server on {args.host}:{args.port}")
    print(f"Set MCP_SERVER_URL=http://{args.host}:{args.port}/sse in your .env")
    mcp.run(transport="sse", host=args.host, port=args.port)
