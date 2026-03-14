# -*- coding: utf-8 -*-
"""
GraphRAG Digital Twin -- Streamlit App
Fully functional: Guest overview + Admin pipeline + Chat hybrid search
"""

import html
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# == PAGE CONFIG ===============================================================
st.set_page_config(
    page_title="GraphRAG . Digital Twin",
    page_icon="\u2b21",
    layout="wide",
    initial_sidebar_state="expanded",
)

# == BACKEND IMPORTS ===========================================================
PIPELINE_AVAILABLE = False
QUERY_AVAILABLE = False
NEO4J_AVAILABLE = False
NEO4J_INGESTION_AVAILABLE = False

try:
    from pipeline.config import settings as _settings
    _NEO4J_URI = _settings.NEO4J_URI
    _NEO4J_USER = _settings.NEO4J_USER
    _NEO4J_PASSWORD = _settings.NEO4J_PASSWORD
except ImportError:
    _settings = None
    _NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    _NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    _NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    pass

try:
    from pipeline.parser import parse_document
    from pipeline.cleaner import clean_vietnamese_text
    from pipeline.chunker import chunk_cleaned_text
    from pipeline.extractor import extract_knowledge
    from pipeline.vectorizer import prepare_for_neo4j
    from pipeline.main import save_neo4j_ready, _detect_core_entity
    PIPELINE_AVAILABLE = True
except ImportError as _e:
    st.session_state.setdefault("_pipeline_err", str(_e))

try:
    from pipeline.hybrid_query_engine import ask as hybrid_ask
    QUERY_AVAILABLE = True
except ImportError as _e:
    st.session_state.setdefault("_query_err", str(_e))

try:
    from pipeline.neo4j_ingestion import Neo4jIngestor
    NEO4J_INGESTION_AVAILABLE = True
except ImportError as _e:
    st.session_state.setdefault("_ingest_err", str(_e))

# == CONSTANTS =================================================================
NEO4J_READY_ROOT = Path("./neo4j_ready")

DOC_TYPES = {
    "cv":      "\U0001f464 CV Nh\u00e2n s\u1ef1",
    "sop":     "\U0001f4cb SOP",
    "project": "\U0001f4c1 D\u1ef1 \u00e1n",
}

EMBED_MODELS: Dict[str, Tuple[str, int, str]] = {
    "PhoBERT v2 (768d)": ("phobert_v2", 768,  "phobert-v2"),
    "BGE-M3 (1024d)":    ("bge_m3",     1024, "bge-m3"),
    "GTE (768d)":        ("gte",        768,  "gte"),
}

PIPELINE_STEPS = ["PARSE", "CLEAN", "CHUNK", "EXTRACT", "VECTORIZE"]
STEP_ICONS_MAP = {"waiting": "\u25cb", "running": "\u25c9", "done": "\u2713", "error": "\u2717"}
STEP_CSS_MAP   = {"waiting": "s-wait", "running": "s-run", "done": "s-done", "error": "s-err"}

