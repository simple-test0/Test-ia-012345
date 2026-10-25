#!/usr/bin/env python3
"""One-click hardware optimisation for AI Studio.

Detects this machine's accelerator + memory, asks the recommendation engine for
the best settings, and updates ``backend/.env``. Safe to re-run anytime
(after a GPU upgrade, a driver change, etc.) — keys it doesn't manage
(HUGGINGFACE_TOKEN, API_TOKEN, ...) are preserved.

    python scripts/optimize.py            # detect, update backend/.env, print summary
    python scripts/optimize.py --print    # show what it would do, write nothing

It degrades gracefully: with no GPU (or torch not yet installed) it produces a
sensible CPU profile instead of failing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
ENV_PATH = BACKEND / ".env"

# Make the backend package importable when run from anywhere.
sys.path.insert(0, str(BACKEND))


def _human_gb(mb: int) -> str:
    return f"{mb / 1024:.1f} GB" if mb else "n/a"


def build_env(rec) -> dict:
    """Translate a RecommendationSet into concrete .env settings."""
    return {
        "DEBUG": "false",
        # Keep one pipeline resident on smaller cards; allow two when there's room.
        "MAX_PIPELINES_LOADED": "2" if rec.vram_mb >= 16384 else "1",
    }


def _read_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    kept = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kept[k.strip()] = v.strip()
    return kept


def write_env(env: dict, path: Path, tier: str) -> None:
    # Managed keys take the new value; everything else in the file is preserved.
    merged = _read_existing(path)
    merged.update(env)
    merged.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
    lines = [
        "# AI Studio — tuned by scripts/optimize.py",
        f"# Detected tier: {tier}",
        "# Re-run `python scripts/optimize.py` after a hardware/driver change.",
        "# Add HUGGINGFACE_TOKEN=hf_xxx below to use gated models (FLUX.1-dev, SD3.5).",
        "",
    ]
    lines += [f"{k}={v}" for k, v in merged.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimise AI Studio for this machine.")
    parser.add_argument(
        "--print", dest="dry", action="store_true", help="Show the recommended settings without writing .env"
    )
    args = parser.parse_args()

    try:
        from hardware.detector import detect_hardware
        from hardware.recommender import recommend
    except Exception as exc:  # pragma: no cover
        print(f"!! Could not import the detection engine: {exc}")
        print("   Make sure backend dependencies are installed (run the installer).")
        return 1

    hw = detect_hardware()
    rec = recommend(hw)
    env = build_env(rec)

    gpu = hw.gpus[0] if hw.gpus else None
    ig = rec.image_gen
    print("\n=== AI Studio — hardware optimisation ===")
    print(f"  Accelerator : {gpu.name if gpu else 'CPU (no GPU detected)'}")
    print(f"  VRAM        : {_human_gb(rec.vram_mb)}" + ("  (reported by driver)" if rec.vram_mb else ""))
    print(f"  System RAM  : {_human_gb(hw.ram_total_mb)}")
    print(f"  Tier        : {rec.tier_label}")
    print("  ---")
    print(f"  Image models: {', '.join(ig.recommended_models)}")
    print(
        f"  Max res     : {ig.max_resolution[0]}x{ig.max_resolution[1]}"
        f" · {ig.recommended_steps} steps · {'fp16' if ig.use_fp16 else 'fp32'}"
    )
    print(f"  LLM models  : {', '.join(rec.agent.recommended_models)}  (Ollama, {rec.agent.quantization})")
    print(
        f"  Train batch : {rec.training.recommended_batch_size}"
        f" · mixed precision: {rec.training.use_mixed_precision}"
        f" · grad accum: {rec.training.gradient_accumulation_steps}"
    )
    print("  ---")
    print("  .env settings:")
    for k, v in env.items():
        print(f"    {k}={v}")

    if args.dry:
        print("\n(--print) Nothing written.")
        return 0

    write_env(env, ENV_PATH, rec.tier_label)
    print(f"\n  Wrote {ENV_PATH.relative_to(ROOT)}")
    if not rec.vram_mb:
        print("  Note: no GPU detected — image generation will be slow but functional.")
    print("  Done. Start the app with start.bat (Windows) or ./start.sh.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
