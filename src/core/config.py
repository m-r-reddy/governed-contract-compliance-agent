"""Typed application configuration loaded from environment variables."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class GatewaySettings(BaseModel):
    """Configuration for the outbound LiteLLM Egress AI Gateway."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(default="http://localhost:4000/v1")
    api_key: str = Field(default="sk-local-master-key")
    extraction_model: str = Field(default="extraction-fast")
    reasoning_model: str = Field(default="compliance-reasoning")
    embedding_model: str = Field(default="text-embedding")
    timeout_seconds: float = Field(default=30.0, gt=0.0)

    @classmethod
    def from_env(cls) -> GatewaySettings:
        return cls(
            base_url=os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1"),
            api_key=os.getenv("LITELLM_MASTER_KEY", "sk-local-master-key"),
            extraction_model=os.getenv("LITELLM_EXTRACTION_MODEL", "extraction-fast"),
            reasoning_model=os.getenv("LITELLM_REASONING_MODEL", "compliance-reasoning"),
            embedding_model=os.getenv("LITELLM_EMBEDDING_MODEL", "text-embedding"),
        )
