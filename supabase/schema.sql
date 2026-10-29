-- Supabase schema with pgvector enabled for Discharge Explainer

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Core documents table
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    record_json TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index on created_at for retention cleanup
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents (created_at);

-- 3. Vector search embeddings table for discharge facts & clinical sections
CREATE TABLE IF NOT EXISTS document_embeddings (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    sentence_id TEXT,
    section TEXT,
    content TEXT NOT NULL,
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. HNSW index for fast approximate nearest neighbor vector search
CREATE INDEX IF NOT EXISTS idx_document_embeddings_hnsw 
ON document_embeddings USING hnsw (embedding vector_cosine_ops);

-- 5. Helper function for semantic similarity search over discharge instructions (plpgsql)
CREATE OR REPLACE FUNCTION match_discharge_sections (
    query_embedding vector(384),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id bigint,
    document_id text,
    sentence_id text,
    section text,
    content text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        de.id,
        de.document_id,
        de.sentence_id,
        de.section,
        de.content,
        (1 - (de.embedding <=> query_embedding))::float AS similarity
    FROM document_embeddings de
    WHERE 1 - (de.embedding <=> query_embedding) > match_threshold
    ORDER BY de.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
