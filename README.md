
# Governed Contract Compliance Agent (`governed-contract-compliance-agent`)

An enterprise-grade agentic compliance and financial reconciliation platform designed to eliminate vendor invoice leakage (typically 3–5% of enterprise spend) by auditing incoming invoices against Master Services Agreements (MSAs), Statements of Work (SOWs), and live ERP Purchase Order ledgers[span_0](start_span)[span_0](end_span)[span_1](start_span)[span_1](end_span).

Built around strict architectural governance boundaries: **Egress AI Gateway routing**, **Early-Binding ACL Hybrid RAG**, **Idempotent MCP Tool Execution**, **Durable State Checkpointing**, and **Asynchronous Human-in-the-Loop (HITL) Approval Gates**[span_2](start_span)[span_2](end_span)[span_3](start_span)[span_3](end_span).

---

## 1. Enterprise Problem & Architectural Goals

Enterprise procurement and legal teams lose significant capital to subtle contract non-compliance—rate card inflation, out-of-scope deliverables, duplicate billing across periods, and Purchase Order (PO) balance overruns[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span). Naive LLM wrappers fail in production due to vendor lock-in, unmonitored token spend, cross-department data leakage in RAG, and non-deterministic ERP side effects[span_6](start_span)[span_6](end_span).

### Core Architectural Pillars
1. **Enterprise AI Gateway (Egress Governance):** Decouples agent logic from model providers via LiteLLM Proxy, enforcing virtual API key spend caps, dynamic model routing, Redis semantic caching, PII redaction, and multi-provider fallbacks[span_7](start_span)[span_7](end_span)[span_8](start_span)[span_8](end_span).
2. **ACL-Aware Hybrid RAG Engine:** Combines dense vector retrieval (`pgvector`) with lexical search (`BM25`) and Cross-Encoder reranking, strictly scoped by pre-retrieval identity/department SQL `WHERE` filters (`Okta` / `Entra ID` JWT claims)[span_9](start_span)[span_9](end_span)[span_10](start_span)[span_10](end_span)[span_11](start_span)[span_11](end_span).
3. **FastMCP Tool Plane & Mock ERP:** Exposes Purchase Orders, vendor statuses, and ledger rate cards over the Model Context Protocol (`FastMCP`) with Pydantic v2 schema validation, input sanitization, and an idempotency register for exactly-once state mutations[span_12](start_span)[span_12](end_span)[span_13](start_span)[span_13](end_span)[span_14](start_span)[span_14](end_span)[span_15](start_span)[span_15](end_span).
4. **Durable Agentic Orchestration (`LangGraph`):** Persists graph execution state in PostgreSQL (`PostgresSaver`) and enforces asynchronous HITL interrupt gates for discrepancies or transactions exceeding `$500`[span_16](start_span)[span_16](end_span)[span_17](start_span)[span_17](end_span)[span_18](start_span)[span_18](end_span).
5. **Empirical Evaluation & Distributed Tracing:** Automated CI/CD evaluation suite (`DeepEval` / `Ragas`) benchmarked against a 30-scenario golden dataset (clean matches, financial discrepancies, and adversarial prompt injections) paired with `Langfuse` observability[span_19](start_span)[span_19](end_span)[span_20](start_span)[span_20](end_span)[span_21](start_span)[span_21](end_span).

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

The end-to-end execution flow from invoice submission and JWT claim extraction through ACL-filtered retrieval, ERP reconciliation, asynchronous HITL suspension, and idempotent payment commit[span_22](start_span)[span_22](end_span)[span_23](start_span)[span_23](end_span)[span_24](start_span)[span_24](end_span):

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

Key architectural trade-offs and security boundaries are documented under `docs/adr/`[span_25](start_span)[span_25](end_span):

* **[ADR-001](docs/adr/ADR-001.md):** *Model Egress Gateway Architecture & Ingress Isolation* — Separating client ingress (`Kong`/`APIM`) from model egress (`LiteLLM Proxy`) for cost attribution, semantic caching, and provider failover[span_26](start_span)[span_26](end_span)[span_27](start_span)[span_27](end_span).
* **[ADR-002](docs/adr/ADR-002.md):** *Document-Level ACL Enforcement & Early-Binding Retrieval* — Enforcing department-level identity claims directly inside SQL `WHERE` clauses prior to vector/BM25 similarity scoring[span_28](start_span)[span_28](end_span)[span_29](start_span)[span_29](end_span).
* **[ADR-003](docs/adr/ADR-003.md):** *Durable State Checkpointing, Idempotency & HITL Gates* — Eliminating long-lived HTTP hangs via `PostgresSaver` checkpointing and guaranteeing exactly-once ERP writes[span_30](start_span)[span_30](end_span)[span_31](start_span)[span_31](end_span).

---

## 6. Target Production SLAs & Evaluation Benchmarks

All releases are evaluated against a 30-scenario golden dataset (`15` clean matches, `10` financial discrepancies, `5` adversarial prompt injections)[span_32](start_span)[span_32](end_span):

| Metric | Target SLA | Verification Method |
| :--- | :--- | :--- |
| **Discrepancy Detection Accuracy** | `> 95%`[span_33](start_span)[span_33](end_span) | Golden dataset assertion suite[span_34](start_span)[span_34](end_span) |
| **Faithfulness / Groundedness** | `0%` financial hallucination[span_35](start_span)[span_35](end_span) | DeepEval / Ragas RAG Triad[span_36](start_span)[span_36](end_span)[span_37](start_span)[span_37](end_span) |
| **ACL Isolation / Data Leakage** | `0%` unauthorized retrieval[span_38](start_span)[span_38](end_span) | Multi-tenant department ACL tests[span_39](start_span)[span_39](end_span) |
| **End-to-End Latency** | `p50 < 2.5s`, `p95 < 6.0s`[span_40](start_span)[span_40](end_span) | Langfuse distributed trace spans[span_41](start_span)[span_41](end_span)[span_42](start_span)[span_42](end_span) |
| **Cost Attribution** | `100%` per cost-center[span_43](start_span)[span_43](end_span) | LiteLLM virtual key telemetry[span_44](start_span)[span_44](end_span)[span_45](start_span)[span_45](end_span) |

---

## 7. Quickstart & Developer Workflow

### Prerequisites
* Python `3.12+` & [`uv`](https://docs.astral.sh/uv/)[span_46](start_span)[span_46](end_span)
* Docker Desktop or OrbStack (`docker compose`)[span_47](start_span)[span_47](end_span)

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
