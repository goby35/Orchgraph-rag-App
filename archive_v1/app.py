import json
import importlib
import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4
import time
import bcrypt
import streamlit as st
from neo4j import GraphDatabase
from streamlit_cookies_controller import CookieController
try:
    ui = importlib.import_module("streamlit_shadcn_ui")
except ModuleNotFoundError:
    ui = None

try:
    _agraph_module = importlib.import_module("streamlit_agraph")
    Config = _agraph_module.Config
    Edge = _agraph_module.Edge
    Node = _agraph_module.Node
    agraph = _agraph_module.agraph
    AGRAPH_AVAILABLE = True
except ModuleNotFoundError:
    Config = None
    Edge = None
    Node = None
    agraph = None
    AGRAPH_AVAILABLE = False

try:
    from pipeline.config import get_logger, settings
    from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine, MasterAgentEngine
    from pipeline.main import process_file, update_partial_info, delete_account
except ImportError as e:
    st.error(f"❌ Import pipeline thất bại: {e}\n\nChạy: pip install -r requirements.txt")
    st.stop()

logger = get_logger(__name__)


st.set_page_config(
    page_title="orchgraph-rag",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

    :root {
        --bg0: #080C12;
        --bg1: #0D1219;
        --bg2: #111620;
        --bg3: #171D2B;
        --bg4: #1E2638;
        --border: rgba(255,255,255,0.08);
        --border-m: rgba(255,255,255,0.15);
        --teal: #00C9B8;
        --teal-glow: rgba(0,201,184,0.14);
        --amber: #F59E0B;
        --blue: #3B82F6;
        --purple: #8B5CF6;
        --green: #22C55E;
        --text1: #E8EDF5;
        --text2: #8E99AE;
        --text3: #556070;
    }

    .stApp {
        background: radial-gradient(circle at 0% 0%, #121a28 0%, var(--bg0) 45%), var(--bg0);
        color: var(--text1);
        font-family: 'Outfit', sans-serif;
    }

    h1, h2, h3, h4 {
        font-family: 'Syne', sans-serif !important;
        letter-spacing: 0.01em;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--bg1), #0A0F15) !important;
        border-right: 1px solid var(--border);
    }

    [data-testid="stSidebar"] * {
        color: var(--text1);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
    }

    .hero-shell {
        border: 1px solid var(--border);
        border-radius: 16px;
        background: linear-gradient(145deg, rgba(13,18,25,0.95), rgba(10,14,20,0.95));
        padding: 20px;
        margin-bottom: 14px;
        box-shadow: 0 10px 32px rgba(0, 0, 0, 0.25);
    }

    .hero-label {
        font-family: 'JetBrains Mono', monospace;
        color: var(--text3);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .hero-title {
        font-family: 'Syne', sans-serif;
        font-size: 28px;
        line-height: 1.15;
        font-weight: 800;
        margin-top: 6px;
    }

    .hero-title .teal {
        color: var(--teal);
    }

    .glass-card {
        border: 1px solid var(--border);
        background: linear-gradient(180deg, var(--bg1), var(--bg2));
        border-radius: 14px;
        padding: 14px 16px;
        margin-bottom: 12px;
    }

    .mode-badge {
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        border-radius: 999px;
        padding: 6px 10px;
        display: inline-block;
        border: 1px solid var(--border-m);
    }

    .mode-public {
        color: var(--amber);
        background: rgba(245,158,11,0.12);
        border-color: rgba(245,158,11,0.3);
    }

    .mode-private {
        color: #6ee7b7;
        background: rgba(34,197,94,0.14);
        border-color: rgba(34,197,94,0.32);
    }

    .stButton > button,
    .stForm button[kind="primary"] {
        border-radius: 10px !important;
        border: 1px solid rgba(0,201,184,0.34) !important;
        background: linear-gradient(180deg, rgba(0,201,184,0.22), rgba(0,201,184,0.12)) !important;
        color: #d8fff9 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 12px !important;
    }

    .stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] > div,
    .stFileUploader {
        background: var(--bg2) !important;
        border: 1px solid var(--border-m) !important;
        border-radius: 10px !important;
        color: var(--text1) !important;
    }

    .stTabs [role="tablist"] {
        background: var(--bg1);
        border: 1px solid var(--border);
        padding: 4px;
        border-radius: 10px;
        gap: 6px;
    }

    .stTabs [role="tab"] {
        border-radius: 8px;
        padding: 8px 12px;
        color: var(--text2);
        font-family: 'JetBrains Mono', monospace;
    }

    .stTabs [aria-selected="true"] {
        background: var(--bg4) !important;
        color: var(--teal) !important;
    }

    .stMetric {
        background: linear-gradient(180deg, var(--bg1), var(--bg2));
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 8px 10px;
    }

    .stAgraph {
        border-radius: 14px;
        overflow: hidden;
        border: 1px solid var(--border);
    }

    .skill-badge {
        display: inline-block;
        margin: 2px;
    }
</style>
""",
    unsafe_allow_html=True,
)

DEFAULTS = {
    "ingested_count": 0,
    "search_results": [],
    "accepted_candidates": set(),
    "interview_messages": [],
    "interview_active": False,
    "interview_personnel_id": "",
    "interview_org_id": "",
    "interview_rel_status": "pending",
    "interview_is_private_mode": False,
    "graph_data": None,
    "logged_in_user": "",
    "logged_in_role": "",
    "logged_in_name": "",
}
for key, val in DEFAULTS.items():
    st.session_state.setdefault(key, val)
st.session_state.setdefault("_graph_show_all", False)


def _get_driver():
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

def _generate_session_id(org_id: str, per_id: str) -> str:
    return f"chat_{org_id}_{per_id}"

def _load_chat_history_neo4j(org_id: str, per_id: str) -> list[dict]:
    session_id = _generate_session_id(org_id, per_id)
    try:
        driver = _get_driver()
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (s:ChatSession {id: $session_id})-[:HAS_MESSAGE]->(m:Message)
                RETURN m.role AS role, m.content AS content, m.reasoning AS reasoning,
                       m.is_private_mode AS is_private_mode
                ORDER BY m.timestamp ASC
                """,
                session_id=session_id
            ).data()
            messages = []
            for row in rows:
                msg = {"role": row["role"], "content": row["content"]}
                if row.get("reasoning"):
                    msg["reasoning"] = json.loads(row["reasoning"])
                if row.get("is_private_mode") is not None:
                    msg["is_private_mode"] = row["is_private_mode"]
                messages.append(msg)
            return messages
    except Exception as e:
        logger.error("Lỗi load chat history từ Neo4j: %s", e)
        return []

