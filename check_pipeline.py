from pipeline.supabase_client import get_supabase
sb = get_supabase()
result = sb.schema('vdme').table('notifications') \
    .select('id, recipient_neo4j_id, type, title, is_read, created_at') \
    .eq('type', 'interview_request') \
    .order('created_at', desc=True).limit(5).execute()
for r in result.data:
    print(r)