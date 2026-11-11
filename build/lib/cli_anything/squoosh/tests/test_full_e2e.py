"""E2E tests: real Squoosh WASM codecs (via Node), real images, installed CLI.

No graceful degradation: if Node or the Squoosh codec tree is missing these
tests fail. Run with -s to see artifact paths.
"""

import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from cli_anything.squoosh.core import codecs
from cli_anything.squoosh.core import export as exp
from cli_anything.squoosh.core import preview as prev
from cli_anything.squoosh.core import project as proj
from cli_anything.squoosh.core.session import Session
from cli_anything.squoosh.utils import squoosh_backend as backend

ROOT = backend.find_squoosh_root()
EXAMPLE = os.path.join(ROOT, "codecs", "example.png")
EW, EH = 2558, 1348  # codecs/example.png


def scaled(w):
    """Height Squoosh gets when resizing example.png to width w."""
    return max(1, round(EH * w / EW))
LOSSY = ["mozjpeg", "webp", "avif", "jxl", "wp2"]


# ---------------------------------------------------------------- PNG helpers (test input/inspection only)
def write_png(path, w, h, pixel):
    """Write an RGBA PNG; pixel(x, y) -> (r, g, b, a)."""
    raw = b"".join(b"\0" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def read_png(path):
    """Read an 8-bit RGBA/RGB non-interlaced PNG -> (w, h, rows of (r,g,b,a))."""
    data = open(path, "rb").read()
    pos, idat, w = 8, b"", None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t, d = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", d[:10])
            assert depth == 8 and ctype in (2, 3, 6), (depth, ctype)
            bpp = 4 if ctype == 6 else 3
        elif t == b"IDAT":
            idat += d
        pos += 12 + n
    if ctype == 3:
        return _read_indexed(data)
    raw, stride, prev_row, rows, i = zlib.decompress(idat), w * bpp, bytearray(w * bpp), [], 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev_row[x]
            c = prev_row[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[k:k + bpp]) + ((255,) if bpp == 3 else ()) for k in range(0, stride, bpp)])
        prev_row = line
    return w, h, rows


