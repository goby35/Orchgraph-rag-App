import json
import os
from neo4j import GraphDatabase

# Assuming the pipeline.config.settings module exists as requested
try:
    from pipeline.config import settings
except ImportError:
    # Fallback mock for demonstration if module is not present in standard path
    class DummySettings:
        NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
        NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    settings = DummySettings()

def save_json(data: dict, filepath: str):
    """Utility to save dictionary as JSON."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def print_table(title: str, headers: list, rows: list):
    """Utility to print simple text tables."""
    print(f"\n{title}")
    print("=" * 60)
    col_widths = [max(len(str(item)) for item in col) for col in zip(*rows, headers)]
    row_format = " | ".join(["{:<" + str(w) + "}" for w in col_widths])
    
    print(row_format.format(*headers))
    print("-+-".join(["-" * w for w in col_widths]))
    for row in rows:
        print(row_format.format(*[str(item) for item in row]))
    print("=" * 60)

def main():
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    results = {}

    try:
        with driver.session() as session:
            # Q1: Node Completeness
            q1_query = """
            MATCH (p:Personnel)
            RETURN count(p) AS total,
                   count(p.public_skills) AS has_skills,
                   count(p.public_professional_summary) AS has_summary,
                   count(p.public_embeddings_phobert) AS has_embedding,
                   count(p.public_is_available) AS has_availability,
                   count(p.public_full_name) AS has_name
            """
            q1_res = session.run(q1_query).single()
            total_personnel = q1_res["total"] or 0
            
            def calc_pct(val, total):
                return round((val / total * 100), 2) if total > 0 else 0.0

            node_completeness = {
                "total": total_personnel,
                "skills_pct": calc_pct(q1_res["has_skills"], total_personnel),
                "summary_pct": calc_pct(q1_res["has_summary"], total_personnel),
                "embedding_pct": calc_pct(q1_res["has_embedding"], total_personnel),
                "availability_pct": calc_pct(q1_res["has_availability"], total_personnel),
                "name_pct": calc_pct(q1_res["has_name"], total_personnel)
            }

            # Q2: Skill Stats (Flat)
            q2_query = """
            MATCH (p:Personnel) WHERE p.public_skills_flat IS NOT NULL
            UNWIND p.public_skills_flat AS skill
            RETURN count(DISTINCT skill) AS unique_skills, 
                   count(skill) AS total_mentions,
                   avg(size(p.public_skills_flat)) AS avg_per_person
            """
            q2_res = session.run(q2_query).single()
            skill_stats = {
                "unique_skills": q2_res["unique_skills"] or 0,
                "total_mentions": q2_res["total_mentions"] or 0,
                "avg_per_person": round(q2_res["avg_per_person"] or 0.0, 2)
            }

            # Q3: Orphan Count
            q3_query = """
            MATCH (p:Personnel) WHERE NOT (p)-[]-()
            RETURN count(p) AS orphan_count
            """
            q3_res = session.run(q3_query).single()
            orphan_count = q3_res["orphan_count"] or 0
            orphan_rate_pct = calc_pct(orphan_count, total_personnel)

            # Q4: Relationships
            q4_query = """
            MATCH ()-[r:CONNECTED_TO]->()
            RETURN count(r) AS total,
                   count(CASE WHEN r.status='accepted' THEN 1 END) AS accepted,
                   count(CASE WHEN r.status='pending'  THEN 1 END) AS pending
            """
            q4_res = session.run(q4_query).single()
            relationship_stats = {
                "total": q4_res["total"] or 0,
                "accepted": q4_res["accepted"] or 0,
                "pending": q4_res["pending"] or 0
            }

            # Q5: Python-side normalisation logic
            q5_query = """
            MATCH (p:Personnel) WHERE p.public_skills IS NOT NULL 
            RETURN p.public_skills AS raw
            """
            q5_records = session.run(q5_query)
            
            all_skills = []
            for record in q5_records:
                raw = record["raw"]
                if not raw:
                    continue
                    
                # Parse JSON string to list
                try:
                    if isinstance(raw, str):
                        skills_list = json.loads(raw)
                    elif isinstance(raw, list):
                        skills_list = raw
                    else:
                        continue
                        
                    if isinstance(skills_list, list):
                        # Ensure all items are strings
                        all_skills.extend([str(s) for s in skills_list])
                except (json.JSONDecodeError, TypeError):
                    continue

            before_unique = len(set(all_skills))
            after_unique = len(set(s.lower().strip() for s in all_skills))
            reduction_pct = 0.0
            if before_unique > 0:
                reduction_pct = round(((before_unique - after_unique) / before_unique) * 100, 2)

            skill_normalization = {
                "before_unique": before_unique,
                "after_unique": after_unique,
                "reduction_pct": reduction_pct
            }

            # Assemble final payload
            eval_data = {
                "node_completeness": node_completeness,
                "skill_stats": skill_stats,
                "orphan_rate_pct": orphan_rate_pct,
                "relationship_stats": relationship_stats,
                "skill_normalization": skill_normalization
            }

            save_json(eval_data, "graph_eval.json")

            # Print Table 1: Node Completeness
            t1_headers = ["Metric", "Value", "Pct (%)"]
            t1_rows = [
                ["Total Personnel", node_completeness["total"], "100.0"],
                ["Has Name", "-", node_completeness["name_pct"]],
                ["Has Skills", "-", node_completeness["skills_pct"]],
                ["Has Summary", "-", node_completeness["summary_pct"]],
                ["Has Embedding", "-", node_completeness["embedding_pct"]],
                ["Has Availability", "-", node_completeness["availability_pct"]],
                ["Orphan Rate", "-", orphan_rate_pct]
            ]
            print_table("TABLE 1: NODE COMPLETENESS", t1_headers, t1_rows)

            # Print Table 2: Relationships + Skills
            t2_headers = ["Stat", "Value"]
            t2_rows = [
                ["Total CONNECTED_TO", relationship_stats["total"]],
                ["Accepted Status", relationship_stats["accepted"]],
                ["Pending Status", relationship_stats["pending"]],
                ["Unique Skills (Flat)", skill_stats["unique_skills"]],
                ["Total Skill Mentions", skill_stats["total_mentions"]],
                ["Avg Skills per Person", skill_stats["avg_per_person"]],
                ["Norm. Before Unique", skill_normalization["before_unique"]],
                ["Norm. After Unique", skill_normalization["after_unique"]],
                ["Norm. Reduction Pct", f"{skill_normalization['reduction_pct']}%"]
            ]
            print_table("TABLE 2: RELATIONSHIPS & SKILLS", t2_headers, t2_rows)

    finally:
        driver.close()

if __name__ == "__main__":
    main()