def _save_chat_message_neo4j(org_id: str, per_id: str, message_dict: dict):
    session_id = _generate_session_id(org_id, per_id)
    role = message_dict.get("role", "user")
    content = message_dict.get("content", "")
    reasoning_str = json.dumps(message_dict.get("reasoning")) if message_dict.get("reasoning") else None
    is_private = message_dict.get("is_private_mode", False)
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:ChatSession {id: $session_id})
                ON CREATE SET s.started_at = datetime(), s.participants = [$org_id, $per_id]
                SET s.last_message_at = datetime()
                WITH s
                MATCH (o:Organization {id: $org_id}), (p:Personnel {id: $per_id})
                MERGE (s)-[:BELONGS_TO]->(o)
                MERGE (s)-[:BELONGS_TO]->(p)
                WITH s
                CREATE (m:Message {
                    role: $role,
                    content: $content,
                    reasoning: $reasoning_str,
                    is_private_mode: $is_private,
                    timestamp: datetime()
                })
                CREATE (s)-[:HAS_MESSAGE]->(m)
                """,
                session_id=session_id, org_id=org_id, per_id=per_id,
                role=role, content=content, reasoning_str=reasoning_str, is_private=is_private
            )
    except Exception as e:
        logger.error("Lỗi save chat message vào Neo4j: %s", e)

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    username_norm = username.strip().lower()
    if not username_norm or not password:
        return None
    cypher = """
    MATCH (u)
    WHERE (u:Organization OR u:Personnel) AND toLower(coalesce(u.username, "")) = $username
    RETURN
        u.id AS user_id,
        labels(u) AS labels,
        coalesce(u.public_name, u.public_full_name, u.name, u.id) AS display_name,
        u.password_hash AS password_hash
    LIMIT 1
    """
    driver = _get_driver()
    try:
        with driver.session() as session:
            row = session.run(cypher, username=username_norm).single()
    finally:
        driver.close()
    if row is None:
        return None
    password_hash = row.get("password_hash")
    if not password_hash:
        return None
    try:
        valid = bcrypt.checkpw(password.encode("utf-8"), str(password_hash).encode("utf-8"))
    except ValueError:
        return None
    if not valid:
        return None
    labels = row.get("labels") or []
    role = "organization" if "Organization" in labels else "personnel"
    return {
        "user_id": str(row.get("user_id") or ""),
        "role": role,
        "name": str(row.get("display_name") or username_norm),
    }


def register_user(username: str, password: str, role: str, name: str, email: str) -> dict[str, str]:
    username_norm = username.strip().lower()
    email_norm = email.strip().lower()
    role_norm = role.strip().lower()
    display_name = name.strip()
    if role_norm not in {"organization", "personnel"}:
        raise ValueError("Role không hợp lệ. Chỉ chấp nhận organization hoặc personnel.")
    if len(password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
    if not username_norm:
        raise ValueError("Username không được để trống.")
    if not display_name:
        raise ValueError("Tên hiển thị không được để trống.")
    if not email_norm:
        raise ValueError("Email không được để trống.")
    label = "Organization" if role_norm == "organization" else "Personnel"
    user_id = str(uuid4())
    password_hash = _hash_password(password)
    driver = _get_driver()
    try:
        with driver.session() as session:
            duplicate = session.run(
                """
                MATCH (u)
                WHERE (u:Organization OR u:Personnel)
                  AND (toLower(coalesce(u.username, "")) = $username
                       OR toLower(coalesce(u.email, "")) = $email)
                RETURN
                    toLower(coalesce(u.username, "")) = $username AS username_taken,
                    toLower(coalesce(u.email, "")) = $email AS email_taken
                LIMIT 1
                """,
                username=username_norm, email=email_norm,
            ).single()
            if duplicate:
                if duplicate.get("username_taken"):
                    raise ValueError("Username đã tồn tại.")
                if duplicate.get("email_taken"):
                    raise ValueError("Email đã tồn tại.")
            session.run(
                f"""
                CREATE (u:{label} {{
                    id: $user_id,
                    username: $username,
                    email: $email,
                    password_hash: $password_hash,
                    public_name: $display_name,
                    public_full_name: $display_name,
                    private_data_blob: "{{}}",
                    public_embeddings_phobert: [],
                    private_embeddings_phobert: [],
                    created_at: datetime(),
                    last_updated: timestamp()
                }})
                """,
                user_id=user_id, username=username_norm, email=email_norm,
                password_hash=password_hash, display_name=display_name,
            )
    finally:
        driver.close()
    return {"user_id": user_id, "role": role_norm, "name": display_name}


def migrate_legacy_passwords(default_password: str = "ChangeMe@123") -> int:
    driver = _get_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (u)
                WHERE (u:Organization OR u:Personnel)
                  AND coalesce(u.username, "") <> ""
                  AND coalesce(u.password_hash, "") = ""
                RETURN u.id AS user_id
                """
            ).data()
            if not rows:
                return 0
            for row in rows:
                session.run(
                    """
                    MATCH (u {id: $user_id})
                    SET u.password_hash = $password_hash, u.last_updated = timestamp()
                    """,
                    user_id=row["user_id"],
                    password_hash=_hash_password(default_password),
                )
            return len(rows)
    finally:
        driver.close()


def _run_auth_migration_once() -> None:
    if st.session_state.get("_auth_migration_done"):
        return
    try:
        updated_count = migrate_legacy_passwords()
        st.session_state["_auth_migration_done"] = True
        st.session_state["_auth_migration_count"] = updated_count
    except Exception as e:
        st.session_state["_auth_migration_done"] = True
        st.session_state["_auth_migration_error"] = str(e)


def _render_page_hero(title: str, subtitle: str) -> None:
    st.markdown(
        (
            "<div class='hero-shell'>"
            f"<div class='hero-label'>{subtitle}</div>"
            f"<div class='hero-title'>{title}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_auth_left_panel() -> None:
    st.markdown(
        """
        <div class='hero-shell'>
            <div class='hero-label'>GraphRAG Platform</div>
            <div class='hero-title'>Tuyen dung the he moi voi <span class='teal'>Graph Reasoning</span> va Digital Twins</div>
            <div class='glass-card'>
                <b>Knowledge Graph (Neo4j)</b><br/>
                Truy van quan he Org-Personnel voi kiem soat truy cap theo relationship status.
            </div>
            <div class='glass-card'>
                <b>Digital Twin Interview</b><br/>
                Chat public/private mode, transparent reasoning, luu lich su hoi thoai.
            </div>
            <div class='glass-card'>
                <b>PhoBERT Vector Search</b><br/>
                Tim ung vien theo Job Description tren personnel_public_idx.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def _safe_card(key: str):
    with st.container(border=True):
        if ui is not None:
            try:
                ui.card(key=f"{key}_shell")
            except Exception:
                pass
        yield


def _safe_metric_card(title: str, content: str, description: str, key: str):
    if ui is not None:
        try:
            ui.metric_card(title=title, content=content, description=description, key=key)
            return
        except Exception:
            pass
    st.metric(label=title, value=content, help=description)


def _safe_button(text: str, variant: str, key: str, disabled: bool = False) -> bool:
    if ui is not None:
        try:
            return bool(ui.button(text=text, variant=variant, key=key, disabled=disabled))
        except Exception:
            pass
    return st.button(text, key=key, disabled=disabled)


def _safe_badge(content: str, variant: str, key: str):
    if ui is not None:
        try:
            ui.badge(content=content, variant=variant, key=key)
            return
        except Exception:
            pass
    st.caption(content)


def _safe_progress(value: int, text: str, key: str):
    if ui is not None:
        try:
            ui.progress(value=value, text=text, key=key)
            return
        except Exception:
            pass
    st.progress(max(0, min(100, value)), text=text)


def _normalize_score(candidate: dict[str, Any]) -> int | None:
    raw_score = (
        candidate.get("score")
        or candidate.get("match_score")
        or candidate.get("relevance")
        or candidate.get("similarity")
    )
    if raw_score is None:
        return None
    try:
        score_val = float(raw_score)
    except (TypeError, ValueError):
        return None
    if score_val <= 1:
        return round(score_val * 100)
    return int(score_val)


def _candidate_to_dict(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return candidate
    return {
        "id": getattr(candidate, "id", ""),
        "full_name": getattr(candidate, "name", ""),
        "name": getattr(candidate, "name", ""),
        "professional_summary": getattr(candidate, "summary", ""),
        "summary": getattr(candidate, "summary", ""),
        "skills": getattr(candidate, "skills", []),
        "score": getattr(candidate, "score", None),
    }


# ── FIX 2: helpers query relationship status từ Neo4j ────────────────────────

@st.cache_data(ttl=30)
def _get_relationship_status(org_id: str, candidate_id: str) -> str | None:
    """
    Query Neo4j lấy trạng thái relationship thực tế.
    Trả về: 'accepted' | 'pending' | None (chưa có relationship).
    Cache 30 giây.
    """
    if not org_id or not candidate_id:
        return None
    try:
        driver = _get_driver()
        with driver.session() as session:
            row = session.run(
                """
                MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p:Personnel {id: $cid})
                RETURN r.status AS status
                LIMIT 1
                """,
                org_id=org_id, cid=candidate_id,
            ).single()
        driver.close()
        return str(row["status"]).lower() if row else None
    except Exception:
        return None


@st.cache_data(ttl=15)
def _count_accepted_connections(org_id: str) -> int:
    """Đếm số Personnel đã accepted. Cache 15 giây."""
    if not org_id:
        return 0
    try:
        driver = _get_driver()
        with driver.session() as session:
            row = session.run(
                """
                MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO {status: 'accepted'}]->(p:Personnel)
                RETURN count(p) AS cnt
                """,
                org_id=org_id,
            ).single()
        driver.close()
        return int(row["cnt"]) if row else 0
    except Exception:
        return 0


def _send_request(candidate_id: str) -> None:
    org_id = str(st.session_state.get("logged_in_user") or "")
    role = str(st.session_state.get("logged_in_role") or "").lower()
    if role != "organization" or not org_id:
        st.toast("❌ Chỉ tài khoản Organization mới có thể Gửi Request", icon="🚨")
        return
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (o:Organization {id: $org_id})
                MERGE (p:Personnel {id: $candidate_id})
                MERGE (o)-[r:CONNECTED_TO]->(p)
                SET r.status = 'pending', r.requested_at = datetime()
                """,
                org_id=org_id, candidate_id=candidate_id,
            )
        st.session_state["graph_data"] = None
        _get_relationship_status.clear()   # invalidate cache
        st.toast(f"✉️ Đã gửi Request phỏng vấn tới: {candidate_id}", icon="✉️")
        st.rerun()
    except Exception as e:
        st.toast(f"❌ Không thể gửi request: {e}", icon="🚨")
        logger.error("Request failed for %s: %s", candidate_id, e, exc_info=True)


