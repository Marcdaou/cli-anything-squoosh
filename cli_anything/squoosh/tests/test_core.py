"""Unit tests: synthetic data only, no Node or WASM."""

import json
import os

import pytest

from cli_anything.squoosh.core import codecs
from cli_anything.squoosh.core import export as exp
from cli_anything.squoosh.core import preview as prev
from cli_anything.squoosh.core import project as proj
from cli_anything.squoosh.core.session import MAX_HISTORY, Session, _locked_save_json


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "fake.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    return str(p)


@pytest.fixture
def sized(img):
    p = proj.new_project("t")
    proj.set_source(p, img, {"format": "png", "width": 400, "height": 200})
    return p


# ---------------------------------------------------------------- codecs
class TestCodecs:
    def test_registry_complete(self):
        assert set(codecs.ENCODERS) == {"mozjpeg", "webp", "avif", "jxl", "wp2", "oxipng", "qoi", "png"}
        for e in codecs.ENCODERS.values():
            assert e["extension"] and e["mime"].startswith("image/") and e["format"] in exp.MAGIC

    def test_merge_full_struct(self):
        o = codecs.merge_options("webp", {"quality": 50})
        assert o["quality"] == 50 and len(o) == len(codecs.ENCODERS["webp"]["defaults"])

    def test_defaults_are_copies(self):
        codecs.default_options("mozjpeg")["quality"] = 1
        assert codecs.ENCODERS["mozjpeg"]["defaults"]["quality"] == 75

    @pytest.mark.parametrize("v,exp_", [("true", True), ("0", False), ("on", True), ("No", False), (True, True)])
    def test_bool_coercion(self, v, exp_):
        assert codecs.coerce_option("mozjpeg", "progressive", v) is exp_

    def test_bool_bad(self):
        with pytest.raises(ValueError, match="true/false"):
            codecs.coerce_option("mozjpeg", "progressive", "maybe")

    def test_int_and_float(self):
        assert codecs.coerce_option("webp", "quality", "80") == 80
        assert codecs.coerce_option("webp", "quality", "80.0") == 80

    def test_int_rejects_fraction(self):
        with pytest.raises(ValueError, match="integer"):
            codecs.coerce_option("webp", "method", "2.5")

    def test_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            codecs.coerce_option("avif", "quality", 101)
        assert codecs.coerce_option("avif", "qualityAlpha", -1) == -1

    def test_unknown_option(self):
        with pytest.raises(ValueError, match="no option 'speed'"):
            codecs.coerce_option("mozjpeg", "speed", 1)

    def test_non_numeric(self):
        with pytest.raises(ValueError, match="number"):
            codecs.coerce_option("jxl", "effort", "fast")

    def test_pairs(self):
        assert codecs.parse_option_pairs("oxipng", ["level=4", "interlace=yes"]) == {"level": 4, "interlace": True}
        with pytest.raises(ValueError, match="key=value"):
            codecs.parse_option_pairs("oxipng", ["level"])

    def test_unknown_encoder(self):
        with pytest.raises(ValueError, match="Unknown encoder"):
            codecs.get_encoder("gif")

    def test_avif_matches_shipped_binary(self):
        d = codecs.ENCODERS["avif"]["defaults"]
        assert "enableSharpDownsampling" in d and "enableSharpYUV" not in d

    def test_unsupported_value_rejected(self):
        with pytest.raises(ValueError, match="not supported"):
            codecs.coerce_option("avif", "enableSharpDownsampling", "true")
        assert codecs.coerce_option("avif", "enableSharpDownsampling", "false") is False


