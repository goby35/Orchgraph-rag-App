from pipeline.supabase_client import get_supabase

sb = get_supabase()

print("=== vdme.users ===")
rows = sb.schema("vdme").table("users").select("id, neo4j_id, role, full_name").execute()
for r in rows.data:
    print(r)

print()
print("=== auth.users metadata ===")
users = sb.auth.admin.list_users()
for u in users:
    meta = u.user_metadata or {}
    neo4j_id = meta.get("neo4j_id")
    role = meta.get("role")
    print(f"email={u.email} | neo4j_id={neo4j_id} | role={role}")


# Thêm vào check_users.py
print("\n=== Kiểm tra account đang dùng để test ===")
users = sb.auth.admin.list_users()
for u in users:
    meta = u.user_metadata or {}
    if meta.get("role") == "PERSONNEL" and "gmail" in (u.email or ""):
        print(f"email={u.email} | neo4j_id={meta.get('neo4j_id')} | role={meta.get('role')}")