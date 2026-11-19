"""Early-binding ACL-aware PostgreSQL (pgvector + BM25 RRF) hybrid RAG adapter."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from openai import AsyncOpenAI, OpenAIError
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from src.core.config import GatewaySettings
from src.core.exceptions import GatewayUpstreamError, TenantAccessDeniedError
from src.domain.context import TenantContext
from src.domain.contract import (
    ContractChunk,
    ContractSearchQuery,
    ContractTerms,
    RetrievedClause,
)
from src.rag.chunker import MarkdownContractChunker

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

_HYBRID_RETRIEVAL_SQL = """
WITH dense_candidates AS (
    SELECT
        chunk_id,
        1.0 - (embedding <=> %(query_embedding)s::vector) AS dense_score,
        ROW_NUMBER() OVER (ORDER BY embedding <=> %(query_embedding)s::vector ASC) AS dense_rank
    FROM contract_chunks
    WHERE tenant_id = %(tenant_id)s
      AND vendor_id = %(vendor_id)s
      AND department_acl && %(department_acl)s::text[]
      AND (%(contract_id)s::text IS NULL OR contract_id = %(contract_id)s::text)
    ORDER BY embedding <=> %(query_embedding)s::vector ASC
    LIMIT %(candidate_limit)s
),
sparse_candidates AS (
    SELECT
        chunk_id,
        ts_rank_cd(search_tsv, plainto_tsquery('english', %(query_text)s)) AS sparse_score,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(search_tsv, plainto_tsquery('english', %(query_text)s)) DESC
        ) AS sparse_rank
    FROM contract_chunks
    WHERE tenant_id = %(tenant_id)s
      AND vendor_id = %(vendor_id)s
      AND department_acl && %(department_acl)s::text[]
      AND (%(contract_id)s::text IS NULL OR contract_id = %(contract_id)s::text)
      AND search_tsv @@ plainto_tsquery('english', %(query_text)s)
    ORDER BY sparse_score DESC
    LIMIT %(candidate_limit)s
),
fused AS (
    SELECT
        COALESCE(d.chunk_id, s.chunk_id) AS chunk_id,
        d.dense_score,
        s.sparse_score,
        (
            COALESCE(%(dense_weight)s::float / (60.0 + d.dense_rank), 0.0) +
            COALESCE(%(sparse_weight)s::float / (60.0 + s.sparse_rank), 0.0)
        ) AS rrf_score
    FROM dense_candidates d
    FULL OUTER JOIN sparse_candidates s ON d.chunk_id = s.chunk_id
)
SELECT
    c.chunk_id,
    c.tenant_id,
    c.contract_id,
    c.vendor_id,
    c.department_acl,
    c.section_header,
    c.clause_type,
    c.chunk_index,
    c.content,
    c.metadata_json,
    f.dense_score,
    f.sparse_score,
    f.rrf_score
FROM fused f
JOIN contract_chunks c
  ON c.tenant_id = %(tenant_id)s
 AND c.chunk_id = f.chunk_id
WHERE c.tenant_id = %(tenant_id)s
  AND c.department_acl && %(department_acl)s::text[]
