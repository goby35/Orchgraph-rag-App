import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.gridspec import GridSpec
from pathlib import Path

# ── Cấu hình phong cách học thuật ──────────────────────────────────────────
plt.rcParams.update({
    "font.family":      "DejaVu Sans",
    "font.size":        10,
    "axes.titlesize":   11,
    "axes.labelsize":   10,
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "axes.grid":        True,
    "grid.alpha":       0.25,
    "grid.linestyle":   "--",
    "figure.dpi":       150,
    "savefig.dpi":      200,
    "savefig.bbox":     "tight",
    "savefig.facecolor":"white",
})

# Bảng màu nhất quán
C_BLUE   = "#2563EB"
C_TEAL   = "#0D9488"
C_ORANGE = "#EA580C"
C_RED    = "#DC2626"
C_PUB    = "#3B82F6"   # Public fields
C_PRV    = "#F59E0B"   # Private fields
C_GRAY   = "#6B7280"

MODELS = ["PhoBERT\nbase-v2", "mE5\nbase", "GTE\nmultilingual", "BGE-M3"]
COLORS_MODEL = [C_RED, C_TEAL, C_BLUE, C_ORANGE]

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# BIỂU ĐỒ 1 — So sánh 4 mô hình embedding (Task A + Task B)
# ═══════════════════════════════════════════════════════════════════════════
def chart1_embedding_comparison():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=False)

    x = np.arange(len(MODELS))
    w = 0.22

    # — Task A —
    ax = axes[0]
    mrr5   = [0.6361, 1.0000, 1.0000, 1.0000]
    rec5   = [0.6694, 0.9556, 0.9722, 0.3890]
    rec10  = [0.7361, 1.0000, 0.9833, 1.0000]
    ndcg5  = [0.5832, 0.9573, 0.9698, 0.9465]

    b1 = ax.bar(x - 1.5*w, mrr5,  w, label="MRR@5",    color=C_BLUE,   alpha=.85)
    b2 = ax.bar(x - 0.5*w, rec5,  w, label="Recall@5", color=C_TEAL,   alpha=.85)
    b3 = ax.bar(x + 0.5*w, rec10, w, label="Recall@10",color=C_ORANGE, alpha=.85)
    b4 = ax.bar(x + 1.5*w, ndcg5, w, label="NDCG@5",   color=C_RED,    alpha=.85)

    ax.set_xticks(x); ax.set_xticklabels(MODELS, fontsize=9)
    ax.set_ylim(0, 1.12); ax.set_ylabel("Score")
    ax.legend(fontsize=8, loc="upper left")
    ax.axhline(1.0, color="gray", lw=0.8, ls=":")
    ax.text(0.5, -0.22, "Task A: Search", ha="center", transform=ax.transAxes, fontsize=9, style="italic", color=C_GRAY)

    # — Task B —
    ax2 = axes[1]
    prec5  = [0.4462, 0.4000, 0.4692, 0.2231]
    recall = [0.7500, 0.6795, 0.7949, 0.3782]
    mrr    = [0.9231, 0.9423, 0.9359, 0.4622]
    hit1   = [0.8462, 0.9231, 0.8846, 0.2692]

    b1 = ax2.bar(x - 1.5*w, prec5,  w, label="Precision@5", color=C_BLUE,   alpha=.85)
    b2 = ax2.bar(x - 0.5*w, recall, w, label="Recall",      color=C_TEAL,   alpha=.85)
    b3 = ax2.bar(x + 0.5*w, mrr,    w, label="MRR",         color=C_ORANGE, alpha=.85)
    b4 = ax2.bar(x + 1.5*w, hit1,   w, label="Hit@1",       color=C_RED,    alpha=.85)

    # Performance drop annotation in upper left


    ax2.set_xticks(x); ax2.set_xticklabels(MODELS, fontsize=9)
    ax2.set_ylim(0, 1.12); ax2.set_ylabel("Score")
    ax2.legend(fontsize=8, loc="upper right")
    ax2.text(0.5, -0.22, "Task B: QA Retrieval", ha="center", transform=ax2.transAxes, fontsize=9, style="italic", color=C_GRAY)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart1_embedding_comparison.png")
    plt.savefig(OUTPUT_DIR / "chart1_embedding_comparison.svg")
    plt.savefig(OUTPUT_DIR / "chart1_embedding_comparison.pdf")
    plt.close()
    print("✓ Chart 1 saved (PNG, SVG, PDF)")


