from neo4j import GraphDatabase
d = GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("neo4j", "password123"))
with d.session() as s:
    for label in ["Document", "Chunk", "Entity"]:
        r = s.run("MATCH (n:%s) RETURN count(n) AS cnt" % label).single()
        print("%s: %d nodes" % (label, r["cnt"]))
    for rtype in ["HAS_CHUNK", "MENTIONS", "RELATED_TO"]:
        r = s.run("MATCH ()-[r:%s]->() RETURN count(r) AS cnt" % rtype).single()
        print("%s: %d rels" % (rtype, r["cnt"]))
    r = s.run("MATCH (d:Document) RETURN d.source_file AS f, labels(d) AS l").single()
    print("Document labels:", r["l"])
    r = s.run('SHOW INDEXES YIELD name, type WHERE type = "VECTOR" RETURN name, type').single()
    if r:
        print("Vector index:", r["name"], r["type"])
    recs = s.run("MATCH (e:Entity) RETURN e.name AS n, e.type AS t LIMIT 3")
    for rec in recs:
        print("Entity:", rec["n"], rec["t"])
    recs = s.run("MATCH (s)-[r:RELATED_TO]->(o) RETURN s.name AS s, r.action AS a, o.name AS o LIMIT 3")
    for rec in recs:
        print("Triplet:", rec["s"], "-->", rec["a"], "-->", rec["o"])
d.close()
