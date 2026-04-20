"""
Node functions for the eligibility routing graph.

Each node takes the full state and returns a partial state (dict of fields to
merge). Nodes should be small, pure where possible, and log their work to
`state["trace"]` so the graph is observable without a tracing vendor wired in.
"""
from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from agent.tools import fetch_regulations


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------
# Default is GPT-4o. To swap in Claude, replace with:
#   from langchain_anthropic import ChatAnthropic
#   return ChatAnthropic(model="claude-sonnet-4-5", temperature=0)
# Everything downstream works unchanged — both providers implement the same
# langchain-core BaseChatModel interface.
def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        temperature=0,
    )


def _append_trace(state: dict, msg: str) -> list[str]:
    return [*state.get("trace", []), msg]


# ---------------------------------------------------------------------------
# Node 1: intake
# ---------------------------------------------------------------------------
def intake_node(state: dict) -> dict:
    """
    Normalize applicant input. In production this is where you'd validate
    against a schema, coerce types, and reject malformed payloads before
    burning an LLM call. Kept minimal here.
    """
    applicant = state.get("applicant", {}) or {}
    normalized = {
        "citizenship": (applicant.get("citizenship") or "").strip().lower() or None,
        "enrollment_status": (applicant.get("enrollment_status") or "").strip().lower() or None,
        "sap_status": (applicant.get("sap_status") or "").strip().lower() or None,
        "prior_default": bool(applicant.get("prior_default", False)),
        "program_type": (applicant.get("program_type") or "").strip().lower() or None,
    }
    return {
        "normalized": normalized,
        "trace": _append_trace(state, f"intake: normalized {len(normalized)} fields"),
    }


# ---------------------------------------------------------------------------
# Node 2: classify
# ---------------------------------------------------------------------------
CLASSIFY_SYSTEM = """You route eligibility queries to the correct regulatory track.

Tracks:
- title_iv: Federal student aid under Title IV of the Higher Education Act (Pell, Direct Loans, FSEOG, Work-Study).
- state_aid: State-level grant and scholarship programs.
- institutional: School-specific aid and scholarships.
- unknown: Cannot determine from the query alone.

Respond with ONLY a JSON object: {"track": "<one of the four>", "reason": "<one sentence>"}.
No prose, no code fences.
"""


def classify_node(state: dict) -> dict:
    """
    Pick the regulatory track. Small, cheap LLM call that gates which corpus
    `retrieve` will hit. In a larger system this could be a conditional edge
    with branching nodes per track; kept linear here for readability.
    """
    query = state.get("query", "")
    normalized = state.get("normalized", {})

    user_payload = json.dumps({"query": query, "applicant": normalized})

    resp = _llm().invoke([
        SystemMessage(content=CLASSIFY_SYSTEM),
        HumanMessage(content=user_payload),
    ])

    try:
        parsed = json.loads(resp.content)
        track = parsed.get("track", "unknown")
        reason = parsed.get("reason", "")
    except (json.JSONDecodeError, AttributeError):
        track, reason = "unknown", "classifier returned non-JSON"

    if track not in {"title_iv", "state_aid", "institutional", "unknown"}:
        track = "unknown"

    return {
        "track": track,
        "trace": _append_trace(state, f"classify: track={track} ({reason})"),
    }


# ---------------------------------------------------------------------------
# Node 3: retrieve (MCP tool call)
# ---------------------------------------------------------------------------
def retrieve_node(state: dict) -> dict:
    """
    Fetch applicable rules for the classified track via the MCP tool.

    This is the only node that touches an external system. Keeping I/O
    quarantined to one node means the rest of the graph is deterministic
    given the same retrieved_rules — which makes testing and replay trivial.
    """
    track = state.get("track", "unknown")
    query = state.get("query", "")

    rules = fetch_regulations(track=track, query=query)

    return {
        "retrieved_rules": rules,
        "trace": _append_trace(state, f"retrieve: {len(rules)} rules for track={track}"),
    }


# ---------------------------------------------------------------------------
# Node 4: decide
# ---------------------------------------------------------------------------
DECIDE_SYSTEM = """You are an eligibility reasoner for regulated aid programs.

Given:
- An applicant profile (normalized)
- A query
- A list of applicable regulations

Produce a decision. Be conservative: when a rule is ambiguous or a required
field is missing, route to human_review rather than guessing.

Respond with ONLY a JSON object shaped exactly like this:
{
  "outcome": "eligible" | "ineligible" | "human_review",
  "rationale": "<2-3 sentences citing the specific regulation IDs you relied on>",
  "citations": ["<regulation id>", ...],
  "missing_information": ["<field>", ...]
}
No prose, no code fences.
"""


def decide_node(state: dict) -> dict:
    """
    Final reasoning step. Sees everything the graph has accumulated and
    emits a structured decision.
    """
    payload = {
        "query": state.get("query", ""),
        "applicant": state.get("normalized", {}),
        "regulations": state.get("retrieved_rules", []),
    }

    resp = _llm().invoke([
        SystemMessage(content=DECIDE_SYSTEM),
        HumanMessage(content=json.dumps(payload)),
    ])

    try:
        decision = json.loads(resp.content)
    except (json.JSONDecodeError, AttributeError):
        decision = {
            "outcome": "human_review",
            "rationale": "Decision model returned non-JSON; escalating for safety.",
            "citations": [],
            "missing_information": [],
        }

    return {
        "decision": decision,
        "trace": _append_trace(state, f"decide: outcome={decision.get('outcome')}"),
    }
