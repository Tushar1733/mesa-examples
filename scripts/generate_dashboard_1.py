"""
Mesa Examples Health Dashboard Generator
-----------------------------------------
Usage:
  python generate_dashboard.py                        # uses embedded DATA dict
  python generate_dashboard.py results.json           # reads from JSON file
  python generate_dashboard.py results.json out.md    # custom output path
"""

import json, sys
from datetime import datetime

# ── Paste your JSON here, or pass a file path as the first CLI argument ───────
DATA = {}   # populated below if no file is passed

# ── Helpers ───────────────────────────────────────────────────────────────────

def pct(n, total):
    return f"{n / total * 100:.1f}%" if total else "0%"

def progress_bar(value, total, width=20):
    filled = round(value / total * width) if total else 0
    return "█" * filled + "░" * (width - filled)

def classify_failure(ex):
    notes    = (ex.get("notes") or "").lower()
    cmd      = (ex.get("run_command") or "").lower()
    mt_notes = ((ex.get("model_test") or {}).get("notes") or "").lower()
    if "mesa runserver" in cmd:          return "Legacy API"
    if "importerror" in notes or "relative import" in notes: return "ImportError"
    if "typeerror" in notes:             return "TypeError"
    if "no mesa.model subclass" in mt_notes: return "No Model subclass"
    return "Other"

def failure_summary(examples):
    cats = {}
    for ex in examples:
        if ex["status"] != "PASS":
            cat = classify_failure(ex)
            cats.setdefault(cat, []).append(ex["name"])
    return cats

# ── Renderer ──────────────────────────────────────────────────────────────────