def _read_indexed(path_or_data):
    """Palette PNGs (OxiPNG output): expand via PLTE/tRNS, any bit depth, no interlace."""
    data = path_or_data
    pos, idat, plte, trns = 8, b"", b"", b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t, d = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            w, h, depth = struct.unpack(">IIB", d[:9])
        elif t == b"PLTE":
            plte = d
        elif t == b"tRNS":
            trns = d
        elif t == b"IDAT":
            idat += d
        pos += 12 + n
    raw, stride = zlib.decompress(idat), (w * depth + 7) // 8
    prev_row, rows, i = bytearray(stride), [], 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - 1] if x >= 1 else 0
            b = prev_row[x]
            c = prev_row[x - 1] if x >= 1 else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        row = []
        for xx in range(w):
            bit = xx * depth
            idx = (line[bit // 8] >> (8 - depth - bit % 8)) & ((1 << depth) - 1)
            row.append(tuple(plte[idx * 3:idx * 3 + 3]) + ((trns[idx] if idx < len(trns) else 255),))
        rows.append(row)
        prev_row = line
    return w, h, rows


def show(label, path):
    print(f"\n  {label}: {path} ({os.path.getsize(path):,} bytes)")


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    return str(tmp_path_factory.mktemp("squoosh_e2e"))


@pytest.fixture(scope="module")
def red(work):
    return write_png(os.path.join(work, "red.png"), 64, 48, lambda x, y: (255, 0, 0, 255))


@pytest.fixture(scope="module")
def gradient(work):
    return write_png(os.path.join(work, "grad.png"), 96, 64,
                     lambda x, y: (x * 255 // 95, y * 255 // 63, (x + y) % 256, 255))


@pytest.fixture(scope="module")
def marker(work):
    # 40x20, white, with a black block in the top-left 4x4.
    return write_png(os.path.join(work, "marker.png"), 40, 20,
                     lambda x, y: (0, 0, 0, 255) if x < 4 and y < 4 else (255, 255, 255, 255))


def project_for(src, encoder="mozjpeg", **opts):
    p = proj.new_project("e2e", encoder)
    proj.set_source(p, src, backend.probe(src))
    if opts:
        proj.set_encoder(p, encoder, opts)
    return p


# ---------------------------------------------------------------- backend basics
class TestBackend:
    def test_doctor(self):
        r = backend.doctor()
        assert r["ok"] and r["node_version"].startswith("v")

    def test_probe_example(self):
        r = backend.probe(EXAMPLE, stats=True)
        assert (r["format"], r["width"], r["height"]) == ("png", EW, EH)
        assert len(r["stats"]["mean"]) == 4

    def test_probe_rejects_garbage(self, work):
        f = os.path.join(work, "junk.bin")
        open(f, "wb").write(b"not an image at all")
        with pytest.raises(backend.BackendError, match="Unsupported"):
            backend.probe(f)

    def test_missing_root_env(self, monkeypatch, work):
        monkeypatch.setenv("SQUOOSH_ROOT", work)
        with pytest.raises(backend.BackendError, match="SQUOOSH_ROOT"):
            backend.find_squoosh_root()


# ---------------------------------------------------------------- every encoder, every decoder
class TestEncoders:
    @pytest.mark.parametrize("enc", list(codecs.ENCODERS))
    def test_encode_example(self, enc, work):
        out = os.path.join(work, f"example.{enc}.{codecs.ENCODERS[enc]['extension']}")
        p = project_for(EXAMPLE, enc)
        proj.set_resize(p, width=480)
        r = exp.render(p, out, overwrite=True)
        assert r["out_bytes"] > 100 and r["format"] == codecs.ENCODERS[enc]["format"]
        back = backend.probe(out)
        assert (back["width"], back["height"]) == (480, scaled(480))
        show(enc, out)

    @pytest.mark.parametrize("enc", list(codecs.ENCODERS))
    def test_solid_red_colour(self, enc, red, work):
        out = os.path.join(work, f"red.{enc}.{codecs.ENCODERS[enc]['extension']}")
        exp.render(project_for(red, enc), out, overwrite=True)
        mean = backend.probe(out, stats=True)["stats"]["mean"]
        tol = 12 if enc in LOSSY else 0
        assert abs(mean[0] - 255) <= tol and mean[1] <= tol and mean[2] <= tol, (enc, mean)

    @pytest.mark.parametrize("enc,fmt", [("mozjpeg", "jpeg"), ("webp", "webp"), ("avif", "avif"),
                                         ("jxl", "jxl"), ("wp2", "wp2"), ("qoi", "qoi"), ("oxipng", "png")])
    def test_decoder_roundtrip(self, enc, fmt, gradient, work):
        out = os.path.join(work, f"g.{enc}.{codecs.ENCODERS[enc]['extension']}")
        exp.render(project_for(gradient, enc), out, overwrite=True)
        png = out + ".decoded.png"
        r = backend.decode_to_png(out, png)
        assert (r["source_format"], r["width"], r["height"]) == (fmt, 96, 64)
        w, h, _ = read_png(png)
        assert (w, h) == (96, 64)


class TestOptionsTakeEffect:
    def test_mozjpeg_quality(self, work):
        sizes = {}
        for q in (10, 90):
            out = os.path.join(work, f"q{q}.jpg")
            p = project_for(EXAMPLE, "mozjpeg", quality=q)
            proj.set_resize(p, width=640)
            sizes[q] = exp.render(p, out, overwrite=True)["out_bytes"]
        assert sizes[10] < sizes[90] / 2

    def test_webp_lossless_exact(self, gradient, work):
        out = os.path.join(work, "lossless.webp")
        exp.render(project_for(gradient, "webp", lossless=1), out, overwrite=True)
        png = out + ".png"
        backend.decode_to_png(out, png)
        assert read_png(png)[2] == read_png(gradient)[2]

    def test_oxipng_levels(self, work):
        sizes = {}
        for lvl in (0, 6):
            p = project_for(EXAMPLE, "oxipng", level=lvl)
            proj.set_resize(p, width=400)
            sizes[lvl] = exp.render(p, os.path.join(work, f"lvl{lvl}.png"), overwrite=True)["out_bytes"]
        assert sizes[6] <= sizes[0]

    def test_avif_speed(self, work):
        p = project_for(EXAMPLE, "avif", speed=10, quality=30)
        proj.set_resize(p, width=320)
        r = exp.render(p, os.path.join(work, "fast.avif"), overwrite=True)
        assert r["options"]["speed"] == 10 and r["format"] == "avif"

    def test_avif_sharp_downsampling_rejected(self):
        # The shipped binary aborts with "libsharpyuv not implemented" if this is on.
        with pytest.raises(ValueError, match="libsharpyuv"):
            project_for(EXAMPLE, "avif", enableSharpDownsampling=True)


# ---------------------------------------------------------------- processors
class TestProcessors:
    @pytest.mark.parametrize("method", codecs.RESIZE_METHODS)
    def test_resize_methods(self, method, gradient, work):
        p = project_for(gradient, "oxipng")
        proj.set_resize(p, width=192, height=128, method=method)
        out = os.path.join(work, f"rs-{method}.png")
        r = exp.render(p, out, overwrite=True)
        assert (r["width"], r["height"]) == (192, 128)
        assert read_png(out)[:2] == (192, 128)

    def test_contain_crops(self, work):
        p = project_for(EXAMPLE, "mozjpeg")
        proj.set_resize(p, width=200, height=200, fit="contain")
        r = exp.render(p, os.path.join(work, "square.jpg"), overwrite=True)
        assert (r["width"], r["height"]) == (200, 200)

    @pytest.mark.parametrize("deg,corner", [(90, "top-right"), (180, "bottom-right"), (270, "bottom-left")])
    def test_rotate_moves_marker(self, deg, corner, marker, work):
        p = project_for(marker, "png")
        proj.set_rotate(p, deg)
        out = os.path.join(work, f"rot{deg}.png")
        r = exp.render(p, out, overwrite=True)
        w, h, rows = read_png(out)
        assert (w, h) == ((20, 40) if deg != 180 else (40, 20)) == (r["width"], r["height"])
        px = {"top-right": rows[0][w - 1], "bottom-right": rows[h - 1][w - 1],
              "bottom-left": rows[h - 1][0]}[corner]
        assert px[:3] == (0, 0, 0) and rows[0][0][:3] == (255, 255, 255)

    def test_quantize_colours(self, gradient, work):
        p = project_for(gradient, "png")
        proj.set_quantize(p, colors=4, dither=0)
        out = os.path.join(work, "q4.png")
        exp.render(p, out, overwrite=True)
        colours = {px for row in read_png(out)[2] for px in row}
        assert 1 < len(colours) <= 4


# ---------------------------------------------------------------- preview bundles
class TestPreview:
    def test_capture_and_cache(self, work):
        p = project_for(EXAMPLE, "webp", quality=60)
        proj.set_resize(p, width=300)
        root = os.path.join(work, "pv")
        m = prev.capture(p, root=root)
        assert m["protocol"] == "preview-bundle/v1" and not m["cached"]
        for a in m["artifacts"]:
            assert os.path.getsize(os.path.join(m["_bundle_dir"], a["path"])) > 0
        assert read_png(os.path.join(m["_bundle_dir"], "decoded.png"))[:2] == (300, scaled(300))
        assert json.load(open(m["summary_path"]))["encoder"] == "webp"
        assert prev.capture(p, root=root)["cached"]
        assert not prev.capture(p, root=root, force=True)["cached"]
        assert prev.latest(root=root)["_bundle_dir"] == m["_bundle_dir"]
        show("preview bundle", m["_manifest_path"])

    def test_diff(self, work):
        p = project_for(EXAMPLE, "mozjpeg", quality=90)
        proj.set_resize(p, width=300)
        m = prev.diff(p, "avif", ["quality=30"], root=os.path.join(work, "pv"))
        s = m["summary"]
        assert s["a"]["encoder"] == "mozjpeg" and s["b"]["encoder"] == "avif"
        assert s["smaller"] == ("a" if s["a"]["out_bytes"] <= s["b"]["out_bytes"] else "b")
        assert len(s["mean_rgba_delta"]) == 4

    def test_failed_capture_leaves_nothing(self, work, monkeypatch):
        p = project_for(EXAMPLE, "webp")
        root = os.path.join(work, "pv_fail")

        def boom(*a, **k):
            raise backend.BackendError("simulated codec failure")
        monkeypatch.setattr(exp.backend, "process", boom)
        with pytest.raises(backend.BackendError):
            prev.capture(p, root=root)
        assert not glob.glob(os.path.join(root, "*"))


# ---------------------------------------------------------------- workflows (core API)
class TestWorkflows:
    def test_web_hero(self, work):
        s = Session()
        s.new("hero", "webp", os.path.join(work, "hero.json"))
        s.mutate(proj.set_source, EXAMPLE, backend.probe(EXAMPLE))
        s.mutate(proj.set_resize, 1280, None, "lanczos3")
        s.mutate(proj.set_encoder, "webp", ["quality=75"])
        r = exp.render(s.project, os.path.join(work, "hero.webp"), overwrite=True)
        s.mutate(exp.record_export, r)
        s.save()
        assert (r["width"], r["height"]) == (1280, scaled(1280))
        assert r["out_bytes"] < r["in_bytes"] * 0.1
        assert Session().open(s.path)["exports"][-1]["bytes"] == r["out_bytes"]
        show("hero", r["output"])

    def test_thumbnail_batch(self, work, gradient):
        p = proj.new_project("thumbs", "mozjpeg")
        proj.set_rotate(p, 90)
        p["source"] = {"path": gradient, "width": 96, "height": 64}
        proj.set_resize(p, 200, 200, fit="contain")
        proj.set_encoder(p, "mozjpeg", ["quality=60"])
        r = exp.batch(p, [EXAMPLE, gradient, os.path.join(work, "missing.png")],
                      os.path.join(work, "thumbs"), overwrite=True)
        assert len(r["processed"]) == 2 and len(r["failed"]) == 1
        for d in r["processed"]:
            b = backend.probe(d["output"])
            assert (b["format"], b["width"], b["height"]) == ("jpeg", 200, 200)

    def test_codec_shootout(self, work):
        p = project_for(EXAMPLE)
        proj.set_resize(p, width=640)
        r = exp.compare(p, ["mozjpeg", "webp", "avif", "jxl", "oxipng"], os.path.join(work, "cmp"))
        sizes = [x["out_bytes"] for x in r["results"]]
        assert sizes == sorted(sizes) and r["smallest"] != "oxipng"
        for x in r["results"]:
            exp.verify_output(x["output"], x["encoder"])

    def test_palette_icon(self, work, gradient):
        p = project_for(gradient, "oxipng", level=3)
        proj.set_quantize(p, colors=16)
        out = os.path.join(work, "icon.png")
        exp.render(p, out, overwrite=True)
        assert len({px for row in read_png(out)[2] for px in row}) <= 16

    def test_iterative_undo(self, work):
        s = Session()
        s.new("tune", "webp")
        s.mutate(proj.set_source, EXAMPLE, backend.probe(EXAMPLE))
        s.mutate(proj.set_resize, 320)
        s.mutate(proj.set_encoder, "webp", ["quality=90"])
        s.mutate(proj.set_encoder, "webp", ["quality=50"])
        s.undo()
        r = exp.render(s.project, os.path.join(work, "tune.webp"), overwrite=True)
        assert r["options"]["quality"] == 90
        s.redo()
        assert s.project["encoder"]["options"]["quality"] == 50


# ---------------------------------------------------------------- folder compression
@pytest.fixture
def photo_folder(tmp_path, gradient, red):
    d = tmp_path / "photos"
    (d / "sub").mkdir(parents=True)
    shutil.copy(EXAMPLE, d / "big.png")
    shutil.copy(gradient, d / "grad.png")
    shutil.copy(red, d / "sub" / "red.png")
    (d / "readme.txt").write_text("not an image")
    (d / "broken.jpg").write_bytes(b"\xff\xd8\xff garbage")
    return str(d)


class TestFolder:
    def test_defaults_quality_70(self, photo_folder):
        r = exp.compress_folder(photo_folder)
        assert r["output_dir"] == photo_folder + "-squoosh-q70"
        assert r["options"]["quality"] == 70
        names = sorted(os.path.basename(d["output"]) for d in r["processed"])
        assert names == ["big.jpg", "grad.jpg"]          # top level only, txt ignored
        assert [os.path.basename(f["input"]) for f in r["failed"]] == ["broken.jpg"]
        for d in r["processed"]:
            exp.verify_output(d["output"], "mozjpeg")
        big = next(d for d in r["processed"] if d["output"].endswith("big.jpg"))
        assert big["out_bytes"] < big["in_bytes"] * 0.1
        show("folder", r["output_dir"])

    def test_quality_changes_size(self, photo_folder, tmp_path):
        a = exp.compress_folder(photo_folder, str(tmp_path / "q30"), quality=30)
        b = exp.compress_folder(photo_folder, str(tmp_path / "q90"), quality=90)
        assert a["total_out"] < b["total_out"]

    def test_recursive_mirrors_tree(self, photo_folder, tmp_path):
        out = str(tmp_path / "out")
        r = exp.compress_folder(photo_folder, out, encoder="webp", recursive=True, width=200)
        assert os.path.isfile(os.path.join(out, "sub", "red.webp"))
        assert backend.probe(os.path.join(out, "big.webp"))["width"] == 200
        assert len(r["processed"]) == 3

    def test_skip_existing_then_overwrite(self, photo_folder, tmp_path):
        out = str(tmp_path / "o")
        exp.compress_folder(photo_folder, out)
        again = exp.compress_folder(photo_folder, out)
        assert not again["processed"] and len(again["skipped"]) == 2
        assert len(exp.compress_folder(photo_folder, out, overwrite=True)["processed"]) == 2

    def test_lossless_ignores_quality(self, photo_folder, tmp_path):
        r = exp.compress_folder(photo_folder, str(tmp_path / "png"), encoder="oxipng")
        assert "quality" not in r["options"] and len(r["processed"]) == 2


# ---------------------------------------------------------------- installed CLI via subprocess
def _resolve_cli(name):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-squoosh")

    def _run(self, args, check=True):
        return subprocess.run(self.CLI_BASE + args, capture_output=True, text=True, check=check)

    def _json(self, args):
        return json.loads(self._run(["--json"] + args).stdout)

    def test_help(self):
        out = self._run(["--help"]).stdout
        for group in ("project", "source", "edit", "encoder", "export", "preview", "batch"):
            assert group in out

    def test_version(self):
        assert "2.0.0" in self._run(["--version"]).stdout

    def test_encoder_list_json(self):
        names = {e["name"] for e in self._json(["encoder", "list"])["encoders"]}
        assert names == set(codecs.ENCODERS)

    def test_encoder_options_json(self):
        d = self._json(["encoder", "options", "jxl"])
        assert d["defaults"]["effort"] == 7 and d["ranges"]["effort"] == [1, 9]

    def test_doctor(self):
        assert self._json(["doctor"])["ok"] is True

    def test_full_agent_workflow(self, tmp_path):
        pj, out = str(tmp_path / "p.json"), str(tmp_path / "out.avif")
        self._run(["--project", pj, "project", "new", "-n", "agent"])
        self._run(["--project", pj, "source", "set", EXAMPLE])
        self._run(["--project", pj, "edit", "resize", "-w", "500"])
        self._run(["--project", pj, "encoder", "set", "avif", "quality=40", "speed=8"])
        r = self._json(["--project", pj, "export", out])
        assert r["format"] == "avif" and r["width"] == 500 and os.path.getsize(out) == r["out_bytes"]
        info = self._json(["--project", pj, "project", "info"])
        assert info["encoder_options"] == {"quality": 40, "speed": 8} and info["exports"] == 1
        m = self._json(["--project", pj, "preview", "capture"])
        assert os.path.isfile(m["_manifest_path"])
        assert self._json(["--project", pj, "preview", "latest"])["_bundle_dir"] == m["_bundle_dir"]
        show("cli avif", out)

    def test_dry_run_does_not_save(self, tmp_path):
        pj = str(tmp_path / "p.json")
        self._run(["--project", pj, "project", "new"])
        self._run(["--dry-run", "--project", pj, "edit", "rotate", "90"])
        assert json.load(open(pj))["preprocess"]["rotate"] == 0
        self._run(["--project", pj, "edit", "rotate", "90"])
        assert json.load(open(pj))["preprocess"]["rotate"] == 90

    def test_error_json_nonzero(self, tmp_path):
        pj = str(tmp_path / "p.json")
        self._run(["--project", pj, "project", "new"])
        r = self._run(["--json", "--project", pj, "encoder", "option", "quality=999"], check=False)
        assert r.returncode == 1 and "between 0 and 100" in json.loads(r.stdout)["error"]
        assert json.load(open(pj))["encoder"]["options"] == {}

    def test_export_without_source(self, tmp_path):
        pj = str(tmp_path / "p.json")
        self._run(["--project", pj, "project", "new"])
        r = self._run(["--project", pj, "export"], check=False)
        assert r.returncode == 1 and "No source" in r.stderr

    def test_compress_oneshot(self, tmp_path):
        out = str(tmp_path / "c.jpg")
        r = self._json(["compress", EXAMPLE, "-o", out, "-q", "50", "-w", "300", "--rotate", "90"])
        assert (r["width"], r["height"], r["format"]) == (300, round(EW * 300 / EH), "jpeg")

    def test_compare_and_batch(self, tmp_path):
        r = self._json(["compare", "-i", EXAMPLE, "-d", str(tmp_path / "cmp"), "-e", "webp,qoi"])
        assert [x["encoder"] for x in r["results"]] == ["webp", "qoi"]
        pj = str(tmp_path / "b.json")
        self._run(["--project", pj, "project", "new", "-e", "webp", "-s", EXAMPLE])
        self._run(["--project", pj, "edit", "resize", "-w", "100"])
        b = self._json(["--project", pj, "batch", os.path.join(ROOT, "codecs", "*.png"),
                        "-d", str(tmp_path / "out")])
        assert len(b["processed"]) >= 2 and not b["failed"]

    def test_undo_across_repl(self, tmp_path):
        pj = str(tmp_path / "r.json")
        self._run(["--project", pj, "project", "new", "-n", "repl"])
        script = "edit rotate 180\nedit rotate 90\nsession undo\nproject save\nquit\n"
        r = subprocess.run(self.CLI_BASE + ["--project", pj], input=script,
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert json.load(open(pj))["preprocess"]["rotate"] == 180

    def test_folder_command(self, photo_folder):
        r = self._json(["folder", photo_folder])
        assert r["output_dir"] == photo_folder + "-squoosh-q70" and len(r["processed"]) == 2
        h = self._run(["folder", photo_folder, "-q", "50", "-o", photo_folder + "-50", "-r"]).stdout
        assert "3 compressed" in h and os.path.isfile(photo_folder + "-50/sub/red.jpg")
        bad = self._run(["--json", "folder", photo_folder, "-q", "150"], check=False)
        assert bad.returncode == 1 and "between 0 and 100" in json.loads(bad.stdout)["error"]

    def test_decode_and_probe(self, tmp_path):
        avif = str(tmp_path / "x.avif")
        self._run(["compress", EXAMPLE, "-e", "avif", "-w", "64", "-o", avif])
        png = str(tmp_path / "x.png")
        d = self._json(["decode", avif, png])
        assert d["source_format"] == "avif" and read_png(png)[:2] == (64, scaled(64))
        assert self._json(["probe", avif])["format"] == "avif"
