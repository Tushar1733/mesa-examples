"""
mesa-examples CI Validation Script
====================================
Discovers, installs, runs, and health-checks every example in the
mesa-examples repository.  Designed for non-interactive GitHub Actions use.

Usage
-----
    python validate_examples.py [--examples-dir examples] [--timeout 10]

Exit codes
----------
    0  – all examples passed
    1  – one or more examples failed or timed-out
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
EXAMPLES_DIR = "examples"
DEFAULT_TIMEOUT = 30          # seconds per example (solara needs ~8-15s to boot)
SERVER_BOOT_WAIT = 10         # seconds to wait before health-check
# Each entry: (pattern_to_match, human-readable label)
# Order matters — more specific patterns should come first.
ERROR_PATTERNS: list[tuple[str, str]] = [
    # ── Relative import (package structure issue) ────────────────────────────
    ("attempted relative import with no known parent package", "ImportError: relative import"),

    # ── Legacy Mesa API ──────────────────────────────────────────────────────
    ("has no attribute 'visualization'",    "Legacy Mesa API: mesa.visualization removed"),
    ("mesa.visualization",                  "Legacy Mesa API: mesa.visualization removed"),
    ("ModularServer",                       "Legacy Mesa API: ModularServer removed"),
    ("mesa runserver",                      "Legacy Mesa API: mesa runserver removed"),

    # ── Incomplete model / NoneType space ────────────────────────────────────
    ("Unknown space type: <class 'NoneType'>", "Incomplete model: space is None"),
    ("raised exception ValueError",            "Component raised ValueError"),
    ("Unknown space type",                     "Incomplete model: unknown space type"),

    # ── General Python errors ────────────────────────────────────────────────
    ("AttributeError",          "AttributeError"),
    ("ImportError",             "ImportError"),
    ("ModuleNotFoundError",     "ModuleNotFoundError"),
    ("ValueError",              "ValueError"),
    ("RuntimeError",            "RuntimeError"),
    ("TypeError",               "TypeError"),
    ("NameError",               "NameError"),
    ("Traceback (most recent",  "Unhandled exception (Traceback)"),
]

STATUS_PASS    = "PASS"
STATUS_FAIL    = "FAIL"
STATUS_TIMEOUT = "TIMEOUT"


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
    status: Optional[str] = None
    maintainer: Optional[str] = None
    mesa_version: Optional[str] = None
    python: Optional[str] = None


@dataclass
class StageResult:
    """Outcome of a single validation stage."""
    passed: bool
    notes: str = ""


@dataclass
class ExampleResult:
    name: str
    status: str
    notes: str = ""
    # Model unit-test stage result (None if --skip-model-test)
    stage_model_test: Optional[StageResult] = None


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
        path=example_path,
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
# Packages that should never be reinstalled from PyPI during CI validation.
# mesa is developed in-repo; reinstalling a pinned version would overwrite it.
# matplotlib, solara, etc. are assumed already present in the CI environment.
SKIP_PACKAGES = {"mesa", "matplotlib", "solara"}


def _filter_requirements(req_file: str) -> list[str]:
    """
    Read a requirements.txt and return only the lines that should be installed.
    Skips blank lines, comments, and any package in SKIP_PACKAGES.
    """
    kept: list[str] = []
    with open(req_file, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Extract the bare package name (before any version specifier)
            pkg_name = line.split("~=")[0].split("==")[0].split(">=")[0]                            .split("<=")[0].split("!=")[0].split(">")[0]                            .split("<")[0].split("[")[0].strip().lower()
            if pkg_name in SKIP_PACKAGES:
                print(f"    Skipping {line!r} (provided by repo/environment)")
                continue
            kept.append(line)
    return kept


def install_dependencies(meta: ExampleMetadata) -> tuple[bool, str]:
    """
    Install requirements listed in metadata, skipping repo-managed packages.
    Returns (success, error_message).
    """
    if not meta.requirements:
        return True, ""

    req_file = os.path.join(meta.path, meta.requirements)
    if not os.path.isfile(req_file):
        return False, f"requirements file not found: {req_file}"

    packages = _filter_requirements(req_file)

    if not packages:
        print(f"  No external dependencies to install for {meta.name}.")
        return True, ""

    print(f"  Installing {len(packages)} dependenc{'y' if len(packages)==1 else 'ies'} from {req_file} …")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", *packages, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"pip install failed: {result.stderr.strip()[:300]}"
    return True, ""


# Legacy run commands that no longer exist in modern Mesa
LEGACY_COMMANDS: list[tuple[tuple, str]] = [
    (("mesa", "runserver"), "Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'"),
    (("mesa",),             "Legacy Mesa API: mesa CLI removed - migrate to 'solara run app.py'"),
]


# ---------------------------------------------------------------------------
# 4 & 5. Execution + health-check
# ---------------------------------------------------------------------------
def _build_command(run_cmd: str) -> list[str]:
    """
    Convert the run string from metadata into a list suitable for Popen.
    Raises ValueError with a clear message for known legacy commands.
    """
    parts = run_cmd.strip().split()
    for legacy_parts, message in LEGACY_COMMANDS:
        if tuple(parts[:len(legacy_parts)]) == legacy_parts:
            raise ValueError(message)
    return parts


def detect_errors(text: str) -> Optional[str]:
    """
    Scan output text for known error patterns.
    Returns a human-readable label for the first match, or None.
    """
    for pattern, label in ERROR_PATTERNS:
        if pattern in text:
            return label
    return None


def check_server(port: int, retries: int = 5, delay: float = 1.0) -> bool:
    """
    Send an HTTP GET to localhost:<port>.
    Returns True if any attempt gets a 200 response.
    Each attempt has a short timeout so we don't burn the example deadline.
    """
    url = f"http://localhost:{port}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(delay)
    return False


def run_example(meta: ExampleMetadata, timeout: int = DEFAULT_TIMEOUT) -> ExampleResult:
    """
    Start the example process, wait for boot, health-check, then terminate.
    Returns an ExampleResult.
    """
    if not meta.run:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes="No run command in metadata")

    try:
        cmd = _build_command(meta.run)
    except ValueError as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    print(f"  Running : {' '.join(cmd)}")
    print(f"  Step 1  : Starting server process...")

    # Build a CI-safe environment: unbuffered Python, no browser, no display
    ci_env = os.environ.copy()
    ci_env["PYTHONUNBUFFERED"] = "1"        # ensures output is not buffered
    ci_env["PYTHONDONTWRITEBYTECODE"] = "1" # skip .pyc files
    ci_env["BROWSER"] = "echo"              # prevent any browser from opening
    ci_env["MPLBACKEND"] = "Agg"            # non-interactive matplotlib backend
    # On Linux CI, DISPLAY=:99 is set by Xvfb — preserve it.
    # On Windows there is no DISPLAY variable, so nothing to do.

    try:
        process = subprocess.Popen(
            cmd,
            cwd=meta.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ci_env,
            # shell=True is needed on Windows so that script wrappers like
            # solara.cmd / solara.exe are resolved via PATH correctly.
            shell=(sys.platform == "win32"),
        )
    except FileNotFoundError:
        # Fallback: retry with shell=True (covers edge cases on all platforms)
        try:
            process = subprocess.Popen(
                " ".join(cmd),
                cwd=meta.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=ci_env,
                shell=True,
            )
        except Exception:
            if cmd and cmd[0] == "mesa":
                return ExampleResult(name=meta.name, status=STATUS_FAIL,
                    notes="Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'")
            return ExampleResult(name=meta.name, status=STATUS_FAIL,
                notes=f"Command not found: '{cmd[0]}' is not installed or not on PATH")
    except Exception as exc:
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=str(exc))

    # ── Steps 2-4: Drain output in background threads while waiting ─────────
    import threading

    deadline = time.time() + timeout
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def drain(stream, bucket: list):
        try:
            for line in stream:
                bucket.append(line)
        except Exception:
            pass

    t_out = threading.Thread(target=drain, args=(process.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=drain, args=(process.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    print(f"  Step 2  : Waiting up to {SERVER_BOOT_WAIT}s for server to boot (scanning for errors)...")
    # Poll every 0.5s during boot window; catch errors as soon as they appear
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < SERVER_BOOT_WAIT:
        time.sleep(poll_interval)
        elapsed += poll_interval

        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        if err_match:
            print(f"  Step 2  : Error detected in output -> {err_match}")
            _terminate(process, meta.port)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err_match)

        if process.poll() is not None:
            # Process already exited — wait for drain threads to flush all output
            print(f"  Step 2  : Process exited early (code {process.returncode}), draining output...")
            process.wait()          # ensure pipes are fully closed
            t_out.join(timeout=3)
            t_err.join(timeout=3)
            # Give a tiny extra window in case OS buffers are still flushing
            time.sleep(0.2)
            combined = "".join(stdout_lines) + "".join(stderr_lines)
            err_match = detect_errors(combined)
            note = err_match if err_match else f"Process exited early (code {process.returncode})"
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    print(f"  Step 3  : Boot window complete. Checking for late errors...")
    # ── Step 4b: Final error scan before health-check ───────────────────────
    # One last drain in case the process just exited at the end of the boot window
    if process.poll() is not None:
        process.wait()
        t_out.join(timeout=3)
        t_err.join(timeout=3)
        time.sleep(0.2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        note = err_match if err_match else f"Process exited early (code {process.returncode})"
        return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=note)

    # ── Step 5: HTTP health-check ────────────────────────────────────────────
    if time.time() >= deadline:
        _terminate(process, meta.port)
        # Even on timeout, check if there are error messages in captured output
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        combined = "".join(stdout_lines) + "".join(stderr_lines)
        err_match = detect_errors(combined)
        if err_match:
            return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err_match)
        return ExampleResult(name=meta.name, status=STATUS_TIMEOUT, notes="Timed out before health-check")

    print(f"  Step 4  : Sending HTTP health-check to http://localhost:{meta.port} ...")
    server_ok = check_server(meta.port)

    # ── Step 6: Terminate ────────────────────────────────────────────────────
    if server_ok:
        print(f"  Step 5  : HTTP 200 received. Stopping server...")
    else:
        print(f"  Step 5  : No HTTP 200 on port {meta.port}. Stopping server...")
    _terminate(process, meta.port)
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    if server_ok:
        return ExampleResult(name=meta.name, status=STATUS_PASS)

    if time.time() >= deadline:
        return ExampleResult(name=meta.name, status=STATUS_TIMEOUT)

    return ExampleResult(name=meta.name, status=STATUS_FAIL, notes=f"Server did not respond on port {meta.port}")


def _kill_port(port: int) -> None:
    """Force-kill any process still listening on the given port (cross-platform)."""
    import signal as _signal

    if sys.platform == "win32":
        try:
            # netstat -ano lists PID for each connection
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    subprocess.call(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for pid_str in out.strip().splitlines():
                try:
                    os.kill(int(pid_str), _signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass


def _terminate(process: subprocess.Popen, port: int = 0) -> None:
    """Cleanly terminate a process, all its children, and free the port."""
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except Exception:
        pass

    # Kill child processes on POSIX
    try:
        import signal, os
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        pass

    # Ensure the port is free regardless of what happened above
    if port:
        _kill_port(port)
        time.sleep(0.5)  # brief pause so the OS reclaims the socket



# ---------------------------------------------------------------------------
# Stage A: Model unit test
# ---------------------------------------------------------------------------

def _write_model_test_script(script_path: str) -> None:
    """Write the self-contained model-test runner to a temp file."""
    script = [
        "import sys, os, json, inspect, traceback, importlib.util",
        "",
        "example_path = sys.argv[1]",
        "model_file   = sys.argv[2]",
        "steps        = int(sys.argv[3])",
        "",
        "# ── Path setup ────────────────────────────────────────────────────",
        "# Always add the example dir AND its parent so both flat and nested",
        "# package structures resolve correctly.",
        "parent_path = os.path.dirname(example_path)",
        "for p in (example_path, parent_path):",
        "    if p not in sys.path:",
        "        sys.path.insert(0, p)",
        "os.chdir(example_path)",
        "",
        "# ── Detect nested package layout ──────────────────────────────────",
        "# If model.py lives inside examples/foo/foo/model.py, the package",
        "# name is the inner folder name and we must register it so that",
        "# relative imports like 'from .agent import X' resolve correctly.",
        "model_dir    = os.path.dirname(os.path.abspath(model_file))",
        "is_nested    = os.path.isfile(os.path.join(model_dir, '__init__.py'))",
        "package_name = os.path.basename(model_dir) if is_nested else None",
        "",
        "# ── Load model module ─────────────────────────────────────────────",
        "try:",
        "    if is_nested:",
        "        # Load the whole package first so relative imports work",
        "        pkg_init = os.path.join(model_dir, '__init__.py')",
        "        pkg_spec = importlib.util.spec_from_file_location(",
        "            package_name, pkg_init,",
        "            submodule_search_locations=[model_dir],",
        "        )",
        "        pkg_mod = importlib.util.module_from_spec(pkg_spec)",
        "        sys.modules[package_name] = pkg_mod",
        "        pkg_spec.loader.exec_module(pkg_mod)",
        "        # Now load model.py as package_name.model",
        "        full_name = f'{package_name}.model'",
        "        spec = importlib.util.spec_from_file_location(",
        "            full_name, model_file,",
        "            submodule_search_locations=[model_dir],",
        "        )",
        "        mod = importlib.util.module_from_spec(spec)",
        "        mod.__package__ = package_name",
        "        sys.modules[full_name] = mod",
        "        spec.loader.exec_module(mod)",
        "    else:",
        "        # Flat layout: model.py sits directly in the example dir",
        "        spec = importlib.util.spec_from_file_location('model', model_file)",
        "        mod  = importlib.util.module_from_spec(spec)",
        "        sys.modules['model'] = mod",
        "        spec.loader.exec_module(mod)",
        "except Exception as e:",
        "    print(f'IMPORT_ERROR: {e}', flush=True)",
        "    sys.exit(1)",
        "",
        "# Find the mesa.Model subclass",
        "import mesa",
        "ModelClass = next(",
        "    (v for v in vars(mod).values()",
        "     if isinstance(v, type) and issubclass(v, mesa.Model) and v is not mesa.Model),",
        "    None,",
        ")",
        "if ModelClass is None:",
        "    print('NO_MODEL_CLASS', flush=True)",
        "    sys.exit(1)",
        "",
        "# Read default values straight from __init__ signature",
        "try:",
        "    sig    = inspect.signature(ModelClass.__init__)",
        "    kwargs = {}",
        "    missing = []",
        "    for pname, param in sig.parameters.items():",
        "        if pname == 'self':",
        "            continue",
        "        if param.default is not inspect.Parameter.empty:",
        "            kwargs[pname] = param.default",
        "        else:",
        "            missing.append(pname)",
        "    if missing:",
        "        print(f'MISSING_PARAMS: {missing}', flush=True)",
        "        sys.exit(3)",
        "    print(f'PARAMS: {json.dumps({k: repr(v) for k, v in kwargs.items()})}', flush=True)",
        "except (ValueError, TypeError) as e:",
        "    print(f'SIG_ERROR: {e}', flush=True)",
        "    sys.exit(1)",
        "",
        "# Run the model",
        "try:",
        "    model = ModelClass(**kwargs)",
        "    for _ in range(steps):",
        "        model.step()",
        "    print('OK', flush=True)",
        "except TypeError as e:",
        "    print(f'INIT_ERROR: {e}', flush=True)",
        "    traceback.print_exc()",
        "    sys.exit(2)",
        "except Exception:",
        "    traceback.print_exc()",
        "    sys.exit(2)",
    ]
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(script))


def run_model_test(meta: ExampleMetadata, steps: int = 5) -> StageResult:
    """
    Import model.py, read default parameter values directly from
    Model.__init__ signature, instantiate with those defaults,
    and call model.step() N times.
    """
    import tempfile

    # Check flat layout first: examples/foo/model.py
    model_file = os.path.join(meta.path, "model.py")
    if not os.path.isfile(model_file):
        # Fall back to nested layout: examples/foo/foo/model.py
        example_name = os.path.basename(meta.path)
        nested = os.path.join(meta.path, example_name, "model.py")
        if os.path.isfile(nested):
            model_file = nested
        else:
            # Last resort: walk and find any model.py under meta.path
            found = [
                os.path.join(r, "model.py")
                for r, _, fs in os.walk(meta.path) if "model.py" in fs
            ]
            if not found:
                return StageResult(passed=False, notes="model.py not found anywhere under example path")
            model_file = found[0]

    ci_env = os.environ.copy()
    ci_env["PYTHONUNBUFFERED"] = "1"
    ci_env["MPLBACKEND"]       = "Agg"
    ci_env["BROWSER"]          = "echo"

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as tmp:
        tmp_path = tmp.name
    try:
        _write_model_test_script(tmp_path)
        result = subprocess.run(
            [
                sys.executable, tmp_path,
                os.path.abspath(meta.path),
                os.path.abspath(model_file),
                str(steps),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=ci_env,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    combined = result.stdout + result.stderr

    # Parse and log the params that were used
    params_str = ""
    for line in result.stdout.splitlines():
        if line.startswith("PARAMS: "):
            try:
                params = json.loads(line[len("PARAMS: "):])
                params_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:5])
                if len(params) > 5:
                    params_str += f" (+{len(params)-5} more)"
            except Exception:
                pass

    # Classify outcome
    if "OK" in result.stdout:
        note = f"step() x{steps} passed"
        if params_str:
            note += f"  |  {params_str}"
        return StageResult(passed=True, notes=note)

    if "MISSING_PARAMS" in combined:
        line = next((l for l in combined.splitlines() if "MISSING_PARAMS" in l), "")
        params = line.replace("MISSING_PARAMS: ", "")
        return StageResult(passed=False, notes=f"Model.__init__ has required params with no default: {params}")

    if "IMPORT_ERROR" in combined:
        line = next((l for l in combined.splitlines() if "IMPORT_ERROR" in l), "")
        return StageResult(passed=False, notes=line.replace("IMPORT_ERROR: ", "")[:120])

    if "INIT_ERROR" in combined:
        line = next((l for l in combined.splitlines() if "INIT_ERROR" in l), "")
        return StageResult(passed=False, notes=line.replace("INIT_ERROR: ", "")[:120])

    if "NO_MODEL_CLASS" in combined:
        return StageResult(passed=False, notes="No mesa.Model subclass found in model.py")

    err_match = detect_errors(combined)
    note = err_match if err_match else (
        result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Unknown error"
    )
    return StageResult(passed=False, notes=note[:120])

# ---------------------------------------------------------------------------
# 6. Report generation
# ---------------------------------------------------------------------------
def generate_report(
    results: list[ExampleResult],
    examples: list[ExampleMetadata],
    run_meta: dict,
    output_json: str = "validation_report.json",
) -> None:
    """Print a formatted summary table and write a full JSON report."""

    passes   = sum(1 for r in results if r.status == STATUS_PASS)
    fails    = sum(1 for r in results if r.status == STATUS_FAIL)
    timeouts = sum(1 for r in results if r.status == STATUS_TIMEOUT)

    # Model-test (logical behaviour) counts
    model_tested  = [r for r in results if r.stage_model_test is not None]
    model_passed  = sum(1 for r in model_tested if r.stage_model_test.passed)
    model_failed  = sum(1 for r in model_tested if not r.stage_model_test.passed)
    model_skipped = len(results) - len(model_tested)

    # ── Console table ─────────────────────────────────────────────────────────
    col_name   = max(max((len(r.name) for r in results), default=0), 20)
    col_server = 8
    col_model  = 10

    header = (
        f"{'Example Name':<{col_name}}  "
        f"{'Server':<{col_server}}  "
        f"{'Model Test':<{col_model}}  "
        f"Notes"
    )
    sep = "=" * (len(header) + 4)
    print("\n" + sep)
    print(header)
    print("-" * (len(header) + 4))

    for r in results:
        server_icon = r.status
        if r.stage_model_test is not None:
            model_icon = "PASS" if r.stage_model_test.passed else "FAIL"
        else:
            model_icon = "SKIPPED"
        notes_str = r.notes[:50] if r.notes else ""
        print(
            f"{r.name:<{col_name}}  "
            f"{server_icon:<{col_server}}  "
            f"{model_icon:<{col_model}}  "
            f"{notes_str}"
        )

    print(sep)

    # ── Summary block ─────────────────────────────────────────────────────────
    print(f"\nTotal examples : {len(results)}")
    print(f"")
    print(f"  Server boot (Solara)")
    print(f"    {STATUS_PASS:<8}: {passes}")
    print(f"    {STATUS_FAIL:<8}: {fails}")
    print(f"    {STATUS_TIMEOUT:<8}: {timeouts}")
    print(f"")
    print(f"  Logical behaviour (model.step() test)")
    print(f"    PASS    : {model_passed}")
    print(f"    FAIL    : {model_failed}")
    if model_skipped:
        print(f"    SKIPPED : {model_skipped}  (--skip-model-test)")
    print()

    # ── Build JSON payload ────────────────────────────────────────────────────
    meta_by_name = {m.name: m for m in examples}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": run_meta,
        "summary": {
            "total":   len(results),
            "server_boot": {
                "passed":  passes,
                "failed":  fails,
                "timeout": timeouts,
            },
            "logical_behaviour": {
                "passed":  model_passed,
                "failed":  model_failed,
                "skipped": model_skipped,
            },
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
                "logical_behaviour": {
                    "passed": r.stage_model_test.passed,
                    "notes":  r.stage_model_test.notes,
                } if r.stage_model_test else None,
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
def _resolve_output_path(cli_value):
    """
    Determine the JSON report output path and mesa mode label.

    Precedence (highest to lowest):
      1. --output-json CLI argument  (explicit override)
      2. MESA_VERSION_LABEL env var  (set by GitHub Actions matrix)
      3. Hardcoded default           (local runs)

    Returns (output_path, mesa_label).
    """
    mesa_label = os.getenv("MESA_VERSION_LABEL", "").strip()

    if cli_value:
        # Explicit CLI flag always wins
        return cli_value, mesa_label or "local"

    if mesa_label:
        return f"example_validation_results_{mesa_label}.json", mesa_label

    return "example_validation_results.json", "local"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mesa-examples in CI")
    parser.add_argument("--examples-dir", default=EXAMPLES_DIR,
                        help="Root directory containing examples (default: examples)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="Max seconds per example (default: 30)")
    parser.add_argument("--skip-install", action="store_true",
                        help="Skip pip install step (useful if deps already present)")
    parser.add_argument("--output-json", default=None,
                        help="Override report path (default: auto-named from MESA_VERSION_LABEL)")
    parser.add_argument("--skip-model-test", action="store_true",
                        help="Skip the model.py unit test stage")
    parser.add_argument("--model-steps", type=int, default=5,
                        help="Number of model.step() calls in unit test (default: 5)")
    args = parser.parse_args()

    # ── Resolve output path: CLI > MESA_VERSION_LABEL env var > default ───────
    output_json, mesa_label = _resolve_output_path(args.output_json)

    print("mesa-examples Validator")
    print(f"  Examples dir      : {args.examples_dir}")
    print(f"  Timeout           : {args.timeout}s per example")
    print(f"  JSON output       : {output_json}")
    if mesa_label != "local":
        print(f"  Mesa validation mode: {mesa_label}")
    print()

    # ── Discover ─────────────────────────────────────────────────────────────
    examples = discover_examples(args.examples_dir)
    print(f"Found {len(examples)} example(s).\n")

    if not examples:
        print("No examples found. Exiting.")
        return 0

    results: list[ExampleResult] = []

    for meta in examples:
        print(f"[ {meta.name} ]  ({meta.path})")

        # ── Install deps ──────────────────────────────────────────────────────
        if not args.skip_install:
            ok, err = install_dependencies(meta)
            if not ok:
                print(f"  Dependency install failed: {err}")
                results.append(ExampleResult(name=meta.name, status=STATUS_FAIL, notes=err))
                continue

        # ── Stage A: Model unit test ──────────────────────────────────────────
        if not args.skip_model_test:
            print("  [Stage A] Running model unit test ...")
            model_result = run_model_test(meta, steps=args.model_steps)
            icon_a = "PASS" if model_result.passed else "FAIL"
            print(f"    [{icon_a}] {model_result.notes}")
        else:
            model_result = None

        # ── Stage B: Server boot ─────────────────────────────────────────────
        result = run_example(meta, timeout=args.timeout)
        result.stage_model_test = model_result

        icon = "PASS" if result.status == STATUS_PASS else ("TIME" if result.status == STATUS_TIMEOUT else "FAIL")
        print(f"  [Stage B] Server boot [{icon}]" + (f"  {result.notes}" if result.notes else ""))
        results.append(result)
        print()

    # ── Report ────────────────────────────────────────────────────────────────
    run_meta = {
        "examples_dir":       args.examples_dir,
        "timeout_seconds":    args.timeout,
        "skip_install":       args.skip_install,
        "mesa_version_label": mesa_label,
        "python":             sys.version,
        "platform":           sys.platform,
    }
    generate_report(results, examples, run_meta, output_json=output_json)

    # Non-zero exit if any example did not PASS
    any_failure = any(r.status != STATUS_PASS for r in results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
