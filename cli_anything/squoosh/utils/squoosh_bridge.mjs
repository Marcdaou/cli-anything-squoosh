// squoosh_bridge.mjs - runs Squoosh's real WASM codecs from Node.
//
// Usage: node squoosh_bridge.mjs <job.json>
// The job JSON is { op, squoosh_root, ... }. The bridge prints one JSON object
// on stdout: { ok: true, result } or { ok: false, error }.
//
// Ops
//   probe   { input, stats? }            -> { format, width, height, bytes, stats? }
//   process { input, output, steps[], encoder:{name, options}, preview_png? }
//           -> { output, format, width, height, in_bytes, out_bytes, ratio, timings, stats }
//   decode  { input, output }            -> decodes any supported file and writes a PNG
//
// Steps run in Squoosh's order: rotate (preprocessor) -> resize -> quantize (processors).

import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

if (typeof globalThis.ImageData === 'undefined') {
  globalThis.ImageData = class ImageData {
    constructor(data, width, height) {
      this.data = data;
      this.width = width;
      this.height = height;
    }
  };
}

const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ROOT = job.squoosh_root;
const C = (...p) => path.join(ROOT, 'codecs', ...p);
const cache = new Map();

// Emscripten glue in Squoosh is ESM, but its Node branch uses CJS globals
// (__dirname, require) and its web branch reads `self`. Supply them.
async function emscripten(rel, wasmRel) {
  const key = rel;
  if (cache.has(key)) return cache.get(key);
  const file = C(rel);
  globalThis.__dirname = path.dirname(file);
  globalThis.__filename = file;
  globalThis.require = createRequire(file);
  if (typeof globalThis.self === 'undefined') globalThis.self = globalThis;
  if (!globalThis.self.location) globalThis.self.location = { href: pathToFileURL(file).href };
  const mod = await import(pathToFileURL(file).href);
  const wasm = wasmRel || rel.replace(/\.js$/, '.wasm');
  const inst = await mod.default({ noInitialRun: true, wasmBinary: fs.readFileSync(C(wasm)) });
  cache.set(key, inst);
  return inst;
}

// wasm-bindgen "web" target packages: init with the wasm bytes.
async function bindgen(rel, wasmRel) {
  if (cache.has(rel)) return cache.get(rel);
  const mod = await import(pathToFileURL(C(rel)).href);
  await mod.default(fs.readFileSync(C(wasmRel)));
  cache.set(rel, mod);
  return mod;
}

const u8 = (d) => new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
const png = () => bindgen('png/pkg/squoosh_png.js', 'png/pkg/squoosh_png_bg.wasm');

// ---------- format sniffing ----------
function sniff(b) {
  if (b.length < 12) return 'unknown';
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return 'png';
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return 'jpeg';
  if (b.toString('latin1', 0, 4) === 'RIFF' && b.toString('latin1', 8, 12) === 'WEBP') return 'webp';
  if (b.toString('latin1', 4, 8) === 'ftyp' && /avi[fs]/.test(b.toString('latin1', 8, 12))) return 'avif';
  if ((b[0] === 0xff && b[1] === 0x0a) || b.toString('latin1', 4, 8) === 'JXL ') return 'jxl';
  if (b.toString('latin1', 0, 4) === 'qoif') return 'qoi';
  if (b[0] === 0xf4 && b[1] === 0xff && b[2] === 0x6f) return 'wp2';
  return 'unknown';
}

// ---------- decoders ----------
const DECODERS = {
  png: async (buf) => (await png()).decode(new Uint8Array(buf)),
  jpeg: async (buf) => (await emscripten('mozjpeg/dec/mozjpeg_node_dec.js')).decode(buf),
  webp: async (buf) => (await emscripten('webp/dec/webp_node_dec.js')).decode(buf),
  avif: async (buf) => (await emscripten('avif/dec/avif_node_dec.js')).decode(buf),
  jxl: async (buf) => (await emscripten('jxl/dec/jxl_node_dec.js')).decode(buf),
  wp2: async (buf) => (await emscripten('wp2/dec/wp2_node_dec.js')).decode(buf),
  qoi: async (buf) => (await emscripten('qoi/dec/qoi_dec.js', 'qoi/dec/qoi_dec.wasm')).decode(buf),
};

