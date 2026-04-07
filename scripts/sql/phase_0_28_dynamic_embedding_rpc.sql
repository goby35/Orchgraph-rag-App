-- Phase 0.28: Dynamic embedding-column RPCs for chunk retrieval.

CREATE OR REPLACE FUNCTION vdme.match_public_chunks_dynamic(
  query_embedding vector,
  target_user_id uuid,
  match_count int DEFAULT 5,
  embedding_col text DEFAULT 'embedding_gte'
)
RETURNS TABLE (id uuid, content text, similarity double precision)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  sql_query text;
BEGIN
  IF embedding_col NOT IN (
    'embedding_gte', 'embedding_bge', 'embedding_e5', 'embedding_phobert'
  ) THEN
    RAISE EXCEPTION 'Invalid embedding column: %', embedding_col;
  END IF;

  sql_query := format(
    'SELECT dc.id,
            dc.content,
            1 - (dc.%1$I <=> $1) AS similarity
     FROM vdme.document_chunks dc
     WHERE dc.user_id = $2
       AND dc.is_public = TRUE
       AND dc.%1$I IS NOT NULL
     ORDER BY dc.%1$I <=> $1
     LIMIT $3',
    embedding_col
  );

  RETURN QUERY EXECUTE sql_query USING query_embedding, target_user_id, match_count;
END;
$$;

CREATE OR REPLACE FUNCTION vdme.match_private_chunks_dynamic(
  query_embedding vector,
  target_user_id uuid,
  match_count int DEFAULT 5,
  embedding_col text DEFAULT 'embedding_gte'
)
RETURNS TABLE (id uuid, content text, similarity double precision)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  sql_query text;
BEGIN
  IF embedding_col NOT IN (
    'embedding_gte', 'embedding_bge', 'embedding_e5', 'embedding_phobert'
  ) THEN
    RAISE EXCEPTION 'Invalid embedding column: %', embedding_col;
  END IF;

  sql_query := format(
    'SELECT dc.id,
            dc.content,
            1 - (dc.%1$I <=> $1) AS similarity
     FROM vdme.document_chunks dc
     WHERE dc.user_id = $2
       AND dc.is_public = FALSE
       AND dc.%1$I IS NOT NULL
     ORDER BY dc.%1$I <=> $1
     LIMIT $3',
    embedding_col
  );

  RETURN QUERY EXECUTE sql_query USING query_embedding, target_user_id, match_count;
END;
$$;
