# Governed Contract Compliance Agent (`governed-contract-compliance-agent`)

An enterprise-grade agentic compliance and financial reconciliation platform designed to eliminate vendor invoice leakage (typically 3–5% of enterprise spend) by auditing incoming invoices against Master Services Agreements (MSAs), Statements of Work (SOWs), and live ERP Purchase Order ledgers.

Built around strict architectural governance boundaries: **Egress AI Gateway routing**, **Early-Binding ACL Hybrid RAG**, **Idempotent MCP Tool Execution**, **Durable State Checkpointing**, and **Asynchronous Human-in-the-Loop (HITL) Approval Gates**.

---

## 1. Enterprise Problem & Architectural Goals

Enterprise procurement and legal teams lose significant capital to subtle contract non-compliance—rate card inflation, out-of-scope deliverables, duplicate billing across periods, and Purchase Order (PO) balance overruns. Naive LLM wrappers fail in production due to vendor lock-in, unmonitored token spend, cross-department data leakage in RAG, and non-deterministic ERP side effects.

### Core Architectural Pillars
1. **Enterprise AI Gateway (Egress Governance):** Decouples agent logic from model providers via LiteLLM Proxy, enforcing virtual API key spend caps, dynamic model routing, Redis semantic caching, PII redaction, and multi-provider fallbacks.
2. **ACL-Aware Hybrid RAG Engine:** Combines dense vector retrieval (`pgvector`) with lexical search (`BM25`) and Cross-Encoder reranking, strictly scoped by pre-retrieval identity/department SQL `WHERE` filters (`Okta` / `Entra ID` JWT claims).
3. **FastMCP Tool Plane & Mock ERP:** Exposes Purchase Orders, vendor statuses, and ledger rate cards over the Model Context Protocol (`FastMCP`) with Pydantic v2 schema validation, input sanitization, and an idempotency register for exactly-once state mutations.
4. **Durable Agentic Orchestration (`LangGraph`):** Persists graph execution state in PostgreSQL (`PostgresSaver`) and enforces asynchronous HITL interrupt gates for discrepancies or transactions exceeding `$500`.
5. **Empirical Evaluation & Distributed Tracing:** Automated CI/CD evaluation suite (`DeepEval` / `Ragas`) benchmarked against a 30-scenario golden dataset (clean matches, financial discrepancies, and adversarial prompt injections) paired with `Langfuse` observability.

---

## 2. High-Level System Architecture

```text
[ Enterprise User / Client Application ]
                │
                ▼ (OAuth 2.0 / Entra ID / Okta JWT)
┌──────────────────────────────────────────────────────────┐
│      ENTERPRISE API GATEWAY (Kong / Azure APIM)          │
│   Client Ingress · User Authentication · Rate Limiting   │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│         AGENTIC ORCHESTRATION & RUNTIME (Python)         │
│  LangGraph · Durable Checkpointing · HITL Approvals      │
│  ┌───────────────────────┬────────────────────────────┐  │
│  │ State Machine Logic   │ Idempotency Key Manager    │  │
│  └───────────┬───────────┴─────────────┬──────────────┘  │
└──────────────┼─────────────────────────┼─────────────────┘
               │                         │
     (Model Egress Calls)         (Tool Calls via MCP)
               │                         │
               ▼                         ▼
┌──────────────────────────────┐ ┌─────────────────────────┐
│     ENTERPRISE AI GATEWAY    │ │   ENTERPRISE TOOL &     │
│   (LiteLLM / Portkey / Kong) │ │      DATA PLANE         │
│ ──────────────────────────── │ │ ─────────────────────── │
│ • Cost & Token Tracking      │ │ • FastMCP Server        │
│ • Dynamic Model Routing      │ │ • Mock ERP (SAP/NetSuite│
│ • Guardrails & PII Filter    │ │ • ACL-Aware RAG Engine  │
│ • Provider Fallback Engine   │ │   (pgvector + BM25)     │
└──────────────┬───────────────┘ └─────────────────────────┘
               │
               ▼
[ External Model Providers: OpenAI / Anthropic / Bedrock ]
```

---

## 3. End-State Runtime Sequence Diagram

The end-to-end execution flow from invoice submission and JWT claim extraction through ACL-filtered retrieval, ERP reconciliation, asynchronous HITL suspension, and idempotent payment commit:

