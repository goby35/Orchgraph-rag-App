"""Neo4j ingestion theo dual-write pattern.

Giữ nguyên toàn bộ flat properties legacy (cho API/index hiện tại),
đồng thời ghi thêm graph nodes trung gian để phục vụ truy vấn Phase 5.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict
from neo4j import GraphDatabase

from pipeline.config import settings, get_logger
from pipeline.schemas import RecruitmentNode, _normalize_entity

logger = get_logger(__name__)

class Neo4jIngestion:
    def __init__(self):
        self._uri = settings.NEO4J_URI
        self._user = settings.NEO4J_USER
        self._password = settings.NEO4J_PASSWORD
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        
    def close(self):
        self._driver.close()

    def _execute_write(self, func, *args, **kwargs):
        with self._driver.session() as session:
            if hasattr(session, "execute_write"):
                return session.execute_write(func, *args, **kwargs)
            write_tx = getattr(session, "write_transaction", None)
            if callable(write_tx):
                return write_tx(func, *args, **kwargs)
            raise RuntimeError("Neo4j session does not support execute_write/write_transaction")

    def verify_connection(self) -> bool:
        """Kiểm tra kết nối Neo4j"""
        try:
            self._driver.verify_connectivity()
            logger.info("Kết nối Neo4j thành công.")
            return True
        except Exception as e:
            logger.error(f"Lỗi kết nối Neo4j: {e}")
            return False

    def setup_indices(self):
        """Khởi tạo các index cần thiết"""
        def _create_indices(tx):
            try:
                tx.run("CREATE INDEX IF NOT EXISTS FOR (p:Personnel) ON (p.id);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (o:Organization) ON (o.id);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (t:TechStack) ON (t.name);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (s:School) ON (s.name);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (r:Role) ON (r.name);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (e:Experience) ON (e.id);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (e:Education) ON (e.id);")
                tx.run("CREATE INDEX IF NOT EXISTS FOR (o:Organization) ON (o.name);")
                logger.info("Đã thiết lập indices cho Personnel và Organization.")
            except Exception as e:
                logger.warning(f"Không thể tạo index hoặc index đã tồn tại: {e}")
        self._execute_write(_create_indices)

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
        return []

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
        return {}

    @staticmethod
    def _clean_skill_list(raw_skills: list[Any]) -> list[str]:
        """Normalize dirty legacy skill strings before MERGE TechStack.

        Examples:
        - "airflow (ml pipeline orchestration)" -> "airflow"
        - "kubernetes / helm" -> ["kubernetes", "helm"]
        """
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_skills:
            if not isinstance(item, str):
                continue

            text = re.sub(r"\s*\(.*?\)", "", item).strip().lower()
            if not text:
                continue

            parts = re.split(r"[/,]", text)
            for part in parts:
                candidate = part.strip()
                if not candidate or len(candidate) <= 1:
                    continue
                normalized = _normalize_entity(candidate)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    cleaned.append(normalized)

        return cleaned

    def ingest_personnel_graph(self, node: RecruitmentNode) -> bool:
        """Ghi graph nodes trung gian cho Personnel (idempotent)."""
        # Defensive normalization to absorb legacy degree labels before graph writes.
        node = RecruitmentNode.model_validate(node.model_dump())
        personnel_id = node.personnel_id or ""
        if not personnel_id:
            logger.warning("Bỏ qua graph ingest vì thiếu personnel_id")
            return False

        pub = node.public_data

        skills = self._clean_skill_list(self._as_list(pub.skills))

        educations: list[dict[str, Any]] = []
        for item in self._as_list(pub.education):
            if isinstance(item, dict):
                educations.append(item)
            else:
                try:
                    educations.append(item.model_dump())
                except Exception:
                    pass

        experiences: list[dict[str, Any]] = []
        for item in self._as_list(pub.experience):
            if isinstance(item, dict):
                experiences.append(item)
            else:
                try:
                    experiences.append(item.model_dump())
                except Exception:
                    pass

        def _write_graph(tx):
            if skills:
                tx.run(
                    """
                    MATCH (p:Personnel {id: $personnel_id})
                    UNWIND $skills AS skill_name
                    MERGE (t:TechStack {name: skill_name})
                    MERGE (p)-[:HAS_SKILL]->(t)
                    """,
                    personnel_id=personnel_id,
                    skills=skills,
                )

            for idx, edu in enumerate(educations):
                edu_key = f"{personnel_id}::edu::{idx}"
                school_name = str(edu.get("school") or "").strip()
                degree = str(edu.get("degree") or "").strip()
                major = str(edu.get("major") or "").strip()
                year = edu.get("year")
                try:
                    year = int(year) if year is not None else None
                except (TypeError, ValueError):
                    year = None

                tx.run(
                    """
                    MATCH (p:Personnel {id: $personnel_id})
                    MERGE (e:Education {id: $edu_id})
                    SET e.degree = $degree,
                        e.major = $major,
                        e.year = $year
                    MERGE (p)-[:HAS_EDUCATION]->(e)
                    """,
                    personnel_id=personnel_id,
                    edu_id=edu_key,
                    degree=degree,
                    major=major,
                    year=year,
                )

                if school_name:
                    tx.run(
                        """
                        MATCH (e:Education {id: $edu_id})
                        MERGE (s:School {name: $school_name})
                        MERGE (e)-[:AT_SCHOOL]->(s)
                        """,
                        edu_id=edu_key,
                        school_name=school_name,
                    )

            for idx, exp in enumerate(experiences):
                exp_key = f"{personnel_id}::exp::{idx}"
                project_name = str(exp.get("project_name") or "").strip()
                role_name = str(exp.get("role") or "").strip()
                org_name = str(exp.get("organization_name") or "").strip()
                tech_stack = self._clean_skill_list(self._as_list(exp.get("tech_stack")))

                tx.run(
                    """
                    MATCH (p:Personnel {id: $personnel_id})
                    MERGE (ex:Experience {id: $exp_id})
                    SET ex.project_name = $project_name
                    MERGE (p)-[:HAS_EXPERIENCE]->(ex)
                    """,
                    personnel_id=personnel_id,
                    exp_id=exp_key,
                    project_name=project_name,
                )

                if role_name:
                    tx.run(
                        """
                        MATCH (ex:Experience {id: $exp_id})
                        MERGE (r:Role {name: $role_name})
                        MERGE (ex)-[:IN_ROLE]->(r)
                        """,
                        exp_id=exp_key,
                        role_name=role_name,
                    )

                if org_name:
                    tx.run(
                        """
                        MATCH (ex:Experience {id: $exp_id})
                        MERGE (o:Organization {name: $org_name})
                        MERGE (ex)-[:AT_ORGANIZATION]->(o)
                        """,
                        exp_id=exp_key,
                        org_name=org_name,
                    )

                if tech_stack:
                    tx.run(
                        """
                        MATCH (ex:Experience {id: $exp_id})
                        UNWIND $tech_stack AS tech_name
                        MERGE (t:TechStack {name: tech_name})
                        MERGE (ex)-[:USED_TECH]->(t)
                        """,
                        exp_id=exp_key,
                        tech_stack=tech_stack,
                    )

            tx.run(
                """
                MATCH (p:Personnel {id: $personnel_id})
                SET p._has_graph_nodes = true,
                    p._graph_nodes_updated_at = timestamp()
                """,
                personnel_id=personnel_id,
            )

        try:
            self._execute_write(_write_graph)
            logger.debug("Đã graph-ingest Personnel %s", personnel_id)
            return True
        except Exception as exc:
            logger.error("Lỗi graph-ingest Personnel %s: %s", personnel_id, exc)
            return False
                
    def ingest_node(
        self,
        node_data: Dict[str, Any],
        target_node_id: str | None = None,
        target_role: str | None = None,
    ):
        """
        Nhập node đơn (Personnel hoặc Organization)
        Sử dụng MERGE để tạo node, kèm prefix public_ và data dump private_
        """
        node_id = target_node_id or node_data.get("node_id")
        if not node_id:
            logger.error("Bỏ qua ingest vì thiếu node_id")
            return

        role_hint = (target_role or "").strip().upper()
        if role_hint in {"ORGANIZATION", "ORG"}:
            record_type_raw = "ORGANIZATION"
        elif role_hint in {"PERSONNEL", "HR", "CANDIDATE"}:
            record_type_raw = "PERSONNEL"
        else:
            record_type_raw = str(node_data.get("record_type", "PERSONNEL")).upper().strip()
        label = "Organization" if record_type_raw == "ORGANIZATION" else "Personnel"
        
        public_data = node_data.get("public_data", {})
        public_embeddings = node_data.get("public_embeddings_phobert", [])
        private_data = node_data.get("private_data", {})
        private_embeddings = node_data.get("private_embeddings_phobert", [])
        source_file = node_data.get("source_file", "unknown")

        # Flat map public fields: prepend 'public_'
        flat_props = {}
        for k, v in public_data.items():
            if k in {"id", "personnel_id", "org_id"}:
                continue
            val = v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)
            flat_props[f"public_{k}"] = val

        # Giữ thêm field list dễ query/filter cho path legacy hiện hữu.
        if isinstance(public_data.get("skills"), list):
            flat_props["public_skills_flat"] = self._clean_skill_list(public_data.get("skills", []))

        if "is_available" in public_data:
            flat_props["public_availability"] = (
                "Open_for_offers" if bool(public_data.get("is_available")) else "Not_available"
            )
            

        cypher = f"""
        MERGE (n:{label} {{id: $node_id}})
        SET n += $public_props,
            n.public_embeddings_phobert = $public_embeddings,
            n.source_file = $source_file,
            n.last_updated = timestamp()
        RETURN n
        """
        try:
            def _merge(tx):
                res = tx.run(
                    cypher,
                    node_id=node_id,
                    public_props=flat_props,
                    public_embeddings=public_embeddings,
                    source_file=source_file,
                )
                return res.single()

            self._execute_write(_merge)

            # Dual-write graph layer cho Personnel nhưng không ảnh hưởng flow legacy.
            if label == "Personnel":
                try:
                    node_payload = {
                        "personnel_id": node_id,
                        "public_data": public_data,
                        "private_data": private_data,
                    }
                    recruitment_node = RecruitmentNode.model_validate(node_payload)
                    self.ingest_personnel_graph(recruitment_node)
                except Exception as graph_exc:
                    logger.error("Graph write lỗi cho %s: %s", node_id, graph_exc)

            logger.debug(f"Đã ingest node {node_id} ({label})")
        except Exception as e:
            logger.error(f"Lỗi khi ingest node {node_id}: {e}")

neo4j_service = Neo4jIngestion()
