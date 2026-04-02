# ===== FILE 2: scripts/eval/run_all.py =====
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

STEPS: dict[str, str] = {
    "cleaner":   "scripts.eval.eval_cleaner",
    "extractor": "scripts.eval.eval_extractor",
    "embedding": "scripts.eval.eval_embeddings",
    "graph":     "scripts.eval.eval_graph",
    "ragas":     "scripts.eval.eval_ragas",
    "privacy":   "scripts.eval.eval_privacy",
}


def _run_step(name: str, module_path: str) -> tuple[bool, float]:
    """Import module and call main(). Returns (success, elapsed_seconds)."""
    t0 = time.perf_counter()
    try:
        mod = importlib.import_module(module_path)
        mod.main()
        elapsed = time.perf_counter() - t0
        return True, elapsed
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [ERROR] {exc}")
        return False, elapsed


def run_cli() -> None:
    args = sys.argv[1:]

    # ── --list ────────────────────────────────────────────────────────────
    if "--list" in args:
        print("Available evaluation steps:")
        for name in STEPS:
            print(f"  {name}")
        print("\nUsage:")
        print("  python scripts/eval/run_all.py               # all steps")
        print("  python scripts/eval/run_all.py cleaner graph # selected steps")
        return

    # ── select steps ──────────────────────────────────────────────────────
    if args:
        unknown = [a for a in args if a not in STEPS]
        if unknown:
            print(f"[ERROR] Unknown steps: {unknown}")
            print(f"Available: {list(STEPS.keys())}")
            sys.exit(1)
        selected = {name: STEPS[name] for name in args}
    else:
        selected = STEPS

    # ── run ───────────────────────────────────────────────────────────────
    total_start = time.perf_counter()
    results: list[tuple[str, bool, float]] = []

    col_w = 12
    print(f"\n{'='*50}")
    print(f"  Running {len(selected)} eval step(s)")
    print(f"{'='*50}\n")

    for name, module_path in selected.items():
        print(f"▶  {name.upper()}")
        print("-" * 40)
        ok, elapsed = _run_step(name, module_path)
        status = "OK" if ok else "FAIL"
        results.append((name, ok, elapsed))
        print(f"\n   → {status}  ({elapsed:.1f}s)\n")

    # ── final summary ─────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start
    n_ok   = sum(1 for _, ok, _ in results if ok)
    n_fail = len(results) - n_ok

    print("=" * 50)
    print("  SUMMARY")
    print("=" * 50)
    name_w = max(len(n) for n, _, _ in results)
    for name, ok, elapsed in results:
        status = "✓ OK  " if ok else "✗ FAIL"
        print(f"  {status}  {name.ljust(name_w)}  {elapsed:6.1f}s")
    print("-" * 50)
    print(f"  {n_ok}/{len(results)} completed in {total_elapsed:.1f}s"
          + (f"  ({n_fail} failed)" if n_fail else ""))
    print()


if __name__ == "__main__":
    run_cli()