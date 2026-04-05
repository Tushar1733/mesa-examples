#!/usr/bin/env python3
"""
scripts/generate_dashboard_1.py

Reads the two JSON validation reports produced by Workflow 1:
  - example_validation_results(declared-deps).json
  - example_validation_results(latest-deps).json

Then writes/updates health_dashboard.md in the repo root.

Called by Workflow 2 with NO arguments:
  python scripts/generate_dashboard_1.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── File paths (relative to repo root, where the workflow runs) ───────────────

DECLARED_JSON = Path("example_validation_results(declared-deps).json")
LATEST_JSON   = Path("example_validation_results(latest-deps).json")
OUTPUT_FILE   = Path("health_dashboard.md")

# ── Status display helpers ────────────────────────────────────────────────────

STATUS_META = {
    "Active-healthy": {"emoji": "✅", "label": "Active – Healthy"},
    "needs_upgrade":  {"emoji": "⚠️",  "label": "Needs Upgrade"},
    "broken":         {"emoji": "❌", "label": "Broken"},
}

PASS_ICON  = "✔️"
FAIL_ICON  = "✖️"


def fmt_check(value) -> str:
    """Render a PASS/FAIL string or True/False bool as an icon."""
    if isinstance(value, bool):
        return PASS_ICON if value else FAIL_ICON
    return PASS_ICON if str(value).upper() == "PASS" else FAIL_ICON


def fmt_status(status: str) -> str:
    meta = STATUS_META.get(status, {"emoji": "❓", "label": status})
    return f"{meta['emoji']} {meta['label']}"


# ── JSON loading ──────────────────────────────────────────────────────────────

def load_examples(path: Path) -> list[dict]:
    """
    Load examples from a JSON file.
    Accepts two shapes:
      - A bare list:              [ { "name": ..., ... }, ... ]
      - A dict with an "examples" key: { "examples": [ ... ] }
    Returns an empty list on missing / invalid / empty file.
    """
    if not path.exists() or path.stat().st_size == 0:
        print(f"⚠️  {path} missing or empty — treating as no examples.")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"⚠️  {path} is invalid JSON ({exc}) — treating as no examples.")
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("examples", [])

    print(f"⚠️  Unexpected JSON shape in {path} — treating as no examples.")
    return []


# ── Record merging ────────────────────────────────────────────────────────────

def merge_records(declared: list[dict], latest: list[dict]) -> list[dict]:
    """
    Merge declared-deps and latest-deps results into one record per example.

    Each output record has:
      name, maintainer,
      declared_server, declared_model,
      latest_server,   latest_model,
      final_status
    """
    # Index latest results by name for O(1) lookup
    latest_by_name = {r.get("name"): r for r in latest}

    records = []
    for d in declared:
        name = d.get("name", "unknown")
        l    = latest_by_name.get(name, {})

        declared_server = d.get("server_status") or d.get("declared_server", "FAIL")
        declared_model  = d.get("model_ok")      if "model_ok" in d \
                          else d.get("declared_model", False)

        latest_server   = l.get("server_status") or l.get("latest_server", "FAIL")
        latest_model    = l.get("model_ok")       if "model_ok" in l \
                          else l.get("latest_model", False)

        # Derive final_status if not already present
        final_status = d.get("final_status") or l.get("final_status")
        if not final_status:
            d_pass = str(declared_server).upper() == "PASS" and bool(declared_model)
            l_pass = str(latest_server).upper()   == "PASS" and bool(latest_model)
            if d_pass and l_pass:
                final_status = "Active-healthy"
            elif d_pass and not l_pass:
                final_status = "needs_upgrade"
            else:
                final_status = "broken"

        records.append({
            "name":            name,
            "maintainer":      d.get("maintainer") or l.get("maintainer", "—"),
            "declared_server": declared_server,
            "declared_model":  declared_model,
            "latest_server":   latest_server,
            "latest_model":    latest_model,
            "final_status":    final_status,
        })

    # Include any examples that appear only in latest (not in declared)
    declared_names = {r.get("name") for r in declared}
    for l in latest:
        name = l.get("name", "unknown")
        if name not in declared_names:
            latest_server  = l.get("server_status") or l.get("latest_server", "FAIL")
            latest_model   = l.get("model_ok") if "model_ok" in l \
                             else l.get("latest_model", False)
            records.append({
                "name":            name,
                "maintainer":      l.get("maintainer", "—"),
                "declared_server": "—",
                "declared_model":  False,
                "latest_server":   latest_server,
                "latest_model":    latest_model,
                "final_status":    l.get("final_status", "broken"),
            })

    return records


# ── Dashboard builder ─────────────────────────────────────────────────────────

def build_dashboard(records: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    counts: dict[str, int] = {}
    for r in records:
        key = r.get("final_status", "unknown")
        counts[key] = counts.get(key, 0) + 1

    healthy  = counts.get("Active-healthy", 0)
    upgrade  = counts.get("needs_upgrade",  0)
    broken   = counts.get("broken",         0)
    total    = len(records)

    lines = [
        "# 🩺 Health Dashboard",
        "",
        f"_Last updated: **{now}**_ &nbsp;|&nbsp; "
        f"**{total}** examples tracked",
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
            f"| `{r['name']}` "
            f"| {r['maintainer']} "
            f"| {fmt_check(r['declared_server'])} "
            f"| {fmt_check(r['declared_model'])} "
            f"| {fmt_check(r['latest_server'])} "
            f"| {fmt_check(r['latest_model'])} "
            f"| {fmt_status(r['final_status'])} |"
        )

    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"📂  Loading {DECLARED_JSON} …")
    declared = load_examples(DECLARED_JSON)

    print(f"📂  Loading {LATEST_JSON} …")
    latest   = load_examples(LATEST_JSON)

    if not declared and not latest:
        print("❌  Both JSON files are empty or missing. Nothing to write.",
              file=sys.stderr)
        sys.exit(1)

    print(f"🔀  Merging {len(declared)} declared + {len(latest)} latest records …")
    records = merge_records(declared, latest)

    print(f"🏗️   Building dashboard for {len(records)} examples …")
    dashboard_md = build_dashboard(records)

    OUTPUT_FILE.write_text(dashboard_md, encoding="utf-8")
    print(f"✅  Written → {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()