# == SESSION STATE =============================================================
def init_session():
    defaults = {
        "messages":       [],
        "pending_query":  None,
        "pipeline_steps": {s: {"status": "waiting", "duration": None} for s in PIPELINE_STEPS},
        "pipeline_logs":  [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# == CSS =======================================================================
def inject_css():
    st.html("""
    <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
    :root {
        --bg:#0A0E1A;--bg2:#111827;--bg3:#1C2333;
        --cyan:#00D4FF;--violet:#7C3AED;--emerald:#10B981;
        --amber:#F59E0B;--red:#EF4444;
        --txt:#F9FAFB;--muted:#6B7280;--border:#1F2D40;
    }
    #MainMenu,footer{visibility:hidden}
    .stApp{background:var(--bg);color:var(--txt);font-family:'DM Sans',sans-serif}
    .block-container{padding-top:4rem!important;max-width:1200px}
    header[data-testid="stHeader"]{background:rgba(10,14,26,.6)!important;backdrop-filter:blur(12px)!important;-webkit-backdrop-filter:blur(12px)!important}
    ::-webkit-scrollbar{width:5px}
    ::-webkit-scrollbar-thumb{background:var(--cyan);border-radius:3px}

    [data-testid="stSidebar"]{background:var(--bg2)!important;border-right:1px solid var(--border)}
    [data-testid="stSidebar"] *{color:var(--txt)!important}

    .g-logo{font-family:'Space Mono',monospace;font-size:1.5rem;font-weight:700;
      background:linear-gradient(135deg,var(--cyan),var(--violet));
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:2px}
    .g-sub{color:var(--muted)!important;font-size:.75rem;margin-bottom:1rem}

    .stRadio>div{gap:4px!important}
    .stRadio>div>label{background:var(--bg3)!important;border:1px solid var(--border)!important;
      border-radius:8px!important;padding:8px 14px!important;cursor:pointer!important}
    .stRadio>div>label:has(input:checked){border-color:var(--cyan)!important;background:rgba(0,212,255,.08)!important}

    .dot-g{display:inline-block;width:8px;height:8px;border-radius:50%;
      background:var(--emerald);box-shadow:0 0 5px var(--emerald);margin-right:5px}
    .dot-r{display:inline-block;width:8px;height:8px;border-radius:50%;
      background:var(--red);box-shadow:0 0 5px var(--red);margin-right:5px}

    .card{background:rgba(17,24,39,.85);border:1px solid var(--border);
      border-radius:12px;padding:1.2rem;backdrop-filter:blur(8px);transition:border-color .25s}
    .card:hover{border-color:var(--cyan)}
    .bar-c{height:3px;border-radius:2px;background:var(--cyan);margin-top:10px}
    .bar-v{height:3px;border-radius:2px;background:var(--violet);margin-top:10px}
    .bar-e{height:3px;border-radius:2px;background:var(--emerald);margin-top:10px}

    .b-c{display:inline-block;font-family:'Space Mono',monospace;font-size:.68rem;
      padding:2px 9px;border-radius:999px;font-weight:700;
      background:rgba(0,212,255,.12);color:var(--cyan);border:1px solid rgba(0,212,255,.3)}
    .b-v{display:inline-block;font-family:'Space Mono',monospace;font-size:.68rem;
      padding:2px 9px;border-radius:999px;font-weight:700;
      background:rgba(124,58,237,.12);color:var(--violet);border:1px solid rgba(124,58,237,.3)}
    .b-e{display:inline-block;font-family:'Space Mono',monospace;font-size:.68rem;
      padding:2px 9px;border-radius:999px;font-weight:700;
      background:rgba(16,185,129,.12);color:var(--emerald);border:1px solid rgba(16,185,129,.3)}
    .b-g{display:inline-block;font-family:'Space Mono',monospace;font-size:.68rem;
      padding:2px 9px;border-radius:999px;
      background:rgba(107,114,128,.12);color:var(--muted);border:1px solid rgba(107,114,128,.3)}

    @keyframes blob{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(20px,-15px) scale(1.04)}}
    .hero{position:relative;overflow:hidden;background:var(--bg2);border-radius:16px;
      border:1px solid var(--border);padding:2.5rem 2rem;margin-bottom:1.5rem}
    .hero-blob{position:absolute;width:300px;height:300px;border-radius:50%;
      background:linear-gradient(135deg,var(--cyan),var(--violet));
      filter:blur(90px);opacity:.35;top:-60px;right:-40px;animation:blob 9s ease-in-out infinite}
    .hero-inner{position:relative;z-index:1}
    .hero-h{font-family:'Space Mono',monospace;font-size:2rem;font-weight:700;color:var(--txt);line-height:1.2}
    .hero-line{width:60px;height:3px;background:var(--cyan);border-radius:2px;margin:10px 0}
    .hero-sub{color:var(--muted);font-family:'Space Mono',monospace;font-size:.9rem}

    .step{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:8px;margin-bottom:4px;
      background:var(--bg3);border:1px solid var(--border);font-size:.87rem}
    .step-ic{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;
      justify-content:center;font-size:.72rem;flex-shrink:0;font-weight:700}
    .s-wait .step-ic{background:rgba(107,114,128,.2);color:var(--muted)}
    .s-run  .step-ic{background:rgba(0,212,255,.18);color:var(--cyan)}
    .s-done .step-ic{background:rgba(16,185,129,.18);color:var(--emerald)}
    .s-err  .step-ic{background:rgba(239,68,68,.18);color:var(--red)}
    .step-name{flex:1;color:var(--txt)}
    .step-dur{font-family:'Space Mono',monospace;font-size:.7rem;color:var(--muted)}

    .terminal{background:#0D1117;border:1px solid var(--border);border-radius:8px;
      padding:10px 12px;font-family:'Space Mono',monospace;font-size:.76rem;
      max-height:220px;overflow-y:auto;line-height:1.65}
    .l-i{color:var(--cyan)}.l-w{color:var(--amber)}.l-e{color:var(--red)}.l-s{color:var(--emerald)}

    .stChatMessage{background:transparent!important}
    [data-testid="stChatMessageContent"]{background:var(--bg2)!important;border-radius:12px!important}

    .src-card{background:var(--bg3);border:1px solid var(--border);border-radius:8px;
      padding:8px 12px;margin:4px 0;font-size:.82rem}
    .src-card:hover{border-color:var(--cyan)}
    .triplet{font-family:'Space Mono',monospace;font-size:.78rem;padding:3px 0;color:var(--muted)}
    .t-s{color:var(--cyan)}.t-r{color:var(--violet)}.t-o{color:var(--emerald)}

    [data-testid="stMetricValue"]{color:var(--cyan)!important;font-family:'Space Mono',monospace!important}
    [data-testid="stMetricLabel"]{color:var(--muted)!important}
    [data-testid="stMetricDelta"]{display:none}

    .stButton>button{background:var(--bg3)!important;border:1px solid var(--border)!important;
      color:var(--txt)!important;border-radius:8px!important}
    .stButton>button:hover{border-color:var(--cyan)!important}
    .stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--cyan),var(--violet))!important;
      border:none!important;color:#fff!important;font-weight:700!important}

    .stTextInput input,.stSelectbox div[data-baseweb="select"]>div,
    .stFileUploader section{background:var(--bg3)!important;border-color:var(--border)!important;
      color:var(--txt)!important;border-radius:8px!important}
    .stTextInput label,.stSelectbox label,.stFileUploader label,
    .stRadio label,.stSlider label{color:var(--muted)!important;font-size:.82rem!important}

    .sec-title{font-family:'Space Mono',monospace;font-size:1rem;font-weight:700;
      color:var(--txt);margin-bottom:.8rem}

    [data-testid="stExpander"]{background:var(--bg3)!important;border:1px solid var(--border)!important;border-radius:8px!important}
    [data-testid="stExpander"] summary{color:var(--muted)!important;font-size:.82rem!important}
    </style>
    """)

inject_css()

# == HELPERS ===================================================================

def _esc(text: str) -> str:
    return html.escape(str(text))


@st.cache_data(ttl=30)
def get_neo4j_stats() -> dict:
    if not NEO4J_AVAILABLE:
        return {"connected": False, "nodes": 0, "rels": 0, "chunks": 0}
    try:
        driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        with driver.session() as session:
            n  = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            r  = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
            ch = session.run("MATCH (c:Chunk) RETURN count(c) as c").single()["c"]
        driver.close()
        return {"connected": True, "nodes": n, "rels": r, "chunks": ch}
    except Exception as e:
        return {"connected": False, "nodes": 0, "rels": 0, "chunks": 0, "err": str(e)}


def add_log(level: str, msg: str):
    st.session_state.pipeline_logs.append({"level": level, "msg": msg})


def render_log_terminal():
    lines_html = ""
    for entry in st.session_state.pipeline_logs[-60:]:
        cls = {"INFO": "l-i", "WARN": "l-w", "ERROR": "l-e", "SUCCESS": "l-s"}.get(entry["level"], "l-i")
        ts = time.strftime("%H:%M:%S")
        lines_html += f'<div class="{cls}">[{ts}] [{entry["level"]}] {_esc(entry["msg"])}</div>'
    if not lines_html:
        lines_html = '<div class="l-i">[--:--:--] Ch\u1edd x\u1eed l\u00fd...</div>'
    st.markdown(f'<div class="terminal">{lines_html}</div>', unsafe_allow_html=True)


def render_pipeline_stepper():
    steps_html = ""
    for name in PIPELINE_STEPS:
        info = st.session_state.pipeline_steps[name]
        s   = info["status"]
        dur = f'{info["duration"]:.1f}s' if info["duration"] else ""
        css = STEP_CSS_MAP[s]
        ic  = STEP_ICONS_MAP[s]
        steps_html += (
            f'<div class="step {css}">'
            f'<div class="step-ic">{ic}</div>'
            f'<div class="step-name">{_esc(name)}</div>'
            f'<div class="step-dur">{dur}</div>'
            f'</div>'
        )
    st.markdown(steps_html, unsafe_allow_html=True)


def save_uploaded_file(uploaded_file, doc_type: str) -> str:
    dest_dir = os.path.join("data_lake", "01_raw", doc_type)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, uploaded_file.name)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest_path


def format_answer_html(answer: str) -> str:
    def replace_vec(m):
        n = _esc(m.group(1))
        return f'<sup><span class="b-c" style="font-size:.6rem;padding:1px 5px">\u25b2{n}</span></sup>'
    def replace_grf(m):
        n = _esc(m.group(1))
        return f'<sup><span class="b-v" style="font-size:.6rem;padding:1px 5px">\u25c6{n}</span></sup>'
    result = re.sub(r'\[VEC:([^\]]+?)\]', replace_vec, answer)
    result = re.sub(r'\[GRF:([^\]]+?)\]', replace_grf, result)
    return result


def build_vec_sources(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "chunk_id":    rec.get("chunk_id", ""),
        "source_file": rec.get("source_file", ""),
        "score":       rec.get("score", 0.0),
        "text":        (rec.get("text", "") or "")[:150],
        "chunk_index": rec.get("chunk_index", 0),
    } for rec in records]


