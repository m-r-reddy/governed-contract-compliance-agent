"""Enterprise domain and infrastructure exception hierarchy."""

from __future__ import annotations


class ComplianceAgentError(Exception):
    """Base exception for all governed-contract-compliance-agent errors."""

    def __init__(self, message: str, *, correlation_id: str | None = None) -> None:
        self.correlation_id = correlation_id
        super().__init__(message)


class TenantAccessDeniedError(ComplianceAgentError):
    """Raised when a principal attempts cross-tenant or unauthorized ACL access."""


class DomainValidationError(ComplianceAgentError):
    """Raised when financial, schema, or invariant rules are violated."""


class GatewayUpstreamError(ComplianceAgentError):
    """Raised when the LiteLLM Egress AI Gateway fails or returns invalid output."""


class IdempotencyConflictError(ComplianceAgentError):
    """Raised when a duplicate side-effect execution is attempted with mismatched payload."""
