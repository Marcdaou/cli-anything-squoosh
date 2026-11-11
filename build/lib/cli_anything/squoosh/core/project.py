"""Squoosh project model.

Squoosh's GUI holds its state in memory: one source image, a preprocessor
(rotate), processors (resize, quantize) and an encoder with options. A project
file captures exactly that state as JSON (*.squoosh.json) so it can be edited
step by step and rendered later.
"""

import os
from copy import deepcopy
from datetime import datetime, timezone

from cli_anything.squoosh.core import codecs

PROJECT_VERSION = 1


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_project(name="untitled", encoder="mozjpeg"):
    codecs.get_encoder(encoder)
    return {
        "format": "cli-anything-squoosh",
        "version": PROJECT_VERSION,
        "name": name,
        "created": _now(),
        "modified": _now(),
        "source": None,
        "preprocess": {"rotate": 0},
        "resize": {"enabled": False, "width": None, "height": None, "method": "lanczos3",
                   "fitMethod": "stretch", "premultiply": True, "linearRGB": True},
        "quantize": {"enabled": False, "zx": 0, "maxNumColors": 256, "dither": 1.0},
        "encoder": {"name": encoder, "options": {}},
        "exports": [],
    }


def validate(project):
    if not isinstance(project, dict) or project.get("format") != "cli-anything-squoosh":
        raise ValueError("Not a cli-anything-squoosh project file")
    for key in ("preprocess", "resize", "quantize", "encoder"):
        if key not in project:
            raise ValueError(f"Project is missing '{key}'")
    codecs.get_encoder(project["encoder"]["name"])
    return project


def touch(project):
    project["modified"] = _now()
    return project


def set_source(project, path, probe=None):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Source image not found: {path}")
    project["source"] = {"path": path, "bytes": os.path.getsize(path)}
    if probe:
        project["source"].update({k: probe[k] for k in ("format", "width", "height") if k in probe})
    return touch(project)


def set_rotate(project, degrees):
    degrees = int(degrees) % 360
    if degrees not in codecs.ROTATIONS:
        raise ValueError(f"Rotation must be one of {codecs.ROTATIONS}, got {degrees}")
    project["preprocess"]["rotate"] = degrees
    return touch(project)


def set_resize(project, width=None, height=None, method=None, fit=None,
               premultiply=None, linear_rgb=None):
    r = project["resize"]
    if width is None and height is None and r["width"] is None and r["height"] is None:
        raise ValueError("Give --width and/or --height")
    for v, name in ((width, "width"), (height, "height")):
        if v is not None and int(v) < 1:
            raise ValueError(f"{name} must be >= 1")
    if method is not None and method not in codecs.RESIZE_METHODS:
        raise ValueError(f"Resize method must be one of {codecs.RESIZE_METHODS}")
    if fit is not None and fit not in codecs.FIT_METHODS:
        raise ValueError(f"Fit method must be one of {codecs.FIT_METHODS}")
    if width is not None:
        r["width"] = int(width)
    if height is not None:
        r["height"] = int(height)
    if method is not None:
        r["method"] = method
    if fit is not None:
        r["fitMethod"] = fit
    if premultiply is not None:
        r["premultiply"] = bool(premultiply)
    if linear_rgb is not None:
        r["linearRGB"] = bool(linear_rgb)
    r["enabled"] = True
    return touch(project)


def disable(project, step):
    if step not in ("resize", "quantize"):
        raise ValueError("Step must be 'resize' or 'quantize'")
    project[step]["enabled"] = False
    return touch(project)


def set_quantize(project, colors=None, dither=None, zx=None):
    q = project["quantize"]
    if colors is not None:
        if not 2 <= int(colors) <= 256:
            raise ValueError("colors must be between 2 and 256")
        q["maxNumColors"] = int(colors)
    if dither is not None:
        if not 0.0 <= float(dither) <= 1.0:
            raise ValueError("dither must be between 0 and 1")
        q["dither"] = float(dither)
    if zx is not None:
        q["zx"] = 1 if zx else 0
    q["enabled"] = True
    return touch(project)


def set_encoder(project, name, options=None, reset=False):
    codecs.get_encoder(name)
    enc = project["encoder"]
    if name != enc["name"] or reset:
        enc["options"] = {}
    enc["name"] = name
    if options:
        enc["options"].update(codecs.parse_option_pairs(name, options)
                              if isinstance(options, (list, tuple)) else
                              {k: codecs.coerce_option(name, k, v) for k, v in options.items()})
    return touch(project)


def target_size(project):
    """Output dimensions after rotate + resize, or None if the source size is unknown."""
    src = project.get("source") or {}
    w, h = src.get("width"), src.get("height")
    if w is None or h is None:
        return None
    if project["preprocess"]["rotate"] % 180:
        w, h = h, w
    r = project["resize"]
    if r["enabled"]:
        rw, rh = r["width"], r["height"]
        if rw and not rh:
            rh = max(1, round(h * rw / w))
        elif rh and not rw:
            rw = max(1, round(w * rh / h))
        w, h = rw, rh
    return w, h


def pipeline_steps(project):
    """The ordered step list sent to the Squoosh bridge."""
    steps = []
    if project["preprocess"]["rotate"]:
        steps.append({"type": "rotate", "options": {"rotate": project["preprocess"]["rotate"]}})
    if project["resize"]["enabled"]:
        size = target_size(project)
        if size is None:
            raise ValueError("Resize needs the source size; set a source first")
        r = project["resize"]
        steps.append({"type": "resize", "options": {
            "width": size[0], "height": size[1], "method": r["method"],
            "fitMethod": r["fitMethod"], "premultiply": r["premultiply"],
            "linearRGB": r["linearRGB"]}})
    if project["quantize"]["enabled"]:
        q = project["quantize"]
        steps.append({"type": "quantize", "options": {
            "zx": q["zx"], "maxNumColors": q["maxNumColors"], "dither": q["dither"]}})
    return steps


def info(project, path=None):
    enc = project["encoder"]
    return {
        "name": project["name"],
        "path": path,
        "source": deepcopy(project["source"]),
        "rotate": project["preprocess"]["rotate"],
        "resize": deepcopy(project["resize"]) if project["resize"]["enabled"] else None,
        "quantize": deepcopy(project["quantize"]) if project["quantize"]["enabled"] else None,
        "encoder": enc["name"],
        "encoder_options": enc["options"],
        "output_size": target_size(project),
        "exports": len(project.get("exports", [])),
        "modified": project.get("modified"),
    }
