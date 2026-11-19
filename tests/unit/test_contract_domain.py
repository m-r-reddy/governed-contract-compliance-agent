"""Unit tests for contract domain entities and retrieval port contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.context import TenantContext
from src.domain.contract import (
    ContractChunk,
    ContractMilestone,
    ContractSearchQuery,
    ContractTerms,
    RateCardEntry,
    RetrievedClause,
)
from src.domain.invoice import DateRange
from src.ports.retrieval import ContractRetrieverProtocol


def test_contract_terms_active_window_and_rate_card() -> None:
    terms = ContractTerms(
        tenant_id="tenant_acme",
        contract_id="MSA-2026-001",
        vendor_id="VEND-CLOUD-01",
        title="Master Cloud Advisory Services Agreement",
        department_acl=["procurement", "legal"],
        effective_window=DateRange(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        ),
        approved_rate_card={
            "Senior Cloud Architect": RateCardEntry(
                role_title="Senior Cloud Architect",
                max_hourly_rate=Decimal("150.00"),
            )
        },
        milestones=[
            ContractMilestone(
                milestone_id="MS-01",
                description="Phase 1 Cloud Landing Zone",
                capped_amount=Decimal("25000.00"),
            )
        ],
    )

    assert terms.is_active_on(date(2026, 6, 15)) is True
    assert terms.is_active_on(date(2027, 1, 1)) is False
    assert (
        terms.approved_rate_card["Senior Cloud Architect"].max_hourly_rate
        == Decimal("150.00")
    )


def test_contract_search_query_enforces_fusion_weights_sum_to_one() -> None:
    valid_query = ContractSearchQuery(
        query_text="Senior Cloud Architect hourly rate PO_10928",
        vendor_id="VEND-CLOUD-01",
        dense_weight=Decimal("0.60"),
        sparse_weight=Decimal("0.40"),
    )
    assert valid_query.top_k == 5

    with pytest.raises(ValidationError, match="must equal 1.00"):
        ContractSearchQuery(
            query_text="Rate card check",
            vendor_id="VEND-CLOUD-01",
            dense_weight=Decimal("0.70"),
            sparse_weight=Decimal("0.50"),
        )


def test_in_memory_retriever_satisfies_protocol() -> None:
    class FakeRetriever:
        async def retrieve_clauses(
            self,
            query: ContractSearchQuery,
            context: TenantContext,
        ) -> list[RetrievedClause]:
            chunk = ContractChunk(
                chunk_id="chk_01",
                tenant_id=context.tenant_id,
                contract_id="MSA-2026-001",
                vendor_id=query.vendor_id,
                department_acl=context.department_acl,
                section_header="Section 4.1 - Rate Card",
                clause_type="rate_card",
                chunk_index=0,
                content="Senior Cloud Architect: $150.00/hr",
            )
            return [RetrievedClause(chunk=chunk, rrf_score=0.032)]

    retriever = FakeRetriever()
    assert isinstance(retriever, ContractRetrieverProtocol)
