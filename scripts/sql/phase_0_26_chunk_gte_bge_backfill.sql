-- Phase 0.26: Add direct GTE/BGE/E5 vectors on chunk rows for Supabase retrieval.

-- Requested DDL for environments where table name is `chunks`.
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_gte vector(768);
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_bge vector(768);
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_e5 vector(768);

-- Repository schema uses vdme.document_chunks as the chunk table.
ALTER TABLE vdme.document_chunks ADD COLUMN IF NOT EXISTS embedding_gte vector(768);
ALTER TABLE vdme.document_chunks ADD COLUMN IF NOT EXISTS embedding_bge vector(768);
ALTER TABLE vdme.document_chunks ADD COLUMN IF NOT EXISTS embedding_e5 vector(768);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_gte_hnsw
  ON vdme.document_chunks USING hnsw (embedding_gte vector_cosine_ops)
  WHERE embedding_gte IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_bge_hnsw
  ON vdme.document_chunks USING hnsw (embedding_bge vector_cosine_ops)
  WHERE embedding_bge IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_e5_hnsw
  ON vdme.document_chunks USING hnsw (embedding_e5 vector_cosine_ops)
  WHERE embedding_e5 IS NOT NULL;

-- Switch retrieval RPCs to GTE vectors on vdme.document_chunks.
CREATE OR REPLACE FUNCTION vdme.match_private_chunks(
  query_embedding vector(768),
  target_user_id uuid,
  match_count int DEFAULT 5
)
RETURNS TABLE (content text, similarity float)
LANGUAGE sql
STABLE
AS $$
  SELECT dc.content,
         1 - (dc.embedding_gte <=> query_embedding) AS similarity
  FROM vdme.document_chunks dc
  WHERE dc.user_id = target_user_id
    AND dc.is_public = FALSE
    AND dc.embedding_gte IS NOT NULL
  ORDER BY dc.embedding_gte <=> query_embedding
  LIMIT match_count;
$$;

CREATE OR REPLACE FUNCTION vdme.match_public_chunks(
  query_embedding vector(768),
  target_user_id uuid,
  match_count int DEFAULT 5
)
RETURNS TABLE (content text, similarity float)
LANGUAGE sql
STABLE
AS $$
  SELECT dc.content,
         1 - (dc.embedding_gte <=> query_embedding) AS similarity
  FROM vdme.document_chunks dc
  WHERE dc.user_id = target_user_id
    AND dc.is_public = TRUE
    AND dc.embedding_gte IS NOT NULL
  ORDER BY dc.embedding_gte <=> query_embedding
  LIMIT match_count;
$$;
