"""Render pipeline: project -> Squoosh WASM codecs -> verified output file."""

import glob
import os
from datetime import datetime, timezone

from cli_anything.squoosh.core import codecs
from cli_anything.squoosh.core import project as proj
from cli_anything.squoosh.utils import squoosh_backend as backend

MAGIC = {
    "jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "avif": lambda b: b[4:8] == b"ftyp" and b[8:12] in (b"avif", b"avis"),
    "jxl": lambda b: b[:2] == b"\xff\x0a" or b[4:8] == b"JXL ",
    "qoi": lambda b: b[:4] == b"qoif",
    "wp2": lambda b: b[:3] == b"\xf4\xff\x6f",
}


def verify_output(path, encoder):
    """Check the file exists, is non-empty and carries the encoder's magic bytes."""
    if not os.path.isfile(path):
        raise RuntimeError(f"Export produced no file: {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise RuntimeError(f"Export produced an empty file: {path}")
    fmt = codecs.get_encoder(encoder)["format"]
    with open(path, "rb") as f:
        head = f.read(16)
    if not MAGIC[fmt](head):
        raise RuntimeError(f"Output {path} is not a valid {fmt} file (bad magic bytes)")
    return {"format": fmt, "file_size": size}


def default_output(project, directory=None):
    src = (project.get("source") or {}).get("path")
    if not src:
        raise ValueError("No source image set. Use 'source set <image>' first.")
    ext = codecs.get_encoder(project["encoder"]["name"])["extension"]
    base = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(directory or os.path.dirname(src), f"{base}.squoosh.{ext}")


def render(project, output=None, overwrite=False, preview_png=None):
    src = (project.get("source") or {}).get("path")
    if not src:
        raise ValueError("No source image set. Use 'source set <image>' first.")
    output = os.path.abspath(output or default_output(project))
    if os.path.exists(output) and not overwrite:
        raise FileExistsError(f"Output exists: {output} (use --overwrite)")
    enc = project["encoder"]
    options = codecs.merge_options(enc["name"], enc["options"])
    result = backend.process(src, output, proj.pipeline_steps(project), enc["name"], options,
                             preview_png=preview_png)
    result.update(verify_output(output, enc["name"]))
    result.update({"encoder": enc["name"], "options": options,
                   "saved_percent": round((1 - result["out_bytes"] / result["in_bytes"]) * 100, 2)})
    return result


def record_export(project, result):
    project.setdefault("exports", []).append({
        "output": result["output"], "encoder": result["encoder"],
        "bytes": result["out_bytes"], "width": result["width"], "height": result["height"],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    del project["exports"][:-50]
    return project


def compress(input_path, output=None, encoder="mozjpeg", options=None, rotate=0,
             width=None, height=None, method="lanczos3", fit="stretch", colors=None,
             dither=1.0, overwrite=False):
    """One-shot: build a throwaway project and render it."""
    p = proj.new_project("oneshot", encoder)
    proj.set_source(p, input_path, backend.probe(input_path))
    if rotate:
        proj.set_rotate(p, rotate)
    if width or height:
        proj.set_resize(p, width, height, method, fit)
    if colors:
        proj.set_quantize(p, colors, dither)
    if options:
        proj.set_encoder(p, encoder, options)
    return render(p, output, overwrite)


def compare(project, encoders, out_dir, options_by_encoder=None):
    """Render the same pipeline with several encoders; rank by size."""
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    base = os.path.splitext(os.path.basename(project["source"]["path"]))[0]
    for name in encoders:
        codecs.get_encoder(name)
        trial = dict(project, encoder={"name": name,
                                       "options": (options_by_encoder or {}).get(name, {})})
        out = os.path.join(out_dir, f"{base}-{name}.{codecs.ENCODERS[name]['extension']}")
        r = render(trial, out, overwrite=True)
        rows.append({k: r[k] for k in ("encoder", "output", "out_bytes", "saved_percent",
                                       "width", "height", "format")}
                    | {"encode_ms": r["timings"].get("encode_ms")})
    rows.sort(key=lambda r: r["out_bytes"])
    return {"source": project["source"]["path"], "results": rows,
            "smallest": rows[0]["encoder"] if rows else None}


def batch(project, inputs, out_dir, overwrite=False):
    """Apply one project's settings to many images."""
    files = []
    for pattern in inputs:
        hits = sorted(glob.glob(pattern)) if any(c in pattern for c in "*?[") else [pattern]
        files.extend(hits)
    if not files:
        raise ValueError("No input files matched")
    os.makedirs(out_dir, exist_ok=True)
    ext = codecs.get_encoder(project["encoder"]["name"])["extension"]
    done, failed = [], []
    for f in files:
        try:
            trial = dict(project)
            proj.set_source(trial, f, backend.probe(f))
            out = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(f))[0]}.{ext}")
            r = render(trial, out, overwrite)
            done.append({"input": os.path.abspath(f), "output": r["output"],
                         "in_bytes": r["in_bytes"], "out_bytes": r["out_bytes"]})
        except Exception as e:  # keep going, report per file
            failed.append({"input": os.path.abspath(f), "error": str(e)})
    total_in = sum(d["in_bytes"] for d in done)
    total_out = sum(d["out_bytes"] for d in done)
    return {"processed": done, "failed": failed, "total_in": total_in, "total_out": total_out,
            "saved_percent": round((1 - total_out / total_in) * 100, 2) if total_in else 0}


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".jxl", ".qoi", ".wp2"}


