"""Port interfaces for ACL-aware contract indexing and hybrid retrieval."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.context import TenantContext
from src.domain.contract import (
    ContractChunk,
    ContractSearchQuery,
    ContractTerms,
    RetrievedClause,
)


@runtime_checkable
class ContractIndexerProtocol(Protocol):
    """Contract for chunking, embedding, and indexing MSAs/SOWs with ACL metadata."""

    async def index_contract(
        self,
        terms: ContractTerms,
        markdown_body: str,
        context: TenantContext,
    ) -> int:
        """Chunk, embed, and persist a contract under strict tenant/ACL ownership.

        Implementations MUST bind persisted rows to `context.tenant_id` and
        enforce tenant ownership validation before writing.
        Returns the number of chunks indexed.
        """
        ...

    async def upsert_chunks(
        self,
        chunks: list[ContractChunk],
        context: TenantContext,
    ) -> int:
        """Embed and persist pre-chunked contract segments bound to `context.tenant_id`.

        Returns the number of chunks indexed.
        """
        ...


@runtime_checkable
class ContractRetrieverProtocol(Protocol):
    """Contract for early-binding ACL-enforced hybrid contract retrieval."""

    async def retrieve_clauses(
        self,
        query: ContractSearchQuery,
        context: TenantContext,
    ) -> list[RetrievedClause]:
        """Execute pre-filtered hybrid search (pgvector + BM25 + RRF + Reranker).

        Implementations MUST enforce `(context.tenant_id, context.department_acl)`
        filtering inside SQL predicates and RLS policies prior to similarity scoring.
        """
        ...
