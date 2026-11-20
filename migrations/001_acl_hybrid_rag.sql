-- Migration 001: ACL-Aware Hybrid RAG Schema & Row-Level Security
-- Enforces ADR-002: Early-Binding Composite (tenant_id, department_acl) Filtering + PostgreSQL RLS

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS contracts (
    tenant_id        VARCHAR(64)  NOT NULL,
    contract_id      VARCHAR(64)  NOT NULL,
    vendor_id        VARCHAR(64)  NOT NULL,
    title            VARCHAR(256) NOT NULL,
    department_acl   TEXT[]       NOT NULL,
    effective_start  DATE         NOT NULL,
    effective_end    DATE         NOT NULL,
    rate_card_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    milestones_json  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, contract_id),
    CONSTRAINT chk_contract_dates CHECK (effective_end >= effective_start),
    CONSTRAINT chk_contract_acl_non_empty CHECK (cardinality(department_acl) > 0)
);

CREATE TABLE IF NOT EXISTS contract_chunks (
    chunk_id         VARCHAR(128) NOT NULL,
    tenant_id        VARCHAR(64)  NOT NULL,
    contract_id      VARCHAR(64)  NOT NULL,
    vendor_id        VARCHAR(64)  NOT NULL,
    department_acl   TEXT[]       NOT NULL,
    section_header   VARCHAR(256) NOT NULL,
    clause_type      VARCHAR(64)  NOT NULL DEFAULT 'general',
    chunk_index      INTEGER      NOT NULL CHECK (chunk_index >= 0),
    content          TEXT         NOT NULL,
    metadata_json    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    embedding        vector(1536) NOT NULL,
    search_tsv       tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(section_header, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'B')
    ) STORED,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, chunk_id),
    CONSTRAINT fk_chunk_contract
        FOREIGN KEY (tenant_id, contract_id)
        REFERENCES contracts (tenant_id, contract_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_chunk_acl_non_empty CHECK (cardinality(department_acl) > 0)
);

-- Composite B-tree + GIN indexes for early-binding ACL predicate pushdown
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_vendor
    ON contract_chunks (tenant_id, vendor_id, contract_id);

CREATE INDEX IF NOT EXISTS idx_chunks_department_acl_gin
    ON contract_chunks USING GIN (department_acl);

CREATE INDEX IF NOT EXISTS idx_chunks_search_tsv_gin
    ON contract_chunks USING GIN (search_tsv);

-- HNSW cosine distance index for dense semantic retrieval
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON contract_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Defense-in-Depth Layer 2: PostgreSQL Row-Level Security (RLS)
ALTER TABLE contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contracts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_contracts ON contracts;
CREATE POLICY tenant_isolation_contracts ON contracts
    USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));

ALTER TABLE contract_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_chunks ON contract_chunks;
CREATE POLICY tenant_isolation_chunks ON contract_chunks
    USING (tenant_id = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));

-- Least-privilege runtime role (NOSUPERUSER so FORCE ROW LEVEL SECURITY is strictly enforced)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'compliance_app') THEN
        CREATE ROLE compliance_app LOGIN PASSWORD 'compliance_app_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE compliance_db TO compliance_app;
GRANT USAGE ON SCHEMA public TO compliance_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE contracts, contract_chunks TO compliance_app;
