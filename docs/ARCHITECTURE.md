# System Architecture & Multi-Client Evolution Strategy

## 1. Enterprise Problem Statement

Global enterprises routinely lose **3% to 5% of total vendor spend** to contract non-compliance and invoice leakage[span_4](start_span)[span_4](end_span). These losses occur in the gap between unstructured legal agreements—Master Services Agreements (MSAs), Statements of Work (SOWs), and rate card addenda—and structured Accounts Payable / ERP ledgers (SAP, NetSuite, Coupa)[span_5](start_span)[span_5](end_span)[span_6](start_span)[span_6](end_span).

### Specific Failure Modes Addressed
1. **Rate Card Inflation:** Vendors billing senior/principal hourly rates above contracted SOW caps (e.g., billing `$185/hr` against an approved `$150/hr` ceiling)[span_7](start_span)[span_7](end_span).
2. **Scope & Deliverable Drift:** Line items billed for out-of-scope services or unapproved travel/expense surcharges[span_8](start_span)[span_8](end_span).
3. **Purchase Order (PO) Exhaustion & Duplicate Billing:** Invoices exceeding remaining committed PO balances or re-billing identical deliverables across billing periods[span_9](start_span)[span_9](end_span).
4. **Manual Audit Bottlenecks:** Legal and procurement analysts manually cross-referencing multi-page PDFs against ERP records, creating multi-week approval delays.

### Why Naive LLM Implementations Fail in Production
* **Uncontrolled Egress & Vendor Lock-In:** Direct SDK calls from application code to model providers prevent centralized spend caps, fallback routing, and PII governance[span_10](start_span)[span_10](end_span)[span_11](start_span)[span_11](end_span).
* **Cross-Department & Cross-Tenant Data Leakage:** Standard vector similarity search retrieves contract clauses without verifying user identity or department entitlements[span_12](start_span)[span_12](end_span)[span_13](start_span)[span_13](end_span).
* **Non-Deterministic ERP Side Effects:** Linear prompt chains risk executing duplicate or hallucinated ERP payment updates during network retries or ambiguous edge cases[span_14](start_span)[span_14](end_span).

---

## 2. Initial Architectural Baseline (Iteration 1: Single-Organization Governance)

We start with a **modular, five-plane architecture** designed so every external boundary—ingress identity, model egress, document retrieval, tool execution, and durable state—is strictly isolated behind typed interfaces[span_15](start_span)[span_15](end_span)[span_16](start_span)[span_16](end_span):

1. **Ingress & Identity Boundary (API Gateway):** Authenticates users via OAuth 2.0 / OIDC (`Okta` / `Entra ID`) and extracts verified identity and department claims (`["legal"]`, `["procurement"]`, `["engineering"]`)[span_17](start_span)[span_17](end_span)[span_18](start_span)[span_18](end_span).
2. **Egress AI Gateway (`LiteLLM Proxy`):** All LLM inference and embedding calls route through a centralized proxy enforcing cost-center budgets, Redis semantic caching, PII filtering, and provider failover[span_19](start_span)[span_19](end_span).
3. **ACL-Aware Hybrid RAG Engine (`pgvector` + `BM25`):** Stores contract clauses in PostgreSQL with `pgvector` and enforces **early-binding SQL `WHERE` filters** on department claims prior to hybrid vector/lexical retrieval and Cross-Encoder reranking[span_20](start_span)[span_20](end_span)[span_21](start_span)[span_21](end_span).
4. **Deterministic Tool Plane (`FastMCP` + ERP Connector):** Exposes read/write ERP operations via Model Context Protocol (`FastMCP`) guarded by Pydantic v2 contracts, input sanitization, and an idempotency register[span_22](start_span)[span_22](end_span)[span_23](start_span)[span_23](end_span).
5. **Durable State Runtime (`LangGraph` + `PostgresSaver`):** Manages compliance workflow state transitions with PostgreSQL checkpoint persistence and asynchronous Human-in-the-Loop (HITL) interrupts for discrepancies or invoices exceeding `$500`[span_24](start_span)[span_24](end_span)[span_25](start_span)[span_25](end_span).

---

## 3. Multi-Client Scaling Roadmap (Future Iterations)

Starting with clean plane separation allows the platform to scale from a single enterprise deployment to a multi-client B2B architecture without rewriting core agent logic:

### Iteration 2: Multi-Tenant Data & Identity Isolation
* **Tenant-Scoped Metadata & Row-Level Security (RLS):** Extend the early-binding SQL `WHERE` filter from `department_acl` to composite `(tenant_id, department_acl)` keys backed by PostgreSQL Row-Level Security policies[span_26](start_span)[span_26](end_span)[span_27](start_span)[span_27](end_span).
* **Per-Client Cryptographic & Vector Partitioning:** Isolate client contract corpora via tenant-partitioned tables or dedicated schemas in PostgreSQL while sharing the stateless retrieval service.

### Iteration 3: Per-Client Egress Governance & Model Policies
* **Tenant Virtual Keys & Spend Caps:** Provision isolated virtual API keys and rate limits per client inside `LiteLLM Proxy`, enabling strict per-client cost attribution and chargeback telemetry[span_28](start_span)[span_28](end_span)[span_29](start_span)[span_29](end_span)[span_30](start_span)[span_30](end_span).
* **Client-Specific Model Routing & BYOK:** Allow regulated enterprise clients to route traffic to dedicated Azure OpenAI / AWS Bedrock endpoints or Bring-Your-Own-Key (BYOK) vaults via declarative gateway routing rules[span_31](start_span)[span_31](end_span).

### Iteration 4: Pluggable ERP Connectors & Custom Policy Engines
* **Adapter Pattern on FastMCP:** Swap the initial Mock ERP backend for client-specific SAP S/4HANA, NetSuite, or Coupa adapters behind identical FastMCP tool schemas[span_32](start_span)[span_32](end_span)[span_33](start_span)[span_33](end_span).
* **Declarative Approval Thresholds:** Externalize the `$500` HITL interrupt threshold and variance tolerances into per-client policy configurations evaluated dynamically by the `LangGraph` state machine[span_34](start_span)[span_34](end_span)[span_35](start_span)[span_35](end_span).