# ---------------------------------------------------------------- project
class TestProject:
    def test_new_defaults(self):
        p = proj.new_project("x", "webp")
        assert p["encoder"] == {"name": "webp", "options": {}}
        assert not p["resize"]["enabled"] and p["preprocess"]["rotate"] == 0

    def test_new_bad_encoder(self):
        with pytest.raises(ValueError):
            proj.new_project("x", "bmp")

    def test_validate(self):
        with pytest.raises(ValueError, match="Not a"):
            proj.validate({"foo": 1})
        p = proj.new_project()
        del p["resize"]
        with pytest.raises(ValueError, match="missing 'resize'"):
            proj.validate(p)

    def test_source_missing(self):
        with pytest.raises(FileNotFoundError):
            proj.set_source(proj.new_project(), "/no/such.png")

    def test_source_probe(self, sized, img):
        assert sized["source"]["path"] == os.path.abspath(img)
        assert sized["source"]["width"] == 400

    @pytest.mark.parametrize("deg,want", [(-90, 270), (450, 90), (180, 180), (0, 0)])
    def test_rotate_normalise(self, deg, want):
        assert proj.set_rotate(proj.new_project(), deg)["preprocess"]["rotate"] == want

    def test_rotate_bad(self):
        with pytest.raises(ValueError):
            proj.set_rotate(proj.new_project(), 45)

    def test_resize_validation(self, sized):
        with pytest.raises(ValueError, match="width and/or"):
            proj.set_resize(proj.new_project())
        with pytest.raises(ValueError, match=">= 1"):
            proj.set_resize(sized, width=0)
        with pytest.raises(ValueError, match="method"):
            proj.set_resize(sized, width=10, method="bicubic")
        with pytest.raises(ValueError, match="Fit"):
            proj.set_resize(sized, width=10, fit="cover")

    def test_resize_aspect(self, sized):
        proj.set_resize(sized, width=100)
        assert proj.target_size(sized) == (100, 50)
        sized["resize"]["width"] = None
        proj.set_resize(sized, height=20)
        assert proj.target_size(sized) == (40, 20)

    def test_target_size_rotated(self, sized):
        proj.set_rotate(sized, 90)
        assert proj.target_size(sized) == (200, 400)
        proj.set_resize(sized, width=100)
        assert proj.target_size(sized) == (100, 200)

    def test_target_size_unknown(self):
        assert proj.target_size(proj.new_project()) is None

    def test_pipeline_order(self, sized):
        proj.set_quantize(sized, colors=16)
        proj.set_resize(sized, width=100)
        proj.set_rotate(sized, 180)
        assert [s["type"] for s in proj.pipeline_steps(sized)] == ["rotate", "resize", "quantize"]
        proj.disable(sized, "resize")
        assert [s["type"] for s in proj.pipeline_steps(sized)] == ["rotate", "quantize"]

    def test_disable_bad(self, sized):
        with pytest.raises(ValueError):
            proj.disable(sized, "rotate")

    def test_quantize_bounds(self, sized):
        with pytest.raises(ValueError):
            proj.set_quantize(sized, colors=1)
        with pytest.raises(ValueError):
            proj.set_quantize(sized, dither=1.5)
        q = proj.set_quantize(sized, colors=8, dither=0.5, zx=True)["quantize"]
        assert (q["maxNumColors"], q["dither"], q["zx"], q["enabled"]) == (8, 0.5, 1, True)

    def test_set_encoder_options(self, sized):
        proj.set_encoder(sized, "mozjpeg", ["quality=40"])
        proj.set_encoder(sized, "mozjpeg", {"progressive": "false"})
        assert sized["encoder"]["options"] == {"quality": 40, "progressive": False}
        proj.set_encoder(sized, "webp")
        assert sized["encoder"]["options"] == {}

    def test_set_encoder_reset(self, sized):
        proj.set_encoder(sized, "mozjpeg", ["quality=40"])
        proj.set_encoder(sized, "mozjpeg", reset=True)
        assert sized["encoder"]["options"] == {}

    def test_info(self, sized):
        i = proj.info(sized, "/x.json")
        assert i["output_size"] == (400, 200) and i["resize"] is None and i["path"] == "/x.json"


