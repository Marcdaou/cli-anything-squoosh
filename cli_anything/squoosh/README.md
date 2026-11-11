# cli-anything-squoosh

A stateful command-line interface to [Squoosh](https://squoosh.app) that AI agents
can drive. Every image is decoded, rotated, resized, quantized and encoded by
**Squoosh's own WebAssembly codecs** (MozJPEG, WebP, AVIF, JPEG XL, WebP2, OxiPNG,
QOI, libimagequant, the resize/hqx/rotate modules), loaded in Node from the Squoosh
source tree. Nothing is reimplemented in Python.

## Requirements

- **Node.js 18+** (`brew install node`, or https://nodejs.org). Required.
- **The Squoosh source tree with built codecs** (the `codecs/` folder, which ships
  prebuilt `.wasm`). Required. When the harness lives inside the Squoosh repo
  it finds the tree on its own; otherwise set `SQUOOSH_ROOT=/path/to/squoosh`.
- Python 3.9+.

## Install

```bash
cd squoosh/agent-harness
pip install -e .
cli-anything-squoosh doctor      # checks node + codec tree
```

## Usage

### One-shot

```bash
cli-anything-squoosh compress photo.png -e webp -q 75 -w 1280 -o photo.webp
cli-anything-squoosh folder ~/Pictures/shots              # -> ~/Pictures/shots-squoosh-q70/
cli-anything-squoosh folder shots -q 60 -e webp -r -o web/  # webp, include subfolders
cli-anything-squoosh compare -i photo.png -d out/ -e mozjpeg,webp,avif,jxl
cli-anything-squoosh probe photo.avif
cli-anything-squoosh decode photo.jxl photo.png
```

### Project workflow (state saved to JSON after every command)

```bash
P="--project hero.squoosh.json"
cli-anything-squoosh $P project new -n hero -s photo.png
cli-anything-squoosh $P edit rotate 90
cli-anything-squoosh $P edit resize -w 1280 -m lanczos3
cli-anything-squoosh $P edit quantize -c 128 -d 0.8
cli-anything-squoosh $P encoder set avif quality=45 speed=6
cli-anything-squoosh $P export hero.avif --overwrite
cli-anything-squoosh $P batch "shots/*.png" -d out/
cli-anything-squoosh $P --dry-run edit rotate 180   # try without saving
```

### Interactive REPL

Run `cli-anything-squoosh` (optionally with `--project file.json`) with no command.
It supports `session undo` / `session redo`. In the REPL, save explicitly with
`project save`.

### JSON output for agents

Put `--json` before the command: `cli-anything-squoosh --json --project p.json export`.
On failure, commands exit with status 1 and print `{"error": "...", "type": "..."}`.

## Command groups

| Group | Commands |
|---|---|
| `project` | `new`, `open`, `save`, `info`, `json` |
| `source` | `set`, `info` |
| `edit` | `rotate`, `resize`, `quantize`, `disable`, `list` |
| `encoder` | `list`, `options`, `set`, `option`, `show` |
| `folder` | Compress a whole folder into a new folder (quality 70 by default) |
| `export` / `compress` / `compare` / `batch` | Render through the real codecs |
| `probe` / `decode` | Inspect or decode any supported format |
| `preview` | `recipes`, `capture`, `latest`, `diff` |
| `session` | `status`, `undo`, `redo` |
| `doctor` | Backend check |

## Previews

Preview support: **static** and **diff** modes (no live mode). Artifacts are images.

- **Producer** (renders through Squoosh): `cli-anything-squoosh --project p.json preview capture`
  writes a `preview-bundle/v1` bundle in `.squoosh-previews/` next to the project. The bundle
  holds the encoded file, `decoded.png` (the output decoded again by Squoosh, so it shows what
  a viewer will see) and `source.png`, plus `manifest.json` and `summary.json`.
  An unchanged project reuses its bundle (`"cached": true`); use `--force` to render again.
  `preview diff avif quality=30` renders the project's encoder next to another one.
  `preview latest` returns the newest bundle without rendering.
- **Consumer** (read-only): `cli-hub previews inspect <bundle_dir>` / `html` / `open`.

The previews are accurate because the "after" image is the real encoder output, decoded
again by the real Squoosh decoder.

## Encoders and limits

`mozjpeg`, `webp`, `avif`, `jxl`, `wp2`, `oxipng`, `qoi`, and `png` (unoptimised). Run
`encoder options <name>` to see every option with its default and allowed range.

Not available, because they need a browser canvas: Squoosh's browser JPEG/PNG/GIF
encoders and SVG vector resize. The shipped AVIF binary was built without libsharpyuv,
so `enableSharpDownsampling=true` is rejected.

## Tests

```bash
pip install pytest
CLI_ANYTHING_FORCE_INSTALLED=1 pytest cli_anything/squoosh/tests -v -s
```

The E2E tests run the real codecs and **fail** (they don't skip) if Node or the codec
tree is missing. See `tests/TEST.md`.
