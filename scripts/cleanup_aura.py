#!/usr/bin/env python3
from pathlib import Path
import sys
import os
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env", override=False)

from pipeline.neo4j_client import get_neo4j_driver
from pipeline.config import settings

print("Cleaning Aura database...")
driver = get_neo4j_driver()
with driver.session(database=settings.neo4j_database) as session:
    result = session.run("MATCH (n) DETACH DELETE n RETURN count(n) as deleted").single()
    deleted = result["deleted"]
    print(f"✅ Deleted {deleted} nodes from Aura")

driver.close()
