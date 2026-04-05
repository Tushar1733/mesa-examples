#!/usr/bin/env python3
"""
scripts/generate_dashboard_1.py

Reads the health report produced by Workflow 1:
  - example_health_report.json

Then writes health_dashboard.md in the repo root.

Called by Workflow 2 with NO arguments:
  python scripts/generate_dashboard_1.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── File paths (relative to repo root, where the workflow runs) ───────────────

INPUT_FILE  = Path("example_health_report.json")
OUTPUT_FILE = Path("health_dashboard.md")

# ── Status display helpers ────────────────────────────────────────────────────

STATUS_META = {
    "Active-healthy": {"emoji": "✅", "label": "Active – Healthy"},
    "needs_upgrade":  {"emoji": "⚠️",  "label": "Needs Upgrade"},
    "broken":         {"emoji": "❌", "label": "Broken"},
}

PASS_ICON = "✔️"
FAIL_ICON = "✖️"


def fmt_check(value) -> str:
    """Render a PASS/FAIL string or True/False bool as an icon."""
    if isinstance(value, bool):
        return PASS_ICON if value else FAIL_ICON
    return PASS_ICON if str(value).upper() == "PASS" else FAIL_ICON


def fmt_status(status: str) -> str:
    meta = STATUS_META.get(status, {"emoji": "❓", "label": status})
    return f"{meta['emoji']} {meta['label']}"


# ── JSON loading ──────────────────────────────────────────────────────────────

def load_records(path: Path) -> list[dict]:
    """
    Load records from a JSON file.
    Accepts two shapes:
      - A bare list:                   [ { "name": ..., ... }, ... ]
      - A dict with an "examples" key: { "examples": [ ... ] }
    Exits with an error on missing / invalid / empty file.
    """
    if not path.exists() or path.stat().st_size == 0:
        print(f"❌  {path} is missing or empty.", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"❌  {path} is invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("examples", [])

    print(f"❌  Unexpected JSON shape in {path}.", file=sys.stderr)
    sys.exit(1)


# ── Dashboard builder ─────────────────────────────────────────────────────────

def build_dashboard(records: list[dict]) -> str:
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(records)

    counts: dict[str, int] = {}
    for r in records:
        key = r.get("final_status", "unknown")
        counts[key] = counts.get(key, 0) + 1

    healthy = counts.get("Active-healthy", 0)
    upgrade = counts.get("needs_upgrade",  0)
    broken  = counts.get("broken",         0)

    lines = [
        "# 🩺 Health Dashboard",
        "",
        f"_Last updated: **{now}**_ &nbsp;|&nbsp; **{total}** examples tracked",
        "",
        "## Summary",
        "",
        "| ✅ Healthy | ⚠️ Needs Upgrade | ❌ Broken |",
        "| :---: | :---: | :---: |",
        f"| {healthy} | {upgrade} | {broken} |",
        "",
        "## Model Status",
        "",
        "| Model | Maintainer | Declared Server | Declared Model "
        "| Latest Server | Latest Model | Status |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    # Sort: healthy first, then needs_upgrade, then broken
    order = {"Active-healthy": 0, "needs_upgrade": 1, "broken": 2}
    for r in sorted(records, key=lambda x: order.get(x.get("final_status", ""), 9)):
        lines.append(
            f"| `{r.get('name', 'N/A')}` "
            f"| {r.get('maintainer', '—')} "
            f"| {fmt_check(r.get('declared_server', 'FAIL'))} "
            f"| {fmt_check(r.get('declared_model', False))} "
            f"| {fmt_check(r.get('latest_server', 'FAIL'))} "
            f"| {fmt_check(r.get('latest_model', False))} "
            f"| {fmt_status(r.get('final_status', 'unknown'))} |"
        )

    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"📂  Loading {INPUT_FILE} …")
    records = load_records(INPUT_FILE)

    if not records:
        print("❌  No records found in the JSON file. Nothing to write.", file=sys.stderr)
        sys.exit(1)

    print(f"🏗️   Building dashboard for {len(records)} examples …")
    dashboard_md = build_dashboard(records)

    OUTPUT_FILE.write_text(dashboard_md, encoding="utf-8")
    print(f"✅  Written → {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()