"""
Tool definitions for the agent.

Primary path: call an MCP server exposing a `fetch_regulations` tool.
Fallback path: an in-process rules fixture so the demo runs with zero setup.

Why both: MCP is the point of this repo, but a reference agent should clone,
install, and run end-to-end with one command. The fallback ships that
guarantee; the MCP client code shows the real integration shape.

Enable MCP mode by setting MCP_SERVER_URL in .env. Otherwise the local
fixture is used and a note is printed.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

# ---------------------------------------------------------------------------
# Local fixture — minimal, illustrative, not legal advice.
# Each "rule" mimics the shape you'd get back from a real regulation store:
# a stable id, the applicable track, a short text, and the field it gates on.
# ---------------------------------------------------------------------------
_LOCAL_RULES: dict[str, list[dict[str, Any]]] = {
    "title_iv": [
        {
            "id": "34_CFR_668.32(a)",
            "track": "title_iv",
            "text": "A student is eligible if they are a U.S. citizen, national, or eligible non-citizen.",
            "gates": ["citizenship"],
        },
        {
            "id": "34_CFR_668.32(c)",
            "track": "title_iv",
            "text": "A student must be enrolled or accepted for enrollment as a regular student in an eligible program.",
            "gates": ["enrollment_status", "program_type"],
        },
        {
            "id": "34_CFR_668.34",
            "track": "title_iv",
            "text": "A student must maintain satisfactory academic progress (SAP) as defined by the institution.",
            "gates": ["sap_status"],
        },
        {
            "id": "34_CFR_668.35",
            "track": "title_iv",
            "text": "A student in default on a Title IV loan is ineligible until the default is resolved.",
            "gates": ["prior_default"],
        },
    ],
    "state_aid": [
        {
            "id": "STATE_GEN_01",
            "track": "state_aid",
            "text": "State residency and enrollment at an in-state institution are typically required.",
            "gates": ["enrollment_status"],
        },
    ],
    "institutional": [
        {
            "id": "INST_GEN_01",
            "track": "institutional",
            "text": "Institutional aid eligibility is governed by school policy and the specific award terms.",
            "gates": [],
        },
    ],
    "unknown": [],
}


# ---------------------------------------------------------------------------
# MCP client path
# ---------------------------------------------------------------------------
async def _fetch_via_mcp(server_url: str, track: str, query: str) -> list[dict[str, Any]]:
    """
    Call the MCP server's `fetch_regulations` tool.

    Expects an MCP server exposing a tool with this signature:
        fetch_regulations(track: str, query: str) -> list[Rule]

    Replace the transport below if your server uses stdio or a different URL scheme.
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "fetch_regulations",
                arguments={"track": track, "query": query},
            )
            # MCP returns content blocks; the server is expected to return
            # a single text block containing a JSON array of rules.
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    import json
                    return json.loads(block.text)
            return []


# ---------------------------------------------------------------------------
# Public API used by retrieve_node
# ---------------------------------------------------------------------------
def fetch_regulations(track: str, query: str) -> list[dict[str, Any]]:
    """
    Synchronous entry point. Uses MCP if MCP_SERVER_URL is set, otherwise
    returns the local fixture. Keeping this sync simplifies the graph —
    async MCP work is encapsulated here.
    """
    server_url = os.getenv("MCP_SERVER_URL")
    if server_url:
        try:
            return asyncio.run(_fetch_via_mcp(server_url, track, query))
        except Exception as e:  # noqa: BLE001 — reference code, wide catch is intentional
            print(f"[tools] MCP call failed ({e}); falling back to local fixture.")

    return list(_LOCAL_RULES.get(track, []))
