-- Phase 0.29: Add PhoBERT chunk embedding column and ANN index.

-- Add column if missing.
ALTER TABLE vdme.document_chunks
  ADD COLUMN IF NOT EXISTS embedding_phobert vector(768);

-- HNSW index for ANN search on PhoBERT chunk vectors.
CREATE INDEX IF NOT EXISTS document_chunks_embedding_phobert_idx
  ON vdme.document_chunks
  USING hnsw (embedding_phobert vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
