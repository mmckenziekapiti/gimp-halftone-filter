"""Amplitude-modulated (AM) halftone screening for single-colour letterpress plates.

This module has no GIMP dependency so it can be tested and used on its own.
It takes an 8-bit greyscale array that has already been resampled to the
output (device) resolution and returns a 1-bit plate image.

Pipeline, per pixel:

1. Convert grey level to ink coverage (0 = paper, 1 = solid ink).
2. Pre-compensate for press dot gain so the *printed* tone matches the
   original rather than the plate tone.
3. Clamp to the printable range: highlight dots smaller than the minimum
   dot drop out (or are held), shadow holes smaller than the minimum hole
   fill in (or are held open).
4. Compare against a threshold derived from a spot function laid over a
   rotated screen grid. The threshold is the *area rank* of the spot value
   inside one cell, so a 30% tone covers 30% of each cell whatever the dot
   shape is.
"""

import math

import numpy as np

DOT_SHAPES = ("round", "euclidean", "ellipse", "square", "diamond", "line")

# Side of the reference pixel patch used to rank spot values.
_CDF_SAMPLES = 1024


def _spot(shape, x, y):
    """Spot function on cell coordinates x, y in [-1, 1).

    Smaller values ink first, so dots grow from the cell centre outward.
    A small radial term breaks ties in shapes with flat regions (square,
    diamond, line) so growth stays centred and stable.
    """
    r2 = x * x + y * y
    if shape == "round":
        return r2
    if shape == "euclidean":
        # Round dots in the highlights, a checkerboard at 50%, round holes
        # in the shadows.
        ax, ay = np.abs(x), np.abs(y)
        inner = ax + ay <= 1.0
        outer = 2.0 - ((1.0 - ax) ** 2 + (1.0 - ay) ** 2)
        return np.where(inner, r2, outer)
    if shape == "ellipse":
        # Elliptical ("chain") dot: joins along one axis first, which
        # softens the tone jump where dots meet.
        return x * x + 1.8 * y * y + 1e-4 * r2
    if shape == "square":
        return np.maximum(np.abs(x), np.abs(y)) + 1e-4 * r2
    if shape == "diamond":
        return np.abs(x) + np.abs(y) + 1e-4 * r2
    if shape == "line":
        return np.abs(y) + 1e-4 * np.abs(x)
    raise ValueError("unknown dot shape: %r" % (shape,))


def _cell_coords(xs, ys, ca, sa):
    """Position of device pixels inside their screen cell, in [-1, 1)."""
    u = xs * ca + ys * sa
    v = ys * ca - xs * sa
    return (u - np.floor(u)) * 2.0 - 1.0, (v - np.floor(v)) * 2.0 - 1.0


def _spot_key(shape, x, y):
    """Spot value plus a tiny position-dependent term that breaks ties.

    Without it, every pixel on a symmetric ring flips at the same grey
    level, which makes tones jump in big steps when the screen lines up
    with the pixel grid (e.g. 0 degrees at a whole-number cell size).
    """
    noise = np.sin(x * 12.9898 + y * 78.233) * 43758.5453
    return _spot(shape, x, y) + 1e-7 * (noise - np.floor(noise))


def _spot_cdf(shape, ca, sa):
    """Sorted spot keys of the device pixels in a reference patch.

    Ranking against the pixels the screen actually lands on (rather than an
    ideal continuous cell) keeps tone values exact when the cell is only a
    few pixels across or aligned to the pixel grid.
    """
    c = np.arange(_CDF_SAMPLES, dtype=np.float64) + 0.5
    fu, fv = _cell_coords(c[None, :], c[:, None], ca, sa)
    return np.sort(_spot_key(shape, fu, fv).ravel())


def compensate_dot_gain(coverage, gain50):
    """Invert a parabolic dot gain model.

    The press is modelled as printed = c + gain50 * 4c(1 - c), i.e. a 50%
    plate dot prints as 50% + gain50. We solve for the plate coverage that
    prints as the requested coverage.
    """
    if gain50 <= 0.0:
        return coverage
    g = min(gain50, 0.24)
    b = 1.0 + 4.0 * g
    disc = np.maximum(b * b - 16.0 * g * coverage, 0.0)
    return (b - np.sqrt(disc)) / (8.0 * g)


def tone_curve(coverage, gain50=0.0, min_dot=0.0, max_dot=1.0, hold_extremes=False):
    """Apply dot gain compensation and printable-range limits to coverage."""
    c = compensate_dot_gain(np.asarray(coverage, dtype=np.float64), gain50)
    if min_dot > 0.0:
        if hold_extremes:
            # Keep every non-white tone as at least the minimum dot.
            c = np.where((c > 0.0) & (c < min_dot), min_dot, c)
        else:
            # Below half the minimum dot, drop to clean paper.
            c = np.where(c < min_dot * 0.5, 0.0, np.maximum(c, min_dot))
    if max_dot < 1.0:
        if hold_extremes:
            c = np.where((c < 1.0) & (c > max_dot), max_dot, c)
        else:
            c = np.where(c > (1.0 + max_dot) * 0.5, 1.0, np.minimum(c, max_dot))
    return c


def halftone(
    grey,
    lpi=85.0,
    dpi=1200.0,
    angle=45.0,
    shape="round",
    gain50=0.0,
    min_dot=0.0,
    max_dot=1.0,
    hold_extremes=False,
    progress=None,
    strip_rows=256,
):
    """Screen an 8-bit greyscale image (0 = black) into a 1-bit plate.

    grey: 2-D uint8 array at the output resolution.
    lpi: screen frequency in lines per inch.
    dpi: output resolution in pixels per inch.
    angle: screen angle in degrees.
    gain50: press dot gain at 50% as a fraction (0.15 = 15 points).
    min_dot / max_dot: smallest printable dot and largest dot that still
        keeps a printable hole, as fractions of a cell.
    progress: optional callable taking a fraction 0..1.

    Returns a uint8 array: 0 where ink prints, 255 where the plate is clear.
    """
    grey = np.asarray(grey)
    if grey.ndim != 2:
        raise ValueError("expected a 2-D greyscale array")
    if lpi <= 0 or dpi <= 0:
        raise ValueError("lpi and dpi must be positive")
    if shape not in DOT_SHAPES:
        raise ValueError("unknown dot shape: %r" % (shape,))

    h, w = grey.shape
    period = dpi / lpi  # cell size in device pixels
    a = math.radians(angle)
    ca, sa = math.cos(a) / period, math.sin(a) / period

    # Map every grey level through the tone curve once.
    levels = np.arange(256, dtype=np.float64)
    coverage_lut = tone_curve(1.0 - levels / 255.0, gain50, min_dot, max_dot, hold_extremes)

    cdf = _spot_cdf(shape, ca, sa)
    n = float(cdf.size)

    out = np.empty((h, w), dtype=np.uint8)
    xs = np.arange(w, dtype=np.float64) + 0.5
    for y0 in range(0, h, strip_rows):
        y1 = min(h, y0 + strip_rows)
        ys = np.arange(y0, y1, dtype=np.float64)[:, None] + 0.5
        fu, fv = _cell_coords(xs, ys, ca, sa)
        # Threshold = fraction of the screen with a lower spot value.
        threshold = (np.searchsorted(cdf, _spot_key(shape, fu, fv)) + 0.5) / n
        coverage = coverage_lut[grey[y0:y1]]
        ink = (coverage > threshold) | (coverage >= 1.0)
        out[y0:y1] = np.where(ink, 0, 255)
        if progress is not None:
            progress(y1 / float(h))
    return out
