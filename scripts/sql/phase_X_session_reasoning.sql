-- Session metadata for interview sidebar and reasoning summaries.

CREATE TABLE IF NOT EXISTS vdme.chat_sessions (
  session_id uuid PRIMARY KEY,
  org_id text NOT NULL,
  personnel_id text NOT NULL,
  job_title text,
  reasoning_summary jsonb DEFAULT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE vdme.chat_sessions
  ADD COLUMN IF NOT EXISTS reasoning_summary jsonb DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_org_id
  ON vdme.chat_sessions (org_id);

WITH first_messages AS (
  SELECT DISTINCT ON (session_id)
    session_id,
    COALESCE(org_id, org_neo4j_id) AS org_id,
    COALESCE(personnel_neo4j_id, per_neo4j_id) AS personnel_id,
    job_title,
    reasoning,
    created_at
  FROM vdme.chat_messages
  WHERE session_id IS NOT NULL
    AND COALESCE(org_id, org_neo4j_id) IS NOT NULL
    AND COALESCE(personnel_neo4j_id, per_neo4j_id) IS NOT NULL
  ORDER BY session_id, created_at ASC
)
INSERT INTO vdme.chat_sessions (
  session_id,
  org_id,
  personnel_id,
  job_title,
  reasoning_summary,
  created_at
)
SELECT
  session_id,
  org_id,
  personnel_id,
  job_title,
  reasoning,
  created_at
FROM first_messages
ON CONFLICT (session_id) DO UPDATE
SET
  org_id = EXCLUDED.org_id,
  personnel_id = EXCLUDED.personnel_id,
  job_title = COALESCE(EXCLUDED.job_title, vdme.chat_sessions.job_title),
  reasoning_summary = COALESCE(EXCLUDED.reasoning_summary, vdme.chat_sessions.reasoning_summary);