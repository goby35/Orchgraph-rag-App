-- Add per-auth-user ownership for recruiter chat isolation.
-- This migration is idempotent and safe to rerun.

begin;

alter table vdme.chat_sessions
  add column if not exists owner_user_id uuid;

alter table vdme.chat_messages
  add column if not exists owner_user_id uuid;

-- Best-effort backfill from vdme.users when one org maps to exactly one recruiter account.
with unique_org_owner as (
  select neo4j_id, min(id::text)::uuid as owner_user_id
  from vdme.users
  where lower(role::text) = 'organization'
  group by neo4j_id
  having count(*) = 1
)
update vdme.chat_sessions as s
set owner_user_id = u.owner_user_id
from unique_org_owner as u
where s.owner_user_id is null
  and s.org_id = u.neo4j_id;

with unique_org_owner as (
  select neo4j_id, min(id::text)::uuid as owner_user_id
  from vdme.users
  where lower(role::text) = 'organization'
  group by neo4j_id
  having count(*) = 1
)
update vdme.chat_messages as m
set owner_user_id = u.owner_user_id
from unique_org_owner as u
where m.owner_user_id is null
  and coalesce(m.org_id, m.org_neo4j_id) = u.neo4j_id;

create index if not exists idx_chat_sessions_owner_created_at
  on vdme.chat_sessions (owner_user_id, created_at desc);

create index if not exists idx_chat_messages_owner_session_created_at
  on vdme.chat_messages (owner_user_id, session_id, created_at);

create index if not exists idx_chat_messages_owner_created_at
  on vdme.chat_messages (owner_user_id, created_at desc);

comment on column vdme.chat_sessions.owner_user_id is
  'Supabase auth.users.id of recruiter who owns this chat session';

comment on column vdme.chat_messages.owner_user_id is
  'Supabase auth.users.id of recruiter who owns this chat message';

commit;