def build_grf_sources(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, sources = set(), []
    for rec in records:
        for t in rec.get("triplets", []):
            subj = t.get("subject", "")
            rel  = t.get("relation", "")
            obj  = t.get("object", "")
            if not subj or not obj:
                continue
            key = f"{subj}|{rel}|{obj}"
            if key in seen:
                continue
            seen.add(key)
            sources.append({"entity": subj, "relation": rel, "object": obj})
    return sources


def run_pipeline_steps(file_path: str, doc_type: str, core_entity: str,
                       model_label: str, step_ph, log_ph):
    """Run pipeline step-by-step with live UI updates."""
    model_slug, model_dim, model_dir = EMBED_MODELS[model_label]

    for k in PIPELINE_STEPS:
        st.session_state.pipeline_steps[k] = {"status": "waiting", "duration": None}
    st.session_state.pipeline_logs = []

    def refresh():
        with step_ph.container():
            render_pipeline_stepper()
        with log_ph.container():
            render_log_terminal()

    def run_step(name, fn, *args, **kwargs):
        st.session_state.pipeline_steps[name]["status"] = "running"
        add_log("INFO", f"B\u1eaft \u0111\u1ea7u {name}...")
        refresh()
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            dur = time.time() - t0
            st.session_state.pipeline_steps[name]["status"] = "done"
            st.session_state.pipeline_steps[name]["duration"] = dur
            add_log("SUCCESS", f"{name} ho\u00e0n t\u1ea5t ({dur:.1f}s)")
            refresh()
            return result
        except Exception as e:
            dur = time.time() - t0
            st.session_state.pipeline_steps[name]["status"] = "error"
            st.session_state.pipeline_steps[name]["duration"] = dur
            add_log("ERROR", f"{name} th\u1ea5t b\u1ea1i: {e}")
            refresh()
            raise

    try:
        raw_text = run_step("PARSE", parse_document, file_path)
        add_log("INFO", f"PARSE: {len(raw_text)} k\u00fd t\u1ef1")
        refresh()

        cleaned = run_step("CLEAN", clean_vietnamese_text, raw_text)
        add_log("INFO", f"CLEAN: {len(cleaned)} k\u00fd t\u1ef1")
        refresh()

        chunks = run_step("CHUNK", chunk_cleaned_text, cleaned)
        add_log("INFO", f"CHUNK: {len(chunks)} ph\u00e2n \u0111o\u1ea1n")
        refresh()

        detected_entity = core_entity.strip() if core_entity else ""
        if not detected_entity:
            detected_entity = _detect_core_entity(cleaned, doc_type)
        if detected_entity:
            add_log("INFO", f"Core entity: {detected_entity}")
            refresh()

        # EXTRACT (per chunk)
        st.session_state.pipeline_steps["EXTRACT"]["status"] = "running"
        add_log("INFO", "B\u1eaft \u0111\u1ea7u EXTRACT...")
        refresh()
        t0 = time.time()
        results, total_ent, total_tri = [], 0, 0
        for ci, chunk in enumerate(chunks, 1):
            try:
                extraction = extract_knowledge(chunk, core_entity=detected_entity)
                prepared = prepare_for_neo4j(chunk, extraction)
                prepared["source_file"] = os.path.basename(file_path)
                prepared["chunk_index"] = ci
                results.append(prepared)
                total_ent += len(extraction.entities)
                total_tri += len(extraction.triplets)
            except Exception as exc:
                add_log("WARN", f"Chunk {ci}: {exc}")
        dur = time.time() - t0
        st.session_state.pipeline_steps["EXTRACT"]["status"] = "done"
        st.session_state.pipeline_steps["EXTRACT"]["duration"] = dur
        add_log("SUCCESS", f"EXTRACT: {len(results)} chunks, {total_ent} entities, {total_tri} triplets ({dur:.1f}s)")
        refresh()

        # VECTORIZE mark (done inside prepare_for_neo4j)
        st.session_state.pipeline_steps["VECTORIZE"]["status"] = "done"
        st.session_state.pipeline_steps["VECTORIZE"]["duration"] = 0.0
        add_log("SUCCESS", f"VECTORIZE: {model_label}")
        refresh()

        if not results:
            add_log("ERROR", "Kh\u00f4ng c\u00f3 k\u1ebft qu\u1ea3 t\u1eeb pipeline.")
            refresh()
            return None

        saved_path = save_neo4j_ready(results, os.path.basename(file_path))
        add_log("SUCCESS", f"\u0110\u00e3 l\u01b0u JSON: {saved_path}")
        refresh()
        return str(saved_path)

    except Exception:
        return None


# == SIDEBAR ===================================================================

with st.sidebar:
    st.markdown('<div class="g-logo">\u2b21 GraphRAG</div>', unsafe_allow_html=True)
    st.markdown('<div class="g-sub">Digital Twin \u2014 Knowledge Graph</div>', unsafe_allow_html=True)
    st.divider()

    ROLE_OPTIONS = [
        "\U0001f310 Kh\u00e1ch",
        "\U0001f510 Qu\u1ea3n tr\u1ecb vi\u00ean",
        "\U0001f4ac Ng\u01b0\u1eddi d\u00f9ng n\u1ed9i b\u1ed9",
    ]
    ROLE_MAP = {
        "\U0001f310 Kh\u00e1ch":              "guest",
        "\U0001f510 Qu\u1ea3n tr\u1ecb vi\u00ean":     "admin",
        "\U0001f4ac Ng\u01b0\u1eddi d\u00f9ng n\u1ed9i b\u1ed9": "user",
    }
    chosen = st.radio("Vai tr\u00f2", ROLE_OPTIONS, key="role_radio", label_visibility="collapsed")
    role = ROLE_MAP[chosen]

    st.divider()

    stats = get_neo4j_stats()
    dot   = '<span class="dot-g"></span>' if stats["connected"] else '<span class="dot-r"></span>'
    label = "Connected" if stats["connected"] else "Disconnected"
    st.markdown("**Tr\u1ea1ng th\u00e1i h\u1ec7 th\u1ed1ng**")
    st.markdown(f'{dot} Neo4j: {label}', unsafe_allow_html=True)
    if stats["connected"]:
        st.caption(f'\U0001f539 {stats["nodes"]:,} nodes \u00b7 {stats["rels"]:,} rels')
        st.caption(f'\U0001f4e6 {stats["chunks"]:,} chunks')
    elif "err" in stats:
        st.caption(f'\u26a0 {stats["err"][:60]}')

    if not PIPELINE_AVAILABLE:
        st.warning(f'\u26a0\ufe0f pipeline: {st.session_state.get("_pipeline_err", "not found")}')
    if not QUERY_AVAILABLE:
        st.warning(f'\u26a0\ufe0f query engine: {st.session_state.get("_query_err", "not found")}')


# == MODULE 1: GUEST ===========================================================

def render_guest():
    st.markdown("""
    <div class="hero">
        <div class="hero-blob"></div>
        <div class="hero-inner">
            <div class="hero-h">H\u1ec7 th\u1ed1ng AI Minh B\u1ea1ch</div>
            <div class="hero-line"></div>
            <div class="hero-sub">Knowledge Graph &nbsp;\u00b7&nbsp; Hybrid Search &nbsp;\u00b7&nbsp; Tr\u00edch d\u1eabn ngu\u1ed3n</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    stats_data = get_neo4j_stats()
    if stats_data["connected"]:
        m1, m2, m3 = st.columns(3)
        m1.metric("Nodes", f'{stats_data["nodes"]:,}')
        m2.metric("Relationships", f'{stats_data["rels"]:,}')
        m3.metric("Chunks", f'{stats_data["chunks"]:,}')

    st.markdown('<div class="sec-title">Ki\u1ebfn tr\u00fac h\u1ec7 th\u1ed1ng</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:2.5rem">\U0001f5c4\ufe0f</div>
        <div style="font-family:'Space Mono',monospace;font-weight:700;font-size:.9rem;margin:8px 0 4px">Data Pipeline</div>
        <div style="color:var(--muted);font-size:.8rem">Parse \u2192 Clean \u2192 Chunk \u2192 Extract \u2192 Vectorize</div>
        <div class="bar-c"></div>
    </div>""", unsafe_allow_html=True)
    c2.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:2.5rem">\U0001f50d</div>
        <div style="font-family:'Space Mono',monospace;font-weight:700;font-size:.9rem;margin:8px 0 4px">Hybrid Search</div>
        <div style="color:var(--muted);font-size:.8rem">Graph exact-match <b>[GRF]</b> + Vector cosine <b>[VEC]</b></div>
        <div class="bar-v"></div>
    </div>""", unsafe_allow_html=True)
    c3.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:2.5rem">\U0001f916</div>
        <div style="font-family:'Space Mono',monospace;font-weight:700;font-size:.9rem;margin:8px 0 4px">LLM Synthesis</div>
        <div style="color:var(--muted);font-size:.8rem">Cerebras llama3.1-8b \u2192 OpenAI GPT-4o fallback</div>
        <div class="bar-e"></div>
    </div>""", unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="sec-title">Lo\u1ea1i t\u00e0i li\u1ec7u h\u1ed7 tr\u1ee3</div>', unsafe_allow_html=True)
    d1, d2, d3 = st.columns(3)
    d1.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:1.8rem">\U0001f4c4</div>
        <div style="font-family:'Space Mono',monospace;font-size:.88rem;font-weight:700;margin:6px 0 8px">CV Nh\u00e2n s\u1ef1</div>
        <div><span class="b-c" style="font-size:.65rem">PERSONNEL</span> <span class="b-c" style="font-size:.65rem">EXPERIENCE</span> <span class="b-c" style="font-size:.65rem">SKILL</span></div>
    </div>""", unsafe_allow_html=True)
    d2.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:1.8rem">\U0001f4cb</div>
        <div style="font-family:'Space Mono',monospace;font-size:.88rem;font-weight:700;margin:6px 0 8px">Quy tr\u00ecnh SOP</div>
        <div><span class="b-v" style="font-size:.65rem">PROCESS_FLOW</span> <span class="b-v" style="font-size:.65rem">APPROVAL</span> <span class="b-v" style="font-size:.65rem">COMPLIANCE</span></div>
    </div>""", unsafe_allow_html=True)
    d3.markdown("""<div class="card" style="text-align:center">
        <div style="font-size:1.8rem">\U0001f4c1</div>
        <div style="font-family:'Space Mono',monospace;font-size:.88rem;font-weight:700;margin:6px 0 8px">T\u00e0i li\u1ec7u D\u1ef1 \u00e1n</div>
        <div><span class="b-e" style="font-size:.65rem">OBJECTIVE</span> <span class="b-e" style="font-size:.65rem">RISK</span> <span class="b-e" style="font-size:.65rem">PLANNING</span></div>
    </div>""", unsafe_allow_html=True)

    st.divider()
    st.markdown("**Tech Stack**")
    techs = ["Neo4j 5.26", "PhoBERT v2", "BGE-M3", "GTE", "Cerebras", "OpenAI", "Streamlit", "Docker"]
    badges = " ".join(f'<span class="b-c">{t}</span>' for t in techs)
    st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:6px">{badges}</div>', unsafe_allow_html=True)


