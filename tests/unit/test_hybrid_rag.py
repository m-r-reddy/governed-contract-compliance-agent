"""Unit tests for Markdown contract chunking and ACL-aware hybrid RAG retrieval."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config import GatewaySettings
from src.core.exceptions import TenantAccessDeniedError
from src.domain.context import TenantContext
from src.domain.contract import ContractSearchQuery, ContractTerms
from src.domain.invoice import DateRange
from src.ports.retrieval import ContractIndexerProtocol, ContractRetrieverProtocol
from src.rag.chunker import MarkdownContractChunker
from src.rag.pgvector_retriever import PgVectorHybridRetriever

SAMPLE_MSA_MARKDOWN = """
# Master Services Agreement (MSA-2026-001)

## Section 1 - Scope of Services
Vendor shall provide cloud architecture advisory and landing zone engineering.

## Section 2 - Approved Rate Card
- Senior Cloud Architect: $150.00/hr maximum
- Platform Engineer: $125.00/hr maximum

## Section 3 - Payment Terms
Invoices must reference PO_10928 and are payable Net 30 upon milestone acceptance.
"""


def _sample_terms(tenant_id: str = "tenant_acme") -> ContractTerms:
    return ContractTerms(
        tenant_id=tenant_id,
        contract_id="MSA-2026-001",
        vendor_id="VEND-CLOUD-01",
        title="Cloud Advisory MSA",
        department_acl=["procurement", "legal"],
        effective_window=DateRange(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        ),
    )


def test_markdown_chunker_preserves_headers_and_clause_types() -> None:
    chunker = MarkdownContractChunker()
    ctx = TenantContext(tenant_id="tenant_acme", department_acl=["procurement"])
    chunks = chunker.chunk_contract(_sample_terms("tenant_acme"), SAMPLE_MSA_MARKDOWN, ctx)

    assert len(chunks) == 3
    assert chunks[0].section_header == "Section 1 - Scope of Services"
    assert chunks[0].clause_type == "scope"
    assert chunks[1].section_header == "Section 2 - Approved Rate Card"
    assert chunks[1].clause_type == "rate_card"
    assert chunks[2].section_header == "Section 3 - Payment Terms"
    assert chunks[2].clause_type == "payment_terms"
    assert all(c.tenant_id == "tenant_acme" for c in chunks)


def test_markdown_chunker_blocks_cross_tenant_mismatch() -> None:
    chunker = MarkdownContractChunker()
    wrong_ctx = TenantContext(tenant_id="tenant_evil", department_acl=["procurement"])
    with pytest.raises(TenantAccessDeniedError):
        chunker.chunk_contract(_sample_terms("tenant_acme"), SAMPLE_MSA_MARKDOWN, wrong_ctx)


@pytest.mark.asyncio
async def test_pgvector_hybrid_retriever_binds_early_acl_predicates() -> None:
    executed_queries: list[tuple[str, object]] = []

    mock_cursor = AsyncMock()

    async def fake_execute(sql: str, params: object = None) -> None:
        executed_queries.append((sql, params))

    mock_cursor.execute.side_effect = fake_execute
    mock_cursor.fetchall.return_value = [
        {
            "chunk_id": "MSA-2026-001:chk:0001",
            "tenant_id": "tenant_acme",
            "contract_id": "MSA-2026-001",
            "vendor_id": "VEND-CLOUD-01",
            "department_acl": ["procurement", "legal"],
            "section_header": "Section 2 - Approved Rate Card",
            "clause_type": "rate_card",
            "chunk_index": 1,
            "content": "Senior Cloud Architect: $150.00/hr maximum",
            "metadata_json": {"contract_title": "Cloud Advisory MSA"},
            "dense_score": 0.91,
            "sparse_score": 0.45,
            "rrf_score": 0.0325,
        }
    ]

    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    cursor_cm.__aexit__ = AsyncMock(return_value=None)

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = cursor_cm
    mock_conn.transaction.return_value = tx_cm

    mock_embed_client = AsyncMock()
    mock_embed_client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.01] * 1536)]
    )

    retriever = PgVectorHybridRetriever(
        connection=mock_conn,
        gateway_settings=GatewaySettings(),
        embedding_client=mock_embed_client,
    )
    assert isinstance(retriever, ContractRetrieverProtocol)
    assert isinstance(retriever, ContractIndexerProtocol)

    ctx = TenantContext(
        tenant_id="tenant_acme",
        user_id="bob@acme.com",
        department_acl=["procurement"],
    )
    query = ContractSearchQuery(
        query_text="Senior Cloud Architect hourly rate",
        vendor_id="VEND-CLOUD-01",
        top_k=3,
        dense_weight=Decimal("0.50"),
        sparse_weight=Decimal("0.50"),
    )

    results = await retriever.retrieve_clauses(query, ctx)

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "MSA-2026-001:chk:0001"
    assert results[0].rerank_score is not None

    # Verify RLS tenant setting and early-binding ACL SQL parameters were executed
    assert executed_queries[0][1] == ("tenant_acme",)
    assert "hnsw.iterative_scan" in executed_queries[1][0]
    hybrid_params = executed_queries[2][1]
    assert isinstance(hybrid_params, dict)
    assert hybrid_params["tenant_id"] == "tenant_acme"
    assert hybrid_params["department_acl"] == ["procurement"]