def generate_dashboard(data, output_path="health_dashboard.md"):
    run      = data["run"]
    summary  = data["summary"]
    examples = data["examples"]

    total    = summary["total"]
    passed   = summary["passed"]
    failed   = summary["failed"]
    timeout  = summary["timeout"]
    pass_pct = passed / total * 100 if total else 0

    gen_dt  = datetime.fromisoformat(data["generated_at"])
    gen_str = gen_dt.strftime("%Y-%m-%d %H:%M UTC")

    passing   = [e for e in examples if e["status"] == "PASS"]
    failing   = [e for e in examples if e["status"] != "PASS"]
    fail_cats = failure_summary(examples)

    # Partial passes: runner OK but model test failed
    partial = [e for e in passing
               if not (e.get("model_test") or {}).get("passed")]

    mt_pass = sum(1 for e in examples if (e.get("model_test") or {}).get("passed"))
    mt_fail = total - mt_pass

    health_emoji = "🟢" if pass_pct >= 80 else ("🟡" if pass_pct >= 50 else "🔴")
    bar = progress_bar(passed, total)

    lines = []
    def h(lvl, txt):  lines.append(f"{'#'*lvl} {txt}")
    def ln(t=""): lines.append(t)
    def hr(): lines.append("---")

    # ── Header ──
    h(1, "🧪 Mesa Examples — Health Dashboard")
    ln(f"> **Generated:** {gen_str}  \n"
       f"> **Platform:** `{run['platform']}` · **Python:** `{run['python'].split()[0]}`  \n"
       f"> **Mesa version label:** `{run['mesa_version_label']}` · **Timeout:** {run['timeout_seconds']}s")
    ln(); hr(); ln()

    # ── Health banner ──
    h(2, "Overall Health")
    ln()
    ln("```")
    ln(f"  {health_emoji}  Health Score : {pass_pct:.0f}%  [{bar}]")
    ln(f"  ✅  Passed      : {passed:>2} / {total}")
    ln(f"  ❌  Failed      : {failed:>2} / {total}")
    ln(f"  ⏱️  Timeout     : {timeout:>2} / {total}")
    ln("```")
    ln(); hr(); ln()

    # ── Summary table ──
    h(2, "📊 Summary")
    ln()
    ln("| Metric | Count | Share |")
    ln("|--------|------:|-------|")
    ln(f"| ✅ Passed          | **{passed}** | {pct(passed, total)} |")
    ln(f"| ❌ Failed          | **{failed}** | {pct(failed, total)} |")
    ln(f"| ⏱️ Timeout         | **{timeout}** | {pct(timeout, total)} |")
    ln(f"| ⚠️ Partial (pass/model fail) | **{len(partial)}** | {pct(len(partial), total)} |")
    ln(f"| 📦 Total examples  | **{total}** | 100% |")
    ln(); hr(); ln()

    # ── Failure breakdown ──
    h(2, "🔍 Failure Breakdown")
    ln()
    ln("| Category | Count | Examples |")
    ln("|----------|------:|---------|")
    for cat, names in sorted(fail_cats.items(), key=lambda x: -len(x[1])):
        names_str = ", ".join(f"`{n}`" for n in names)
        ln(f"| {cat} | {len(names)} | {names_str} |")
    # Other row if empty
    if not fail_cats:
        ln("| — | 0 | — |")
    ln()
    if partial:
        ln("> **ℹ️ Note — Partial Passes:** The following examples have a green runner status")
        ln("> but their model unit test failed:")
        ln(">")
        for ex in partial:
            mt_notes = (ex.get("model_test") or {}).get("notes", "")
            ln(f"> - `{ex['name']}`: {mt_notes}")
    ln(); hr(); ln()

    # ── All examples table ──
    h(2, "📋 All Examples")
    ln()
    ln("| Example | Runner | Model Test | Run Command | Mesa Req | Notes |")
    ln("|---------|:------:|:----------:|-------------|----------|-------|")
    for ex in examples:
        mt = ex.get("model_test") or {}
        runner_b = "✅ PASS" if ex["status"] == "PASS" else "❌ FAIL"
        mt_b     = "✅ OK"   if mt.get("passed")       else "⚠️ FAIL"
        notes    = (ex.get("notes") or "—").replace("|", "\\|")
        if len(notes) > 50:
            notes = notes[:47] + "…"
        ln(f"| **{ex['name']}** | {runner_b} | {mt_b} | "
           f"`{ex['run_command']}` | `{ex['mesa_version']}` | {notes} |")
    ln(); hr(); ln()

    # ── Passing details ──
    h(2, "✅ Passing Examples — Model Test Details")
    ln()
    for ex in passing:
        if (ex.get("model_test") or {}).get("passed"):
            h(3, f"`{ex['name']}`")
            ln(f"- **Path:** `{ex['path']}`")
            ln(f"- **Run:** `{ex['run_command']}`")
            ln(f"- **Mesa:** `{ex['mesa_version']}`")
            ln(f"- **Test:** {(ex.get('model_test') or {}).get('notes', '—')}")
            ln()

    hr(); ln()

    # ── Failing details with remediation ──
    h(2, "❌ Failing Examples — Details & Remediation")
    ln()
    remediation = {
        "Legacy API":         "Migrate `run_command` from `mesa runserver` to `solara run app.py`.",
        "ImportError":        "Fix relative imports: ensure the package is installed or run as a module (`python -m <pkg>`).",
        "TypeError":          "Check API signature — a method received too many positional arguments.",
        "No Model subclass":  "Add a `mesa.Model` subclass to `model.py` so the test runner can discover it.",
        "Other":              "Investigate the error reported in the notes field.",
    }
    for ex in failing:
        cat = classify_failure(ex)
        mt  = ex.get("model_test") or {}
        mt_status = "✅ passed" if mt.get("passed") else "❌ failed"
        h(3, f"`{ex['name']}`")
        ln(f"- **Path:** `{ex['path']}`")
        ln(f"- **Run command:** `{ex['run_command']}`")
        ln(f"- **Mesa:** `{ex['mesa_version']}`")
        ln(f"- **Runner notes:** {ex.get('notes') or '—'}")
        ln(f"- **Model test:** {mt_status} — {mt.get('notes') or '—'}")
        ln(f"- **💡 Remediation:** {remediation.get(cat, 'See notes.')}")
        ln()

    hr(); ln()

    # ── Run config ──
    h(2, "⚙️ Run Configuration")
    ln()
    ln("| Parameter | Value |")
    ln("|-----------|-------|")
    ln(f"| Examples directory | `{run['examples_dir']}` |")
    ln(f"| Timeout            | `{run['timeout_seconds']}s` |")
    ln(f"| Skip install       | `{run['skip_install']}` |")
    ln(f"| Mesa version label | `{run['mesa_version_label']}` |")
    ln(f"| Python             | `{run['python']}` |")
    ln(f"| Platform           | `{run['platform']}` |")
    ln()
    hr(); ln()
    ln("*Dashboard auto-generated by `generate_dashboard.py`*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅  Dashboard written to: {output_path}")
    print(f"    {total} examples · {passed} passed · {failed} failed · health {pass_pct:.0f}%")

