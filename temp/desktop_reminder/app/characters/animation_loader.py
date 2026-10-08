"""Builds Animation objects from manifest entries."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtGui import QMovie, QPixmap

from app.characters.animation import Animation, FrameAnimation


class AnimationLoadError(Exception):
    pass


def _load_pixmap(path: Path) -> QPixmap:
    pix = QPixmap(str(path))
    if pix.isNull():
        raise AnimationLoadError("cannot read image %s" % path)
    return pix


def _png_sequence(spec: Dict[str, Any], base: Path) -> Animation:
    if spec.get("files"):
        paths = [base / f for f in spec["files"]]
    else:
        paths = sorted(base.glob(spec.get("pattern", "*.png")))
    if not paths:
        raise AnimationLoadError("no frames match %r in %s" % (spec.get("pattern"), base))
    return FrameAnimation([_load_pixmap(p) for p in paths], spec.get("fps", 8), spec.get("loop", True))


def _movie(spec: Dict[str, Any], base: Path) -> Animation:
    path = base / spec["file"]
    movie = QMovie(str(path))
    if not movie.isValid():
        raise AnimationLoadError("cannot read animation %s" % path)
    frames: List[QPixmap] = []
    delays: List[int] = []
    limit = movie.frameCount() if movie.frameCount() > 0 else 300
    for i in range(limit):
        if not movie.jumpToFrame(i):
            break
        frames.append(QPixmap.fromImage(movie.currentImage()))
        delays.append(movie.nextFrameDelay() or 100)
    if not frames:
        raise AnimationLoadError("no frames decoded from %s" % path)
    fps = spec.get("fps") or 1000.0 / (sum(delays) / len(delays))
    return FrameAnimation(frames, fps, spec.get("loop", True))


def _spritesheet(spec: Dict[str, Any], base: Path) -> Animation:
    sheet = _load_pixmap(base / spec["file"])
    fw, fh = int(spec["frame_width"]), int(spec["frame_height"])
    if fw <= 0 or fh <= 0:
        raise AnimationLoadError("invalid sprite sheet frame size")
    cols, rows = sheet.width() // fw, sheet.height() // fh
    count = int(spec.get("count", cols * rows))
    frames = [sheet.copy((i % cols) * fw, (i // cols) * fh, fw, fh)
              for i in range(min(count, cols * rows))]
    if not frames:
        raise AnimationLoadError("sprite sheet %s is smaller than one frame" % spec["file"])
    return FrameAnimation(frames, spec.get("fps", 8), spec.get("loop", True))


_BUILDERS = {"png_sequence": _png_sequence, "gif": _movie, "webp": _movie,
             "spritesheet": _spritesheet}


def build_animation(spec: Dict[str, Any], base_dir: Path) -> Animation:
    kind = spec.get("type")
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise AnimationLoadError("unknown animation type %r" % (kind,))
    try:
        return builder(spec, base_dir)
    except AnimationLoadError:
        raise
    except Exception as exc:                       # KeyError, ValueError, OSError ...
        raise AnimationLoadError("bad animation spec %r: %r" % (spec, exc))
