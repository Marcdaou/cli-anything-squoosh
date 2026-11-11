"""cli-anything-squoosh: a stateful CLI for Squoosh, rendered by its real WASM codecs."""

import json
import os
import shlex
import sys

import click

from cli_anything.squoosh import __version__
from cli_anything.squoosh.core import codecs
from cli_anything.squoosh.core import export as exp
from cli_anything.squoosh.core import preview as prev
from cli_anything.squoosh.core import project as proj
from cli_anything.squoosh.core.session import Session
from cli_anything.squoosh.utils import squoosh_backend as backend

_session = Session()
_repl_mode = False


def get_session():
    return _session


# ---------------------------------------------------------------- output helpers
def _json_mode():
    ctx = click.get_current_context(silent=True)
    while ctx is not None:
        if ctx.obj and "json" in ctx.obj:
            return ctx.obj["json"]
        ctx = ctx.parent
    return False


def emit(data, human=None):
    if _json_mode():
        click.echo(json.dumps(data, indent=2, default=str))
    elif human is not None:
        click.echo(human)
    else:
        _print_human(data)


def _print_human(data, indent=0):
    pad = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                click.echo(f"{pad}{k}:")
                _print_human(v, indent + 1)
            else:
                click.echo(f"{pad}{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                click.echo(f"{pad}-")
                _print_human(item, indent + 1)
            else:
                click.echo(f"{pad}- {item}")
    else:
        click.echo(f"{pad}{data}")


def fail(err):
    """Report an error; in one-shot mode exit non-zero (skips auto-save)."""
    msg = str(err)
    if _json_mode():
        click.echo(json.dumps({"error": msg, "type": type(err).__name__}))
    else:
        click.echo(f"Error: {msg}", err=True)
    if not _repl_mode:
        sys.exit(1)


def handled(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except (ValueError, RuntimeError, FileNotFoundError, FileExistsError, KeyError) as e:
            fail(e)
    return wrapper


def _mutate(fn, *args, **kwargs):
    sess = get_session()
    sess.mutate(fn, *args, **kwargs)
    return sess.project


# ---------------------------------------------------------------- root group
@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.option("--project", "project_path", type=str, default=None,
              help="Path to a .squoosh.json project file")
@click.option("--dry-run", "dry_run", is_flag=True, default=False,
              help="Run the command without saving project changes to disk")
@click.version_option(__version__)
@click.pass_context
def cli(ctx, use_json, project_path, dry_run):
    """Squoosh image compression CLI, rendered by Squoosh's own WASM codecs.

    Run with no command to start the interactive REPL.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json
    ctx.obj["dry_run"] = dry_run
    sess = get_session()
    if project_path and not _repl_mode:
        try:
            if os.path.exists(project_path):
                sess.open(project_path)
            else:
                sess.path = os.path.abspath(project_path)
        except (ValueError, FileNotFoundError) as e:
            fail(e)
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl, project_path=project_path)


@cli.result_callback()
def auto_save_on_exit(result, use_json, project_path, dry_run, **kwargs):
    if _repl_mode or dry_run:
        return
    sess = get_session()
    if sess.project is not None and sess.modified and sess.path:
        try:
            sess.save()
        except Exception as e:
            click.echo(f"Warning: auto-save failed: {e}", err=True)


# ---------------------------------------------------------------- project
@cli.group()
def project():
    """Create, open, save and inspect compression projects."""


@project.command("new")
@click.option("-n", "--name", default="untitled", help="Project name")
@click.option("-e", "--encoder", default="mozjpeg", type=click.Choice(list(codecs.ENCODERS)))
@click.option("-o", "--output", "output", default=None, help="Project file path to save")
@click.option("-s", "--source", default=None, help="Source image to load")
@handled
def project_new(name, encoder, output, source):
    """Create a new project (and save it if -o is given)."""
    sess = get_session()
    path = output or sess.path
    sess.new(name, encoder, path)
    if source:
        proj.set_source(sess.project, source, backend.probe(source))
    if sess.path and not click.get_current_context().find_root().obj.get("dry_run"):
        sess.save()
    emit(proj.info(sess.project, sess.path), f"Created project '{name}'"
         + (f" -> {sess.path}" if sess.path else ""))


@project.command("open")
@click.argument("path")
@handled
def project_open(path):
    """Open a project file."""
    sess = get_session()
    sess.open(path)
    emit(proj.info(sess.project, sess.path), f"Opened {sess.path}")


@project.command("save")
@click.argument("path", required=False)
@handled
def project_save(path):
    """Save the project (optionally to a new path)."""
    saved = get_session().save(path)
    emit({"saved": saved}, f"Saved {saved}")


@project.command("info")
@handled
def project_info():
    """Show the full project state."""
    sess = get_session()
    emit(proj.info(sess.require(), sess.path))


@project.command("json")
@handled
def project_json():
    """Print the raw project JSON."""
    click.echo(json.dumps(get_session().require(), indent=2))


# ---------------------------------------------------------------- source
@cli.group()
def source():
    """The source image (what you drop onto Squoosh)."""


@source.command("set")
@click.argument("path")
@handled
def source_set(path):
    """Set the source image (decoded by Squoosh to read its size)."""
    info = backend.probe(path)
    _mutate(proj.set_source, path, info)
    emit(get_session().project["source"],
         f"Source: {os.path.abspath(path)} ({info['format']}, {info['width']}x{info['height']})")


@source.command("info")
@handled
def source_info():
    """Show the source image details."""
    src = get_session().require().get("source")
    if not src:
        raise ValueError("No source image set")
    emit(src)


# ---------------------------------------------------------------- edit
@cli.group()
def edit():
    """Preprocessing and processing steps: rotate, resize, quantize."""


@edit.command("rotate")
@click.argument("degrees", type=int)
@handled
def edit_rotate(degrees):
    """Rotate by 0, 90, 180 or 270 degrees (Squoosh's rotate preprocessor)."""
    p = _mutate(proj.set_rotate, degrees)
    emit(p["preprocess"], f"Rotate: {p['preprocess']['rotate']}°")


@edit.command("resize")
@click.option("-w", "--width", type=int, default=None)
@click.option("-h", "--height", type=int, default=None)
@click.option("-m", "--method", type=click.Choice(codecs.RESIZE_METHODS), default=None)
@click.option("--fit", type=click.Choice(codecs.FIT_METHODS), default=None)
@click.option("--premultiply/--no-premultiply", default=None)
@click.option("--linear-rgb/--no-linear-rgb", default=None)
@handled
def edit_resize(width, height, method, fit, premultiply, linear_rgb):
    """Enable resize. Give one side to keep the aspect ratio."""
    p = _mutate(proj.set_resize, width, height, method, fit, premultiply, linear_rgb)
    size = proj.target_size(p)
    emit(dict(p["resize"], output_size=size),
         f"Resize: {p['resize']['method']} -> {size[0]}x{size[1]}" if size else "Resize enabled")


@edit.command("quantize")
@click.option("-c", "--colors", type=int, default=None, help="Max colours (2-256)")
@click.option("-d", "--dither", type=float, default=None, help="Dithering 0-1")
@click.option("--zx/--no-zx", default=None, help="ZX Spectrum palette mode")
@handled
def edit_quantize(colors, dither, zx):
    """Enable colour reduction (libimagequant)."""
    p = _mutate(proj.set_quantize, colors, dither, zx)
    emit(p["quantize"], f"Quantize: {p['quantize']['maxNumColors']} colours, "
                        f"dither {p['quantize']['dither']}")


@edit.command("disable")
@click.argument("step", type=click.Choice(["resize", "quantize", "rotate"]))
@handled
def edit_disable(step):
    """Turn a step off."""
    if step == "rotate":
        _mutate(proj.set_rotate, 0)
    else:
        _mutate(proj.disable, step)
    emit({"disabled": step}, f"Disabled {step}")


@edit.command("list")
@handled
def edit_list():
    """List the active pipeline steps in render order."""
    steps = proj.pipeline_steps(get_session().require())
    emit({"steps": steps}, "\n".join(f"{i + 1}. {s['type']} {s['options']}"
                                     for i, s in enumerate(steps)) or "(no steps)")


# ---------------------------------------------------------------- encoder
@cli.group()
def encoder():
    """Choose the output codec and tune its options."""


@encoder.command("list")
@handled
def encoder_list():
    """List encoders available through Squoosh's Node codecs."""
    rows = codecs.list_encoders()
    emit({"encoders": rows, "browser_only_not_available": codecs.BROWSER_ONLY},
         "\n".join(f"{r['name']:<8} .{r['extension']:<5} {r['label']}" for r in rows))


@encoder.command("options")
@click.argument("name", required=False)
@handled
def encoder_options(name):
    """Show an encoder's options, defaults and ranges (default: the project's encoder)."""
    if name is None:
        name = get_session().require()["encoder"]["name"]
    enc = codecs.get_encoder(name)
    data = {"encoder": name, "defaults": enc["defaults"],
            "ranges": {k: list(v) for k, v in enc["ranges"].items()}}
    emit(data)


@encoder.command("set")
@click.argument("name", type=click.Choice(list(codecs.ENCODERS)))
@click.argument("options", nargs=-1)
@click.option("--reset", is_flag=True, help="Drop previously set options")
@handled
def encoder_set(name, options, reset):
    """Select an encoder, optionally with key=value options, e.g. `encoder set webp quality=80`."""
    p = _mutate(proj.set_encoder, name, list(options), reset)
    emit(p["encoder"], f"Encoder: {name} {p['encoder']['options'] or ''}".rstrip())


@encoder.command("option")
@click.argument("pairs", nargs=-1, required=True)
@handled
def encoder_option(pairs):
    """Set options on the current encoder: `encoder option quality=60 progressive=false`."""
    name = get_session().require()["encoder"]["name"]
    p = _mutate(proj.set_encoder, name, list(pairs))
    emit(p["encoder"], f"{name}: {p['encoder']['options']}")


@encoder.command("show")
@handled
def encoder_show():
    """Show the current encoder with the full effective option set."""
    enc = get_session().require()["encoder"]
    emit({"encoder": enc["name"], "overrides": enc["options"],
          "effective": codecs.merge_options(enc["name"], enc["options"])})


# ---------------------------------------------------------------- export / one-shot
@cli.command("export")
@click.argument("output", required=False)
@click.option("--overwrite", is_flag=True)
@handled
def export_cmd(output, overwrite):
    """Render the project through the real Squoosh codecs."""
    sess = get_session()
    r = exp.render(sess.require(), output, overwrite)
    sess.mutate(exp.record_export, r)
    emit(r, f"{r['output']}\n  {r['in_bytes']:,} -> {r['out_bytes']:,} bytes "
            f"({r['saved_percent']}% smaller), {r['width']}x{r['height']} {r['format']}")


@cli.command("compress")
@click.argument("input_path")
@click.option("-o", "--output", default=None)
@click.option("-e", "--encoder", default="mozjpeg", type=click.Choice(list(codecs.ENCODERS)))
@click.option("-O", "--option", "options", multiple=True, help="Encoder option key=value")
@click.option("-q", "--quality", type=float, default=None, help="Shortcut for quality=")
@click.option("--rotate", type=int, default=0)
@click.option("-w", "--width", type=int, default=None)
@click.option("-h", "--height", type=int, default=None)
@click.option("-m", "--method", type=click.Choice(codecs.RESIZE_METHODS), default="lanczos3")
@click.option("--fit", type=click.Choice(codecs.FIT_METHODS), default="stretch")
@click.option("-c", "--colors", type=int, default=None, help="Quantize to N colours")
@click.option("--dither", type=float, default=1.0)
@click.option("--overwrite", is_flag=True)
@handled
def compress_cmd(input_path, output, encoder, options, quality, rotate, width, height,
                 method, fit, colors, dither, overwrite):
    """One-shot: compress INPUT_PATH without a project file."""
    opts = list(options) + ([f"quality={quality:g}"] if quality is not None else [])
    r = exp.compress(input_path, output, encoder, opts, rotate, width, height, method, fit,
                     colors, dither, overwrite)
    emit(r, f"{r['output']}\n  {r['in_bytes']:,} -> {r['out_bytes']:,} bytes "
            f"({r['saved_percent']}% smaller)")


@cli.command("compare")
@click.option("-e", "--encoders", default="mozjpeg,webp,avif,jxl,oxipng",
              help="Comma-separated encoders")
@click.option("-d", "--out-dir", required=True)
@click.option("-i", "--input", "input_path", default=None,
              help="Image to test (default: the project's source)")
@handled
def compare_cmd(encoders, out_dir, input_path):
    """Encode one image with several codecs and rank by size."""
    sess = get_session()
    p = sess.project or proj.new_project("compare")
    if input_path:
        p = dict(p)
        proj.set_source(p, input_path, backend.probe(input_path))
    r = exp.compare(p, [e.strip() for e in encoders.split(",") if e.strip()], out_dir)
    lines = [f"{x['encoder']:<8} {x['out_bytes']:>10,} bytes  {x['saved_percent']:>6}%  {x['output']}"
             for x in r["results"]]
    emit(r, "\n".join(lines) + f"\nSmallest: {r['smallest']}")


@cli.command("batch")
@click.argument("inputs", nargs=-1, required=True)
@click.option("-d", "--out-dir", required=True)
@click.option("--overwrite", is_flag=True)
@handled
def batch_cmd(inputs, out_dir, overwrite):
    """Apply the project's settings to many images (globs allowed)."""
    r = exp.batch(get_session().require(), list(inputs), out_dir, overwrite)
    emit(r, f"{len(r['processed'])} done, {len(r['failed'])} failed, "
            f"{r['total_in']:,} -> {r['total_out']:,} bytes ({r['saved_percent']}% smaller)")
    if r["failed"] and not r["processed"]:
        sys.exit(1)


@cli.command("folder")
@click.argument("input_dir")
@click.option("-o", "--output", "output_dir", default=None,
              help="Output folder (default: <input>-squoosh-q<quality> next to the input)")
@click.option("-q", "--quality", type=float, default=70, show_default=True,
              help="Quality 0-100 (ignored by lossless encoders)")
@click.option("-e", "--encoder", default="mozjpeg", show_default=True,
              type=click.Choice(list(codecs.ENCODERS)))
@click.option("-r", "--recursive", is_flag=True, help="Include subfolders (structure is mirrored)")
@click.option("-w", "--width", type=int, default=None, help="Also resize to this width")
@click.option("-O", "--option", "options", multiple=True, help="Extra encoder option key=value")
@click.option("--overwrite", is_flag=True, help="Replace files already in the output folder")
@handled
def folder_cmd(input_dir, output_dir, quality, encoder, recursive, width, options, overwrite):
    """Compress every image in INPUT_DIR into a new folder (default quality 70)."""
    if not 0 <= quality <= 100:
        raise ValueError("quality must be between 0 and 100")
    opts = codecs.parse_option_pairs(encoder, list(options))
    r = exp.compress_folder(input_dir, output_dir, quality, encoder, recursive, width,
                            overwrite, opts)
    lines = [f"  {os.path.relpath(d['input'], r['input_dir'])}: {d['in_bytes']:,} -> "
             f"{d['out_bytes']:,} ({d['saved_percent']}% smaller)" for d in r["processed"]]
    lines += [f"  SKIPPED {os.path.relpath(d['input'], r['input_dir'])}: {d['reason']}" for d in r["skipped"]]
    lines += [f"  FAILED {os.path.relpath(d['input'], r['input_dir'])}: {d['error']}" for d in r["failed"]]
    emit(r, f"{r['output_dir']}\n" + "\n".join(lines) +
            f"\n{len(r['processed'])} compressed, {len(r['skipped'])} skipped, {len(r['failed'])} failed: "
            f"{r['total_in']:,} -> {r['total_out']:,} bytes ({r['saved_percent']}% smaller)")
    if r["failed"] and not r["processed"]:
        sys.exit(1)


@cli.command("probe")
@click.argument("path")
@click.option("--stats", is_flag=True, help="Also compute mean colour and colour count")
@handled
def probe_cmd(path, stats):
    """Detect format and dimensions with Squoosh's decoders."""
    r = backend.probe(path, stats)
    emit(r, f"{r['format']} {r['width']}x{r['height']} {r['bytes']:,} bytes"
            + (f" mean={r['stats']['mean']}" if stats else ""))


@cli.command("decode")
@click.argument("input_path")
@click.argument("output")
@handled
def decode_cmd(input_path, output):
    """Decode any supported image (AVIF, JXL, WebP, WP2, QOI...) to PNG."""
    emit(backend.decode_to_png(input_path, output))


@cli.command("doctor")
@handled
def doctor_cmd():
    """Check Node.js and the Squoosh codec tree."""
    r = backend.doctor()
    emit(r)
    if not r["ok"]:
        sys.exit(1)


# ---------------------------------------------------------------- preview
@cli.group()
def preview():
    """Publish preview bundles (preview-bundle/v1) rendered by the real codecs."""


@preview.command("recipes")
def preview_recipes():
    """List preview recipes."""
    emit({"recipes": prev.RECIPES}, "\n".join(f"{k}: {v}" for k, v in prev.RECIPES.items()))


@preview.command("capture")
@click.option("--root", default=None, help="Preview directory (default: .squoosh-previews next to the project)")
@click.option("--force", is_flag=True, help="Render even if an identical bundle exists")
@handled
def preview_capture(root, force):
    """Render the project and publish a bundle (encoded file, decoded-back PNG, source PNG)."""
    sess = get_session()
    m = prev.capture(sess.require(), sess.path, root, force)
    emit(m, f"Bundle: {m['_bundle_dir']}" + (" (cached)" if m.get("cached") else "")
            + f"\n  {m['summary']['out_bytes']:,} bytes, {m['summary']['saved_percent']}% smaller")


@preview.command("latest")
@click.option("--root", default=None)
@handled
def preview_latest(root):
    """Return the newest existing bundle without rendering."""
    m = prev.latest(get_session().path, root)
    emit(m, f"Bundle: {m['_bundle_dir']} ({m['recipe']})")


@preview.command("diff")
@click.argument("other_encoder", type=click.Choice(list(codecs.ENCODERS)))
@click.argument("options", nargs=-1)
@click.option("--root", default=None)
@handled
def preview_diff(other_encoder, options, root):
    """Compare the project's encoder against OTHER_ENCODER [key=value ...]."""
    sess = get_session()
    m = prev.diff(sess.require(), other_encoder, list(options), sess.path, root)
    s = m["summary"]
    emit(m, f"Bundle: {m['_bundle_dir']}\n  a={s['a']['encoder']} {s['a']['out_bytes']:,}  "
            f"b={s['b']['encoder']} {s['b']['out_bytes']:,}  smaller: {s['smaller']}")


# ---------------------------------------------------------------- session
@cli.group()
def session():
    """Undo/redo and session status."""


@session.command("status")
def session_status():
    """Show project path, modified flag and undo/redo depth."""
    emit(get_session().status())


@session.command("undo")
@handled
def session_undo():
    """Undo the last change."""
    get_session().undo()
    emit(get_session().status(), "Undone")


@session.command("redo")
@handled
def session_redo():
    """Redo the last undone change."""
    get_session().redo()
    emit(get_session().status(), "Redone")


# ---------------------------------------------------------------- REPL
REPL_HELP = {
    "project new|open|save|info|json": "Manage the project file",
    "source set <img> | info": "Set or inspect the source image",
    "edit rotate|resize|quantize|disable|list": "Pipeline steps",
    "encoder list|options|set|option|show": "Codec selection and tuning",
    "export [out] [--overwrite]": "Render via Squoosh codecs",
    "compress <img> [-e enc] [-q N]": "One-shot compression",
    "compare -d <dir> [-e a,b,c]": "Rank encoders by size",
    "batch <globs...> -d <dir>": "Apply project to many files",
    "folder <dir> [-q 70] [-o out]": "Compress a whole folder",
    "preview capture|latest|diff|recipes": "Preview bundles",
    "probe <img> | decode <img> <png>": "Inspect / decode images",
    "session undo|redo|status": "History",
    "doctor": "Check backend",
    "help | quit": "This help / exit",
}


@cli.command("repl", hidden=True)
@click.option("--project", "project_path", default=None)
def repl(project_path):
    """Interactive mode."""
    global _repl_mode
    from cli_anything.squoosh.utils.repl_skin import ReplSkin
    _repl_mode = True
    sess = get_session()
    skin = ReplSkin("squoosh", version=__version__)
    if project_path and os.path.exists(project_path) and sess.project is None:
        try:
            sess.open(project_path)
        except Exception as e:
            skin.error(str(e))
    skin.print_banner()
    pt = skin.create_prompt_session()
    while True:
        try:
            line = skin.get_input(pt, project_name=(sess.project or {}).get("name", ""),
                                  modified=sess.modified)
        except (EOFError, KeyboardInterrupt):
            break
        line = (line or "").strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            if sess.modified and sess.project is not None:
                skin.warning("Unsaved changes discarded (use 'project save' first)")
            break
        if line in ("help", "?"):
            skin.help(REPL_HELP)
            continue
        try:
            args = shlex.split(line)
        except ValueError as e:
            skin.error(str(e))
            continue
        try:
            cli.main(args=args, prog_name="squoosh", standalone_mode=False)
        except click.exceptions.UsageError as e:
            skin.error(e.format_message())
        except SystemExit:
            pass
        except Exception as e:
            skin.error(str(e))
    skin.print_goodbye()
    _repl_mode = False


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