async function decode(file) {
  const buf = fs.readFileSync(file);
  const fmt = sniff(buf);
  if (!DECODERS[fmt]) throw new Error(`Unsupported or unrecognised image format: ${file}`);
  const img = await DECODERS[fmt](buf);
  if (!img || !img.width) throw new Error(`Squoosh ${fmt} decoder failed on ${file}`);
  return { img, fmt, bytes: buf.length };
}

// ---------- encoders ----------
const ENCODERS = {
  mozjpeg: async (img, o) => (await emscripten('mozjpeg/enc/mozjpeg_node_enc.js')).encode(img.data, img.width, img.height, o),
  webp: async (img, o) => (await emscripten('webp/enc/webp_node_enc.js')).encode(img.data, img.width, img.height, o),
  avif: async (img, o) => (await emscripten('avif/enc/avif_node_enc.js')).encode(img.data, img.width, img.height, o),
  jxl: async (img, o) => (await emscripten('jxl/enc/jxl_node_enc.js')).encode(img.data, img.width, img.height, o),
  wp2: async (img, o) => (await emscripten('wp2/enc/wp2_node_enc.js')).encode(img.data, img.width, img.height, o),
  qoi: async (img, o) => (await emscripten('qoi/enc/qoi_enc.js', 'qoi/enc/qoi_enc.wasm')).encode(img.data, img.width, img.height, o),
  oxipng: async (img, o) => {
    const m = await bindgen('oxipng/pkg/squoosh_oxipng.js', 'oxipng/pkg/squoosh_oxipng_bg.wasm');
    return m.optimise(new Uint8ClampedArray(img.data), img.width, img.height, o.level, !!o.interlace);
  },
  png: async (img) => (await png()).encode(u8(img.data), img.width, img.height),
};

// ---------- processors ----------
async function rotate(img, deg) {
  if (!deg) return img;
  const { instance } = await WebAssembly.instantiate(fs.readFileSync(C('rotate/rotate.wasm')));
  const bytes = img.width * img.height * 4;
  const need = Math.ceil((bytes * 2 + 8) / 65536);
  const have = Math.floor(instance.exports.memory.buffer.byteLength / 65536);
  if (need > have) instance.exports.memory.grow(need - have);
  const view = new Uint8ClampedArray(instance.exports.memory.buffer);
  view.set(img.data, 8);
  instance.exports.rotate(img.width, img.height, deg);
  const flip = deg % 180 !== 0;
  return new ImageData(view.slice(bytes + 8, bytes * 2 + 8),
    flip ? img.height : img.width, flip ? img.width : img.height);
}

function containOffsets(sw, sh, dw, dh) {
  const ci = sw / sh, co = dw / dh;
  if (co > ci) { const h = sw / co; return { sx: 0, sy: (sh - h) / 2, sw, sh: h }; }
  const w = sh * co; return { sx: (sw - w) / 2, sy: 0, sw: w, sh };
}

function crop(img, sx, sy, sw, sh) {
  const out = new Uint8ClampedArray(sw * sh * 4);
  for (let y = 0; y < sh; y++) {
    const s = ((y + sy) * img.width + sx) * 4;
    out.set(img.data.subarray(s, s + sw * 4), y * sw * 4);
  }
  return new ImageData(out, sw, sh);
}

const RESIZE_METHODS = ['triangle', 'catrom', 'mitchell', 'lanczos3'];

async function resize(img, o) {
  let input = img;
  let method = o.method;
  if (method === 'hqx') {
    const hqx = await bindgen('hqx/pkg/squooshhqx.js', 'hqx/pkg/squooshhqx_bg.wasm');
    const factor = Math.min(4, Math.max(1, Math.ceil(Math.max(o.width / img.width, o.height / img.height))));
    if (factor > 1) {
      const px = new Uint32Array(img.data.buffer.slice(img.data.byteOffset, img.data.byteOffset + img.data.byteLength));
      const r = hqx.resize(px, img.width, img.height, factor);
      input = new ImageData(new Uint8ClampedArray(r.buffer), img.width * factor, img.height * factor);
    }
    method = 'catrom';
  }
  if (o.fitMethod === 'contain') {
    const c = containOffsets(input.width, input.height, o.width, o.height);
    input = crop(input, Math.round(c.sx), Math.round(c.sy), Math.round(c.sw), Math.round(c.sh));
  }
  const m = await bindgen('resize/pkg/squoosh_resize.js', 'resize/pkg/squoosh_resize_bg.wasm');
  const out = m.resize(u8(input.data), input.width, input.height, o.width, o.height,
    RESIZE_METHODS.indexOf(method), !!o.premultiply, !!o.linearRGB);
  return new ImageData(new Uint8ClampedArray(out.buffer), o.width, o.height);
}

