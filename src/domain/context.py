"""Multi-tenant identity, ACL, and FinOps attribution context."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TenantContext(BaseModel):
    """Immutable execution context propagated from Ingress JWT through all planes."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(default="org_default", min_length=2, max_length=64)
    user_id: str = Field(default="system_ingest", min_length=1, max_length=128)
    department_acl: list[str] = Field(
        default_factory=lambda: ["procurement"],
        min_length=1,
    )
    cost_center: str = Field(default="CC-FINOPS-001", min_length=2, max_length=64)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
