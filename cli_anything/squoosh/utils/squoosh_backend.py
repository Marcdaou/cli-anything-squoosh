"""Backend: runs Squoosh's real WASM codecs through Node (squoosh_bridge.mjs).

Squoosh is a web app with no CLI of its own. Its codecs ship Node builds
(codecs/*/enc/*_node_enc.js, wasm-bindgen pkgs), so the bridge loads those
exact modules - the same code the GUI runs in its workers.
"""

import json
import os
import shutil
import subprocess
import tempfile

BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "squoosh_bridge.mjs")
INSTALL_NODE = "Node.js 18+ is required: https://nodejs.org (macOS: brew install node)"
INSTALL_SQUOOSH = ("Squoosh codec tree not found. Clone https://github.com/GoogleChromeLabs/squoosh "
                   "and set SQUOOSH_ROOT=/path/to/squoosh (the folder that contains codecs/).")
_REQUIRED = ["codecs/mozjpeg/enc/mozjpeg_node_enc.js", "codecs/png/pkg/squoosh_png_bg.wasm",
             "codecs/resize/pkg/squoosh_resize_bg.wasm", "codecs/rotate/rotate.wasm"]


class BackendError(RuntimeError):
    pass


def find_node():
    node = os.environ.get("SQUOOSH_NODE") or shutil.which("node")
    if not node:
        raise BackendError(f"node not found in PATH. {INSTALL_NODE}")
    return node


def _is_root(path):
    return path and all(os.path.isfile(os.path.join(path, r)) for r in _REQUIRED)


def find_squoosh_root():
    env = os.environ.get("SQUOOSH_ROOT")
    if env:
        if not _is_root(env):
            raise BackendError(f"SQUOOSH_ROOT={env} does not contain built codecs. {INSTALL_SQUOOSH}")
        return os.path.abspath(env)
    d = os.path.dirname(BRIDGE)
    while True:
        if _is_root(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise BackendError(INSTALL_SQUOOSH)
        d = parent


def node_version():
    out = subprocess.run([find_node(), "--version"], capture_output=True, text=True)
    return out.stdout.strip()


def run(op, timeout=600, **params):
    """Run one bridge op and return its result dict; raise BackendError on failure."""
    job = {"op": op, "squoosh_root": find_squoosh_root(), **params}
    fd, job_path = tempfile.mkstemp(suffix=".json", prefix="squoosh_job_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(job, f)
        proc = subprocess.run([find_node(), "--no-warnings", BRIDGE, job_path],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackendError(f"Squoosh bridge timed out after {timeout}s ({op})")
    finally:
        os.unlink(job_path)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise BackendError(f"Squoosh bridge crashed ({op}): {(proc.stderr or proc.stdout).strip()[-800:]}")
    if not payload.get("ok"):
        raise BackendError(payload.get("error", "unknown bridge error"))
    return payload["result"]


def probe(path, stats=False):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image not found: {path}")
    return run("probe", input=os.path.abspath(path), stats=stats)


def process(input_path, output_path, steps, encoder, options, preview_png=None):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Image not found: {input_path}")
    params = dict(input=os.path.abspath(input_path), output=os.path.abspath(output_path),
                  steps=steps, encoder={"name": encoder, "options": options})
    if preview_png:
        params["preview_png"] = os.path.abspath(preview_png)
    return run("process", **params)


def decode_to_png(input_path, output_path):
    return run("decode", input=os.path.abspath(input_path), output=os.path.abspath(output_path))


def doctor():
    report = {"bridge": BRIDGE, "ok": True}
    try:
        report["node"] = find_node()
        report["node_version"] = node_version()
    except BackendError as e:
        report.update(ok=False, node_error=str(e))
    try:
        root = find_squoosh_root()
        report["squoosh_root"] = root
        from cli_anything.squoosh.core.codecs import ENCODERS
        report["codecs_present"] = sorted(ENCODERS)
    except BackendError as e:
        report.update(ok=False, squoosh_error=str(e))
    return report