# ---------------------------------------------------------------- session
class TestSession:
    def test_require(self):
        with pytest.raises(RuntimeError, match="No project"):
            Session().require()

    def test_roundtrip(self, tmp_path):
        s = Session()
        s.new("rt", "avif", str(tmp_path / "p.json"))
        s.mutate(proj.set_rotate, 90)
        s.save()
        t = Session()
        t.open(str(tmp_path / "p.json"))
        assert t.project["preprocess"]["rotate"] == 90 and not t.modified

    def test_save_no_path(self):
        s = Session()
        s.new()
        with pytest.raises(ValueError, match="No save path"):
            s.save()

    def test_undo_redo(self):
        s = Session()
        s.new()
        s.mutate(proj.set_rotate, 90)
        s.mutate(proj.set_rotate, 180)
        s.undo()
        assert s.project["preprocess"]["rotate"] == 90
        s.redo()
        assert s.project["preprocess"]["rotate"] == 180

    def test_new_mutation_clears_redo(self):
        s = Session()
        s.new()
        s.mutate(proj.set_rotate, 90)
        s.undo()
        s.mutate(proj.set_rotate, 270)
        with pytest.raises(RuntimeError, match="redo"):
            s.redo()

    def test_failed_mutation_rolls_back(self):
        s = Session()
        s.new()
        with pytest.raises(ValueError):
            s.mutate(proj.set_rotate, 45)
        assert s.project["preprocess"]["rotate"] == 0 and s.status()["undo_depth"] == 0

    def test_nothing_to_undo(self):
        s = Session()
        s.new()
        with pytest.raises(RuntimeError, match="undo"):
            s.undo()

    def test_history_cap(self):
        s = Session()
        s.new()
        for i in range(MAX_HISTORY + 20):
            s.mutate(proj.set_rotate, 90 * (i % 4))
        assert s.status()["undo_depth"] == MAX_HISTORY

    def test_locked_save_truncates(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text(json.dumps({"x": "y" * 1000}))
        _locked_save_json(str(f), {"a": 1})
        assert json.loads(f.read_text()) == {"a": 1}

    def test_open_corrupt(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{nope")
        with pytest.raises(ValueError, match="not valid JSON"):
            Session().open(str(f))


# ---------------------------------------------------------------- export
HEADS = {
    "mozjpeg": b"\xff\xd8\xff\xe0", "oxipng": b"\x89PNG\r\n\x1a\n", "webp": b"RIFF\0\0\0\0WEBPVP8 ",
    "avif": b"\0\0\0\x1cftypavif", "jxl": b"\xff\x0a", "qoi": b"qoif", "wp2": b"\xf4\xff\x6f",
}


class TestExport:
    @pytest.mark.parametrize("enc", list(HEADS))
    def test_magic_ok(self, tmp_path, enc):
        f = tmp_path / "o"
        f.write_bytes(HEADS[enc] + b"\0" * 16)
        assert exp.verify_output(str(f), enc)["format"] == codecs.ENCODERS[enc]["format"]

    def test_magic_bad(self, tmp_path):
        f = tmp_path / "o"
        f.write_bytes(b"GIF89a" + b"\0" * 16)
        with pytest.raises(RuntimeError, match="magic"):
            exp.verify_output(str(f), "webp")

    def test_empty_and_missing(self, tmp_path):
        f = tmp_path / "o"
        f.write_bytes(b"")
        with pytest.raises(RuntimeError, match="empty"):
            exp.verify_output(str(f), "png")
        with pytest.raises(RuntimeError, match="no file"):
            exp.verify_output(str(tmp_path / "none"), "png")

    def test_default_output(self, sized, img):
        proj.set_encoder(sized, "avif")
        assert exp.default_output(sized) == os.path.join(os.path.dirname(img), "fake.squoosh.avif")

    def test_render_guards(self, sized, tmp_path):
        with pytest.raises(ValueError, match="No source"):
            exp.render(proj.new_project())
        out = tmp_path / "exists.jpg"
        out.write_bytes(b"x")
        with pytest.raises(FileExistsError):
            exp.render(sized, str(out))


# ---------------------------------------------------------------- preview
class TestPreview:
    def test_fingerprint(self, sized):
        a = prev.fingerprint(sized)
        assert a == prev.fingerprint(sized)
        proj.set_encoder(sized, "mozjpeg", ["quality=10"])
        assert a != prev.fingerprint(sized)

    def test_latest_none(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No previews"):
            prev.latest(root=str(tmp_path / "pv"))

    def test_building_cleans_up(self, tmp_path):
        d = tmp_path / "b"
        with pytest.raises(RuntimeError):
            with prev._building(str(d)):
                (d / "partial.png").write_bytes(b"x")
                raise RuntimeError("boom")
        assert not d.exists()


class TestFolderGuards:
    def test_not_a_folder(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Not a folder"):
            exp.compress_folder(str(tmp_path / "nope"))

    def test_no_images(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hi")
        with pytest.raises(ValueError, match="No images"):
            exp.compress_folder(str(tmp_path))

    def test_output_same_as_input(self, tmp_path):
        with pytest.raises(ValueError, match="must not be the input"):
            exp.compress_folder(str(tmp_path), str(tmp_path))

    def test_default_output_name(self, tmp_path):
        assert exp.default_folder_output(str(tmp_path / "pics") + "/", 70) == str(tmp_path / "pics-squoosh-q70")