```text
User / Client       API Gateway       LangGraph         LiteLLM Proxy       ACL-Aware RAG       FastMCP / ERP        Postgres DB
 (Okta JWT)         (Ingress)       (Orchestrator)       (AI Egress)       (pgvector+BM25)       (Tool Plane)       (Checkpoints)
     │                  │                 │                   │                   │                   │                   │
     │──1. Submit Inv──▶│                 │                   │                   │                   │                   │
     │   (PDF + JWT)    │                 │                   │                   │                   │                   │
     │                  │──2. Auth & ────▶│                   │                   │                   │                   │
     │                  │  Extract Claims │                   │                   │                   │                   │
     │                  │                 │──3. Save Initial─▶│───────────────────│───────────────────│──────────────────▶│
     │                  │                 │  State Checkpoint │                   │                   │                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──4. Parse Invoice─▶│                  │                   │                   │
     │                  │                 │  (Pydantic Schema)│                   │                   │                   │
     │                  │                 │                   │──5. Check Redis ──│                   │                   │
     │                  │                 │                   │  Semantic Cache / │                   │                   │
     │                  │                 │                   │  Route to LLM     │                   │                   │
     │                  │                 │◀──Structured JSON─│                   │                   │                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──6. Retrieve MSA/SOW Clauses─────────▶│                   │                   │
     │                  │                 │  (Early-Binding ACL: WHERE dept=JWT)  │                   │                   │
     │                  │                 │                   │                   │──Hybrid Search +  │                   │
     │                  │                 │                   │                   │  Cross-Encoder    │                   │
     │                  │                 │◀──Approved Rate Card & Terms──────────│                   │                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──7. Query PO & Vendor Status─────────────────────────────▶│                   │
     │                  │                 │  (Validated FastMCP Tool Call)        │                   │                   │
     │                  │                 │◀──PO Balance & Ledger Status──────────────────────────────│                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──8. Reconcile ───▶│                   │                   │                   │
     │                  │                 │  (Compare Inv vs. │                   │                   │                   │
     │                  │                 │   MSA & PO)       │                   │                   │                   │
     │                  │                 │◀──Audit Verdict───│                   │                   │                   │
     │                  │                 │  (Match / Flag)   │                   │                   │                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──9. Persist State & Check HITL Policy─│───────────────────│──────────────────▶│
     │                  │                 │                   │                   │                   │                   │
     │      ╔═══════════╧═════════════════╧═══════════════════╧═══════════════════╧═══════════════════╧═══════════╗       │
     │      ║  BRANCH: Discrepancy Found OR Invoice Amount > $500 (Asynchronous HITL Interrupt Gate)             ║       │
     │      ╚═══════════╤═════════════════╤═══════════════════╤═══════════════════╤═══════════════════╤═══════════╝       │
     │                  │                 │                   │                   │                   │                   │
     │◀─10. PAUSE: Awaiting Human Review──│ (Thread suspended in PostgresSaver; zero compute held)    │                   │
     │                  │                 │                   │                   │                   │                   │
     │──11. Approve / ──▶│──Resume────────▶│                   │                   │                   │                   │
     │   Reject Verdict │  Thread ID      │──12. Hydrate State from Checkpoint────│───────────────────│──────────────────▶│
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──13. Update ERP Payment Status───────────────────────────▶│                   │
     │                  │                 │  (With Idempotency Key: inv_10928_v1) │                   │──Check/Write      │
     │                  │                 │                   │                   │                   │  Idempotency Reg  │
     │                  │                 │◀──200 OK (Committed)──────────────────────────────────────│                   │
     │                  │                 │                   │                   │                   │                   │
     │                  │                 │──14. Commit Final Checkpoint──────────│───────────────────│──────────────────▶│
     │◀─15. Final Compliance Audit Report─│                   │                   │                   │                   │
     │                  │                 │                   │                   │                   │                   │
```

---

## 4. Repository Structure

```text
governed-contract-compliance-agent/
├── config/                  # Declarative LiteLLM gateway & container configurations
├── data/                    # Synthetic vendor invoices, sample MSAs/SOWs, golden eval fixtures
├── docs/
│   └── adr/                 # Architecture Decision Records (ADR-001 through ADR-003)
├── src/
│   ├── gateway/             # LiteLLM egress client, cost attribution & fallback wrappers
│   ├── ingestion/           # Pydantic v2 schemas & deterministic invoice/contract parsers
│   ├── rag/                 # ACL-filtered pgvector + BM25 hybrid search & reranker
│   └── tools/               # FastMCP server, Mock ERP ledger, & idempotency manager
├── tests/                   # Unit, integration, and adversarial security test suites
├── docker-compose.yml       # Local stack: PostgreSQL 16 (pgvector), Redis, LiteLLM Proxy
├── pyproject.toml           # Project manifest & dependencies (managed via uv)
└── uv.lock                  # Deterministic dependency lockfile
```

---

## 5. Architecture Decision Records (ADRs)

Key architectural trade-offs and security boundaries are documented under `docs/adr/`:

* **[ADR-001](docs/adr/ADR-001.md):** *Model Egress Gateway Architecture & Ingress Isolation* — Separating client ingress (`Kong`/`APIM`) from model egress (`LiteLLM Proxy`) for cost attribution, semantic caching, and provider failover.
* **[ADR-002](docs/adr/ADR-002.md):** *Document-Level ACL Enforcement & Early-Binding Retrieval* — Enforcing department-level identity claims directly inside SQL `WHERE` clauses prior to vector/BM25 similarity scoring.
* **[ADR-003](docs/adr/ADR-003.md):** *Durable State Checkpointing, Idempotency & HITL Gates* — Eliminating long-lived HTTP hangs via `PostgresSaver` checkpointing and guaranteeing exactly-once ERP writes.

---

## 6. Target Production SLAs & Evaluation Benchmarks

All releases are evaluated against a 30-scenario golden dataset (`15` clean matches, `10` financial discrepancies, `5` adversarial prompt injections):

| Metric | Target SLA | Verification Method |
| :--- | :--- | :--- |
| **Discrepancy Detection Accuracy** | `> 95%` | Golden dataset assertion suite |
| **Faithfulness / Groundedness** | `0%` financial hallucination | DeepEval / Ragas RAG Triad |
| **ACL Isolation / Data Leakage** | `0%` unauthorized retrieval | Multi-tenant department ACL tests |
| **End-to-End Latency** | `p50 < 2.5s`, `p95 < 6.0s` | Langfuse distributed trace spans |
| **Cost Attribution** | `100%` per cost-center | LiteLLM virtual key telemetry |

---

## 7. Quickstart & Developer Workflow

### Prerequisites
* Python `3.12+` & [`uv`](https://docs.astral.sh/uv/)
* Docker Desktop or OrbStack (`docker compose`)

### Setup & Verification
```bash
# 1. Sync exact dependencies into isolated .venv
uv sync

# 2. Start local infrastructure (PostgreSQL 16 + pgvector, Redis, LiteLLM)
docker compose up -d

# 3. Run static analysis & unit tests
uv run ruff check .
uv run mypy src/
uv run pytest tests/
```
