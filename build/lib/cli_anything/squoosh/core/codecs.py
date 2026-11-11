"""Codec and processor registry, mirrored from Squoosh's src/features/*/shared/meta.ts.

Every encoder listed here is rendered by the real Squoosh WASM build through
utils/squoosh_bridge.mjs. Browser-only encoders (browserJPEG/PNG/GIF) need a
canvas and are not exposed.
"""

from copy import deepcopy

# name -> {label, extension, mime, defaults, ranges}
# ranges: option -> (min, max) for numeric options; bool options are typed by their default.
ENCODERS = {
    "mozjpeg": {
        "label": "MozJPEG", "extension": "jpg", "mime": "image/jpeg", "format": "jpeg",
        "defaults": {
            "quality": 75, "baseline": False, "arithmetic": False, "progressive": True,
            "optimize_coding": True, "smoothing": 0, "color_space": 3, "quant_table": 3,
            "trellis_multipass": False, "trellis_opt_zero": False, "trellis_opt_table": False,
            "trellis_loops": 1, "auto_subsample": True, "chroma_subsample": 2,
            "separate_chroma_quality": False, "chroma_quality": 75,
        },
        "ranges": {"quality": (0, 100), "smoothing": (0, 100), "color_space": (1, 3),
                   "quant_table": (0, 8), "trellis_loops": (1, 50), "chroma_subsample": (1, 4),
                   "chroma_quality": (0, 100)},
    },
    "webp": {
        "label": "WebP", "extension": "webp", "mime": "image/webp", "format": "webp",
        "defaults": {
            "quality": 75, "target_size": 0, "target_PSNR": 0, "method": 4, "sns_strength": 50,
            "filter_strength": 60, "filter_sharpness": 0, "filter_type": 1, "partitions": 0,
            "segments": 4, "pass": 1, "show_compressed": 0, "preprocessing": 0, "autofilter": 0,
            "partition_limit": 0, "alpha_compression": 1, "alpha_filtering": 1,
            "alpha_quality": 100, "lossless": 0, "exact": 0, "image_hint": 0,
            "emulate_jpeg_size": 0, "thread_level": 0, "low_memory": 0, "near_lossless": 100,
            "use_delta_palette": 0, "use_sharp_yuv": 0,
        },
        "ranges": {"quality": (0, 100), "method": (0, 6), "sns_strength": (0, 100),
                   "filter_strength": (0, 100), "filter_sharpness": (0, 7), "segments": (1, 4),
                   "pass": (1, 10), "alpha_quality": (0, 100), "lossless": (0, 1),
                   "exact": (0, 1), "near_lossless": (0, 100), "use_sharp_yuv": (0, 1),
                   "autofilter": (0, 1), "filter_type": (0, 1)},
    },
    "avif": {
        "label": "AVIF", "extension": "avif", "mime": "image/avif", "format": "avif",
        "defaults": {
            "quality": 50, "qualityAlpha": -1, "denoiseLevel": 0, "tileColsLog2": 0,
            "tileRowsLog2": 0, "speed": 6, "subsample": 1, "chromaDeltaQ": False,
            "sharpness": 0, "tune": 0,
            # The shipped avif_node_enc.wasm predates the enableSharpYUV rename.
            "enableSharpDownsampling": False,
        },
        "ranges": {"quality": (0, 100), "qualityAlpha": (-1, 100), "denoiseLevel": (0, 50),
                   "tileColsLog2": (0, 6), "tileRowsLog2": (0, 6), "speed": (0, 10),
                   "subsample": (0, 3), "sharpness": (0, 7), "tune": (0, 2)},
    },
    "jxl": {
        "label": "JPEG XL", "extension": "jxl", "mime": "image/jxl", "format": "jxl",
        "defaults": {
            "effort": 7, "quality": 75, "progressive": False, "epf": -1, "lossyPalette": False,
            "decodingSpeedTier": 0, "photonNoiseIso": 0, "lossyModular": False,
        },
        "ranges": {"effort": (1, 9), "quality": (0, 100), "epf": (-1, 3),
                   "decodingSpeedTier": (0, 4), "photonNoiseIso": (0, 50000)},
    },
    "wp2": {
        "label": "WebP v2", "extension": "wp2", "mime": "image/webp2", "format": "wp2",
        "defaults": {
            "quality": 75, "alpha_quality": 75, "effort": 5, "pass": 1, "sns": 50,
            "uv_mode": 3, "csp_type": 1, "error_diffusion": 0, "use_random_matrix": False,
        },
        "ranges": {"quality": (0, 100), "alpha_quality": (0, 100), "effort": (0, 9),
                   "pass": (1, 10), "sns": (0, 100), "uv_mode": (0, 3), "csp_type": (0, 3),
                   "error_diffusion": (0, 100)},
    },
    "oxipng": {
        "label": "OxiPNG", "extension": "png", "mime": "image/png", "format": "png",
        "defaults": {"level": 2, "interlace": False},
        "ranges": {"level": (0, 6)},
    },
    "qoi": {
        "label": "QOI", "extension": "qoi", "mime": "image/qoi", "format": "qoi",
        "defaults": {}, "ranges": {},
    },
    "png": {
        "label": "PNG (squoosh_png, unoptimised)", "extension": "png", "mime": "image/png",
        "format": "png", "defaults": {}, "ranges": {},
    },
}

