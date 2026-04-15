"""Fetch current top free-tier models with strict structured-output support.

Usage:
    docker compose exec backend python -m app.analysis.list_free_models [--top N]

Prints a ready-to-paste comma-separated list for OPENROUTER_FREE_MODELS.

Selection criteria:
  1. pricing.prompt == 0 AND pricing.completion == 0  (truly free)
  2. "structured_outputs" in supported_parameters      (strict JSON schema support)
  3. Excludes aggregator endpoints (openrouter/*)       — unpredictable routing
  4. Sorted by created_at DESC (newest first) — proxy for "currently maintained"

No dynamic startup fetch on purpose: OpenRouter removes/renames models frequently,
so we keep the list static in config and refresh via this script on demand.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import httpx


API_URL = "https://openrouter.ai/api/v1/models"


def fetch(top: int) -> list[dict]:
    resp = httpx.get(API_URL, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()

    candidates: list[dict] = []
    for m in data.get("data", []):
        pricing = m.get("pricing", {}) or {}
        if pricing.get("prompt") not in ("0", 0):
            continue
        if pricing.get("completion") not in ("0", 0):
            continue
        mid = m.get("id", "")
        if mid.startswith("openrouter/"):
            # Skip aggregator endpoints — opaque routing, not a real model.
            continue
        supported = m.get("supported_parameters", []) or []
        if "structured_outputs" not in supported:
            continue
        candidates.append({
            "id": mid,
            "created": m.get("created") or 0,
            "ctx": m.get("context_length") or 0,
            "name": m.get("name", ""),
        })

    candidates.sort(key=lambda x: x["created"], reverse=True)
    return candidates[:top]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top", type=int, default=4, help="How many models to list (default: 4)")
    p.add_argument("--json", action="store_true", help="Print raw JSON instead of table")
    args = p.parse_args()

    try:
        picks = fetch(args.top)
    except httpx.HTTPError as exc:
        print(f"ERROR: OpenRouter API request failed: {exc}", file=sys.stderr)
        return 1

    if not picks:
        print("No free models with structured_outputs found.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(picks, indent=2))
        return 0

    print(f"Top {len(picks)} free-tier models with strict structured_outputs:\n")
    print(f"  {'Created':<11} {'Ctx':>6}  {'Model ID'}")
    print(f"  {'-'*10} {'-'*6}  {'-'*60}")
    for m in picks:
        dt = datetime.fromtimestamp(m["created"], tz=timezone.utc).strftime("%Y-%m-%d") if m["created"] else "?"
        ctx = f"{m['ctx']//1000}k" if m["ctx"] else "?"
        print(f"  {dt:<11} {ctx:>6}  {m['id']}")

    print("\nPaste into .env as OPENROUTER_FREE_MODELS (comma-separated, no spaces):\n")
    print("OPENROUTER_FREE_MODELS=" + ",".join(m["id"] for m in picks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
