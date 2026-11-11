"""Preview bundles (preview-bundle/v1): truthful snapshots of what the project renders to.

A capture runs the real Squoosh pipeline, then decodes the encoded output back
with Squoosh's own decoder and saves it as PNG - the same "after" image the
GUI's comparison slider shows. Bundles are immutable and keyed by a fingerprint
of the source file and the render settings, so an unchanged project reuses
its last bundle.
"""

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone

from cli_anything.squoosh.core import codecs
from cli_anything.squoosh.core import export as exp
from cli_anything.squoosh.core import project as proj
from cli_anything.squoosh.utils import squoosh_backend as backend

PROTOCOL = "preview-bundle/v1"


@contextmanager
def _building(bundle_dir):
    """Bundles are all-or-nothing: a failed render leaves no partial directory."""
    os.makedirs(bundle_dir, exist_ok=True)
    try:
        yield
    except Exception:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        raise

RECIPES = {
    "result": "Encode with the project settings; save the encoded file, the decoded-back "
              "PNG and size/colour stats.",
    "diff": "Render the project with two encoders (or option sets) side by side and "
            "report the size and colour difference.",
}


def preview_root(project_path=None, root=None):
    if root:
        return os.path.abspath(root)
    base = os.path.dirname(os.path.abspath(project_path)) if project_path else os.getcwd()
    return os.path.join(base, ".squoosh-previews")


def fingerprint(project, extra=None):
    src = project.get("source") or {}
    path = src.get("path")
    st = os.stat(path) if path and os.path.exists(path) else None
    key = {"src": path, "size": st.st_size if st else None, "mtime": st.st_mtime if st else None,
           "steps": proj.pipeline_steps(project) if path else [],
           "encoder": project["encoder"]["name"],
           "options": codecs.merge_options(project["encoder"]["name"], project["encoder"]["options"]),
           "extra": extra}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def _write_manifest(bundle_dir, manifest):
    path = os.path.join(bundle_dir, "manifest.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    summary = os.path.join(bundle_dir, "summary.json")
    with open(summary, "w") as f:
        json.dump(manifest["summary"], f, indent=2)
    manifest["_bundle_dir"] = bundle_dir
    manifest["_manifest_path"] = path
    manifest["summary_path"] = summary
    return manifest


def _load(bundle_dir):
    path = os.path.join(bundle_dir, "manifest.json")
    with open(path) as f:
        m = json.load(f)
    m.update(_bundle_dir=bundle_dir, _manifest_path=path,
             summary_path=os.path.join(bundle_dir, "summary.json"), cached=True)
    return m


def capture(project, project_path=None, root=None, force=False):
    if not (project.get("source") or {}).get("path"):
        raise ValueError("No source image set. Use 'source set <image>' first.")
    fp = fingerprint(project)
    bundle_dir = os.path.join(preview_root(project_path, root), f"result-{fp}")
    if os.path.isfile(os.path.join(bundle_dir, "manifest.json")) and not force:
        return _load(bundle_dir)
    ext = codecs.get_encoder(project["encoder"]["name"])["extension"]
    encoded = os.path.join(bundle_dir, f"output.{ext}")
    decoded = os.path.join(bundle_dir, "decoded.png")
    with _building(bundle_dir):
        r = exp.render(project, encoded, overwrite=True, preview_png=decoded)
        backend.decode_to_png(project["source"]["path"], os.path.join(bundle_dir, "source.png"))
    summary = {"encoder": r["encoder"], "in_bytes": r["in_bytes"], "out_bytes": r["out_bytes"],
               "saved_percent": r["saved_percent"], "size": [r["width"], r["height"]],
               "mean_rgba_after": r.get("stats", {}).get("mean"),
               "steps": [s["type"] for s in proj.pipeline_steps(project)]}
    manifest = {
        "protocol": PROTOCOL, "recipe": "result", "fingerprint": fp,
        "software": "squoosh", "status": "ok",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifacts": [
            {"role": "encoded", "path": os.path.basename(encoded), "mime": codecs.ENCODERS[r["encoder"]]["mime"]},
            {"role": "after", "path": "decoded.png", "mime": "image/png"},
            {"role": "before", "path": "source.png", "mime": "image/png"},
        ],
        "summary": summary,
        "cached": False,
    }
    return _write_manifest(bundle_dir, manifest)


def latest(project_path=None, root=None):
    base = preview_root(project_path, root)
    if not os.path.isdir(base):
        raise FileNotFoundError(f"No previews yet under {base}. Run 'preview capture' first.")
    bundles = [os.path.join(base, d) for d in os.listdir(base)
               if os.path.isfile(os.path.join(base, d, "manifest.json"))]
    if not bundles:
        raise FileNotFoundError(f"No previews yet under {base}. Run 'preview capture' first.")
    return _load(max(bundles, key=lambda d: os.path.getmtime(os.path.join(d, "manifest.json"))))


def diff(project, other_encoder, other_options=None, project_path=None, root=None):
    other = dict(project, encoder={"name": other_encoder,
                                   "options": codecs.parse_option_pairs(other_encoder, other_options)})
    fp = fingerprint(project, extra=fingerprint(other))
    bundle_dir = os.path.join(preview_root(project_path, root), f"diff-{fp}")
    sides = {}
    with _building(bundle_dir):
        _render_sides(project, other, bundle_dir, sides)
    a, b = sides["a"], sides["b"]
    summary = {"a": a, "b": b, "bytes_delta": b["out_bytes"] - a["out_bytes"],
               "smaller": "a" if a["out_bytes"] <= b["out_bytes"] else "b",
               "mean_rgba_delta": [round(y - x, 2) for x, y in zip(a["mean_rgba"], b["mean_rgba"])]}
    manifest = {"protocol": PROTOCOL, "recipe": "diff", "fingerprint": fp, "software": "squoosh",
                "status": "ok", "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "artifacts": [{"role": f"{k}-{t}", "path": p} for k, s in sides.items()
                              for t, p in (("encoded", s["file"]), ("after", f"{k}_decoded.png"))],
                "summary": summary, "cached": False}
    return _write_manifest(bundle_dir, manifest)


def _render_sides(project, other, bundle_dir, sides):
    for label, p in (("a", project), ("b", other)):
        ext = codecs.ENCODERS[p["encoder"]["name"]]["extension"]
        r = exp.render(p, os.path.join(bundle_dir, f"{label}.{ext}"), overwrite=True,
                       preview_png=os.path.join(bundle_dir, f"{label}_decoded.png"))
        sides[label] = {"encoder": r["encoder"], "out_bytes": r["out_bytes"],
                        "file": os.path.basename(r["output"]),
                        "mean_rgba": r.get("stats", {}).get("mean")}