# ═══════════════════════════════════════════════════════════════════════════
# BIỂU ĐỒ 2 — Kết quả RAGAS của 4 cấu hình Retrieval
# ═══════════════════════════════════════════════════════════════════════════
def chart2_ragas_comparison():
    fig, ax = plt.subplots(figsize=(11, 5))

    systems = ["RAG\n(Pure Vector)", "GraphRAG\n(Pure Graph)", "Hybrid\n(Baseline)", "Hybrid+\n(Proposed)"]
    metrics = ["Faithfulness", "Answer\nRelevancy", "Context\nRecall", "Context\nPrecision", "Answer\nCorrectness"]

    data = np.array([
        [0.8727, 0.6458, 0.9615, 0.9103, 0.6613],  # RAG
        [0.8833, 0.6761, 0.9615, 0.9167, 0.7052],  # GraphRAG
        [0.8613, 0.7462, 0.9615, 0.9103, 0.6378],  # Hybrid
        [0.8803, 0.7474, 0.9615, 0.9167, 0.6567],  # Hybrid+
    ])

    x     = np.arange(len(metrics))
    n     = len(systems)
    w     = 0.18
    colors = [C_GRAY, C_ORANGE, C_TEAL, C_BLUE]
    hatches = ["", "//", "..", ""]

    for i, (sys, color, hatch) in enumerate(zip(systems, colors, hatches)):
        offset = (i - (n-1)/2) * w
        lw = 2.5 if i == 3 else 1
        bars = ax.bar(x + offset, data[i], w, label=sys,
                      color=color, alpha=0.80, hatch=hatch,
                      edgecolor="white" if i == 3 else color, linewidth=lw)

    ax.set_xticks(x); ax.set_xticklabels(metrics, fontsize=9)
    ax.set_ylim(0.55, 1.05); ax.set_ylabel("RAGAS Score")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.axhline(1.0, color="gray", lw=0.6, ls=":")

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart2_ragas_comparison.png")
    plt.savefig(OUTPUT_DIR / "chart2_ragas_comparison.svg")
    plt.savefig(OUTPUT_DIR / "chart2_ragas_comparison.pdf")
    plt.close()
    print("✓ Chart 2 saved (PNG, SVG, PDF)")


# ═══════════════════════════════════════════════════════════════════════════
# BIỂU ĐỒ 3 — Phân bổ thời gian Pipeline Ingestion (horizontal bar)
# ═══════════════════════════════════════════════════════════════════════════
def chart3_ingestion_time():
    fig, ax = plt.subplots(figsize=(10, 4))

    steps  = ["1. Load & Parse PDF", "2. Cleaner", "3. Extractor (LLM call)",
              "4. Embedder", "5. Neo4j Writer", "6. Supabase Writer"]
    # Estimated time (seconds) — Extractor ~8.97s takes ~65%
    times  = [0.45, 0.30, 8.97, 1.20, 0.55, 0.40]
    total  = sum(times)
    pcts   = [t/total*100 for t in times]

    colors_bar = [C_TEAL, C_TEAL, C_BLUE, C_ORANGE, C_TEAL, C_TEAL]
    colors_bar[2] = C_BLUE  # highlight Extractor

    bars = ax.barh(steps, pcts, color=colors_bar, alpha=0.82, edgecolor="white", height=0.55)

    # Bottleneck annotation
    ax.annotate("⚡ Bottleneck\n(LLM I/O bound)",
                xy=(pcts[2], 2),
                xytext=(50, 1.0),
                fontsize=8.5, color=C_BLUE, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BLUE))

    ax.set_xlabel("Time Ratio (%)")
    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines["left"].set_visible(False)

    # Total time info
    ax.text(0.98, -0.12, f"Total: {total:.2f}s / CV  |  Extractor: {pcts[2]:.1f}%",
            transform=ax.transAxes, ha="right", fontsize=9, color=C_GRAY, style="italic")

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart3_ingestion_time.png")
    plt.savefig(OUTPUT_DIR / "chart3_ingestion_time.svg")
    plt.savefig(OUTPUT_DIR / "chart3_ingestion_time.pdf")
    plt.close()
    print("✓ Chart 3 saved (PNG, SVG, PDF)")


