#!/usr/bin/env python3
from pathlib import Path
import sys
import os
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env", override=False)

from pipeline.neo4j_client import get_neo4j_driver
from pipeline.config import settings

print("=" * 60)
print(f"Connecting to: {settings.neo4j_uri}")
print(f"Is Aura: {settings.is_aura}")
print("=" * 60)

driver = get_neo4j_driver()
with driver.session(database=settings.neo4j_database) as session:
    print("\nNode counts on Aura:")
    counts = list(session.run(
        "MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt ORDER BY cnt DESC"
    ))
    for r in counts:
        print(f"  {r['label']}: {r['cnt']}")
    
    rel = session.run("MATCH ()-[r]->() RETURN count(r) as cnt").single()
    print(f"\nTotal relationships: {rel['cnt']}")

driver.close()
print("\n✅ Aura connection and data verification successful!")
