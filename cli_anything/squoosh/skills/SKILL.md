---
name: >-
  cli-anything-squoosh
description: >-
  Compress, resize, rotate, palette-reduce and convert images with Squoosh's real WASM codecs
  (MozJPEG, WebP, AVIF, JPEG XL, WebP2, OxiPNG, QOI) from the command line. Use it to shrink images
  for the web, compare codecs by size, batch-convert folders, or decode AVIF/JXL/WebP to PNG.
---

# cli-anything-squoosh

A stateful CLI for [Squoosh](https://squoosh.app). Every pixel operation runs in Squoosh's own
WebAssembly codecs, loaded in Node from the Squoosh source tree. No codec is reimplemented.

## Installation

```bash
cd squoosh/agent-harness && pip install -e .
cli-anything-squoosh doctor        # must report ok: True
```

Prerequisites: Python 3.9+, **Node.js 18+**, and the Squoosh repo's `codecs/` folder (found
automatically when the harness lives inside the repo; otherwise `export SQUOOSH_ROOT=/path/to/squoosh`).

## Two ways to use it

**One-shot (no state):**

```bash
cli-anything-squoosh compress in.png -e webp -q 75 -w 1280 -o out.webp
cli-anything-squoosh compress in.png -e avif -O quality=40 -O speed=6 --rotate 90 -c 64
```

**Whole folder (quality 70 by default):**

```bash
cli-anything-squoosh --json folder ~/Pictures/shots            # -> ~/Pictures/shots-squoosh-q70/
```

**Project (state in a JSON file, auto-saved after each command):**

```bash
P="--project hero.squoosh.json"
cli-anything-squoosh $P project new -n hero -s photo.png     # -e <encoder> optional
cli-anything-squoosh $P edit resize -w 1280                  # one side keeps the aspect ratio
cli-anything-squoosh $P encoder set avif quality=45 speed=6
cli-anything-squoosh $P export hero.avif --overwrite
```

Running with no command starts an interactive REPL (`help`, `session undo`, `project save`, `quit`).

## Command groups

| Group | Commands | Notes |
|---|---|---|
| `project` | `new [-n NAME] [-e ENC] [-s IMG] [-o FILE]`, `open`, `save [PATH]`, `info`, `json` | |
| `source` | `set IMG`, `info` | Probes the image with Squoosh's decoders |
| `edit` | `rotate 0\|90\|180\|270`, `resize -w -h -m METHOD --fit stretch\|contain`, `quantize -c N -d 0..1 [--zx]`, `disable resize\|quantize\|rotate`, `list` | Render order: rotate → resize → quantize → encode |
| `encoder` | `list`, `options [ENC]`, `set ENC [k=v ...] [--reset]`, `option k=v ...`, `show` | Switching encoders clears the old options |
| `export` | `export [OUT] [--overwrite]` | Default name: `<source>.squoosh.<ext>` next to the source |
| `compress` | `compress IMG [-o OUT] [-e ENC] [-q Q] [-O k=v] [--rotate] [-w] [-h] [-m] [--fit] [-c] [--dither]` | Stateless |
| `compare` | `compare -d DIR [-e a,b,c] [-i IMG]` | Same pipeline, several codecs, sorted by size |
| `folder` | `folder DIR [-o OUT] [-q 70] [-e ENC] [-r] [-w W] [-O k=v] [--overwrite]` | Compresses every image in DIR into OUT (default `DIR-squoosh-q70`), mirroring subfolders with `-r`. Existing outputs are skipped unless `--overwrite`; non-image files are ignored; failures are reported per file |
| `batch` | `batch GLOB... -d DIR [--overwrite]` | Applies the project's settings to many files |
| `probe` / `decode` | `probe IMG [--stats]`, `decode IMG OUT.png` | Reads PNG, JPEG, WebP, AVIF, JXL, WP2, QOI |
| `preview` | `recipes`, `capture [--force]`, `latest`, `diff ENC [k=v ...]` | preview-bundle/v1 |
| `session` | `status`, `undo`, `redo` | |
| `doctor` | | Checks Node and the codec tree |

Global flags go **before** the command: `--json`, `--project FILE`, `--dry-run`.

## Encoders

| Name | Ext | Key options (run `encoder options NAME` for all of them, with ranges) |
|---|---|---|
| `mozjpeg` | jpg | `quality` 0-100 (75), `progressive`, `chroma_subsample`, `trellis_loops` |
| `webp` | webp | `quality` (75), `method` 0-6, `lossless` 0/1, `near_lossless`, `alpha_quality` |
| `avif` | avif | `quality` (50), `speed` 0-10, `subsample`, `qualityAlpha`; `enableSharpDownsampling` must stay false |
| `jxl` | jxl | `quality` (75), `effort` 1-9, `progressive`, `lossyModular` |
| `wp2` | wp2 | `quality`, `effort` 0-9, `alpha_quality` |
| `oxipng` | png | `level` 0-6, `interlace` (lossless) |
| `qoi` | qoi | none (lossless) |
| `png` | png | none (plain PNG, not optimised) |

Not available: the browser-only encoders (browserJPEG/PNG/GIF) and SVG vector resize.

## Previews

- **Producer:** `cli-anything-squoosh --project p.json preview capture` renders through Squoosh
  and writes a bundle to `.squoosh-previews/result-<fingerprint>/`: the encoded file,
  `decoded.png` (what a viewer will see), `source.png`, `manifest.json` and `summary.json`.
  An unchanged project returns the cached bundle (`"cached": true`).
  `preview diff avif quality=30` renders the project's encoder (`a`) next to another one (`b`).
  `preview latest` reads the newest bundle and renders nothing.
- **Consumer:** `cli-hub previews inspect|html|open <bundle_dir>`. These are read-only and never render.
- Modes: static and diff (no live mode). Artifacts are images.

## Agent guidance

- Always use `--json`. Results include `output`, `in_bytes`, `out_bytes`, `saved_percent`,
  `width`, `height`, `format` and `timings`.
- Errors exit with status 1 and print `{"error": "...", "type": "..."}` on stdout. On an error the
  project file is not changed.
- Inspect before changing anything: `--json project info`, `--json encoder show`, `--json edit list`.
- Try a change without saving: `--dry-run`. Undo inside the REPL with `session undo`. (Each one-shot
  process starts with empty history, so undo only works within one REPL session.)
- To pick a codec, run `compare` first, then `encoder set <smallest>`.
- Every export is checked for valid magic bytes. To check pixels, run `probe OUT --stats`
  (mean RGBA) or `decode OUT x.png`.

## Example: smallest web image under a width limit

```bash
cli-anything-squoosh --json --project w.json project new -s photo.png
cli-anything-squoosh --json --project w.json edit resize -w 1600
cli-anything-squoosh --json --project w.json compare -d trials -e mozjpeg,webp,avif,jxl
cli-anything-squoosh --json --project w.json encoder set avif quality=45
cli-anything-squoosh --json --project w.json export photo.avif --overwrite
```