async function quantize(img, o) {
  const m = await emscripten('imagequant/imagequant_node.js');
  const out = o.zx
    ? m.zx_quantize(img.data, img.width, img.height, o.dither)
    : m.quantize(img.data, img.width, img.height, o.maxNumColors, o.dither);
  return new ImageData(new Uint8ClampedArray(out), img.width, img.height);
}

function stats(img) {
  const d = img.data, n = img.width * img.height;
  const sum = [0, 0, 0, 0];
  const colors = new Set();
  const step = Math.max(1, Math.floor(n / 200000));
  for (let i = 0; i < n; i += step) {
    const p = i * 4;
    sum[0] += d[p]; sum[1] += d[p + 1]; sum[2] += d[p + 2]; sum[3] += d[p + 3];
    if (colors.size <= 70000) colors.add((d[p] << 24) | (d[p + 1] << 16) | (d[p + 2] << 8) | d[p + 3]);
  }
  const k = Math.ceil(n / step);
  return { mean: sum.map((s) => +(s / k).toFixed(2)), unique_colors_sampled: colors.size };
}

// ---------- ops ----------
async function opProbe() {
  const { img, fmt, bytes } = await decode(job.input);
  const r = { format: fmt, width: img.width, height: img.height, bytes };
  if (job.stats) r.stats = stats(img);
  return r;
}

async function opProcess() {
  const t0 = Date.now();
  const { img: src, fmt, bytes } = await decode(job.input);
  let img = src;
  const timings = { decode_ms: Date.now() - t0 };
  for (const step of job.steps || []) {
    const t = Date.now();
    if (step.type === 'rotate') img = await rotate(img, step.options.rotate);
    else if (step.type === 'resize') img = await resize(img, step.options);
    else if (step.type === 'quantize') img = await quantize(img, step.options);
    else throw new Error(`Unknown step: ${step.type}`);
    timings[`${step.type}_ms`] = Date.now() - t;
  }
  const enc = ENCODERS[job.encoder.name];
  if (!enc) throw new Error(`Unknown encoder: ${job.encoder.name}`);
  const t = Date.now();
  const out = await enc(img, job.encoder.options || {});
  if (!out || !out.length) throw new Error(`Squoosh ${job.encoder.name} encoder returned no data`);
  timings.encode_ms = Date.now() - t;
  fs.mkdirSync(path.dirname(path.resolve(job.output)), { recursive: true });
  fs.writeFileSync(job.output, Buffer.from(out.buffer, out.byteOffset, out.byteLength));
  const result = {
    output: path.resolve(job.output), input_format: fmt, format: sniff(fs.readFileSync(job.output)),
    in_width: src.width, in_height: src.height, width: img.width, height: img.height,
    in_bytes: bytes, out_bytes: out.length, ratio: +(out.length / bytes).toFixed(4), timings,
  };
  if (job.preview_png) {
    // Decode the encoded result back with Squoosh's own decoder: what a viewer would see.
    const back = await decode(job.output);
    const p = await ENCODERS.png(back.img);
    fs.writeFileSync(job.preview_png, Buffer.from(p.buffer, p.byteOffset, p.byteLength));
    result.preview_png = path.resolve(job.preview_png);
    result.stats = stats(back.img);
  }
  return result;
}

async function opDecode() {
  const { img, fmt } = await decode(job.input);
  const p = await ENCODERS.png(img);
  fs.writeFileSync(job.output, Buffer.from(p.buffer, p.byteOffset, p.byteLength));
  return { output: path.resolve(job.output), source_format: fmt, width: img.width, height: img.height };
}

const OPS = { probe: opProbe, process: opProcess, decode: opDecode };

try {
  if (!OPS[job.op]) throw new Error(`Unknown op: ${job.op}`);
  const result = await OPS[job.op]();
  process.stdout.write(JSON.stringify({ ok: true, result }));
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
  process.exitCode = 1;
}