DEFAULT_INPUT  = "example_validation_results(latest-deps).json"
DEFAULT_OUTPUT = "health_dashboard.md"

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    input_file  = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    output_file = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT

    try:
        with open(input_file, encoding="utf-8") as f:
            DATA = json.load(f)
        print(f"📂  Reading from: {input_file}")
    except FileNotFoundError:
        print(f"⚠️  '{input_file}' not found — falling back to embedded JSON data.")
        DATA = {
          "generated_at": "2026-03-29T22:46:38.823848+00:00",
          "run": {"examples_dir":"examples","timeout_seconds":30,"skip_install":False,"mesa_version_label":"local","python":"3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]","platform":"win32"},
          "summary": {"total":20,"passed":11,"failed":9,"timeout":0},
          "examples": [
            {"name":"aco_tsp","status":"PASS","notes":None,"path":"examples\\aco_tsp","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  num_agents=20, max_steps=1000000, ant_alpha=1.0, ant_beta=5.0"}},
            {"name":"bank_reserves","status":"PASS","notes":None,"path":"examples\\bank_reserves","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":False,"notes":"attempted relative import with no known parent package"}},
            {"name":"boltzmann_wealth_model_network","status":"PASS","notes":None,"path":"examples\\boltzmann_wealth_model_network","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  n=7, num_nodes=10, rng=None"}},
            {"name":"caching_and_replay","status":"FAIL","notes":"Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'","path":"examples\\caching_and_replay","run_command":"mesa runserver","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  height=20, width=20"}},
            {"name":"charts","status":"FAIL","notes":"Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'","path":"examples\\charts","run_command":"mesa runserver","port":8765,"maintainer":"your_username","mesa_version":">=2.0","requirements":"requirements.txt","model_test":{"passed":False,"notes":"attempted relative import with no known parent package"}},
            {"name":"color_patches","status":"FAIL","notes":"Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'","path":"examples\\color_patches","run_command":"mesa runserver","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  width=20, height=20"}},
            {"name":"conways_game_of_life_fast","status":"FAIL","notes":"ImportError","path":"examples\\conways_game_of_life_fast","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=2.3","requirements":"requirements.txt","model_test":{"passed":False,"notes":"No mesa.Model subclass found in model.py"}},
            {"name":"deffuant_weisbuch","status":"PASS","notes":None,"path":"examples\\deffuant_weisbuch","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  n=100, epsilon=0.2, mu=0.5, rng=None"}},
            {"name":"dining_philosophers","status":"PASS","notes":None,"path":"examples\\dining_philosophers","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  num_philosophers=5"}},
            {"name":"emperor_dilemma","status":"FAIL","notes":"ImportError: relative import","path":"examples\\emperor_dilemma","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  width=25, height=25"}},
            {"name":"Forest Fire Model","status":"PASS","notes":None,"path":"examples\\forest_fire","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  width=100, height=100, density=0.65, rng=None"}},
            {"name":"hex_ant","status":"FAIL","notes":"ImportError: relative import","path":"examples\\hex_ant","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":False,"notes":"attempted relative import with no known parent package"}},
            {"name":"hex_snowflake","status":"FAIL","notes":"Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'","path":"examples\\hex_snowflake","run_command":"mesa runserver","port":8765,"maintainer":"your_username","mesa_version":">=2.0","requirements":"requirements.txt","model_test":{"passed":False,"notes":"attempted relative import with no known parent package"}},
            {"name":"hotelling_law","status":"PASS","notes":None,"path":"examples\\hotelling_law","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  n_stores=20, n_consumers=100"}},
            {"name":"humanitarian_aid_distribution","status":"PASS","notes":None,"path":"examples\\humanitarian_aid_distribution","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  num_beneficiaries=30, num_trucks=3"}},
            {"name":"rumor_mill","status":"PASS","notes":None,"path":"examples\\rumor_mill","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  width=10, height=10"}},
            {"name":"shape_example","status":"FAIL","notes":"Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'","path":"examples\\shape_example","run_command":"mesa runserver","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  num_agents=2"}},
            {"name":"termites","status":"FAIL","notes":"TypeError","path":"examples\\termites","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":False,"notes":"HasPropertyLayers.add_property_layer() takes 2 positional arguments but 3 were given"}},
            {"name":"virus_antibody","status":"PASS","notes":None,"path":"examples\\virus_antibody","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  rng=None, initial_antibody=20, initial_viruses=20"}},
            {"name":"warehouse","status":"PASS","notes":None,"path":"examples\\warehouse","run_command":"solara run app.py","port":8765,"maintainer":"your_username","mesa_version":">=3.0","requirements":"requirements.txt","model_test":{"passed":True,"notes":"step() x5 passed  |  rng=42"}}
          ]
        }

    generate_dashboard(DATA, output_file)
