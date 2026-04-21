"""
mesa-examples CI Validation Script
====================================
Discovers, installs, runs, and health-checks every example in the
mesa-examples repository.  Designed for non-interactive GitHub Actions use.

Usage
-----
    python validate_examples.py [--examples-dir examples] [--timeout 30]

Exit codes
----------
    0  – script completed successfully (check JSON report for per-example results)
    1  – script-level failure (examples dir not found, or no examples discovered)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

# Force UTF-8 output on all platforms (Windows cp1252, Linux pipes, CI runners)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------
EXAMPLES_DIR     = "examples"
DEFAULT_TIMEOUT  = 30    # seconds per example (solara needs ~8-15s to boot)
SERVER_BOOT_WAIT = 10    # seconds to poll for errors before health-check
MODEL_STEP_COUNT = 5     # how many steps to run in the model unit test

# Each entry: (pattern_to_match, human-readable label)
# Order matters — more specific patterns must come first.
ERROR_PATTERNS: list[tuple[str, str]] = [
    ("attempted relative import with no known parent package", "ImportError: relative import"),
    ("has no attribute 'visualization'", "Legacy Mesa API: mesa.visualization removed"),
    ("mesa.visualization",               "Legacy Mesa API: mesa.visualization removed"),
    ("ModularServer",                    "Legacy Mesa API: ModularServer removed"),
    ("mesa runserver",                   "Legacy Mesa API: mesa runserver removed"),
    ("Unknown space type: <class 'NoneType'>", "Incomplete model: space is None"),
    ("raised exception ValueError",            "Component raised ValueError"),
    ("Unknown space type",                     "Incomplete model: unknown space type"),
    ("AttributeError",         "AttributeError"),
    ("ImportError",            "ImportError"),
    ("ModuleNotFoundError",    "ModuleNotFoundError"),
    ("ValueError",             "ValueError"),
    ("RuntimeError",           "RuntimeError"),
    ("TypeError",              "TypeError"),
    ("NameError",              "NameError"),
    ("Traceback (most recent", "Unhandled exception (Traceback)"),
]

STATUS_PASS    = "PASS"
STATUS_FAIL    = "FAIL"
STATUS_TIMEOUT = "TIMEOUT"

LEGACY_COMMANDS: list[tuple[tuple, str]] = [
    (("mesa", "runserver"), "Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'"),
    (("mesa",),             "Legacy Mesa API: mesa CLI removed - migrate to 'solara run app.py'"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ExampleMetadata:
    name: str
    path: str
    requirements: Optional[str] = None
    run: Optional[str] = None
    port: int = 8765
    maintainer: Optional[str] = None
    mesa_version: Optional[str] = None
    python: Optional[str] = None


@dataclass
class ModelTestResult:
    passed: bool
    notes: str = ""


@dataclass
class ExampleResult:
    name: str
    status: str
    notes: str = ""
    model_test: Optional[ModelTestResult] = None


# ---------------------------------------------------------------------------
# Virtualenv creation
# ---------------------------------------------------------------------------
def create_virtualenv(meta: ExampleMetadata) -> str:
    """
    Create an isolated .venv inside the example's directory (if not already
    present), upgrade pip, install solara, and install mesa from the local repo.
    Returns the path to the venv's Python executable.
    """
    venv_path = os.path.join(meta.path, ".venv")

    if sys.platform == "win32":
        python_exec = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exec = os.path.join(venv_path, "bin", "python")

    if not os.path.exists(venv_path):
        print(f"  Creating virtualenv for {meta.name} …")

        subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            check=True, timeout=60,
        )
        subprocess.run(
            [python_exec, "-m", "pip", "install", "--upgrade", "pip", "--no-cache-dir"],
            check=True, timeout=60,
        )
        print(f"  Installing solara + mesa into venv for {meta.name} …")
        subprocess.run(
            [python_exec, "-m", "pip", "install", "solara", "--no-cache-dir"],
            check=True, timeout=300,
        )
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isfile(os.path.join(repo_root, "pyproject.toml")) or \
           os.path.isfile(os.path.join(repo_root, "setup.py")):
            subprocess.run(
                [python_exec, "-m", "pip", "install", "-e", repo_root, "--no-cache-dir"],
                check=True, timeout=300,
            )
        else:
            subprocess.run(
                [python_exec, "-m", "pip", "install", "mesa", "--no-cache-dir"],
                check=True, timeout=300,
            )

    return python_exec


# ---------------------------------------------------------------------------
# 1. Discovery
# ---------------------------------------------------------------------------
def discover_examples(examples_dir: str = EXAMPLES_DIR) -> list[ExampleMetadata]:
    """Recursively find all directories containing example.yaml."""
    found: list[ExampleMetadata] = []
    for root, _dirs, files in os.walk(examples_dir):
        if "example.yaml" in files:
            meta = load_metadata(root)
            if meta:
                found.append(meta)
    return found


# ---------------------------------------------------------------------------
# 2. Metadata loading
# ---------------------------------------------------------------------------
def load_metadata(example_path: str) -> Optional[ExampleMetadata]:
    """Parse example.yaml and return an ExampleMetadata object."""
    yaml_path = os.path.join(example_path, "example.yaml")
    try:
        with open(yaml_path, "r") as fh:
            raw: dict = yaml.safe_load(fh) or {}
    except Exception as exc:
        print(f"  [WARN] Could not read {yaml_path}: {exc}")
        return None

    return ExampleMetadata(
        name=raw.get("name", os.path.basename(example_path)),
        path=os.path.abspath(example_path),
        requirements=raw.get("requirements"),
        run=raw.get("run"),
        port=int(raw.get("port", 8765)),
        maintainer=raw.get("maintainer"),
        mesa_version=str(raw.get("mesa_version", "")),
        python=str(raw.get("python", "")),
    )


# ---------------------------------------------------------------------------
# 3. Dependency installation
# ---------------------------------------------------------------------------
def _filter_requirements(req_file: str) -> list[str]:
    """Read requirements.txt, skip blank lines and comments."""
    kept: list[str] = []
    with open(req_file, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kept.append(line)
    return kept


def install_dependencies(meta: ExampleMetadata, python_exec: str) -> tuple[bool, str]:
    """Install requirements listed in metadata into the venv."""
    if not meta.requirements:
        return True, ""

    req_file = os.path.join(meta.path, meta.requirements)
    if not os.path.isfile(req_file):
        return False, f"requirements file not found: {req_file}"

    packages = _filter_requirements(req_file)
    if not packages:
        print(f"  No external dependencies to install for {meta.name}.")
        return True, ""

    print(f"  Installing {len(packages)} dependenc{'y' if len(packages) == 1 else 'ies'} from {req_file} …")
    for pkg in packages:
        print(f"    installing: {pkg}")

    result = subprocess.run(
        [python_exec, "-m", "pip", "install", *packages, "--no-cache-dir"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  pip stdout:\n{result.stdout.strip()}")
        print(f"  pip stderr:\n{result.stderr.strip()}")
        return False, f"pip install failed: {result.stderr.strip()[:300]}"

    print(f"  pip install succeeded for {meta.name}")
    return True, ""


# ---------------------------------------------------------------------------
# 4. Model unit test
# ---------------------------------------------------------------------------

# The runner script is injected as a string and executed inside the venv's
# Python so it has access to all installed packages without any imports in
# the outer process. It prints a single JSON line to stdout.
_MODEL_TEST_RUNNER = """
import sys, json, inspect, importlib.util, traceback, os

