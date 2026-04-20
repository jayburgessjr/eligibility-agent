# Architecture Case Study: Eligibility Routing Agent

## Problem

Regulated eligibility decisions — federal financial aid, healthcare enrollment, insurance underwriting — share a structural problem: the rules are codified, the inputs are messy, and the audit trail matters as much as the answer. Traditional rule engines are brittle to input variation; pure LLM prompts are too opaque to defend to auditors. The middle path is an agent that **routes** through explicit stages, each observable, each swappable.

## Approach

A four-node LangGraph agent, with the only external I/O quarantined to a single node that calls an MCP server.

```
intake → classify → retrieve → decide → END
                        │
                        └─── MCP: fetch_regulations(track, query)
```

| Stage | What it does | Why it's a separate node |
|---|---|---|
| **intake** | Normalize applicant payload | Defensive boundary — dirty input never reaches the LLM |
| **classify** | Pick regulatory track | Small LLM call that gates corpus selection |
| **retrieve** | Fetch applicable rules via MCP | Only node with external I/O — isolates determinism boundary |
| **decide** | Reason over rules + applicant | Structured JSON output with citations |

## Key decisions

**LangGraph over LangChain chains.** Graph topology makes each node independently testable. When the real system needed a conditional edge from `decide` back to `retrieve` for follow-up rules, it was a three-line change.

**MCP for the rule store.** The regulation source is the thing auditors care about. Making it a separate MCP server means the same rule corpus can back multiple agents, a Slack bot, or a direct API — and it can be versioned and audited independently of the agent code.

**Conservative decisioning.** The `decide` node is prompted to prefer `human_review` over guessing. In regulated work, a wrong `eligible` is worse than a slow `escalate`.

**Structured output with citations.** Every decision carries the specific regulation IDs it relied on. This is the audit trail — without it, the agent is unusable in production regardless of accuracy.

## What this pattern scales to

The production system this is distilled from adds: vector-backed retrieval, parallel retrieval nodes with a join, a conditional edge for follow-up rules, Pydantic-validated structured output, and Supabase-backed audit logging as a terminal node. The four-node topology in this repo is the seed — it's what the production graph looks like before the operational concerns are layered on.

## What this pattern does *not* solve

- **Ambiguous regulations.** If the source rules are contradictory or vague, the agent will correctly escalate to `human_review`, but it won't resolve the ambiguity. That's a policy problem, not an agent problem.
- **Adversarial input.** This pattern assumes cooperative inputs. KYC or fraud-detection use cases need an adversarial layer on top.
- **Low-latency use cases.** Four sequential LLM-involving nodes is ~3–6s end-to-end. Real-time applications need a different shape.

## References

- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [34 CFR Part 668 — Student Assistance General Provisions](https://www.ecfr.gov/current/title-34/subtitle-B/chapter-VI/part-668) (public regulations referenced in the demo fixture)
