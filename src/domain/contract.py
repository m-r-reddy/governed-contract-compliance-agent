"""Canonical contract, rate card, chunk, and retrieval domain entities."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.invoice import DateRange


class RateCardEntry(BaseModel):
    """Approved labor role hourly rate ceiling defined in an MSA or SOW."""

    model_config = ConfigDict(frozen=True)

    role_title: str = Field(min_length=2, max_length=128)
    max_hourly_rate: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class ContractMilestone(BaseModel):
    """Approved SOW deliverable milestone and fee cap."""

    model_config = ConfigDict(frozen=True)

    milestone_id: str = Field(min_length=2, max_length=64)
    description: str = Field(min_length=3, max_length=500)
    capped_amount: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)


class ContractTerms(BaseModel):
    """Structured Master Services Agreement (MSA) or Statement of Work (SOW) metadata."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(default="org_default", min_length=2, max_length=64)
    contract_id: str = Field(min_length=3, max_length=64)
    vendor_id: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=3, max_length=256)
    department_acl: list[str] = Field(min_length=1)
    effective_window: DateRange
    approved_rate_card: dict[str, RateCardEntry] = Field(default_factory=dict)
    milestones: list[ContractMilestone] = Field(default_factory=list)

    def is_active_on(self, target_date: date) -> bool:
        """Return True if target_date falls within the contract effective window."""
        return (
            self.effective_window.start_date
            <= target_date
            <= self.effective_window.end_date
        )


class ContractChunk(BaseModel):
    """Markdown-aware contract section chunk persisted for hybrid RAG retrieval."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=3, max_length=128)
    tenant_id: str = Field(min_length=2, max_length=64)
    contract_id: str = Field(min_length=3, max_length=64)
    vendor_id: str = Field(min_length=2, max_length=64)
    department_acl: list[str] = Field(min_length=1)
    section_header: str = Field(min_length=1, max_length=256)
    clause_type: str = Field(default="general", min_length=2, max_length=64)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ContractSearchQuery(BaseModel):
    """Structured hybrid retrieval request scoped to a vendor and optional contract."""

    model_config = ConfigDict(frozen=True)

    query_text: str = Field(min_length=2, max_length=2000)
    vendor_id: str = Field(min_length=2, max_length=64)
    contract_id: str | None = Field(default=None, min_length=3, max_length=64)
    top_k: int = Field(default=5, ge=1, le=25)
    dense_weight: Decimal = Field(
        default=Decimal("0.50"), ge=Decimal("0.00"), le=Decimal("1.00")
    )
    sparse_weight: Decimal = Field(
        default=Decimal("0.50"), ge=Decimal("0.00"), le=Decimal("1.00")
    )

    @model_validator(mode="after")
    def validate_fusion_weights(self) -> ContractSearchQuery:
        total = (self.dense_weight + self.sparse_weight).quantize(Decimal("0.01"))
        if total != Decimal("1.00"):
            raise ValueError(
                f"dense_weight + sparse_weight must equal 1.00, got {total}"
            )
        return self


class RetrievedClause(BaseModel):
    """Ranked contract clause returned by the ACL-aware hybrid retrieval pipeline."""

    model_config = ConfigDict(frozen=True)

    chunk: ContractChunk
    dense_score: float | None = Field(default=None)
    sparse_score: float | None = Field(default=None)
    rrf_score: float = Field(ge=0.0)
    rerank_score: float | None = Field(default=None)

    @model_validator(mode="after")
    def validate_non_empty_content(self) -> RetrievedClause:
        if not self.chunk.content.strip():
            raise ValueError("RetrievedClause cannot wrap an empty ContractChunk.")
        return self
