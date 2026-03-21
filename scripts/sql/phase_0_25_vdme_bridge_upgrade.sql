-- Phase 0 + 2.5 bridge upgrade for existing vdme schema
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

ALTER TABLE vdme.users
  ADD COLUMN IF NOT EXISTS neo4j_id text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'users_neo4j_id_key'
      AND conrelid = 'vdme.users'::regclass
  ) THEN
    ALTER TABLE vdme.users
      ADD CONSTRAINT users_neo4j_id_key UNIQUE (neo4j_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS vdme.chat_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_neo4j_id text NOT NULL,
  per_neo4j_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('user', 'assistant')),
  content text NOT NULL,
  is_private_mode boolean DEFAULT false,
  reasoning jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_session
  ON vdme.chat_messages (org_neo4j_id, per_neo4j_id, created_at);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chunk_embeddings_model_chunk_unique'
      AND conrelid = 'vdme.chunk_embeddings'::regclass
  ) THEN
    ALTER TABLE vdme.chunk_embeddings
      ADD CONSTRAINT chunk_embeddings_model_chunk_unique UNIQUE (chunk_id, model_name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chunk_embeddings_single_dimension_check'
      AND conrelid = 'vdme.chunk_embeddings'::regclass
  ) THEN
    ALTER TABLE vdme.chunk_embeddings
      ADD CONSTRAINT chunk_embeddings_single_dimension_check
      CHECK (
        (embedding_384 IS NOT NULL)::int +
        (embedding_768 IS NOT NULL)::int +
        (embedding_1024 IS NOT NULL)::int = 1
      );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS embed_768_hnsw
  ON vdme.chunk_embeddings USING hnsw (embedding_768 vector_cosine_ops)
  WHERE embedding_768 IS NOT NULL;

CREATE INDEX IF NOT EXISTS embed_1024_hnsw
  ON vdme.chunk_embeddings USING hnsw (embedding_1024 vector_cosine_ops)
  WHERE embedding_1024 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_user
  ON vdme.document_chunks (user_id, is_public);

CREATE OR REPLACE FUNCTION vdme.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_updated ON vdme.users;
CREATE TRIGGER trg_users_updated
BEFORE UPDATE ON vdme.users
FOR EACH ROW
EXECUTE FUNCTION vdme.set_updated_at();

DROP TRIGGER IF EXISTS trg_profiles_updated ON vdme.profiles;
CREATE TRIGGER trg_profiles_updated
BEFORE UPDATE ON vdme.profiles
FOR EACH ROW
EXECUTE FUNCTION vdme.set_updated_at();

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
         1 - (ce.embedding_768 <=> query_embedding) AS similarity
  FROM vdme.chunk_embeddings ce
  JOIN vdme.document_chunks dc ON dc.id = ce.chunk_id
  WHERE dc.user_id = target_user_id
    AND dc.is_public = FALSE
    AND ce.model_name = 'phobert'
    AND ce.embedding_768 IS NOT NULL
  ORDER BY ce.embedding_768 <=> query_embedding
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
         1 - (ce.embedding_768 <=> query_embedding) AS similarity
  FROM vdme.chunk_embeddings ce
  JOIN vdme.document_chunks dc ON dc.id = ce.chunk_id
  WHERE dc.user_id = target_user_id
    AND dc.is_public = TRUE
    AND ce.model_name = 'phobert'
    AND ce.embedding_768 IS NOT NULL
  ORDER BY ce.embedding_768 <=> query_embedding
  LIMIT match_count;
$$;
