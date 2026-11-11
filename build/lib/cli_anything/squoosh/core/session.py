"""Stateful session: the open project, undo/redo history, locked saves."""

import json
import os
from copy import deepcopy

from cli_anything.squoosh.core import project as proj

MAX_HISTORY = 100


def _locked_save_json(path, data, **dump_kwargs):
    """Write JSON under an exclusive lock; truncate only once the lock is held."""
    try:
        f = open(path, "r+")
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        f = open(path, "w")
    with f:
        locked = False
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, **dump_kwargs)
            f.flush()
        finally:
            if locked:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class Session:
    def __init__(self):
        self.project = None
        self.path = None
        self.modified = False
        self._undo = []
        self._redo = []

    # ---- lifecycle ----
    def new(self, name="untitled", encoder="mozjpeg", path=None):
        self.project = proj.new_project(name, encoder)
        self.path = os.path.abspath(path) if path else None
        self.modified = True
        self._undo.clear()
        self._redo.clear()
        return self.project

    def open(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Project file not found: {path}")
        with open(path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Project file is not valid JSON: {e}")
        self.project = proj.validate(data)
        self.path = path
        self.modified = False
        self._undo.clear()
        self._redo.clear()
        return self.project

    def save(self, path=None):
        self.require()
        path = os.path.abspath(path) if path else self.path
        if not path:
            raise ValueError("No save path: pass a path or open the project from a file")
        _locked_save_json(path, self.project, indent=2)
        self.path = path
        self.modified = False
        return path

    def require(self):
        if self.project is None:
            raise RuntimeError("No project open. Use 'project new' or 'project open' first.")
        return self.project

    # ---- mutation with history ----
    def mutate(self, fn, *args, **kwargs):
        """Apply fn(project, ...) with an undo snapshot; restore on failure."""
        self.require()
        snapshot = deepcopy(self.project)
        try:
            result = fn(self.project, *args, **kwargs)
        except Exception:
            self.project = snapshot
            raise
        self._undo.append(snapshot)
        del self._undo[:-MAX_HISTORY]
        self._redo.clear()
        self.modified = True
        return result

    def undo(self):
        self.require()
        if not self._undo:
            raise RuntimeError("Nothing to undo")
        self._redo.append(deepcopy(self.project))
        self.project = self._undo.pop()
        self.modified = True
        return self.project

    def redo(self):
        self.require()
        if not self._redo:
            raise RuntimeError("Nothing to redo")
        self._undo.append(deepcopy(self.project))
        self.project = self._redo.pop()
        self.modified = True
        return self.project

    def status(self):
        return {
            "open": self.project is not None,
            "name": self.project["name"] if self.project else None,
            "path": self.path,
            "modified": self.modified,
            "undo_depth": len(self._undo),
            "redo_depth": len(self._redo),
        }
