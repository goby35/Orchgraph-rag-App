# Neo4j Aura Compatibility Audit

Date: 2026-04-07

## Scope
Search patterns:
- apoc.
- gds.
- CALL apoc
- CALL gds

## Findings

1. Runtime Python code (pipeline, api, scripts):
- No direct APOC/GDS procedure calls were found.
- Current graph logic is already based on standard Cypher and should run on Aura Free tier.

2. Local Docker configuration:
- docker-compose.yml contains local-only procedure allowlist/unrestricted settings:
  - NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.*
  - NEO4J_dbms_security_procedures_allowlist=apoc.*,gds.*
- This does not apply to Aura and can be ignored for cloud runtime.

3. Documentation/archive references:
- archive_v1/README copy.md references apoc.create.addLabels().
- This is documentation/archive content, not active runtime code.

4. Local Neo4j logs:
- neo4j/logs/debug.log includes many APOC/GDS plugin lines.
- These are local container logs and not part of Aura execution path.

## Replacement status for Aura
- Required in active runtime code: none found.
- If APOC/GDS is introduced later, replace with pure Cypher alternatives.