def _accept_candidate(candidate_id: str) -> None:
    org_id = str(st.session_state.get("logged_in_user") or "")
    role = str(st.session_state.get("logged_in_role") or "").lower()
    if role != "organization" or not org_id:
        st.toast("❌ Chỉ tài khoản Organization mới có thể Accept", icon="🚨")
        return
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (o:Organization {id: $org_id})
                MERGE (p:Personnel {id: $candidate_id})
                MERGE (o)-[r:CONNECTED_TO]->(p)
                SET r.status = 'accepted', r.accepted_at = datetime(), r.updated_at = datetime()
                """,
                org_id=org_id, candidate_id=candidate_id,
            )
        st.session_state["accepted_candidates"].add(candidate_id)
        st.session_state["graph_data"] = None
        _get_relationship_status.clear()   # invalidate cache
        _count_accepted_connections.clear()
        st.toast(f"🔓 Đã Accept: {candidate_id}", icon="✅")
        st.rerun()
    except Exception as e:
        st.toast(f"❌ Không thể Accept: {e}", icon="🚨")
        logger.error("Accept failed for %s: %s", candidate_id, e, exc_info=True)


def render_ingestion():
    st.subheader("🗂️ Nạp Dữ Liệu")
    _safe_metric_card(
        title="File đã nạp",
        content=str(st.session_state["ingested_count"]),
        description="trong phiên làm việc này",
        key="metric_ingested",
    )
    uploaded = st.file_uploader(
        "Chọn file để nạp vào Neo4j",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "md", "json"],
        help="JSON -> luồng nhanh (không cần LLM). PDF/DOCX/TXT/MD -> Parse + LLM Extract.",
    )
    if uploaded:
        json_files = [f for f in uploaded if f.name.lower().endswith(".json")]
        doc_files = [f for f in uploaded if not f.name.lower().endswith(".json")]
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"⚡ {len(json_files)} file JSON (nhanh)")
        with col2:
            st.caption(f"📄 {len(doc_files)} file tài liệu (cần LLM)")

    process_btn = st.button(
        "▶ Bắt đầu xử lý",
        disabled=not uploaded,
        type="primary",
        key="process_batch_btn",
    )

    if process_btn and uploaded:
        progress = st.progress(0, text="Đang chuẩn bị...")
        total = len(uploaded)
        for idx, file in enumerate(uploaded, start=1):
            suffix = Path(file.name).suffix
            file_type = "JSON" if suffix.lower() == ".json" else "DOC"
            progress.progress(
                (idx - 1) / total,
                text=f"[{idx}/{total}] [{file_type}] {file.name}...",
            )
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file.getvalue())
                    tmp_path = tmp.name
                process_file(
                    Path(tmp_path),
                    target_node_id=st.session_state.get("logged_in_user") or None,
                    target_role=st.session_state.get("logged_in_role") or None,
                )
                st.session_state["ingested_count"] += 1
                st.toast(f"✅ {file.name}", icon="✅")
                logger.info("Ingested: %s", file.name)
            except Exception as e:
                st.toast(f"❌ {file.name}: {e}", icon="🚨")
                logger.error("Failed: %s - %s", file.name, e, exc_info=True)
            finally:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
        progress.progress(1.0, text="Hoàn tất!")
        st.toast(
            f"Batch xử lý xong: {st.session_state['ingested_count']} file thành công",
            icon="🎉",
        )

    st.divider()
    with st.expander("⚙️ Quản lý Tài khoản", expanded=False):
        current_user = str(st.session_state.get("logged_in_user") or "")
        current_role = str(st.session_state.get("logged_in_role") or "")
        if not current_user or not current_role:
            st.info("Vui lòng đăng nhập để quản lý tài khoản.")
            return
        st.caption(f"ID: {current_user} | Role: {current_role}")
        availability_val = st.text_input(
            "Trạng thái làm việc (Availability)",
            placeholder="VD: Sẵn sàng full-time từ tháng 5",
            key="account_availability_input",
        )
        if st.button("Cập nhật trạng thái", key="update_availability_btn"):
            try:
                value = availability_val.strip() if availability_val.strip() else None
                update_partial_info(
                    node_id=current_user, role=current_role,
                    compartment="public_data", field_name="availability", new_value=value,
                )
                st.toast("✅ Cập nhật trạng thái thành công", icon="✅")
            except Exception as e:
                st.toast(f"❌ Cập nhật thất bại: {e}", icon="🚨")
        if st.button("🗑️ Xóa tài khoản", type="primary", key="soft_delete_account_btn"):
            try:
                delete_account(node_id=current_user, role=current_role, hard_delete=False)
                st.toast("🗑️ Tài khoản đã được xóa mềm", icon="🗑️")
                st.session_state["logged_in_user"] = ""
                st.session_state["logged_in_role"] = ""
                st.session_state["logged_in_name"] = ""
                st.session_state["interview_active"] = False
                st.session_state["interview_messages"] = []
                try:
                    controller = CookieController()
                    controller.remove("logged_in_user")
                    controller.remove("logged_in_role")
                    controller.remove("logged_in_name")
                except Exception as cookie_err:
                    logger.warning("Không thể xóa cookie sau soft delete: %s", cookie_err)
                st.rerun()
            except Exception as e:
                st.toast(f"❌ Xóa tài khoản thất bại: {e}", icon="🚨")


def render_search():
    st.subheader("🌐 Tìm Ứng Viên")
    query = st.text_area(
        "Job Description",
        height=180,
        placeholder="Nhập mô tả vị trí tuyển dụng (tiếng Việt hoặc tiếng Anh)...",
    )
    col_btn, col_hint, col_topk = st.columns([1, 3, 1.2])
    with col_btn:
        search_btn = st.button(
            "🔍 Tìm kiếm",
            type="primary",
            disabled=len(query.strip()) < 20,
            key="search_btn",
        )
    with col_hint:
        if len(query.strip()) < 20:
            st.caption("⚠️ Nhập ít nhất 20 ký tự để có kết quả chính xác")
    with col_topk:
        top_k = st.slider("Top-K", min_value=3, max_value=20, value=5, key="search_topk")

    if search_btn:
        with st.spinner("Đang query vector index personnel_public_idx..."):
            try:
                with MasterAgentEngine() as engine:
                    raw_results = engine.search_candidates(query, top_k=top_k)
                st.session_state["search_results"] = [_candidate_to_dict(x) for x in raw_results]
            except Exception as e:
                st.error(f"Lỗi tìm kiếm: {e}")
                st.stop()

    results = st.session_state["search_results"]
    if not results:
        st.info("Chưa có kết quả. Nhập JD và bấm Tìm kiếm.")
        return

    st.caption(f"Tìm thấy {len(results)} ứng viên phù hợp")

    for i, candidate in enumerate(results):
        cid = str(candidate.get("id") or f"candidate_{i}")
        name = candidate.get("full_name", candidate.get("name", "Không rõ tên"))
        title = candidate.get("title", candidate.get("current_position", ""))
        school = candidate.get("school", "")
        skills = candidate.get("skills", [])
        if isinstance(skills, str):
            import ast
            try:
                skills = ast.literal_eval(skills)
            except Exception:
                skills = [s.strip() for s in skills.split(",")]
        if not isinstance(skills, list):
            skills = [str(skills)]
        summary = candidate.get("professional_summary", candidate.get("summary", ""))
        score_pct = _normalize_score(candidate)

        with _safe_card(key=f"card_{cid}"):
            col_info, col_score, col_action = st.columns([3, 1.5, 1.5])

            with col_info:
                st.markdown(f"### {name}")
                if title:
                    st.caption(f"💼 {title}")
                if school:
                    st.caption(f"🎓 {school}")
                if skills:
                    for s_idx, skill in enumerate(skills[:8]):
                        _safe_badge(content=str(skill), variant="secondary",
                                    key=f"badge_{cid}_{s_idx}")
                    if len(skills) > 8:
                        st.caption(f"+{len(skills) - 8} kỹ năng khác")

            with col_score:
                if score_pct is not None:
                    st.markdown(
                        f"<p style='text-align:center;font-weight:600;"
                        f"font-size:1.4rem;margin-bottom:4px'>{score_pct}%</p>",
                        unsafe_allow_html=True,
                    )
                    _safe_progress(value=score_pct, text=f"Match: {score_pct}%",
                                   key=f"prog_{cid}")
                else:
                    st.caption("Score: N/A")

            # ── FIX 2: col_action dùng Neo4j status thực tế ──────────────
            with col_action:
                st.write("")
                org_id = str(st.session_state.get("logged_in_user") or "")
                role   = str(st.session_state.get("logged_in_role") or "").lower()

                if role != "organization":
                    st.caption("Chỉ Org mới có thể gửi request")
                else:
                    rel_status = _get_relationship_status(org_id, cid)

                    if rel_status == "accepted":
                        _safe_badge(content="✅ Accepted", variant="default",
                                    key=f"status_badge_{cid}")
                        if _safe_button("💬 Phỏng vấn ngay", variant="outline",
                                        key=f"goto_interview_{cid}"):
                            st.session_state["_prefill_interview_id"] = cid
                            st.toast(f"Chuyển sang tab Phỏng Vấn để chat với {cid}", icon="💬")

                    elif rel_status == "pending":
                        _safe_badge(content="⏳ Chờ xác nhận", variant="secondary",
                                    key=f"status_badge_{cid}")
                        st.caption("Đang chờ ứng viên accept")

                    else:
                        c_req, c_acc = st.columns(2)
                        with c_req:
                            if _safe_button("✉️ Request", variant="outline",
                                            key=f"req_btn_{cid}"):
                                _send_request(cid)
                        with c_acc:
                            if _safe_button("✅ Accept", variant="default",
                                            key=f"accept_btn_{cid}"):
                                _accept_candidate(cid)

            if summary:
                with st.expander("▼ Xem chi tiết hồ sơ"):
                    st.write(summary)
                    experience = candidate.get("experience", [])
                    if experience:
                        st.markdown("**Kinh nghiệm:**")
                        for exp in experience[:3]:
                            if isinstance(exp, dict):
                                proj = exp.get("project_name", exp.get("title", ""))
                                role_exp = exp.get("role", "")
                                st.markdown(f"- **{proj}** - {role_exp}")
                    education = candidate.get("education", [])
                    if education:
                        st.markdown("**Học vấn:**")
                        edu_list = education if isinstance(education, list) else [education]
                        for edu in edu_list[:2]:
                            if isinstance(edu, dict):
                                st.markdown(
                                    f"- {edu.get('degree', '')} · {edu.get('school', '')} · {edu.get('year', '')}"
                                )


def _render_reasoning(reasoning: dict[str, Any] | None, personnel_id: str, is_private_mode: bool):
    current_org_id = str(st.session_state.get("interview_org_id") or st.session_state.get("logged_in_user") or "ORG")
    with st.expander("🧠 Báo cáo Suy luận (Transparent Reasoning)"):
        st.markdown("**Cypher truy vấn dữ liệu:**")
        if reasoning and reasoning.get("cypher"):
            st.code(str(reasoning["cypher"]), language="cypher")
        else:
            demo_cypher = f"""// Public data (luôn truy cập được)