DECODERS = ["png", "jpeg", "webp", "avif", "jxl", "wp2", "qoi"]
RESIZE_METHODS = ["triangle", "catrom", "mitchell", "lanczos3", "hqx"]
FIT_METHODS = ["stretch", "contain"]
ROTATIONS = [0, 90, 180, 270]
# Values the shipped WASM builds accept in the struct but cannot honour.
UNSUPPORTED = {
    ("avif", "enableSharpDownsampling", True):
        "the shipped avif_node_enc.wasm was built without libsharpyuv; leave it false",
}
BROWSER_ONLY = ["browserJPEG", "browserPNG", "browserGIF", "vector resize (SVG)"]


def list_encoders():
    return [{"name": n, "label": e["label"], "extension": e["extension"], "mime": e["mime"],
             "options": sorted(e["defaults"])} for n, e in ENCODERS.items()]


def get_encoder(name):
    if name not in ENCODERS:
        raise ValueError(f"Unknown encoder '{name}'. Choose from: {', '.join(ENCODERS)}")
    return ENCODERS[name]


def default_options(name):
    return deepcopy(get_encoder(name)["defaults"])


def _check_supported(encoder, key, value):
    why = UNSUPPORTED.get((encoder, key, value))
    if why:
        raise ValueError(f"{encoder} option {key}={str(value).lower()} is not supported: {why}")
    return value


def coerce_option(encoder, key, value):
    """Validate and type-convert one option value (strings accepted, as from the CLI)."""
    enc = get_encoder(encoder)
    if key not in enc["defaults"]:
        opts = ", ".join(sorted(enc["defaults"])) or "(none)"
        raise ValueError(f"Encoder '{encoder}' has no option '{key}'. Options: {opts}")
    default = enc["defaults"][key]
    if isinstance(default, bool):
        if isinstance(value, bool):
            return _check_supported(encoder, key, value)
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return _check_supported(encoder, key, True)
        if s in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"Option '{key}' expects true/false, got '{value}'")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Option '{key}' expects a number, got '{value}'")
    num = int(num) if isinstance(default, int) and num == int(num) else num
    if isinstance(default, int) and not isinstance(num, int):
        raise ValueError(f"Option '{key}' expects an integer, got '{value}'")
    lo_hi = enc["ranges"].get(key)
    if lo_hi and not (lo_hi[0] <= num <= lo_hi[1]):
        raise ValueError(f"Option '{key}' must be between {lo_hi[0]} and {lo_hi[1]}, got {num}")
    return num


def merge_options(encoder, overrides=None):
    """Defaults + validated overrides: the full struct Squoosh's encoder expects."""
    opts = default_options(encoder)
    for k, v in (overrides or {}).items():
        opts[k] = coerce_option(encoder, k, v)
    return opts


def parse_option_pairs(encoder, pairs):
    """Parse ['quality=80', 'progressive=false'] into a validated dict."""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise ValueError(f"Expected key=value, got '{p}'")
        k, v = p.split("=", 1)
        out[k.strip()] = coerce_option(encoder, k.strip(), v.strip())
    return out
