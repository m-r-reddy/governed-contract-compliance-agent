"""Live PostgreSQL 16 integration tests for RLS, early-binding ACLs, and Hybrid RRF."""

from __future__ import annotations

import math
import os
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
import pytest_asyncio
from psycopg.errors import InsufficientPrivilege

from src.core.config import GatewaySettings
from src.domain.context import TenantContext
from src.domain.contract import ContractSearchQuery, ContractTerms, RateCardEntry
from src.domain.invoice import DateRange
from src.rag.pgvector_retriever import PgVectorHybridRetriever

POSTGRES_DSN = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://compliance_app:compliance_app_pass@localhost:5432/compliance_db",
)

ENGINEERING_SOW_MD = """
# Engineering Cloud Modernization SOW

## Section 1 - Infrastructure Architecture Scope
Vendor shall provide Senior Infrastructure Advisory and Kubernetes migration design.

## Section 2 - Approved Rate Card
- Principal Cloud Architect: $220.00/hr maximum
- Senior DevOps Engineer: $175.00/hr maximum

## Section 4.2(b) - Purchase Order Reference
All billing under this SOW must reference PO-88412 and Net-45 payment terms.
"""

CONFIDENTIAL_LEGAL_MSA_MD = """
# Executive M&A Legal Retainer Agreement

## Section 1 - Confidential Advisory Scope
Counsel shall advise on Project Titan acquisition diligence and regulatory filings.

## Section 2 - Approved Rate Card
- Managing Partner M&A: $850.00/hr maximum
"""


def _topic_aware_embedding(texts: list[str]) -> SimpleNamespace:
    """Produce deterministic 1536-dim orthogonal topic vectors for offline hybrid testing."""
    items = []
    for text in texts:
        lowered = text.lower()
        # Orthogonal semantic axes: [cloud/infra, legal/m&a, rate/pricing, lexical_noise]
        cloud_axis = (
            1.0
            if any(
                k in lowered
                for k in ("cloud", "infrastructure", "kubernetes", "advisory", "architect")
            )
            else 0.05
        )
        legal_axis = (
            1.0
            if any(k in lowered for k in ("titan", "acquisition", "regulatory", "counsel"))
            else 0.05
        )
        rate_axis = (
            1.0
            if any(k in lowered for k in ("rate", "hourly", "maximum", "billing"))
            else 0.05
        )
        norm = math.sqrt(cloud_axis**2 + legal_axis**2 + rate_axis**2)
        vec = [cloud_axis / norm, legal_axis / norm, rate_axis / norm] + [0.0] * 1533
        items.append(SimpleNamespace(embedding=vec))
    return SimpleNamespace(data=items)

@pytest_asyncio.fixture
async def pg_conn() -> AsyncIterator[psycopg.AsyncConnection[object]]:
    """Open an async connection as least-privilege compliance_app and clean up fixtures."""
    try:
        conn = await psycopg.AsyncConnection.connect(POSTGRES_DSN, autocommit=False)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Live compliance-postgres container not reachable: {exc}")

    yield conn

    # Clean up test contracts across both tenants under their respective RLS contexts
    for tid, cid in [
        ("tenant_alpha", "SOW-ENG-101"),
        ("tenant_alpha", "MSA-TITAN-999"),
    ]:
        async with conn.transaction(), conn.cursor() as cur:
            await cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tid,))
            await cur.execute(
                "DELETE FROM contracts WHERE tenant_id = %s AND contract_id = %s;",
                (tid, cid),
            )
    await conn.close()