MATCH (p:Personnel {{id: '{personnel_id}'}})
RETURN p.public_data

// Private data (chỉ khi accepted)
MATCH (o:Organization {{id: '{current_org_id}'}})
      -[:CONNECTED_TO {{status: 'accepted'}}]->
      (p:Personnel {{id: '{personnel_id}'}})
RETURN p.private_data"""
            st.code(demo_cypher, language="cypher")
            st.caption("_Cypher minh họa - engine không trả về query thực tế_")

        if reasoning:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Nguồn dữ liệu", str(reasoning.get("data_source", "N/A")))
            with col_b:
                private_unlocked = bool(reasoning.get("private_unlocked"))
                st.metric("Private access", "✅ Có" if private_unlocked else "🔒 Chỉ Public")
            with col_c:
                st.metric("Tokens dùng", str(reasoning.get("tokens_used", "N/A")))
            if reasoning.get("debug"):
                st.markdown("**Debug log:**")
                st.json(reasoning["debug"])

        if is_private_mode:
            st.success(
                f"📋 Ứng viên {personnel_id} đã được Accept bởi "
                f"{current_org_id} - private data đã được mở khóa."
            )
        else:
            st.info("📋 Phiên hiện tại đang ở chế độ Public. Các thông tin nhạy cảm sẽ được ẩn.")


# ═══════════════════════════════════════════════════════════════════════════════
# INTERVIEW SCHEDULING
# ═══════════════════════════════════════════════════════════════════════════════

def _save_interview_schedule(
    org_id: str, per_id: str, interview_dt: str, fmt: str,
    notes: str = "", meet_link: str = "", address: str = "",
) -> str:
    schedule_id = f"sched_{uuid4().hex[:12]}"
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MATCH (o:Organization {id: $org_id}), (p:Personnel {id: $per_id})
                CREATE (s:InterviewSchedule {
                    id: $schedule_id, org_id: $org_id, per_id: $per_id,
                    interview_dt: $interview_dt, format: $fmt, notes: $notes,
                    meet_link: $meet_link, address: $address,
                    status: "pending", created_at: datetime()
                })
                CREATE (o)-[:SCHEDULED_INTERVIEW {status: "pending", created_at: datetime()}]->(s)
                CREATE (s)-[:FOR_PERSONNEL]->(p)
                """,
                schedule_id=schedule_id, org_id=org_id, per_id=per_id,
                interview_dt=interview_dt, fmt=fmt, notes=notes,
                meet_link=meet_link, address=address,
            )
        driver.close()
    except Exception as e:
        logger.error("Loi luu lich phong van: %s", e)
        raise
    return schedule_id


def _load_interview_invitations(per_id: str) -> list[dict]:
    try:
        driver = _get_driver()
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (s:InterviewSchedule {per_id: $per_id})-[:FOR_PERSONNEL]->(p:Personnel)
                MATCH (o:Organization)-[:SCHEDULED_INTERVIEW]->(s)
                RETURN
                    s.id AS schedule_id, s.interview_dt AS interview_dt,
                    s.format AS fmt, s.notes AS notes, s.meet_link AS meet_link,
                    s.address AS address, s.status AS status, s.alt_dt AS alt_dt,
                    coalesce(o.public_name, o.id) AS org_name, o.id AS org_id
                ORDER BY s.created_at DESC
                """,
                per_id=per_id,
            ).data()
        driver.close()
        return rows
    except Exception as e:
        logger.error("Loi load invitations: %s", e)
        return []


def _respond_to_interview(schedule_id: str, response: str, alt_dt: str = "") -> None:
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MATCH (s:InterviewSchedule {id: $schedule_id})
                SET s.status = $response, s.alt_dt = $alt_dt, s.updated_at = datetime()
                """,
                schedule_id=schedule_id, response=response, alt_dt=alt_dt,
            )
        driver.close()
    except Exception as e:
        logger.error("Loi cap nhat lich: %s", e)
        raise


