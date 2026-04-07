-- Phase 0.27: Add E5 embedding column for Supabase chunks.

ALTER TABLE IF EXISTS chunks
  ADD COLUMN IF NOT EXISTS embedding_e5 vector(768);

ALTER TABLE vdme.document_chunks
  ADD COLUMN IF NOT EXISTS embedding_e5 vector(768);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_e5_hnsw
  ON vdme.document_chunks USING hnsw (embedding_e5 vector_cosine_ops)
  WHERE embedding_e5 IS NOT NULL;