# == MODULE 2: ADMIN ===========================================================

def render_admin():
    st.markdown('<div class="sec-title">\u2b06 Upload & Ingest</div>', unsafe_allow_html=True)
    col_left, col_right = st.columns([4, 6], gap="large")

    with col_left:
        uploaded = st.file_uploader("Ch\u1ecdn t\u00e0i li\u1ec7u", type=["pdf", "docx", "doc", "md"])
        doc_type = st.radio(
            "Lo\u1ea1i t\u00e0i li\u1ec7u",
            list(DOC_TYPES.keys()),
            format_func=lambda x: DOC_TYPES[x],
            horizontal=True,
        )
        core_entity    = st.text_input("Core entity (t\u00f9y ch\u1ecdn)", placeholder="V\u00ed d\u1ee5: Nguy\u1ec5n V\u0103n A, D\u1ef1 \u00e1n TSC...")
        embedding_label = st.selectbox("Embedding model", list(EMBED_MODELS.keys()))
        run_clicked    = st.button("\U0001f680 B\u1eaft \u0111\u1ea7u x\u1eed l\u00fd", use_container_width=True, type="primary")

    with col_right:
        step_ph = st.empty()
        st.caption("Pipeline logs")
        log_ph    = st.empty()
        result_ph = st.empty()
        with step_ph.container():
            render_pipeline_stepper()
        with log_ph.container():
            render_log_terminal()

    if run_clicked:
        if uploaded is None:
            st.error("\u26a0\ufe0f Vui l\u00f2ng upload file tr\u01b0\u1edbc!")
        elif not PIPELINE_AVAILABLE:
            st.error("\u274c Pipeline module ch\u01b0a \u0111\u01b0\u1ee3c c\u00e0i \u0111\u1eb7t.")
        else:
            file_path = save_uploaded_file(uploaded, doc_type)
            st.toast(f"\u2705 \u0110\u00e3 l\u01b0u: {uploaded.name}", icon="\U0001f4be")

            json_path = run_pipeline_steps(file_path, doc_type, core_entity, embedding_label, step_ph, log_ph)

            if json_path:
                model_slug, model_dim, model_dir = EMBED_MODELS[embedding_label]
                neo4j_dir = NEO4J_READY_ROOT / model_dir
                if NEO4J_INGESTION_AVAILABLE and neo4j_dir.exists():
                    st.toast("\U0001f504 \u0110ang n\u1ea1p v\u00e0o Neo4j...", icon="\U0001f5c4\ufe0f")
                    try:
                        with Neo4jIngestor() as ingestor:
                            res = ingestor.ingest_directory(
                                str(neo4j_dir),
                                embedding_dim=model_dim,
                                model_name=model_slug,
                            )
                        with result_ph.container():
                            st.success(f"\u2705 Ho\u00e0n t\u1ea5t! {res.get('files_processed',0)} files \u00b7 {res.get('chunks_total',0)} chunks")
                            r1, r2, r3 = st.columns(3)
                            r1.metric("Files", res.get("files_processed", 0))
                            r2.metric("Chunks", res.get("chunks_total", 0))
                            r3.metric("Failed", res.get("files_failed", 0))
                        st.toast("\U0001f389 N\u1ea1p Neo4j th\u00e0nh c\u00f4ng!", icon="\u2705")
                        get_neo4j_stats.clear()
                    except Exception as e:
                        with result_ph.container():
                            st.error(f"\u274c L\u1ed7i n\u1ea1p Neo4j: {e}")
                else:
                    add_log("WARN", "Neo4j ingestion kh\u00f4ng kh\u1ea3 d\u1ee5ng ho\u1eb7c th\u01b0 m\u1ee5c ch\u01b0a t\u1ed3n t\u1ea1i.")
                    with log_ph.container():
                        render_log_terminal()
            else:
                with result_ph.container():
                    st.error("\u274c Pipeline th\u1ea5t b\u1ea1i. Xem log b\u00ean tr\u00ean.")