@pytest.mark.asyncio
async def test_rls_and_same_vendor_department_isolation(
    pg_conn: psycopg.AsyncConnection[object],
) -> None:
    """Verify 0% leakage across tenants AND across departments for the same vendor."""
    mock_embed_client = AsyncMock()
    mock_embed_client.embeddings.create.side_effect = (
        lambda **kwargs: _topic_aware_embedding(kwargs["input"])
    )

    alpha_legal = TenantContext(
        tenant_id="tenant_alpha",
        user_id="alice.legal@alpha.com",
        department_acl=["legal", "executive"],
    )
    alpha_eng = TenantContext(
        tenant_id="tenant_alpha",
        user_id="bob.eng@alpha.com",
        department_acl=["engineering"],
    )
    beta_legal = TenantContext(
        tenant_id="tenant_beta",
        user_id="eve.legal@beta.com",
        department_acl=["legal", "executive"],
    )

    eng_terms = ContractTerms(
        tenant_id="tenant_alpha",
        contract_id="SOW-ENG-101",
        vendor_id="VEND-SHARED-01",
        title="Cloud Modernization SOW",
        department_acl=["engineering", "procurement"],
        effective_window=DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)),
        approved_rate_card={
            "Principal Cloud Architect": RateCardEntry(
                role_title="Principal Cloud Architect",
                max_hourly_rate=Decimal("220.00"),
            )
        },
    )
    legal_terms = ContractTerms(
        tenant_id="tenant_alpha",
        contract_id="MSA-TITAN-999",
        vendor_id="VEND-SHARED-01",
        title="Project Titan Legal Retainer",
        department_acl=["legal", "executive"],
        effective_window=DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)),
        approved_rate_card={
            "Managing Partner M&A": RateCardEntry(
                role_title="Managing Partner M&A",
                max_hourly_rate=Decimal("850.00"),
            )
        },
    )

    retriever = PgVectorHybridRetriever(
        connection=pg_conn,
        gateway_settings=GatewaySettings(),
        embedding_client=mock_embed_client,
    )

    assert await retriever.index_contract(eng_terms, ENGINEERING_SOW_MD, alpha_eng) == 3
    assert await retriever.index_contract(legal_terms, CONFIDENTIAL_LEGAL_MSA_MD, alpha_legal) == 2

    # 1. Engineering queries shared vendor -> sees ONLY SOW-ENG-101, zero MSA-TITAN-999 chunks
    eng_hits = await retriever.retrieve_clauses(
        ContractSearchQuery(
            query_text="Approved hourly rate card maximum",
            vendor_id="VEND-SHARED-01",
            top_k=10,
        ),
        alpha_eng,
    )
    assert len(eng_hits) == 3
    assert {hit.chunk.contract_id for hit in eng_hits} == {"SOW-ENG-101"}
    assert all("850.00" not in hit.chunk.content for hit in eng_hits)

    # 2. Tenant Beta Legal queries shared vendor -> 0% leakage blocked by tenant_id + RLS
    beta_hits = await retriever.retrieve_clauses(
        ContractSearchQuery(
            query_text="Managing Partner M&A hourly rate",
            vendor_id="VEND-SHARED-01",
            top_k=10,
        ),
        beta_legal,
    )
    assert beta_hits == []


@pytest.mark.asyncio
async def test_hybrid_bm25_exact_id_and_semantic_ranking(
    pg_conn: psycopg.AsyncConnection[object],
) -> None:
    """Verify BM25 exact identifier lookup (PO-88412) and semantic paraphrase recall."""
    mock_embed_client = AsyncMock()
    mock_embed_client.embeddings.create.side_effect = (
        lambda **kwargs: _topic_aware_embedding(kwargs["input"])
    )

    alpha_eng = TenantContext(
        tenant_id="tenant_alpha",
        user_id="bob.eng@alpha.com",
        department_acl=["engineering"],
    )
    eng_terms = ContractTerms(
        tenant_id="tenant_alpha",
        contract_id="SOW-ENG-101",
        vendor_id="VEND-SHARED-01",
        title="Cloud Modernization SOW",
        department_acl=["engineering"],
        effective_window=DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)),
    )

    retriever = PgVectorHybridRetriever(
        connection=pg_conn,
        gateway_settings=GatewaySettings(),
        embedding_client=mock_embed_client,
    )
    await retriever.index_contract(eng_terms, ENGINEERING_SOW_MD, alpha_eng)

    # Exact lexical query for PO-88412 must rank Section 4.2(b) #1 via BM25 + RRF
    lexical_hits = await retriever.retrieve_clauses(
        ContractSearchQuery(
            query_text="PO-88412 Net-45",
            vendor_id="VEND-SHARED-01",
            top_k=3,
            dense_weight=Decimal("0.30"),
            sparse_weight=Decimal("0.70"),
        ),
        alpha_eng,
    )
    assert len(lexical_hits) >= 1
    assert "4.2(b)" in lexical_hits[0].chunk.section_header
    assert lexical_hits[0].sparse_score is not None and lexical_hits[0].sparse_score > 0.0

    # Semantic paraphrase query ("Kubernetes cloud architecture consulting") ranks Section 1 #1
    semantic_hits = await retriever.retrieve_clauses(
        ContractSearchQuery(
            query_text="Kubernetes cloud architecture consulting",
            vendor_id="VEND-SHARED-01",
            top_k=3,
            dense_weight=Decimal("0.80"),
            sparse_weight=Decimal("0.20"),
        ),
        alpha_eng,
    )
    assert len(semantic_hits) >= 1
    assert "Section 1" in semantic_hits[0].chunk.section_header
    assert semantic_hits[0].dense_score is not None and semantic_hits[0].dense_score > 0.9


@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_write_with_check(
    pg_conn: psycopg.AsyncConnection[object],
) -> None:
    """Verify PostgreSQL RLS WITH CHECK blocks inserting rows for another tenant."""
    with pytest.raises(InsufficientPrivilege):
        async with pg_conn.transaction(), pg_conn.cursor() as cur:
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', 'tenant_beta', true);"
            )
            await cur.execute(
                """
                INSERT INTO contracts (
                    tenant_id, contract_id, vendor_id, title, department_acl,
                    effective_start, effective_end
                )
                VALUES ('tenant_alpha', 'SPOOF-001', 'VEND-X', 'Spoofed', ARRAY['legal'],
                        '2026-01-01', '2026-12-31');
                """
            )