def _load_org_schedules(org_id: str) -> list[dict]:
    try:
        driver = _get_driver()
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (o:Organization {id: $org_id})-[:SCHEDULED_INTERVIEW]->(s:InterviewSchedule)
                MATCH (s)-[:FOR_PERSONNEL]->(p:Personnel)
                RETURN
                    s.id AS schedule_id, s.interview_dt AS interview_dt,
                    s.format AS fmt, s.status AS status, s.alt_dt AS alt_dt,
                    s.meet_link AS meet_link, s.address AS address,
                    coalesce(p.public_name, p.id) AS per_name, p.id AS per_id
                ORDER BY s.created_at DESC
                """,
                org_id=org_id,
            ).data()
        driver.close()
        return rows
    except Exception as e:
        logger.error("Loi load org schedules: %s", e)
        return []


def _status_badge_html(status: str) -> str:
    cfg = {
        "pending":     ("⏳ Chờ xác nhận", "#F59E0B", "rgba(245,158,11,0.12)"),
        "accepted":    ("✅ Đã đồng ý",     "#22C55E", "rgba(34,197,94,0.14)"),
        "rescheduled": ("🔄 Đề xuất lại",   "#3B82F6", "rgba(59,130,246,0.14)"),
        "rejected":    ("❌ Đã từ chối",     "#EF4444", "rgba(239,68,68,0.14)"),
    }
    label, color, bg = cfg.get(status, ("❓ " + status, "#6B7280", "rgba(107,114,128,0.14)"))
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f"font-size:.75rem;font-family:'JetBrains Mono',monospace;"
        f'color:{color};background:{bg};border:1px solid {color}44">'
        f"{label}</span>"
    )


def render_schedule_form(personnel_id: str, org_id: str) -> None:
    import datetime as _dt
    with st.expander("📅 Tiến hành phỏng vấn trực tiếp", expanded=False):
        st.markdown(
            "<div style='padding:4px 0 12px;font-family:\"Syne\",sans-serif;"
            "font-size:1rem;font-weight:700;color:#E8EDF5'>"
            "🗓️ Đặt lịch phỏng vấn trực tiếp</div>",
            unsafe_allow_html=True,
        )
        fmt = st.radio(
            "Hình thức",
            options=["💻 Online (Google Meet)", "🏢 Offline (Tại văn phòng)"],
            horizontal=True,
            key=f"sched_fmt_{personnel_id}",
        )
        is_online = fmt.startswith("💻")
        col_d, col_t = st.columns(2)
        with col_d:
            interview_date = st.date_input(
                "Ngày phỏng vấn",
                value=_dt.date.today() + _dt.timedelta(days=3),
                min_value=_dt.date.today(),
                key=f"sched_date_{personnel_id}",
            )
        with col_t:
            interview_time = st.time_input(
                "Giờ phỏng vấn", value=_dt.time(10, 0), step=1800,
                key=f"sched_time_{personnel_id}",
            )
        if is_online:
            meet_link = st.text_input(
                "Link Google Meet (tuỳ chọn)",
                placeholder="https://meet.google.com/...",
                key=f"sched_link_{personnel_id}",
            )
            address = ""
        else:
            address = st.text_input(
                "Địa chỉ văn phòng",
                placeholder="Tầng 5, Toà nhà ABC, 123 Nguyễn Huệ, Q.1, TP.HCM",
                key=f"sched_addr_{personnel_id}",
            )
            meet_link = ""
        notes = st.text_area(
            "Ghi chú (tuỳ chọn)",
            placeholder="Mang theo hồ sơ gốc, tìm gặp HR tại lễ tân...",
            height=80,
            key=f"sched_notes_{personnel_id}",
        )
        if st.button(
            "📨 Gửi lời mời lịch phỏng vấn", type="primary",
            key=f"sched_confirm_{personnel_id}", use_container_width=True,
        ):
            interview_dt_iso = _dt.datetime.combine(interview_date, interview_time).isoformat()
            fmt_key = "online" if is_online else "offline"
            try:
                sid = _save_interview_schedule(
                    org_id=org_id, per_id=personnel_id,
                    interview_dt=interview_dt_iso, fmt=fmt_key,
                    notes=notes, meet_link=meet_link, address=address,
                )
                st.success(
                    f"✅ Đã gửi lời mời tới **{personnel_id}**! "
                    f"Ứng viên sẽ thấy trong Hòm thư. _(ID: {sid})_"
                )
                st.balloons()
            except Exception as e:
                st.error(f"❌ Không thể lưu lịch: {e}")


def _render_invitation_card(inv: dict, per_id: str, interactive: bool) -> None:
    import datetime as _dt
    sid       = inv.get("schedule_id", "")
    org_name  = inv.get("org_name", inv.get("org_id", "Tổ chức"))
    raw_dt    = inv.get("interview_dt", "")
    fmt       = inv.get("fmt", "online")
    notes     = inv.get("notes", "")
    meet_link = inv.get("meet_link", "")
    address   = inv.get("address", "")
    status    = inv.get("status", "pending")
    alt_dt    = inv.get("alt_dt", "")
    try:
        dt_display = _dt.datetime.fromisoformat(raw_dt).strftime("%H:%M, %d/%m/%Y")
    except Exception:
        dt_display = raw_dt or "Chưa xác định"
    fmt_icon  = "💻" if fmt == "online" else "🏢"
    fmt_label = "Online (Google Meet)" if fmt == "online" else "Offline (Tại văn phòng)"
    with st.container(border=True):
        st.markdown(
            f"<div style='padding:2px 0 8px'>"
            f"<span style=\"font-family:'Syne',sans-serif;font-size:1.05rem;font-weight:700\">"
            f"🏢 {org_name}</span>&nbsp;&nbsp;"
            + _status_badge_html(status) + "</div>",
            unsafe_allow_html=True,
        )
        extra = ""
        if meet_link:
            extra += f'<br><span style="color:#8E99AE">🔗 <a href="{meet_link}" target="_blank" style="color:#00C9B8">Tham gia Google Meet</a></span>'
        if address:
            extra += f'<br><span style="color:#8E99AE">📍 {address}</span>'
        if notes:
            extra += f'<br><span style="color:#8E99AE">📝 {notes}</span>'
        st.markdown(
            f"<div style='background:rgba(0,201,184,0.06);border:1px solid rgba(0,201,184,0.2);"
            f"border-radius:10px;padding:12px 16px;margin-bottom:10px'>"
            f"<b style='color:#E8EDF5'>✨ {org_name} hài lòng với Bản sao số của bạn<br>"
            f"và muốn đặt lịch phỏng vấn thật!</b><br><br>"
            f"<span style='color:#8E99AE'>📅 Thời gian: <b style='color:#00C9B8'>{dt_display}</b></span><br>"
            f"<span style='color:#8E99AE'>{fmt_icon} Hình thức: <b style='color:#E8EDF5'>{fmt_label}</b></span>"
            + extra + "</div>",
            unsafe_allow_html=True,
        )
        if alt_dt and status == "rescheduled":
            try:
                alt_display = _dt.datetime.fromisoformat(alt_dt).strftime("%H:%M, %d/%m/%Y")
            except Exception:
                alt_display = alt_dt
            st.info(f"🔄 Bạn đã đề xuất giờ khác: **{alt_display}**")
        if interactive:
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Đồng ý lịch", key=f"acc_inv_{sid}",
                             use_container_width=True, type="primary"):
                    try:
                        _respond_to_interview(sid, "accepted")
                        st.toast("🎉 Đã xác nhận lịch phỏng vấn!", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")
            with col_b:
                with st.expander("❌ Đề xuất giờ khác"):
                    import datetime as _dt2
                    alt_d = st.date_input("Ngày khác", key=f"alt_d_{sid}",
                                          min_value=_dt2.date.today())
                    alt_t = st.time_input("Giờ khác", key=f"alt_t_{sid}",
                                          value=_dt2.time(14, 0), step=1800)
                    if st.button("📨 Gửi đề xuất", key=f"alt_send_{sid}", use_container_width=True):
                        alt_iso = _dt2.datetime.combine(alt_d, alt_t).isoformat()
                        try:
                            _respond_to_interview(sid, "rescheduled", alt_iso)
                            st.toast("📨 Đã gửi đề xuất!", icon="🔄")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi: {e}")


def render_interview_invitations() -> None:
    per_id = str(st.session_state.get("logged_in_user") or "")
    if not per_id:
        st.error("Chưa đăng nhập.")
        return
    st.subheader("📬 Hòm thư — Lời mời phỏng vấn")
    if st.button("🔄 Làm mới", key="refresh_invitations"):
        st.rerun()
    invitations = _load_interview_invitations(per_id)
    if not invitations:
        st.info("Chưa có lời mời phỏng vấn nào. Hãy quay lại sau!")
        return
    pending   = [i for i in invitations if i.get("status") == "pending"]
    responded = [i for i in invitations if i.get("status") != "pending"]
    if pending:
        st.markdown(f"### 🔔 Chờ phản hồi &nbsp; `{len(pending)}`", unsafe_allow_html=True)
        for inv in pending:
            _render_invitation_card(inv, per_id, interactive=True)
    if responded:
        st.markdown(f"### 📁 Đã phản hồi &nbsp; `{len(responded)}`", unsafe_allow_html=True)
        for inv in responded:
            _render_invitation_card(inv, per_id, interactive=False)


def render_org_schedule_overview() -> None:
    import datetime as _dt
    org_id = str(st.session_state.get("logged_in_user") or "")
    st.subheader("📅 Lịch Phỏng Vấn Đã Đặt")
    if st.button("🔄 Làm mới", key="refresh_org_sched"):
        st.rerun()
    schedules = _load_org_schedules(org_id)
    if not schedules:
        st.info("Chưa có lịch phỏng vấn nào. Hãy đặt lịch sau khi chat với ứng viên.")
        return
    status_filter = st.selectbox(
        "Lọc theo trạng thái",
        ["Tất cả", "pending", "accepted", "rescheduled", "rejected"],
        key="org_sched_filter",
    )
    filtered = schedules if status_filter == "Tất cả" else [
        s for s in schedules if s.get("status") == status_filter
    ]
    st.caption(f"Hiển thị **{len(filtered)}** / {len(schedules)} lịch hẹn")
    for sch in filtered:
        raw_dt    = sch.get("interview_dt", "")
        alt_dt    = sch.get("alt_dt", "")
        per_name  = sch.get("per_name", sch.get("per_id", "?"))
        status    = sch.get("status", "pending")
        fmt       = sch.get("fmt", "online")
        meet_link = sch.get("meet_link", "")
        try:
            dt_display = _dt.datetime.fromisoformat(raw_dt).strftime("%H:%M, %d/%m/%Y")
        except Exception:
            dt_display = raw_dt
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"**👤 {per_name}**")
                st.caption(f"{'💻' if fmt == 'online' else '🏢'}  {dt_display}")
            with c2:
                st.markdown(_status_badge_html(status), unsafe_allow_html=True)
                if alt_dt and status == "rescheduled":
                    try:
                        alt_disp = _dt.datetime.fromisoformat(alt_dt).strftime("%H:%M, %d/%m/%Y")
                    except Exception:
                        alt_disp = alt_dt
                    st.caption(f"🔄 Đề xuất: {alt_disp}")
            with c3:
                if meet_link:
                    st.markdown(f"[🔗 Mở Meet]({meet_link})")


def _update_request_status(org_id: str, per_id: str, new_status: str):
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(
                """
                MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p:Personnel {id: $per_id})
                SET r.status = $new_status, r.updated_at = datetime()
                """,
                org_id=org_id, per_id=per_id, new_status=new_status
            )
        st.session_state["graph_data"] = None
        _get_relationship_status.clear()
        _count_accepted_connections.clear()
    except Exception as e:
        st.error(f"Lỗi cập nhật trạng thái: {e}")


def render_interview():
    st.subheader("💬 Phỏng Vấn Kín")
    my_id   = str(st.session_state.get("logged_in_user") or "")
    my_role = str(st.session_state.get("logged_in_role") or "").lower()
    if not my_id or my_role not in {"organization", "personnel"}:
        st.error("Thiếu thông tin người dùng đăng nhập. Vui lòng đăng nhập lại.")
        return

    driver = _get_driver()
    try:
        with driver.session() as session:
            if my_role == "organization":
                rows = session.run(
                    """
                    MATCH (o:Organization {id: $my_id})-[r:CONNECTED_TO]->(p:Personnel)
                    RETURN
                        p.id AS target_id,
                        coalesce(p.public_name, p.id) AS target_name,
                        coalesce(r.status, 'pending') AS rel_status
                    ORDER BY target_name
                    """,
                    my_id=my_id,
                ).data()
            else:
                rows = session.run(
                    """
                    MATCH (p:Personnel {id: $my_id})<-[r:CONNECTED_TO]-(o:Organization)
                    RETURN
                        o.id AS target_id,
                        coalesce(o.public_name, o.id) AS target_name,
                        coalesce(r.status, 'pending') AS rel_status
                    ORDER BY target_name
                    """,
                    my_id=my_id,
                ).data()
    finally:
        driver.close()

    options = {
        str(r.get("target_name") or r.get("target_id")): {
            "target_id": str(r.get("target_id") or ""),
            "rel_status": str(r.get("rel_status") or "pending").lower(),
        }
        for r in rows
        if r.get("target_id")
    }

    col_left, col_right = st.columns([1.05, 2.45])
    with col_left:
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("#### Điều khiển phiên chat")

        if my_role == "personnel":
            # ── PERSONNEL SIDE ───────────────────────────────────────────
            pending_orgs = {k: v for k, v in options.items() if v["rel_status"] == "pending"}
            st.markdown("##### Lời mời chờ duyệt")
            if not pending_orgs:
                st.caption("Không có lời mời mới.")
            else:
                for org_name, org_data in pending_orgs.items():
                    org_id_target = org_data["target_id"]
                    with st.container(border=True):
                        st.write(f"**{org_name}**")
                        ca, cb = st.columns(2)
                        with ca:
                            if st.button("Accept", key=f"acc_{org_id_target}"):
                                _update_request_status(org_id_target, my_id, "accepted")
                                st.toast(f"Đã chấp nhận {org_name}", icon="✅")
                                st.rerun()
                        with cb:
                            if st.button("Reject", key=f"rej_{org_id_target}"):
                                _update_request_status(org_id_target, my_id, "rejected")
                                st.toast(f"Đã từ chối {org_name}", icon="⚠️")
                                st.rerun()

            accepted_orgs = [k for k, v in options.items() if v["rel_status"] == "accepted"]
            st.markdown("##### Lịch sử phỏng vấn")
            if accepted_orgs:
                selected_name = st.selectbox("Tổ chức", options=accepted_orgs,
                                             key="personnel_org_select")
                selected_data = options[selected_name]
                org_id, personnel_id = selected_data["target_id"], my_id
                if st.button("Mở lịch sử", key="view_hist_btn"):
                    st.session_state.update({
                        "interview_active": True,
                        "interview_personnel_id": personnel_id,
                        "interview_org_id": org_id,
                        "interview_rel_status": "accepted",
                        "interview_is_private_mode": True,
                        "interview_messages": _load_chat_history_neo4j(org_id, personnel_id),
                    })
                    st.rerun()
            else:
                st.caption("Chưa có kết nối accepted.")

        else:
            # ── FIX 3: ORG SIDE với notification ─────────────────────────
            accepted_count = _count_accepted_connections(my_id)
            if accepted_count > 0:
                st.markdown(
                    f"<div style='background:rgba(34,197,94,0.12);border:1px solid "
                    f"rgba(34,197,94,0.3);border-radius:8px;padding:8px 12px;margin-bottom:12px'>"
                    f"🟢 <b style='color:#22C55E'>{accepted_count} ứng viên</b> đã accept "
                    f"— sẵn sàng phỏng vấn private mode!</div>",
                    unsafe_allow_html=True,
                )

            accepted_options = {k: v for k, v in options.items() if v["rel_status"] == "accepted"}
            pending_options  = {k: v for k, v in options.items() if v["rel_status"] == "pending"}

            selected_name       = None
            selected_id         = ""
            selected_rel_status = "pending"

            if accepted_options:
                st.markdown("##### ✅ Đã accepted — có thể phỏng vấn private")
                selected_name = st.selectbox(
                    "Chọn ứng viên",
                    options=list(accepted_options.keys()),
                    key="org_accepted_select",
                    help="Những ứng viên này đã xác nhận — có thể truy cập private data",
                )
                if selected_name:
                    selected_id         = accepted_options[selected_name]["target_id"]
                    selected_rel_status = "accepted"

            if pending_options:
                st.markdown("##### ⏳ Chờ xác nhận")
                for pname in list(pending_options.keys())[:5]:
                    st.caption(f"• {pname} — đang chờ accept")

            manual_target = st.text_input(
                "Hoặc nhập thẳng Personnel ID",
                placeholder="VD: P_001",
                key="manual_personnel_id",
            ).strip()
            if manual_target:
                selected_id         = manual_target
                selected_name       = manual_target
                selected_rel_status = "pending"

            # Prefill từ Tab 2 "Phỏng vấn ngay"
            prefill = st.session_state.pop("_prefill_interview_id", None)
            if prefill:
                selected_id   = prefill
                selected_name = prefill
                real_status   = _get_relationship_status(my_id, prefill)
                selected_rel_status = real_status or "pending"

            if selected_id:
                org_id, personnel_id = my_id, selected_id
                if selected_rel_status == "accepted":
                    st.markdown(
                        "<span style='color:#22C55E;font-size:.85rem'>"
                        "🔓 Private mode sẽ được bật</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<span style='color:#F59E0B;font-size:.85rem'>"
                        "🔒 Chỉ public mode (chưa accepted)</span>",
                        unsafe_allow_html=True,
                    )
                if _safe_button("💬 Bắt đầu phỏng vấn", variant="default",
                                key="start_interview_btn"):
                    st.session_state.update({
                        "interview_active": True,
                        "interview_personnel_id": personnel_id,
                        "interview_org_id": org_id,
                        "interview_rel_status": selected_rel_status,
                        "interview_is_private_mode": selected_rel_status == "accepted",
                        "interview_messages": _load_chat_history_neo4j(org_id, personnel_id),
                    })
                    st.toast(
                        f"{'🔓 Private' if selected_rel_status == 'accepted' else '🔒 Public'} "
                        f"mode — {selected_name or selected_id}",
                        icon="🤖",
                    )
                    st.rerun()
            else:
                st.info("Chọn ứng viên hoặc nhập Personnel ID để bắt đầu.")

            if not accepted_options and not pending_options:
                st.info("Chưa có kết nối nào. Vào Tab **🌐 Tìm Ứng Viên** để gửi Request.")

        if st.session_state.get("interview_active") and _safe_button(
            "Kết thúc phiên", variant="outline", key="end_interview_btn"
        ):
            st.session_state["interview_active"] = False
            st.session_state["interview_messages"] = []
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    with col_right:
        if not st.session_state.get("interview_active"):
            st.info("Chọn đối tượng và bấm Bắt đầu phỏng vấn.")
            return

        current_private_mode = bool(st.session_state.get("interview_is_private_mode", False))
        if current_private_mode:
            st.markdown(
                "<div class='mode-badge mode-private'>🔓 PRIVATE MODE · Đã mở khóa dữ liệu mật</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='mode-badge mode-public'>🔒 PUBLIC MODE · Chỉ CV công khai được sử dụng</div>",
                unsafe_allow_html=True,
            )

        for msg in st.session_state["interview_messages"]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if msg["role"] == "assistant":
                    _render_reasoning(
                        reasoning=msg.get("reasoning"),
                        personnel_id=st.session_state["interview_personnel_id"],
                        is_private_mode=bool(msg.get("is_private_mode", False)),
                    )

        prompt = st.chat_input(
            "Nhập câu hỏi phỏng vấn...",
            disabled=(not st.session_state.get("interview_active")) or (my_role == "personnel"),
            key="interview_chat_input",
        )
        if not prompt:
            return

        user_msg = {"role": "user", "content": prompt}
        st.session_state["interview_messages"].append(user_msg)
        _save_chat_message_neo4j(
            st.session_state["interview_org_id"],
            st.session_state["interview_personnel_id"],
            user_msg,
        )

        with st.spinner("Digital Twin đang trả lời..."):
            try:
                with DigitalTwinInterviewEngine() as engine:
                    raw_response = engine.answer_interview(
                        org_id=str(st.session_state.get("interview_org_id") or ""),
                        personnel_id=st.session_state["interview_personnel_id"],
                        interview_question=prompt,
                    )
                if isinstance(raw_response, dict):
                    response_text    = str(raw_response.get("answer", raw_response))
                    reasoning_data   = raw_response.get("reasoning")
                    is_private_mode  = bool(raw_response.get("is_private_mode", False))
                    st.session_state["interview_is_private_mode"] = is_private_mode
                    st.session_state["interview_rel_status"] = str(
                        raw_response.get("rel_status") or "pending"
                    ).lower()
                else:
                    response_text   = str(raw_response)
                    reasoning_data  = None
                    is_private_mode = False
            except Exception as e:
                response_text   = str(e)
                reasoning_data  = None
                is_private_mode = False

        assistant_msg = {
            "role": "assistant",
            "content": response_text,
            "reasoning": reasoning_data,
            "is_private_mode": is_private_mode,
        }
        st.session_state["interview_messages"].append(assistant_msg)
        _save_chat_message_neo4j(
            st.session_state["interview_org_id"],
            st.session_state["interview_personnel_id"],
            assistant_msg,
        )
        st.rerun()

    # Đặt lịch phỏng vấn trực tiếp (Org only, sau khi có tin nhắn)
    if (
        st.session_state.get("interview_active")
        and my_role == "organization"
        and st.session_state.get("interview_messages")
    ):
        st.divider()
        _pid = st.session_state.get("interview_personnel_id", "")
        _oid = st.session_state.get("interview_org_id", "")
        if _pid and _oid:
            render_schedule_form(_pid, _oid)


def _fetch_graph_data(show_all: bool) -> list[dict[str, Any]]:
    driver = _get_driver()
    try:
        with driver.session() as session:
            if show_all:
                return session.run(
                    """
                    MATCH (p:Personnel)
                    OPTIONAL MATCH (o:Organization)-[r:CONNECTED_TO]->(p)
                    RETURN
                        p.id AS personnel_id,
                        p.full_name AS personnel_name,
                        o.id AS org_id,
                        r.status AS rel_status
                    LIMIT 200
                    """
                ).data()
            return session.run(
                """
                MATCH (o:Organization)-[r:CONNECTED_TO]->(p:Personnel)
                RETURN
                    o.id AS org_id,
                    p.id AS personnel_id,
                    p.full_name AS personnel_name,
                    r.status AS rel_status
                LIMIT 200
                """
            ).data()
    finally:
        driver.close()


def render_graph():
    st.subheader("🕸️ Knowledge Graph")
    if not AGRAPH_AVAILABLE:
        st.error("Thiếu dependency streamlit-agraph. Cài bằng: pip install streamlit-agraph>=0.0.45")
        return

    assert Config is not None and Node is not None and Edge is not None and agraph is not None

    col_ctrl, col_graph = st.columns([1, 3])
    with col_ctrl:
        with _safe_card("graph_controls"):
            st.markdown("### ⚙️ Điều khiển")
            show_all = st.toggle("Hiển thị tất cả Personnel", value=False, key="toggle_show_all")
            st.caption("Tắt: chỉ hiện node có CONNECTED_TO relationship")
            refresh_btn = _safe_button(text="🔄 Làm mới đồ thị", variant="outline",
                                       key="refresh_graph")
            st.markdown("---")
            st.markdown("**Chú thích:**")
            st.markdown("🔵 Organization")
            st.markdown("🟠 Personnel")
            st.markdown("🟢 Edge: accepted")
            st.markdown("⚪ Edge: pending")

    with col_graph:
        if st.session_state.get("_graph_show_all") != show_all:
            st.session_state["graph_data"] = None
            st.session_state["_graph_show_all"] = show_all

        if st.session_state["graph_data"] is None or refresh_btn:
            with st.spinner("Đang tải dữ liệu từ Neo4j..."):
                try:
                    st.session_state["graph_data"] = _fetch_graph_data(show_all)
                except Exception as e:
                    st.error(f"Không thể fetch graph data: {e}")
                    st.session_state["graph_data"] = []

        records = st.session_state["graph_data"] or []
        if not records:
            st.info("Graph trống. Hãy Accept ít nhất một ứng viên ở Tab 2.")
            return

        nodes: list[Any] = []
        edges: list[Any] = []
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str]] = set()

        for row in records:
            org_id = row.get("org_id")
            pid    = row.get("personnel_id")
            pname  = row.get("personnel_name") or pid
            status = row.get("rel_status") or "pending"

            if org_id and org_id not in seen_nodes:
                nodes.append(Node(id=org_id, label=org_id, size=30, color="#4F8EF7",
                                  shape="ellipse", title=f"Organization: {org_id}"))
                seen_nodes.add(org_id)

            if pid and pid not in seen_nodes:
                nodes.append(Node(id=pid, label=pname or pid, size=20, color="#F7894F",
                                  shape="dot", title=f"Personnel: {pname}\nID: {pid}"))
                seen_nodes.add(pid)

            if org_id and pid:
                edge_key = (org_id, pid)
                if edge_key not in seen_edges:
                    edge_color = "#4CAF50" if status == "accepted" else "#BDBDBD"
                    edges.append(Edge(source=org_id, target=pid, label=status,
                                      color=edge_color, width=2 if status == "accepted" else 1))
                    seen_edges.add(edge_key)

        config = Config(
            width="100%", height=550, directed=True, physics=True,
            hierarchical=False, nodeHighlightBehavior=True, highlightColor="#FFD700",
            collapsible=False, node={"labelProperty": "label"},
            link={"labelProperty": "label", "renderLabel": True},
        )
        clicked_node = agraph(nodes=nodes, edges=edges, config=config)
        if clicked_node:
            st.markdown(f"**Node được chọn:** `{clicked_node}`")
            relevant = [r for r in records
                        if r.get("personnel_id") == clicked_node or r.get("org_id") == clicked_node]
            if relevant:
                st.json(relevant[0])
        st.caption(f"Hiển thị {len(nodes)} nodes · {len(edges)} edges")


def main():
    _render_page_hero("Orchgraph-RAG Platform", "GraphRAG / Neo4j / Vector Search")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🗂️ Nạp Dữ Liệu", "🌐 Tìm Ứng Viên",
        "💬 Phỏng Vấn Kín", "📅 Lịch Phỏng Vấn", "🕸️ Knowledge Graph",
    ])
    with tab1: render_ingestion()
    with tab2: render_search()
    with tab3: render_interview()
    with tab4: render_org_schedule_overview()
    with tab5: render_graph()


def main_personnel():
    _render_page_hero("Orchgraph-RAG Platform", "Personnel Workspace")
    tab1, tab2, tab3, tab4 = st.tabs([
        "🗂️ Nạp Dữ Liệu", "📬 Hòm thư",
        "💬 Phỏng Vấn Kín", "🕸️ Knowledge Graph",
    ])
    with tab1: render_ingestion()
    with tab2: render_interview_invitations()
    with tab3: render_interview()
    with tab4: render_graph()


def run_app_with_authentication():
    _run_auth_migration_once()

    controller = CookieController(key="digital_twin_auth")  # thêm key để namespace cookie, tránh xung đột

    # ── BƯỚC 1: Thử đọc cookie ngay lập tức ────────────────────────────────
    saved_user   = controller.get("logged_in_user")
    saved_role   = controller.get("logged_in_role")
    saved_name   = controller.get("logged_in_name")

    # ── BƯỚC 2: Nếu cookie chưa sẵn sàng (None) → chờ 1 frame & rerun ───────
    if saved_user is None and not st.session_state.get("_cookie_waited", False):
        with st.spinner("Đang khôi phục phiên làm việc từ cookie..."):
            time.sleep(0.08)  # rất ngắn, đủ để JS chạy
        st.session_state["_cookie_waited"] = True
        st.rerun()  # quay lại ngay lập tức, lần này cookie thường đã có

    # ── BƯỚC 3: Nếu có cookie → khôi phục session ───────────────────────────
    if saved_user:
        # Chỉ cập nhật nếu session chưa có (tránh ghi đè khi đã login)
        if not st.session_state.get("logged_in_user"):
            st.session_state["logged_in_user"] = saved_user
            st.session_state["logged_in_role"] = saved_role or ""
            st.session_state["logged_in_name"] = saved_name or ""
            st.session_state["_cookie_waited"] = False  # reset flag
            st.rerun()  # ép UI cập nhật giao diện ngay

    # ── BƯỚC 4: Đăng xuất ──────────────────────────────────────────────────
    if st.session_state.get("logged_in_user"):
        st.sidebar.markdown(f"Chào **{st.session_state.get('logged_in_name', 'User')}**")
        st.sidebar.caption(f"Role: {st.session_state.get('logged_in_role')}")
        
        if st.sidebar.button("🚪 Đăng xuất", key="logout_btn"):
            st.session_state["logged_in_user"] = ""
            st.session_state["logged_in_role"] = ""
            st.session_state["logged_in_name"] = ""
            st.session_state["_cookie_waited"] = False
            st.session_state["interview_active"] = False
            st.session_state["interview_messages"] = []
            
            # Xóa cookie
            controller.remove("logged_in_user")
            controller.remove("logged_in_role")
            controller.remove("logged_in_name")
            
            st.rerun()
        
        # Chọn giao diện theo role
        if st.session_state["logged_in_role"] == "organization":
            main()
        else:
            main_personnel()
        return

    # ── Login / Register ─────────────────────────────────────────────────────
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        _render_auth_left_panel()

    with right:
        _render_page_hero("Chào mừng trở lại", "Đăng nhập để truy cập nền tảng")

        if st.session_state.get("_auth_migration_error"):
            st.warning(f"Migration lỗi: {st.session_state['_auth_migration_error']}")
        elif st.session_state.get("_auth_migration_count", 0) > 0:
            st.info(f"Đã migration password cho {st.session_state['_auth_migration_count']} node cũ.")

        login_tab, register_tab = st.tabs(["Đăng nhập", "Đăng ký"])

        with login_tab:
            with st.form("login_form"):
                username  = st.text_input("Username")
                password  = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Đăng nhập", type="primary")

            if submitted:
                try:
                    user = authenticate_user(username, password)
                except Exception as e:
                    st.error(f"Lỗi đăng nhập: {e}")
                    user = None

                if user:
                    st.session_state["logged_in_user"] = user["user_id"]
                    st.session_state["logged_in_role"] = user["role"]
                    st.session_state["logged_in_name"] = user["name"]
                    st.session_state["_cookie_restore_done"] = True
                    controller.set("logged_in_user", user["user_id"])
                    controller.set("logged_in_role", user["role"])
                    controller.set("logged_in_name", user["name"])
                    st.success("Đăng nhập thành công")
                    st.rerun()
                else:
                    st.error("Username hoặc password không đúng")

        with register_tab:
            with st.form("register_form"):
                name      = st.text_input("Họ và tên")
                email     = st.text_input("Email")
                username  = st.text_input("Username", key="register_username")
                password  = st.text_input("Password", type="password", key="register_password")
                role      = st.selectbox("Role", options=["organization", "personnel"])
                submitted = st.form_submit_button("Tạo tài khoản", type="primary")

            if submitted:
                try:
                    created_user = register_user(
                        username=username, password=password,
                        role=role, name=name, email=email,
                    )
                    st.success(
                        f"Đăng ký thành công. User ID: {created_user['user_id']}. "
                        f"Mời bạn đăng nhập."
                    )
                except ValueError as ve:
                    st.error(str(ve))
                except Exception as e:
                    st.error(f"Đăng ký thất bại: {e}")


if __name__ == "__main__":
    run_app_with_authentication()