# == MODULE 3: CHAT ============================================================

def _render_assistant_msg(msg: dict):
    if "error" in msg:
        st.error(f"\u274c {msg['error']}")
        return

    elapsed  = msg.get("elapsed_ms", 0)
    n_chunks = msg.get("chunks_retrieved", 0)
    st.caption(f"\u2b21 GraphRAG \u00b7 {elapsed:.0f}ms \u00b7 {n_chunks} chunks")

    answer_html = format_answer_html(msg.get("answer", ""))
    st.markdown(answer_html, unsafe_allow_html=True)

    vec_sources = msg.get("vec_sources", [])
    grf_sources = msg.get("grf_sources", [])

    if vec_sources or grf_sources:
        with st.expander(f"\U0001f4da Ngu\u1ed3n tr\u00edch d\u1eabn ({len(vec_sources)} VEC \u00b7 {len(grf_sources)} GRF)"):
            if vec_sources:
                st.markdown("**\U0001f4c4 Vector Sources**")
                for i, src in enumerate(vec_sources, 1):
                    score = src.get("score", 0)
                    fname = os.path.basename(src.get("source_file", "?"))
                    text  = _esc(src.get("text", "")[:120])
                    st.markdown(
                        f'<div class="src-card">'
                        f'<span class="b-c">\u25b2{i} VEC {score:.2f}</span> '
                        f'<span style="color:var(--muted);font-size:.8rem"> {_esc(fname)}</span><br>'
                        f'<span style="font-size:.8rem;color:var(--muted)">{text}\u2026</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            if grf_sources:
                st.markdown("**\U0001f517 Graph Sources**")
                for i, src in enumerate(grf_sources, 1):
                    ent = _esc(src.get("entity", "?"))
                    rel = _esc(src.get("relation", "?"))
                    obj = _esc(src.get("object", "?"))
                    st.markdown(
                        f'<div class="src-card">'
                        f'<span class="b-v">\u25c6{i} GRF</span> '
                        f'<span class="triplet">'
                        f'<span class="t-s">{ent}</span>'
                        f' \u2500\u2500[<span class="t-r">{rel}</span>]\u2500\u2500\u25b6 '
                        f'<span class="t-o">{obj}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )

    if grf_sources:
        with st.expander("\U0001f578 Knowledge Graph Triplets"):
            for src in grf_sources:
                ent = _esc(src.get("entity", "?"))
                rel = _esc(src.get("relation", "?"))
                obj = _esc(src.get("object", "?"))
                st.markdown(
                    f'<div class="triplet">'
                    f'<span class="t-s">{ent}</span>'
                    f' \u2500\u2500[<span class="t-r">{rel}</span>]\u2500\u2500\u25b6 '
                    f'<span class="t-o">{obj}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


def render_chat():
    st.markdown('<div class="sec-title">\U0001f4ac Hybrid Search Chat</div>', unsafe_allow_html=True)
    stats_data = get_neo4j_stats()

    tb1, tb2, tb3 = st.columns([4, 2, 2])
    with tb1:
        if stats_data["connected"]:
            st.markdown(
                f'<span class="b-c">\U0001f50d {stats_data["nodes"]:,} nodes</span> '
                f'<span class="b-v">\U0001f517 {stats_data["rels"]:,} rels</span> '
                f'<span class="b-e">\U0001f4e6 {stats_data["chunks"]:,} chunks</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<span class="b-g">\u26a0 Neo4j Disconnected</span>', unsafe_allow_html=True)
    with tb2:
        embed_label = st.selectbox("Embedding", list(EMBED_MODELS.keys()), key="chat_embed", label_visibility="collapsed")
    with tb3:
        top_k = st.slider("Top-K", 3, 10, 5, label_visibility="collapsed")

    SUGGESTIONS = [
        "Ai l\u00e0 CTO c\u1ee7a c\u00f4ng ty?",
        "Quy tr\u00ecnh ph\u00ea duy\u1ec7t d\u1ef1 \u00e1n?",
        "K\u1ef9 n\u0103ng c\u1ee7a dev team?",
        "C\u00e1c d\u1ef1 \u00e1n \u0111ang th\u1ef1c hi\u1ec7n?",
    ]
    chip_cols = st.columns(len(SUGGESTIONS))
    for i, sug in enumerate(SUGGESTIONS):
        if chip_cols[i].button(sug, key=f"chip_{i}", use_container_width=True):
            st.session_state.pending_query = sug
            st.rerun()

    st.divider()

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                _render_assistant_msg(msg)

    user_input = st.chat_input("H\u1ecfi v\u1ec1 nh\u00e2n s\u1ef1, quy tr\u00ecnh, d\u1ef1 \u00e1n...")

    query = user_input
    if not query and st.session_state.pending_query:
        query = st.session_state.pending_query
        st.session_state.pending_query = None

    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        if not QUERY_AVAILABLE:
            with st.chat_message("assistant"):
                st.error("\u274c Query engine ch\u01b0a kh\u1edfi t\u1ea1o. Ki\u1ec3m tra Neo4j v\u00e0 pipeline module.")
        else:
            model_slug, _, _ = EMBED_MODELS.get(embed_label, ("phobert_v2", 768, "phobert-v2"))
            with st.chat_message("assistant"):
                with st.spinner("\u0110ang t\u00ecm ki\u1ebfm trong Knowledge Graph..."):
                    try:
                        result = hybrid_ask(query, top_k=top_k, model_name=model_slug)
                        records  = result.get("records", [])
                        elapsed  = result.get("elapsed", 0)
                        msg_obj  = {
                            "role":             "assistant",
                            "answer":           result.get("answer", ""),
                            "vec_sources":      build_vec_sources(records),
                            "grf_sources":      build_grf_sources(records),
                            "elapsed_ms":       elapsed * 1000,
                            "chunks_retrieved": result.get("num_chunks", 0),
                        }
                        st.session_state.messages.append(msg_obj)
                        _render_assistant_msg(msg_obj)
                    except Exception as e:
                        err_obj = {"role": "assistant", "error": str(e)}
                        st.session_state.messages.append(err_obj)
                        st.error(f"\u274c L\u1ed7i query: {e}")


# == ROUTER ====================================================================

if role == "guest":
    render_guest()
elif role == "admin":
    render_admin()
elif role == "user":
    render_chat()
