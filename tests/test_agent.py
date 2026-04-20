"""
Unit tests for the eligibility agent.

These tests cover the graph's deterministic layers (intake, retrieve, state
merging) and the decision fallback behavior. The LLM-dependent nodes
(classify, decide) are tested with mocked LLM responses so the suite runs
without API keys and completes in milliseconds.

Run:
    python -m pytest tests/ -v
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# intake_node — pure, no LLM
# ---------------------------------------------------------------------------
class TestIntakeNode:
    def test_normalizes_fields(self):
        from agent.nodes import intake_node

        state = {
            "applicant": {
                "citizenship": "  US_CITIZEN  ",
                "enrollment_status": "FULL_TIME",
                "sap_status": "Meeting",
                "prior_default": False,
                "program_type": "Undergraduate_Degree",
            }
        }
        result = intake_node(state)

        assert result["normalized"]["citizenship"] == "us_citizen"
        assert result["normalized"]["enrollment_status"] == "full_time"
        assert result["normalized"]["sap_status"] == "meeting"
        assert result["normalized"]["prior_default"] is False

    def test_handles_empty_applicant(self):
        from agent.nodes import intake_node

        result = intake_node({"applicant": {}})
        assert result["normalized"]["citizenship"] is None
        assert result["normalized"]["prior_default"] is False

    def test_handles_missing_applicant_key(self):
        from agent.nodes import intake_node

        result = intake_node({})
        assert "normalized" in result

    def test_appends_trace(self):
        from agent.nodes import intake_node

        result = intake_node({"trace": ["prior step"], "applicant": {}})
        assert len(result["trace"]) == 2
        assert "intake" in result["trace"][-1]


# ---------------------------------------------------------------------------
# retrieve_node — uses tools.py local fixture, no network
# ---------------------------------------------------------------------------
class TestRetrieveNode:
    def test_title_iv_returns_rules(self):
        from agent.nodes import retrieve_node

        result = retrieve_node({"track": "title_iv", "query": "Is the applicant eligible?"})
        rules = result["retrieved_rules"]

        assert len(rules) > 0
        assert all("id" in r for r in rules)
        assert all("text" in r for r in rules)

    def test_unknown_track_returns_empty(self):
        from agent.nodes import retrieve_node

        result = retrieve_node({"track": "unknown", "query": "?"})
        assert result["retrieved_rules"] == []

    def test_appends_trace(self):
        from agent.nodes import retrieve_node

        result = retrieve_node({"track": "title_iv", "query": "test", "trace": []})
        assert any("retrieve" in t for t in result["trace"])


# ---------------------------------------------------------------------------
# classify_node — mocked LLM
# ---------------------------------------------------------------------------
class TestClassifyNode:
    def _mock_llm_response(self, content: str):
        mock = MagicMock()
        mock.content = content
        return mock

    def test_returns_title_iv_for_federal_query(self):
        from agent.nodes import classify_node

        llm_resp = self._mock_llm_response(
            json.dumps({"track": "title_iv", "reason": "Federal aid query"})
        )
        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.return_value = llm_resp
            result = classify_node(
                {"query": "Is this student eligible for Pell?", "normalized": {}}
            )

        assert result["track"] == "title_iv"

    def test_falls_back_to_unknown_on_bad_json(self):
        from agent.nodes import classify_node

        bad_resp = self._mock_llm_response("not json at all")
        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.return_value = bad_resp
            result = classify_node({"query": "?", "normalized": {}})

        assert result["track"] == "unknown"

    def test_rejects_invalid_track_value(self):
        from agent.nodes import classify_node

        llm_resp = self._mock_llm_response(
            json.dumps({"track": "made_up_track", "reason": "hallucinated"})
        )
        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.return_value = llm_resp
            result = classify_node({"query": "?", "normalized": {}})

        assert result["track"] == "unknown"


# ---------------------------------------------------------------------------
# decide_node — mocked LLM
# ---------------------------------------------------------------------------
class TestDecideNode:
    def _make_state(self, outcome: str = "eligible"):
        return {
            "query": "Is the applicant eligible?",
            "normalized": {"citizenship": "us_citizen", "prior_default": False},
            "retrieved_rules": [
                {"id": "34_CFR_668.32(a)", "text": "Must be US citizen.", "gates": ["citizenship"]}
            ],
        }

    def test_passes_through_valid_decision(self):
        from agent.nodes import decide_node

        decision = {
            "outcome": "eligible",
            "rationale": "Meets all Title IV requirements.",
            "citations": ["34_CFR_668.32(a)"],
            "missing_information": [],
        }
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(decision)

        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.return_value = mock_resp
            result = decide_node(self._make_state())

        assert result["decision"]["outcome"] == "eligible"
        assert "34_CFR_668.32(a)" in result["decision"]["citations"]

    def test_falls_back_to_human_review_on_bad_json(self):
        from agent.nodes import decide_node

        mock_resp = MagicMock()
        mock_resp.content = "sorry, I cannot help"

        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.return_value = mock_resp
            result = decide_node(self._make_state())

        assert result["decision"]["outcome"] == "human_review"


# ---------------------------------------------------------------------------
# fetch_regulations — local fixture path (no MCP server)
# ---------------------------------------------------------------------------
class TestFetchRegulations:
    def test_title_iv_returns_four_rules(self):
        from agent.tools import fetch_regulations

        rules = fetch_regulations(track="title_iv", query="eligible?")
        assert len(rules) == 4

    def test_all_rules_have_required_keys(self):
        from agent.tools import fetch_regulations

        rules = fetch_regulations(track="title_iv", query="eligible?")
        for rule in rules:
            assert "id" in rule
            assert "track" in rule
            assert "text" in rule
            assert "gates" in rule

    def test_unknown_track_returns_empty_list(self):
        from agent.tools import fetch_regulations

        assert fetch_regulations(track="nonexistent", query="?") == []

    def test_mcp_failure_falls_back_to_fixture(self, capsys):
        from agent.tools import fetch_regulations
        import os

        with patch.dict(os.environ, {"MCP_SERVER_URL": "http://bad-host:9999/sse"}):
            rules = fetch_regulations(track="title_iv", query="eligible?")

        # should still return rules from the local fixture
        assert len(rules) > 0


# ---------------------------------------------------------------------------
# graph integration — no LLM, checks that state merges are correct
# ---------------------------------------------------------------------------
class TestGraphIntegration:
    """
    Runs the full graph with mocked LLM calls. Verifies that state fields
    accumulate correctly through all four nodes and the final state shape
    matches the expected schema.
    """

    def test_full_graph_produces_decision(self):
        from agent.graph import build_graph

        classify_resp = MagicMock()
        classify_resp.content = json.dumps({"track": "title_iv", "reason": "test"})

        decide_resp = MagicMock()
        decide_resp.content = json.dumps({
            "outcome": "eligible",
            "rationale": "All criteria met.",
            "citations": ["34_CFR_668.32(a)"],
            "missing_information": [],
        })

        with patch("agent.nodes._llm") as mock_llm_factory:
            mock_llm_factory.return_value.invoke.side_effect = [classify_resp, decide_resp]

            graph = build_graph()
            final = graph.invoke({
                "query": "Is this applicant eligible?",
                "applicant": {
                    "citizenship": "us_citizen",
                    "enrollment_status": "full_time",
                    "sap_status": "meeting",
                    "prior_default": False,
                    "program_type": "undergraduate_degree",
                },
            })

        assert "decision" in final
        assert final["decision"]["outcome"] in {"eligible", "ineligible", "human_review"}
        assert "trace" in final
        assert len(final["trace"]) == 4  # one entry per node
        assert final["track"] == "title_iv"
        assert len(final["retrieved_rules"]) > 0
