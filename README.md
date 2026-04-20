# eligibility-agent

A minimal, production-shaped reference implementation of a **LangGraph agent** that uses **MCP tools** to make eligibility decisions over regulated documents.

Clone, install, add an API key, run it. Under five minutes. No Docker, no database, no UI scaffolding.

```bash
git clone <this-repo>
cd eligibility-agent
pip install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY
python -m agent.run --query "Is this applicant eligible for Title IV aid?" \
                    --applicant examples/applicant_eligible.json --verbose
```

---

## Why this exists

Most agent examples are either toy chatbots or framework demos that stop at "hello world." Regulated domains — financial aid, healthcare intake, KYC, insurance underwriting — need something in between: a graph that's small enough to read in one sitting but shaped like what actually ships.

This repo is that middle. It's built around a realistic pattern I've run in production (Title IV federal financial aid compliance), stripped to its structural bones and anonymized. The domain here is **eligibility routing**: take an intake payload, classify it to a regulatory track, retrieve the applicable rules via an MCP tool, and emit a structured decision with citations.

The domain is a vehicle. The point is the shape of the graph and the wiring of the tool.

## Architecture

```
  ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌────────┐
  │ intake  │───▶│ classify │───▶│ retrieve │───▶│ decide │───▶ decision
  └─────────┘    └──────────┘    └────┬─────┘    └────────┘
                                      │
                                      ▼
                              ┌───────────────┐
                              │  MCP server   │
                              │ fetch_regs()  │
                              └───────────────┘
```

Four nodes, one tool call, one LLM reasoning step per node that needs it.

| Node | Responsibility | LLM? | External I/O? |
|---|---|---|---|
| `intake` | Normalize and validate the applicant payload | No | No |
| `classify` | Pick the regulatory track (Title IV / state / institutional) | Yes (small) | No |
| `retrieve` | Fetch applicable rules via MCP | No | **Yes — MCP** |
| `decide` | Reason over rules + applicant, emit structured decision | Yes | No |

State flows through a single `TypedDict` merged by LangGraph between nodes. Every node appends to `state["trace"]`, so you can observe execution without wiring a tracing vendor.

## Design decisions

**Why LangGraph over a straight LangChain chain.** Chains are linear by default and conflate orchestration with prompt logic. Graphs separate them: each node is a pure `(state) → partial_state` function, independently testable and swappable. When `retrieve` needs to become two parallel retrievals, or `decide` needs a conditional edge back to `retrieve` for follow-up rules, that's a three-line change to the graph definition. In a chain it's a rewrite.

**Why MCP for the tool layer.** The alternative is hard-coding a retrieval client inside the node. MCP makes the regulation store a separate, versionable, reusable service — the same server can back a different agent, a Slack bot, or a direct API consumer. Decoupling matters most in regulated work, where the rule source is the thing auditors care about.

**Why a local fallback alongside the MCP client.** Reference repos should run end-to-end on a clean clone. `agent/tools.py` ships a small in-process rules fixture; if you set `MCP_SERVER_URL`, it calls a real server instead. Same function signature, same return shape. The fallback is how the demo ships in five minutes; the MCP path is how it scales.

**Why GPT-4o as default, Claude as a one-line swap.** Model-agnostic is a credibility marker. The LLM factory in `agent/nodes.py` is the only place the provider is named. Comment above it shows the Claude swap via `langchain-anthropic`.

**What I deliberately left out.** No vector DB — retrieval is keyed on track, not semantic search, because eligibility rules are finite and enumerable per track. No streaming UI — this is a reference agent, not a product. No LangSmith tracing — the `trace` list in state is enough to debug at this size; wire LangSmith in when you have more than four nodes.

## What's in here

```
eligibility-agent/
├── README.md
├── Makefile                          ← make install / demo / test / server
├── agent/
│   ├── graph.py                      ← LangGraph state graph (the topology)
│   ├── nodes.py                      ← four node functions + LLM factory
│   ├── tools.py                      ← MCP client + local fallback
│   └── run.py                        ← CLI entry point
├── mcp_server/
│   └── server.py                     ← MCP server exposing fetch_regulations()
├── tests/
│   └── test_agent.py                 ← unit + integration tests (no API key needed)
├── examples/
│   ├── applicant_eligible.json       ← clean profile → should return `eligible`
│   ├── applicant_default.json        ← prior loan default → should return `ineligible`
│   └── applicant_incomplete.json     ← missing SAP field → should return `human_review`
├── docs/
│   └── architecture.md               ← 1-page case study
├── requirements.txt
├── .env.example
└── LICENSE
```

## Running it

**Quick start via make:**

```bash
make install
make demo              # eligible applicant, local fixture
make demo-ineligible   # prior default → ineligible
make demo-incomplete   # missing SAP → human_review
```

**Or directly:**

```bash
python -m agent.run \
  --query "Is this applicant eligible for Title IV aid?" \
  --applicant examples/applicant_eligible.json \
  --verbose
```

Expected output shape:

```json
{
  "outcome": "eligible",
  "rationale": "Applicant meets citizenship (34 CFR 668.32(a)), enrollment (34 CFR 668.32(c)), and SAP (34 CFR 668.34) requirements with no prior default.",
  "citations": ["34_CFR_668.32(a)", "34_CFR_668.32(c)", "34_CFR_668.34"],
  "missing_information": []
}
```

Try all three fixtures — `applicant_default.json` should return `ineligible` citing `34_CFR_668.35`; `applicant_incomplete.json` should route to `human_review` with `sap_status` in `missing_information`.

**Run the MCP server (full round-trip):**

In one terminal:
```bash
make server
# Starting regulation MCP server on localhost:8000
```

In another:
```bash
MCP_SERVER_URL=http://localhost:8000/sse make demo
```

The agent will now call the MCP server's `fetch_regulations` tool instead of the local fixture. Same output — the decoupling is the point.

**Run the tests (no API key required):**

```bash
make test
```

LLM-dependent nodes are covered with mocked responses. The test suite completes in under two seconds and validates intake normalization, tool retrieval, error fallbacks, and full-graph state accumulation.

## Extending it

- **Add a track.** Append to `_LOCAL_RULES` in `tools.py` and extend the `CLASSIFY_SYSTEM` prompt. No graph changes required.
- **Add a node** (e.g., `audit_log`). Add the function to `nodes.py`, register it in `graph.py`, add an edge. That's it.
- **Add a conditional edge** (e.g., loop back to `retrieve` when `decide` flags missing rules). Use `graph.add_conditional_edges()` in `graph.py`.
- **Swap the LLM.** One line in `_llm()` in `nodes.py`.
- **Swap the tool.** Replace `fetch_regulations` in `tools.py`. Everything upstream is unchanged.

## What this pattern scales to

The production system this was distilled from runs the same four-node shape with: a vector-backed retrieval tool instead of the fixture, three parallel retrieval nodes with a join, a conditional edge from `decide` back to `retrieve` for follow-up, Supabase-backed audit logging as a terminal node, and structured-output validation via Pydantic. The topology in `graph.py` is the seed of all of that — it's not a toy you throw away when you go to production; it's what the production graph looks like before you add the rest of the lines.

## License

MIT. Use it, fork it, build on it.

---

*Built by [Jay Burgess](https://github.com/) — Principal AI Systems Architect. This repo is a sanitized, domain-agnostic reference distilled from production agentic compliance work.*
