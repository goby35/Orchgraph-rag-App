from neo4j import GraphDatabase
d = GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("neo4j", "password123"))
with d.session() as s:
    s.run("MATCH (n) DETACH DELETE n")
    for rec in s.run("SHOW CONSTRAINTS").data():
        s.run("DROP CONSTRAINT %s IF EXISTS" % rec["name"])
    for rec in s.run('SHOW INDEXES YIELD name, type WHERE type = "VECTOR"').data():
        s.run("DROP INDEX %s IF EXISTS" % rec["name"])
    print("Cleared all nodes, constraints, and vector indexes")
d.close()
