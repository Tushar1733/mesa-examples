#!/usr/bin/env python3
"""
update_readme_dashboard.py

Reads model health data from a JSON file and inserts/updates a
Health Dashboard section in README.md using Markdown table format.

Usage:
    python update_readme_dashboard.py \
        --json  health_data.json \
        --readme README.md

The script looks for a pair of sentinel comments in README.md:
    <!-- HEALTH_DASHBOARD_START -->
    <!-- HEALTH_DASHBOARD_END -->

If found, it replaces everything between them with the new dashboard.
If not found, it appends the dashboard (including sentinels) to the end of the file.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Status display helpers ────────────────────────────────────────────────────

STATUS_META = {
    "Active-healthy":  {"emoji": "✅", "label": "Active – Healthy"},
    "needs_upgrade":   {"emoji": "⚠️",  "label": "Needs Upgrade"},
    "broken":          {"emoji": "❌", "label": "Broken"},
}

PASS_ICON = "✔️"
FAIL_ICON = "✖️"
TRUE_ICON = "✔️"
FALSE_ICON = "✖️"


def fmt_status(status: str) -> str:
    meta = STATUS_META.get(status, {"emoji": "❓", "label": status})
    return f"{meta['emoji']} {meta['label']}"


def fmt_check(value) -> str:
    """Format a PASS/FAIL string or True/False boolean as an icon."""
    if isinstance(value, bool):
        return TRUE_ICON if value else FALSE_ICON
    return PASS_ICON if str(value).upper() == "PASS" else FAIL_ICON


# ── Dashboard builder ─────────────────────────────────────────────────────────

def build_dashboard(records: list[dict]) -> str:
    """Return the full Markdown dashboard string (without sentinel comments)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Summary counts
    counts = {"Active-healthy": 0, "needs_upgrade": 0, "broken": 0}
    for r in records:
        key = r.get("final_status", "")
        counts[key] = counts.get(key, 0) + 1

    lines = [
        "## 🩺 Health Dashboard",
        "",
        f"_Last updated: **{now}**_",
        "",
        "### Summary",
        "",
        f"| {STATUS_META['Active-healthy']['emoji']} Healthy "
        f"| {STATUS_META['needs_upgrade']['emoji']} Needs Upgrade "
        f"| {STATUS_META['broken']['emoji']} Broken |",
        "| :---: | :---: | :---: |",
        f"| {counts.get('Active-healthy', 0)} "
        f"| {counts.get('needs_upgrade', 0)} "
        f"| {counts.get('broken', 0)} |",
        "",
        "### Model Status",
        "",
        "| Model | Maintainer | Declared Server | Declared Model "
        "| Latest Server | Latest Model | Status |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in records:
        row = (
            f"| `{r.get('name', 'N/A')}` "
            f"| {r.get('maintainer', 'N/A')} "
            f"| {fmt_check(r.get('declared_server', ''))} "
            f"| {fmt_check(r.get('declared_model', False))} "
            f"| {fmt_check(r.get('latest_server', ''))} "
            f"| {fmt_check(r.get('latest_model', False))} "
            f"| {fmt_status(r.get('final_status', 'unknown'))} |"
        )
        lines.append(row)

    lines.append("")
    return "\n".join(lines)


# ── README injection ──────────────────────────────────────────────────────────

SENTINEL_START = "<!-- HEALTH_DASHBOARD_START -->"
SENTINEL_END   = "<!-- HEALTH_DASHBOARD_END -->"

BLOCK_PATTERN = re.compile(
    rf"{re.escape(SENTINEL_START)}.*?{re.escape(SENTINEL_END)}",
    re.DOTALL,
)


def inject_dashboard(readme_path: Path, dashboard_md: str) -> None:
    """Insert or replace the dashboard section in the README file."""
    original = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    block = f"{SENTINEL_START}\n{dashboard_md}\n{SENTINEL_END}"

    if SENTINEL_START in original:
        updated = BLOCK_PATTERN.sub(block, original)
    else:
        separator = "\n\n" if original and not original.endswith("\n\n") else ""
        updated = original + separator + block + "\n"

    readme_path.write_text(updated, encoding="utf-8")
    print(f"✅  README updated → {readme_path.resolve()}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inject a health dashboard into README.md from a JSON file.",
    )
    parser.add_argument(
        "--json", dest="json_path", required=True,
        help="Path to the JSON file containing health data.",
    )
    parser.add_argument(
        "--readme", dest="readme_path", default="README.md",
        help="Path to the README.md file (default: README.md).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    json_path   = Path(args.json_path)
    readme_path = Path(args.readme_path)

    # Validate JSON file
    if not json_path.exists():
        print(f"❌  JSON file not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    try:
        records = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"❌  Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(records, list):
        print("❌  JSON root must be a list of model records.", file=sys.stderr)
        sys.exit(1)

    dashboard_md = build_dashboard(records)
    inject_dashboard(readme_path, dashboard_md)


if __name__ == "__main__":
    main()