example_path = sys.argv[1]
steps        = int(sys.argv[2])

def find_model_class(module):
    try:
        import mesa
    except ImportError:
        return None
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, mesa.Model) and obj is not mesa.Model:
            return obj
    return None

def get_init_params(cls):
    try:
        sig = inspect.signature(cls.__init__)
        params = {}
        for name, p in sig.parameters.items():
            if name == "self":
                continue
            if p.default is not inspect.Parameter.empty:
                params[name] = p.default
        return params
    except Exception:
        return {}

def fmt_params(inst):
    try:
        sig = inspect.signature(inst.__class__.__init__)
        parts = []
        for i, (name, p) in enumerate(sig.parameters.items()):
            if name == "self":
                continue
            val = getattr(inst, name, p.default)
            parts.append(f"{name}={repr(val)}")
        if len(parts) > 5:
            shown = ", ".join(parts[:5])
            return shown + f" (+{len(parts)-5} more)"
        return ", ".join(parts)
    except Exception:
        return ""

# Add example path to sys.path so relative imports resolve
sys.path.insert(0, example_path)

result = {"passed": False, "notes": ""}

# Try model.py first, then app.py
for candidate in ["model.py", "app.py"]:
    fpath = os.path.join(example_path, candidate)
    if not os.path.isfile(fpath):
        continue
    try:
        spec   = importlib.util.spec_from_file_location("_model_module", fpath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = find_model_class(module)
        if cls is None:
            result["notes"] = f"No mesa.Model subclass found in {candidate}"
            continue
        params = get_init_params(cls)
        inst   = cls(**params)
        for _ in range(steps):
            inst.step()
        result["passed"] = True
        result["notes"]  = f"step() x{steps} passed  |  {fmt_params(inst)}"
        break
    except Exception as e:
        result["notes"] = str(e) if str(e) else type(e).__name__
        break

print(json.dumps(result))
"""


def run_model_test(meta: ExampleMetadata, python_exec: str) -> ModelTestResult:
    """
    Run the model unit test in an isolated subprocess inside the venv.
    Imports model.py (or app.py), finds the mesa.Model subclass,
    instantiates it with default params, and calls step() MODEL_STEP_COUNT times.
    Returns a ModelTestResult with passed=True/False and a notes string.
    """
    print(f"  Running model test for {meta.name} …")
    try:
        result = subprocess.run(
            [python_exec, "-c", _MODEL_TEST_RUNNER, meta.path, str(MODEL_STEP_COUNT)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "PYTHONPATH": meta.path,
                "PATH": os.path.dirname(python_exec) + os.pathsep + os.environ.get("PATH", ""),
                "VIRTUAL_ENV": os.path.dirname(os.path.dirname(python_exec)),
                "MPLBACKEND": "Agg",
            },
        )
    except subprocess.TimeoutExpired:
        return ModelTestResult(passed=False, notes="Model test timed out after 60s")
    except Exception as exc:
        return ModelTestResult(passed=False, notes=f"Model test error: {exc}")

    # Parse the JSON line printed by the runner
    output = result.stdout.strip()
    if not output:
        stderr = result.stderr.strip()
        # Extract the most useful line from stderr
        last_meaningful = next(
            (l for l in reversed(stderr.splitlines()) if l.strip()),
            f"No output (exit code {result.returncode})"
        )
        return ModelTestResult(passed=False, notes=last_meaningful)

    try:
        data = json.loads(output.splitlines()[-1])
        return ModelTestResult(passed=data["passed"], notes=data.get("notes", ""))
    except Exception:
        return ModelTestResult(passed=False, notes=f"Could not parse model test output: {output[:200]}")


# ---------------------------------------------------------------------------
# 5. Command building
# ---------------------------------------------------------------------------
def _build_command(run_cmd: str, python_exec: str, port: int) -> list[str]:
    """
    Convert the run string from metadata into an argv list for Popen.
    Resolves venv binaries, rejects legacy commands, injects --port.
    """
    parts = run_cmd.strip().split()

    for legacy_parts, message in LEGACY_COMMANDS:
        if tuple(parts[:len(legacy_parts)]) == legacy_parts:
            raise ValueError(message)

    venv_bin = os.path.dirname(python_exec)

    if parts[0] == "python":
        parts[0] = python_exec

    if parts[0] == "solara":
        solara_in_venv = os.path.join(venv_bin, "solara")
        if os.path.exists(solara_in_venv):
            parts[0] = solara_in_venv

    if "solara" in parts[0] and "run" in parts and "--port" not in parts:
        parts.extend(["--port", str(port)])

    return parts


# ---------------------------------------------------------------------------
# 6. Error detection
# ---------------------------------------------------------------------------
def detect_errors(text: str) -> Optional[str]:
    for pattern, label in ERROR_PATTERNS:
        if pattern in text:
            return label
    return None


# ---------------------------------------------------------------------------
# 7. Health check
# ---------------------------------------------------------------------------
def check_server(port: int, deadline: float, retries: int = 5, delay: float = 1.0) -> bool:
    url = f"http://localhost:{port}"
    for attempt in range(1, retries + 1):
        if time.time() >= deadline:
            return False
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# 8. Run example (server test)
# ---------------------------------------------------------------------------
def run_example(meta: ExampleMetadata, python_exec: str, timeout: int = DEFAULT_TIMEOUT) -> ExampleResult:
    """
    Launch the example, wait for boot, health-check the server, terminate.
    Returns an ExampleResult with PASS / FAIL / TIMEOUT and model_test populated.
    """
    if not meta.run:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes="No run command in metadata")

    try:
        cmd = _build_command(meta.run, python_exec, meta.port)
    except ValueError as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    print(f"  Running: {' '.join(cmd)}")

    ci_env = os.environ.copy()
    ci_env["PYTHONUNBUFFERED"]        = "1"
    ci_env["PYTHONDONTWRITEBYTECODE"] = "1"
    ci_env["BROWSER"]                 = "echo"
    ci_env["MPLBACKEND"]              = "Agg"
    if sys.platform != "win32":
        ci_env.pop("DISPLAY", None)

    venv_bin = os.path.dirname(python_exec)
    ci_env["PATH"]        = venv_bin + os.pathsep + ci_env.get("PATH", "")
    ci_env["VIRTUAL_ENV"] = os.path.dirname(venv_bin)

    deadline = time.time() + timeout

    try:
        process = subprocess.Popen(
            cmd,
            cwd=meta.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=ci_env,
            shell=(sys.platform == "win32"),
        )
    except FileNotFoundError:
        try:
            process = subprocess.Popen(
                " ".join(cmd),
                cwd=meta.path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                env=ci_env, shell=True,
            )
        except Exception:
            return ExampleResult(
                name=meta.name, status=STATUS_FAIL,
                notes=f"Command not found: '{cmd[0]}' is not installed or not on PATH",
            )
    except Exception as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    import threading
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def drain(stream, bucket):
        try:
            for line in stream:
                bucket.append(line)
        except Exception:
            pass

    t_out = threading.Thread(target=drain, args=(process.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=drain, args=(process.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < SERVER_BOOT_WAIT:
        if time.time() >= deadline:
            _terminate(process, meta.port)
            t_out.join(timeout=2); t_err.join(timeout=2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err = detect_errors(combined)
            if err:
                return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err)
            return ExampleResult(name=meta.name, status=STATUS_TIMEOUT,
                                 notes=f"Timed out during boot wait after {timeout}s")

        time.sleep(poll_interval)
        elapsed += poll_interval

        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err = detect_errors(combined)
        if err:
            _terminate(process, meta.port)
            t_out.join(timeout=2); t_err.join(timeout=2)
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err)

        if process.poll() is not None:
            process.wait()
            t_out.join(timeout=3); t_err.join(timeout=3)
            time.sleep(0.2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err = detect_errors(combined)
            note = err if err else f"Process exited early (code {process.returncode})"
            if combined.strip():
                print(f"  --- captured output ---")
                for line in combined.splitlines()[-20:]:
                    print(f"  | {line}")
                print(f"  --- end output ---")
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    if process.poll() is not None:
        process.wait()
        t_out.join(timeout=3); t_err.join(timeout=3)
        time.sleep(0.2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err = detect_errors(combined)
        note = err if err else f"Process exited early (code {process.returncode})"
        if combined.strip():
            print(f"  --- captured output ---")
            for line in combined.splitlines()[-20:]:
                print(f"  | {line}")
            print(f"  --- end output ---")
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    if time.time() >= deadline:
        _terminate(process, meta.port)
        t_out.join(timeout=2); t_err.join(timeout=2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err = detect_errors(combined)
        if err:
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err)
        return ExampleResult(name=meta.name, status=STATUS_TIMEOUT,
                             notes=f"Timed out before health-check after {timeout}s")

    server_ok = check_server(meta.port, deadline=deadline)
    _terminate(process, meta.port)
    t_out.join(timeout=2); t_err.join(timeout=2)

    if server_ok:
        return ExampleResult(name=meta.name, status=STATUS_PASS)

    if time.time() >= deadline:
        return ExampleResult(name=meta.name, status=STATUS_TIMEOUT,
                             notes=f"Timed out during health-check after {timeout}s")

    return ExampleResult(name=meta.name, status=STATUS_FAIL,
                         notes=f"Server did not respond on port {meta.port}")


# ---------------------------------------------------------------------------
# 9. Process cleanup
# ---------------------------------------------------------------------------
def _kill_port(port: int) -> None:
    import signal as _signal
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.strip().split()[-1])
                    subprocess.call(["taskkill", "/F", "/PID", str(pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"],
                                          text=True, stderr=subprocess.DEVNULL)
            for pid_str in out.strip().splitlines():
                try:
                    os.kill(int(pid_str), _signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass


def _terminate(process: subprocess.Popen, port: int = 0) -> None:
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except Exception:
        pass
    try:
        import signal
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        pass
    if port:
        _kill_port(port)
        time.sleep(1.5)


# ---------------------------------------------------------------------------
# 10. Report generation
# ---------------------------------------------------------------------------
def generate_report(
    results: list[ExampleResult],
    examples: list[ExampleMetadata],
    run_meta: dict,
    output_json: str = "validation_report.json",
) -> None:
    passes   = sum(1 for r in results if r.status == STATUS_PASS)
    fails    = sum(1 for r in results if r.status == STATUS_FAIL)
    timeouts = sum(1 for r in results if r.status == STATUS_TIMEOUT)

    # Console table
    col_name = max(max((len(r.name) for r in results), default=0), 20)
    header   = f"{'Example Name':<{col_name}}  {'Status':<8}  {'Model Test':<12}  Notes"
    print("\n" + "=" * (len(header) + 4))
    print(header)
    print("-" * (len(header) + 4))
    for r in results:
        mt = ""
        if r.model_test:
            mt = "PASS" if r.model_test.passed else "FAIL"
        print(f"{r.name:<{col_name}}  {r.status:<8}  {mt:<12}  {r.notes[:50] if r.notes else ''}")
    print("=" * (len(header) + 4))
    print(f"\nTotal : {len(results)}")
    print(f"  {STATUS_PASS:<8}: {passes}")
    print(f"  {STATUS_FAIL:<8}: {fails}")
    print(f"  {STATUS_TIMEOUT:<8}: {timeouts}")
    print()

    meta_by_name = {m.name: m for m in examples}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": run_meta,
        "summary": {
            "total":   len(results),
            "passed":  passes,
            "failed":  fails,
            "timeout": timeouts,
        },
        "examples": [
            {
                "name":         r.name,
                "status":       r.status,
                "notes":        r.notes or None,
                "path":         meta_by_name[r.name].path         if r.name in meta_by_name else None,
                "run_command":  meta_by_name[r.name].run          if r.name in meta_by_name else None,
                "port":         meta_by_name[r.name].port         if r.name in meta_by_name else None,
                "maintainer":   meta_by_name[r.name].maintainer   if r.name in meta_by_name else None,
                "mesa_version": meta_by_name[r.name].mesa_version if r.name in meta_by_name else None,
                "requirements": meta_by_name[r.name].requirements if r.name in meta_by_name else None,
                "model_test": {
                    "passed": r.model_test.passed,
                    "notes":  r.model_test.notes,
                } if r.model_test else None,
            }
            for r in results
        ],
    }

    with open(output_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"  JSON report saved to: {output_json}\n")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def _resolve_output_path(cli_value: Optional[str]) -> tuple[str, str]:
    mesa_label = os.getenv("MESA_VERSION_LABEL", "").strip()
    if cli_value:
        return cli_value, mesa_label or "local"
    if mesa_label:
        return f"example_validation_results_{mesa_label}.json", mesa_label
    return "example_validation_results_declared-deps.json", "local"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mesa-examples in CI")
    parser.add_argument("--examples-dir", default=EXAMPLES_DIR)
    parser.add_argument("--timeout",      type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--output-json",  default=None)
    args = parser.parse_args()

    output_json, mesa_label = _resolve_output_path(args.output_json)

    print("mesa-examples Validator")
    print(f"  Working dir  : {os.getcwd()}")
    print(f"  Script dir   : {os.path.dirname(os.path.abspath(__file__))}")
    print(f"  Examples dir : {args.examples_dir}")
    print(f"  Timeout      : {args.timeout}s per example")
    print(f"  JSON output  : {output_json}")
    if mesa_label != "local":
        print(f"  Mesa label   : {mesa_label}")
    print()

    args.examples_dir = os.path.abspath(args.examples_dir)

    if not os.path.isdir(args.examples_dir):
        print(f"ERROR: Examples directory not found: {args.examples_dir}")
        return 1

    examples = discover_examples(args.examples_dir)
    print(f"Found {len(examples)} example(s).\n")

    if not examples:
        print("ERROR: No examples found — check --examples-dir or example.yaml files.")
        return 1

    results: list[ExampleResult] = []

    for meta in examples:
        print(f"[ {meta.name} ]  ({meta.path})")

        try:
            python_exec = create_virtualenv(meta)
        except Exception as exc:
            print(f"  Virtualenv creation failed: {exc}")
            results.append(ExampleResult(name=meta.name, status=STATUS_FAIL,
                                         notes=f"Venv error: {exc}"))
            continue

        if not args.skip_install:
            ok, err = install_dependencies(meta, python_exec)
            if not ok:
                print(f"  Dependency install failed: {err}")
                results.append(ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err))
                continue

        # ── Model unit test (always runs regardless of server test outcome) ──
        model_result = run_model_test(meta, python_exec)
        mt_icon = "PASS" if model_result.passed else "FAIL"
        print(f"  [model {mt_icon}]  {model_result.notes[:80]}")

        # ── Server / solara test ──────────────────────────────────────────────
        result = run_example(meta, python_exec=python_exec, timeout=args.timeout)
        result.model_test = model_result

        icon = "PASS" if result.status == STATUS_PASS else (
               "TIME" if result.status == STATUS_TIMEOUT else "FAIL")
        print(f"  [server {icon}]" + (f"  {result.notes}" if result.notes else ""))
        results.append(result)
        print()

    run_meta = {
        "examples_dir":       args.examples_dir,
        "timeout_seconds":    args.timeout,
        "skip_install":       args.skip_install,
        "mesa_version_label": mesa_label,
        "python":             sys.version,
        "platform":           sys.platform,
    }
    generate_report(results, examples, run_meta, output_json=output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
    