# ═══════════════════════════════════════════════════════════════════════════
# BIỂU ĐỒ 4 — Field Coverage Extractor (Public vs Private)
# ═══════════════════════════════════════════════════════════════════════════
def chart4_field_coverage():
    fig, ax = plt.subplots(figsize=(11, 5.5))

    # (field, coverage, is_public)
    fields_data = [
        ("full_name",              1.00, True),
        ("professional_summary",   1.00, True),
        ("skills",                 1.00, True),
        ("salary_expectation",     0.96, False),
        ("experience",             0.96, True),
        ("contact.email",          0.92, False),
        ("contact.phone",          0.92, False),
        ("education",              0.88, True),
        ("certificates",           0.64, True),
        ("project_technical_secrets", 0.24, False),
        ("blacklist_orgs",         0.24, False),
        ("cultural_tags",          0.12, True),
    ]

    fields   = [f[0] for f in fields_data]
    coverage = [f[1] for f in fields_data]
    is_pub   = [f[2] for f in fields_data]

    colors_bar = [C_PUB if p else C_PRV for p in is_pub]
    y = np.arange(len(fields))

    bars = ax.barh(y, coverage, color=colors_bar, alpha=0.82, edgecolor="white", height=0.6)

    # Keep numeric labels for each bar in chart 4
    for bar, val, pub in zip(bars, coverage, is_pub):
        clr = "#1D4ED8" if pub else "#92400E"
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                f"{val:.2f}", va="center", fontsize=9, color=clr, fontweight="bold")

    # Đường mốc 0.80
    ax.axvline(0.80, color=C_GRAY, lw=1.0, ls="--", alpha=0.6)
    ax.text(0.80, len(fields) - 0.2, "0.80", ha="center", fontsize=8, color=C_GRAY)

    ax.set_yticks(y); ax.set_yticklabels(fields, fontsize=9)
    ax.set_xlabel("Coverage (0 → 1)")
    ax.set_xlim(0, 1.18)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    ax.spines["left"].set_visible(False)

    # Summary box - lower right
    avg_pub = np.mean([f[1] for f in fields_data if f[2]])
    avg_prv = np.mean([f[1] for f in fields_data if not f[2]])
    summary = f"Avg Public: {avg_pub:.3f}   |   Avg Private: {avg_prv:.3f}"
    ax.text(0.98, 0.02, summary, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=9.5, color=C_GRAY, style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#F3F4F6", edgecolor=C_GRAY, alpha=0.7))

    # Legend - lower right, above summary box
    pub_patch = mpatches.Patch(color=C_PUB, alpha=0.82, label="Public field")
    prv_patch = mpatches.Patch(color=C_PRV, alpha=0.82, label="Private field")
    ax.legend(handles=[pub_patch, prv_patch], loc="lower right", fontsize=9, bbox_to_anchor=(0.98, 0.12))

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart4_field_coverage.png")
    plt.savefig(OUTPUT_DIR / "chart4_field_coverage.svg")
    plt.savefig(OUTPUT_DIR / "chart4_field_coverage.pdf")
    plt.close()
    print("✓ Chart 4 saved (PNG, SVG, PDF)")


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    chart1_embedding_comparison()
    chart2_ragas_comparison()
    chart3_ingestion_time()
    chart4_field_coverage()
    print(f"\n✅ All 4 charts saved to {OUTPUT_DIR} (PNG, SVG, PDF formats)")
