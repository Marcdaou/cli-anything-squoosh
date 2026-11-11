# Squoosh: harness analysis and SOP

## Backend engine

Squoosh is a Preact web app (`src/client`) that sends all image work to Web Workers
(`src/features/*/worker`). The workers call WebAssembly codecs built from `codecs/`.
Those codecs also ship **Node builds**, and those are the backend this harness uses:

| Role | Module (under `codecs/`) | Loader |
|---|---|---|
| Decode PNG / encode PNG | `png/pkg/squoosh_png.js` | wasm-bindgen |
| MozJPEG enc/dec | `mozjpeg/{enc,dec}/mozjpeg_node_*.js` | emscripten |
| WebP enc/dec | `webp/{enc,dec}/webp_node_*.js` | emscripten |
| AVIF enc/dec | `avif/{enc,dec}/avif_node_*.js` | emscripten |
| JPEG XL enc/dec | `jxl/{enc,dec}/jxl_node_*.js` | emscripten |
| WebP2 enc/dec | `wp2/{enc,dec}/wp2_node_*.js` | emscripten |
| QOI enc/dec | `qoi/{enc,dec}/qoi_*.js` | emscripten |
| OxiPNG | `oxipng/pkg/squoosh_oxipng.js` | wasm-bindgen |
| Resize | `resize/pkg/squoosh_resize.js` (+ `hqx/pkg`) | wasm-bindgen |
| Quantize | `imagequant/imagequant_node.js` | emscripten |
| Rotate | `rotate/rotate.wasm` | raw WebAssembly |

`utils/squoosh_bridge.mjs` loads these modules, with shims for the CJS globals the
emscripten glue expects. It runs one job (probe / process / decode) per Node
process. `utils/squoosh_backend.py` locates Node and the codec tree and calls the bridge.

## GUI → CLI mapping

| GUI action | CLI |
|---|---|
| Drop an image | `source set <img>` |
| Rotate button (preprocessor) | `edit rotate 0/90/180/270` |
| Resize panel (method, fit, premultiply, linear RGB) | `edit resize -w -h -m --fit` |
| Reduce palette panel | `edit quantize -c -d --zx` |
| Encoder dropdown + options panel | `encoder set <name> k=v`, `encoder option k=v` |
| Download | `export [out]` |
| Left vs right comparison | `preview diff`, `compare` |
| Before/after slider | `preview capture` (source.png vs decoded.png) |

The render order matches the workers: rotate → resize → quantize → encode.

## Data model

Squoosh keeps all state in memory and has no project file. The harness defines
`*.squoosh.json` (`format: cli-anything-squoosh`, `version: 1`) to hold the source path
and probed size, the rotate value, the resize and quantize settings (each with an
`enabled` flag), the encoder name with only the options you changed, and the export
history. Defaults are filled in from the registry at render time, because the
emscripten encoders reject a struct with missing fields.

## Findings while building

- The shipped `avif_node_enc.wasm` predates a source rename: it expects
  `enableSharpDownsampling`, not `enableSharpYUV` as `avif_enc.d.ts` says, and it aborts
  if that option is true (it was built without libsharpyuv). The registry follows the binary.
- OxiPNG may write palette (indexed) PNGs.
- Browser encoders (`browserJPEG/PNG/GIF`) and vector resize need a canvas and are not exposed.

## State, undo, saving

`core/session.py` keeps snapshot-based undo/redo (up to 100 steps) and saves with an
exclusive `fcntl` lock. One-shot commands auto-save through a result callback.
`--dry-run` skips the save, and the REPL never auto-saves.
