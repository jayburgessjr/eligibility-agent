"""
Eligibility routing graph.

Graph topology:

    intake ──▶ classify ──▶ retrieve ──▶ decide ──▶ END
                                 ▲
                                 └── (MCP tool call to regulation store)

Each node is a pure function (state) -> partial state.
State is a TypedDict; LangGraph merges partial returns into the running state.

Why this shape:
- intake normalizes the applicant payload (defensive; real systems get dirty input)
- classify picks the regulatory track (Title IV, state aid, institutional) so the
  retrieval step knows which corpus to query
- retrieve is the only node that calls an external tool (MCP server for regs)
- decide is the LLM reasoning step; it sees normalized intake + retrieved rules
  and emits a structured decision

The split matters: each node is independently testable, observable, and
swappable. You could replace `retrieve` with a vector DB call without touching
the other nodes. That's the point of graph-shaped agents over monolithic
prompt chains.
"""
from __future__ import annotations

from typing import TypedDict, Literal, Any
from langgraph.graph import StateGraph, END

from agent.nodes import intake_node, classify_node, retrieve_node, decide_node


class AgentState(TypedDict, total=False):
    # Input
    query: str
    applicant: dict[str, Any]

    # Intermediate
    normalized: dict[str, Any]
    track: Literal["title_iv", "state_aid", "institutional", "unknown"]
    retrieved_rules: list[dict[str, Any]]

    # Output
    decision: dict[str, Any]
    trace: list[str]


def build_graph():
    """
    Construct and compile the eligibility routing graph.

    Returns a compiled graph you invoke with `.invoke(state)` or `.stream(state)`.
    """
    graph = StateGraph(AgentState)

    graph.add_node("intake", intake_node)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("decide", decide_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "decide")
    graph.add_edge("decide", END)

    return graph.compile()
