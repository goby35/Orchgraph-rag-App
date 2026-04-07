-- Add session-based chat persistence columns for Digital Twin chat restore flow.
ALTER TABLE vdme.chat_messages
  ADD COLUMN IF NOT EXISTS session_id uuid,
  ADD COLUMN IF NOT EXISTS job_title text,
  ADD COLUMN IF NOT EXISTS org_id text,
  ADD COLUMN IF NOT EXISTS personnel_neo4j_id text;

-- Backfill new aliases from legacy columns when possible.
UPDATE vdme.chat_messages
SET
  org_id = COALESCE(org_id, org_neo4j_id),
  personnel_neo4j_id = COALESCE(personnel_neo4j_id, per_neo4j_id)
WHERE org_id IS NULL OR personnel_neo4j_id IS NULL;

-- Existing rows without a session are assigned deterministic UUIDs per row to keep data queryable.
UPDATE vdme.chat_messages
SET session_id = gen_random_uuid()
WHERE session_id IS NULL;

ALTER TABLE vdme.chat_messages
  ALTER COLUMN session_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
  ON vdme.chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_messages_org_session
  ON vdme.chat_messages (org_id, session_id, created_at DESC);
