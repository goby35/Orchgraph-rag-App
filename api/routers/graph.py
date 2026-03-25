from __future__ import annotations
import json
from fastapi import APIRouter, Depends, Query
from neo4j import GraphDatabase
from api.deps import get_current_user
from pipeline.config import settings

router = APIRouter()


def _parse_json_field(value: object) -> list[str]:
    """Parse JSON string field từ Neo4j → list[str]."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


@router.get("")
async def get_graph(
    show_all: bool = Query(False),
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    # 1. Trích xuất ID của user đang đăng nhập (Tùy JWT của Sếp lưu ở field nào)
    user_id = user.get("neo4j_id") or user.get("sub") or user.get("id")

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    try:
        with driver.session() as session:
            if show_all:
                # Lấy giới hạn để không lag browser nếu admin muốn xem toàn cảnh
                query = "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200"
                params = {}
            else:
                # FIX TIER 1: Ego-Graph. Chỉ lấy chính user đó và các quan hệ 1 bước nhảy
                query = """
                MATCH (n {id: $user_id})
                OPTIONAL MATCH (n)-[r]-(m)
                RETURN n, r, m
                """
                params = {"user_id": user_id}

            records = session.run(query, **params)

            nodes = []
            edges = []
            seen_nodes = set()
            seen_edges = set()

            # Hàm con xử lý Động (Dynamic Parsing) cho bất kỳ loại Node nào
            def add_node(node):
                if node is None: return
                
                # Trích xuất ID (neo4j driver trả về object Node)
                node_id = node.get("id") or str(node.element_id)
                if node_id in seen_nodes: return
                
                labels = list(node.labels)
                node_type = labels[0].lower() if labels else "unknown"
                
                # Ưu tiên lấy tên hiển thị (tương thích cho mọi loại Node)
                label = node.get("public_name") or node.get("name") or node.get("title") or node_id
                
                node_data = {
                    "label": label,
                    "type": node_type,
                }
                
                # Giữ nguyên cấu trúc riêng nếu là Personnel để UI không bị vỡ
                if node_type == "personnel":
                    node_data["skills"] = _parse_json_field(node.get("public_skills"))
                    node_data["summary"] = node.get("public_professional_summary", "")
                    node_data["availability"] = bool(node.get("public_is_available", False))
                    
                nodes.append({
                    "id": node_id,
                    "type": node_type, # Quan trọng để React Flow biết dùng Custom Node nào
                    "data": node_data,
                    "position": {"x": 0, "y": 0}
                })
                seen_nodes.add(node_id)

            for record in records:
                n = record.get("n")
                r = record.get("r")
                m = record.get("m")

                # Parse cả 2 đầu của đồ thị
                add_node(n)
                add_node(m)

                # Parse Cạnh (Edges)
                if r is not None:
                    source_id = r.start_node.get("id") or str(r.start_node.element_id)
                    target_id = r.end_node.get("id") or str(r.end_node.element_id)
                    rel_type = r.type
                    edge_id = f"{source_id}-{rel_type}-{target_id}"
                    
                    if edge_id not in seen_edges:
                        # Ưu tiên hiển thị status (VD: accepted), nếu không thì hiện Tên quan hệ (VD: HAS_SKILL)
                        rel_status = r.get("status") or rel_type
                        edges.append({
                            "id": edge_id,
                            "source": source_id,
                            "target": target_id,
                            "label": rel_status,
                            "style": {"stroke": "#22C55E" if rel_status == "accepted" else "#9CA3AF"}
                        })
                        seen_edges.add(edge_id)

    finally:
        driver.close()

    return {"nodes": nodes, "edges": edges}