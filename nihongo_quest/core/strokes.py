"""Stroke geometry: SVG path parsing, sampling, and judging a hand-drawn stroke.

KanjiVG stores each stroke as SVG path data in a 109 x 109 box. For both
animation and handwriting checks a stroke is reduced to a polyline of evenly
spaced points. Pure Python - the widgets convert to Qt types.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

BOX = 109.0
Point = tuple[float, float]

_TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtZz])|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "Z": 0}


def parse_path(d: str) -> list[tuple]:
    """SVG path data -> absolute segments: ('M', x, y), ('L', x, y), ('C', x1, y1, x2, y2, x, y)."""
    tokens = [(m.group(1), m.group(2)) for m in _TOKEN.finditer(d)]
    segs: list[tuple] = []
    i = 0
    cmd = ""
    x = y = 0.0
    start = (0.0, 0.0)
    last_ctrl: Point | None = None      # reflected for S / T
    last_kind = ""
    while i < len(tokens):
        letter, number = tokens[i]
        if letter:
            cmd = letter
            i += 1
            if cmd in "Zz":
                segs.append(("L", start[0], start[1]))
                x, y = start
                last_kind = "Z"
                continue
        elif not cmd:
            raise ValueError(f"path data does not start with a command: {d[:30]!r}")
        need = _ARGS[cmd.upper()]
        vals = []
        for _ in range(need):
            if i >= len(tokens) or tokens[i][1] is None:
                raise ValueError(f"path data ends mid-command: {d[:40]!r}")
            vals.append(float(tokens[i][1]))
            i += 1
        rel = cmd.islower()
        up = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if up == "M":
            x, y = vals[0] + ox, vals[1] + oy
            start = (x, y)
            segs.append(("M", x, y))
            cmd = "l" if rel else "L"        # further pairs are implicit line-tos
        elif up == "L":
            x, y = vals[0] + ox, vals[1] + oy
            segs.append(("L", x, y))
        elif up == "H":
            x = vals[0] + ox
            segs.append(("L", x, y))
        elif up == "V":
            y = vals[0] + oy
            segs.append(("L", x, y))
        elif up == "C":
            x1, y1, x2, y2, ex, ey = (vals[0] + ox, vals[1] + oy, vals[2] + ox, vals[3] + oy, vals[4] + ox, vals[5] + oy)
            segs.append(("C", x1, y1, x2, y2, ex, ey))
            last_ctrl = (x2, y2)
            x, y = ex, ey
        elif up == "S":
            if last_kind in ("C", "S") and last_ctrl is not None:
                x1, y1 = 2 * x - last_ctrl[0], 2 * y - last_ctrl[1]
            else:
                x1, y1 = x, y
            x2, y2, ex, ey = vals[0] + ox, vals[1] + oy, vals[2] + ox, vals[3] + oy
            segs.append(("C", x1, y1, x2, y2, ex, ey))
            last_ctrl = (x2, y2)
            x, y = ex, ey
        elif up in ("Q", "T"):
            if up == "Q":
                qx, qy, ex, ey = vals[0] + ox, vals[1] + oy, vals[2] + ox, vals[3] + oy
            else:
                if last_kind in ("Q", "T") and last_ctrl is not None:
                    qx, qy = 2 * x - last_ctrl[0], 2 * y - last_ctrl[1]
                else:
                    qx, qy = x, y
                ex, ey = vals[0] + ox, vals[1] + oy
            # raise the quadratic to a cubic
            segs.append(("C", x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y),
                         ex + 2 / 3 * (qx - ex), ey + 2 / 3 * (qy - ey), ex, ey))
            last_ctrl = (qx, qy)
            x, y = ex, ey
        last_kind = up
    return segs


def flatten(d: str, steps: int = 14) -> list[Point]:
    """Polyline approximation of a path (curves cut into ``steps`` pieces)."""
    pts: list[Point] = []
    x = y = 0.0
    for seg in parse_path(d):
        if seg[0] in ("M", "L"):
            x, y = seg[1], seg[2]
            pts.append((x, y))
        else:
            _, x1, y1, x2, y2, ex, ey = seg
            for k in range(1, steps + 1):
                t = k / steps
                u = 1 - t
                pts.append((u ** 3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * ex,
                            u ** 3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * ey))
            x, y = ex, ey
    return pts


def length(pts: list[Point]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def resample(pts: list[Point], n: int) -> list[Point]:
    """``n`` points evenly spaced along a polyline (first and last preserved)."""
    if not pts:
        return []
    if len(pts) == 1 or n < 2:
        return [pts[0]] * max(n, 1)
    total = length(pts)
    if total <= 1e-9:
        return [pts[0]] * n
    step = total / (n - 1)
    out = [pts[0]]
    acc = 0.0
    target = step
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.dist(a, b)
        while seg > 0 and acc + seg >= target - 1e-9 and len(out) < n - 1:
            t = (target - acc) / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            target += step
        acc += seg
    out.append(pts[-1])
    while len(out) < n:
        out.insert(-1, pts[-1])
    return out


@lru_cache(maxsize=4096)
def stroke_points(d: str, n: int = 32) -> tuple[Point, ...]:
    """A stroke as ``n`` evenly spaced points, cached per path string."""
    return tuple(resample(flatten(d), n))


@dataclass(frozen=True)
class Judgement:
    ok: bool
    reason: str = ""          # '', 'short', 'backwards', 'elsewhere', 'shape'
    error: float = 0.0        # mean distance to the model stroke, in box units


def judge_stroke(drawn: list[Point], target: list[Point], box: float = BOX) -> Judgement:
    """Does a drawn stroke match the model stroke?

    Both are polylines in the same coordinate space. The test is deliberately
    forgiving - a mouse is a clumsy brush - and checks position, direction and
    rough shape: where the stroke starts and ends, and the mean distance
    between corresponding points along the two lines.
    """
    n = 16
    if len(drawn) < 2:
        return Judgement(False, "short")
    drawn_len, target_len = length(drawn), length(target)
    dot = target_len < box * 0.14                      # dots and ticks: only position matters much
    if drawn_len < (box * 0.012 if dot else max(box * 0.05, target_len * 0.3)):
        return Judgement(False, "short")
    a, b = resample(drawn, n), resample(target, n)
    mean = sum(math.dist(p, q) for p, q in zip(a, b)) / n
    mean_rev = sum(math.dist(p, q) for p, q in zip(reversed(a), b)) / n
    end_tol = box * (0.22 if dot else 0.20) + target_len * 0.10
    mean_tol = box * (0.16 if dot else 0.13) + target_len * 0.05
    start_ok = math.dist(a[0], b[0]) <= end_tol
    end_ok = math.dist(a[-1], b[-1]) <= end_tol
    too_long = drawn_len > target_len * (4.0 if dot else 2.2) + box * 0.08
    if start_ok and end_ok and mean <= mean_tol and not too_long:
        return Judgement(True, "", mean)
    if not dot and mean_rev <= mean_tol and mean_rev < mean * 0.6 \
            and math.dist(a[-1], b[0]) <= end_tol and math.dist(a[0], b[-1]) <= end_tol:
        return Judgement(False, "backwards", mean_rev)
    if mean > mean_tol * 1.8 and not (start_ok or end_ok):
        return Judgement(False, "elsewhere", mean)
    return Judgement(False, "shape", mean)


def best_match(drawn: list[Point], targets: list[list[Point]]) -> int | None:
    """Index of the model stroke the drawing matches, if any (used to notice out-of-order strokes)."""
    best, best_err = None, 1e9
    for i, t in enumerate(targets):
        j = judge_stroke(drawn, t)
        if j.ok and j.error < best_err:
            best, best_err = i, j.error
    return best