ORDER BY f.rrf_score DESC
LIMIT %(rerank_pool_limit)s;
"""


@runtime_checkable
class ClauseRerankerProtocol(Protocol):
    """Port interface for second-stage Cross-Encoder reranking."""

    async def rerank(
        self,
        query_text: str,
        candidates: list[RetrievedClause],
        top_k: int,
    ) -> list[RetrievedClause]: ...


class TokenOverlapReranker:
    """Lightweight deterministic fallback reranker scoring query-clause term overlap."""

    async def rerank(
        self,
        query_text: str,
        candidates: list[RetrievedClause],
        top_k: int,
    ) -> list[RetrievedClause]:
        query_tokens = set(_TOKEN_RE.findall(query_text.lower()))
        if not query_tokens:
            return candidates[:top_k]

        rescored: list[RetrievedClause] = []
        for item in candidates:
            doc_tokens = set(
                _TOKEN_RE.findall(
                    f"{item.chunk.section_header} {item.chunk.content}".lower()
                )
            )
            overlap_ratio = len(query_tokens & doc_tokens) / len(query_tokens)
            combined_score = round((0.6 * overlap_ratio) + (0.4 * item.rrf_score * 30.0), 6)
            rescored.append(item.model_copy(update={"rerank_score": combined_score}))

        rescored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return rescored[:top_k]


class PgVectorHybridRetriever:
    """PostgreSQL 16 (pgvector + BM25 RRF) retriever with early-binding ACLs and RLS."""

    def __init__(
        self,
        connection: AsyncConnection[Any],
        gateway_settings: GatewaySettings | None = None,
        embedding_client: AsyncOpenAI | None = None,
        chunker: MarkdownContractChunker | None = None,
        reranker: ClauseRerankerProtocol | None = None,
    ) -> None:
        self._conn = connection
        self._settings = gateway_settings or GatewaySettings.from_env()
        self._embed_client = embedding_client or AsyncOpenAI(
            base_url=self._settings.base_url,
            api_key=self._settings.api_key,
            timeout=self._settings.timeout_seconds,
        )
        self._chunker = chunker or MarkdownContractChunker()
        self._reranker: ClauseRerankerProtocol = reranker or TokenOverlapReranker()

    async def _embed_texts(
        self, texts: list[str], context: TenantContext
    ) -> list[list[float]]:
        try:
            response = await self._embed_client.embeddings.create(
                model=self._settings.embedding_model,
                input=texts,
                extra_body={
                    "metadata": {
                        "tenant_id": context.tenant_id,
                        "user_id": context.user_id,
                        "cost_center": context.cost_center,
                        "correlation_id": context.correlation_id,
                    }
                },
            )
        except OpenAIError as exc:
            raise GatewayUpstreamError(
                f"LiteLLM embedding request failed: {exc}",
                correlation_id=context.correlation_id,
            ) from exc

        return [item.embedding for item in response.data]

    async def index_contract(
        self,
        terms: ContractTerms,
        markdown_body: str,
        context: TenantContext,
    ) -> int:
        """Chunk, embed via LiteLLM Proxy, and persist contract + chunks under RLS."""
        if terms.tenant_id != context.tenant_id:
            raise TenantAccessDeniedError(
                f"Cannot index contract for tenant '{terms.tenant_id}' under "
                f"context '{context.tenant_id}'.",
                correlation_id=context.correlation_id,
            )

        chunks = self._chunker.chunk_contract(terms, markdown_body, context)
        embeddings = await self._embed_texts(
            [f"{c.section_header}\n{c.content}" for c in chunks],
            context,
        )

        rate_card_dump = {
            role: {
                "role_title": entry.role_title,
                "max_hourly_rate": str(entry.max_hourly_rate),
                "currency": entry.currency,
            }
            for role, entry in terms.approved_rate_card.items()
        }
        milestones_dump = [
            {
                "milestone_id": m.milestone_id,
                "description": m.description,
                "capped_amount": str(m.capped_amount),
            }
            for m in terms.milestones
        ]

        async with (
            self._conn.transaction(),
            self._conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true);",
                (context.tenant_id,),
            )
            await cur.execute(
                """
                INSERT INTO contracts (
                    tenant_id, contract_id, vendor_id, title, department_acl,
                    effective_start, effective_end, rate_card_json, milestones_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (tenant_id, contract_id) DO UPDATE SET
                    vendor_id = EXCLUDED.vendor_id,
                    title = EXCLUDED.title,
                    department_acl = EXCLUDED.department_acl,
                    effective_start = EXCLUDED.effective_start,
                    effective_end = EXCLUDED.effective_end,
                    rate_card_json = EXCLUDED.rate_card_json,
                    milestones_json = EXCLUDED.milestones_json;
                """,
                (
                    context.tenant_id,
                    terms.contract_id,
                    terms.vendor_id,
                    terms.title,
                    list(terms.department_acl),
                    terms.effective_window.start_date,
                    terms.effective_window.end_date,
                    json.dumps(rate_card_dump),
                    json.dumps(milestones_dump),
                ),
            )

            for chunk, vector in zip(chunks, embeddings, strict=True):
                vector_literal = "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
                await cur.execute(
                    """
                    INSERT INTO contract_chunks (
                        chunk_id, tenant_id, contract_id, vendor_id, department_acl,
                        section_header, clause_type, chunk_index, content,
                        metadata_json, embedding
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (tenant_id, chunk_id) DO UPDATE SET
                        department_acl = EXCLUDED.department_acl,
                        section_header = EXCLUDED.section_header,
                        clause_type = EXCLUDED.clause_type,
                        content = EXCLUDED.content,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        chunk.chunk_id,
                        context.tenant_id,
                        chunk.contract_id,
                        chunk.vendor_id,
                        list(chunk.department_acl),
                        chunk.section_header,
                        chunk.clause_type,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(chunk.metadata),
                        vector_literal,
                    ),
                )

        return len(chunks)

    async def upsert_chunks(
        self,
        chunks: list[ContractChunk],
        context: TenantContext,
    ) -> int:
        """Embed and upsert pre-built ContractChunk records under RLS."""
        if not chunks:
            return 0
        for chunk in chunks:
            if chunk.tenant_id != context.tenant_id:
                raise TenantAccessDeniedError(
                    f"Chunk tenant '{chunk.tenant_id}' mismatches context '{context.tenant_id}'.",
                    correlation_id=context.correlation_id,
                )

        embeddings = await self._embed_texts(
            [f"{c.section_header}\n{c.content}" for c in chunks],
            context,
        )

        async with (
            self._conn.transaction(),
            self._conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true);",
                (context.tenant_id,),
            )
            for chunk, vector in zip(chunks, embeddings, strict=True):
                vector_literal = "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
                await cur.execute(
                    """
                    INSERT INTO contract_chunks (
                        chunk_id, tenant_id, contract_id, vendor_id, department_acl,
                        section_header, clause_type, chunk_index, content,
                        metadata_json, embedding
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (tenant_id, chunk_id) DO UPDATE SET
                        department_acl = EXCLUDED.department_acl,
                        section_header = EXCLUDED.section_header,
                        clause_type = EXCLUDED.clause_type,
                        content = EXCLUDED.content,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        chunk.chunk_id,
                        context.tenant_id,
                        chunk.contract_id,
                        chunk.vendor_id,
                        list(chunk.department_acl),
                        chunk.section_header,
                        chunk.clause_type,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(chunk.metadata),
                        vector_literal,
                    ),
                )
        return len(chunks)

    async def retrieve_clauses(
        self,
        query: ContractSearchQuery,
        context: TenantContext,
    ) -> list[RetrievedClause]:
        """Execute early-binding ACL hybrid search (pgvector + BM25 + RRF + Reranker)."""
        [query_vector] = await self._embed_texts([query.query_text], context)
        vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"

        candidate_limit = max(query.top_k * 4, 20)
        rerank_pool_limit = max(query.top_k * 2, 10)

        async with (
            self._conn.transaction(),
            self._conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true);",
                (context.tenant_id,),
            )
            await cur.execute("SET LOCAL hnsw.iterative_scan = 'strict_order';")
            await cur.execute(
                _HYBRID_RETRIEVAL_SQL,
                {
                    "query_embedding": vector_literal,
                    "query_text": query.query_text,
                    "tenant_id": context.tenant_id,
                    "vendor_id": query.vendor_id,
                    "department_acl": list(context.department_acl),
                    "contract_id": query.contract_id,
                    "dense_weight": float(query.dense_weight),
                    "sparse_weight": float(query.sparse_weight),
                    "candidate_limit": candidate_limit,
                    "rerank_pool_limit": rerank_pool_limit,
                },
            )
            rows = await cur.fetchall()

        candidates: list[RetrievedClause] = []
        for row in rows:
            raw_meta = row["metadata_json"]
            parsed_meta = (
                json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta or {})
            )
            chunk = ContractChunk(
                chunk_id=str(row["chunk_id"]),
                tenant_id=str(row["tenant_id"]),
                contract_id=str(row["contract_id"]),
                vendor_id=str(row["vendor_id"]),
                department_acl=list(row["department_acl"]),
                section_header=str(row["section_header"]),
                clause_type=str(row["clause_type"]),
                chunk_index=int(row["chunk_index"]),
                content=str(row["content"]),
                metadata={str(k): str(v) for k, v in parsed_meta.items()},
            )
            candidates.append(
                RetrievedClause(
                    chunk=chunk,
                    dense_score=float(row["dense_score"])
                    if row["dense_score"] is not None
                    else None,
                    sparse_score=float(row["sparse_score"])
                    if row["sparse_score"] is not None
                    else None,
                    rrf_score=float(row["rrf_score"]),
                )
            )

        return await self._reranker.rerank(
            query_text=query.query_text,
            candidates=candidates,
            top_k=query.top_k,
        )