def default_folder_output(input_dir, quality):
    input_dir = os.path.abspath(input_dir).rstrip(os.sep)
    return f"{input_dir}-squoosh-q{quality:g}"


def compress_folder(input_dir, output_dir=None, quality=70, encoder="mozjpeg", recursive=False,
                    width=None, overwrite=False, options=None):
    """Compress every image in INPUT_DIR into OUTPUT_DIR, mirroring subfolders.

    `quality` is applied to encoders that have a quality option; it is ignored for
    lossless ones (oxipng, qoi, png).
    """
    input_dir = os.path.abspath(input_dir)
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Not a folder: {input_dir}")
    enc = codecs.get_encoder(encoder)
    opts = dict(options or {})
    if "quality" in enc["defaults"]:
        opts.setdefault("quality", quality)
    output_dir = os.path.abspath(output_dir or default_folder_output(input_dir, quality))
    if output_dir == input_dir or output_dir.startswith(input_dir + os.sep) and recursive:
        raise ValueError("Output folder must not be the input folder or inside it when recursive")

    files = []
    for root, dirs, names in os.walk(input_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and os.path.join(root, d) != output_dir)
        files += [os.path.join(root, n) for n in sorted(names)
                  if os.path.splitext(n)[1].lower() in IMAGE_EXTENSIONS and not n.startswith(".")]
        if not recursive:
            break
    if not files:
        raise ValueError(f"No images found in {input_dir} (looked for {', '.join(sorted(IMAGE_EXTENSIONS))})")

    done, skipped, failed = [], [], []
    for f in files:
        rel = os.path.relpath(f, input_dir)
        out = os.path.join(output_dir, os.path.splitext(rel)[0] + "." + enc["extension"])
        if os.path.exists(out) and not overwrite:
            skipped.append({"input": f, "output": out, "reason": "exists (use --overwrite)"})
            continue
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            p = proj.new_project("folder", encoder)
            proj.set_source(p, f, backend.probe(f))
            if width:
                proj.set_resize(p, width=width)
            proj.set_encoder(p, encoder, opts)
            r = render(p, out, overwrite=True)
            done.append({"input": f, "output": r["output"], "in_bytes": r["in_bytes"],
                         "out_bytes": r["out_bytes"], "saved_percent": r["saved_percent"]})
        except Exception as e:  # report per file, keep going
            failed.append({"input": f, "error": str(e)})
    total_in = sum(d["in_bytes"] for d in done)
    total_out = sum(d["out_bytes"] for d in done)
    return {"input_dir": input_dir, "output_dir": output_dir, "encoder": encoder,
            "options": codecs.merge_options(encoder, opts), "processed": done,
            "skipped": skipped, "failed": failed, "total_in": total_in, "total_out": total_out,
            "saved_percent": round((1 - total_out / total_in) * 100, 2) if total_in else 0}
