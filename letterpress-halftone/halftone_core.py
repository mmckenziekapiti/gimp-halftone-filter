"""Amplitude-modulated (AM) halftone screening for single-colour letterpress plates.

Pure Python with no GIMP or numpy dependency, so it runs inside the Python
that ships with GIMP on Windows. It does the per-cell maths only; the
per-pixel work is either done by GEGL (in the plug-in) or by numpy (in
halftone(), used by the CLI and tests).

How a pixel is decided:

1. Grey level -> ink coverage (0 = paper, 1 = solid), through a tone curve
   that pre-compensates dot gain and clamps to the printable dot range.
   This is a 256-entry lookup table, coverage_lut().
2. Each device pixel gets a threshold from a spot function laid over the
   screen grid. Thresholds are the *rank* of the spot value among the pixels
   of one cell, so a 30% tone inks 30% of every cell whatever the dot shape.
3. Ink prints where coverage > threshold.

The screen is a rational-tangent screen: one cell edge is a whole-number
pixel vector (a, b). That makes the threshold pattern repeat exactly, so
only one cell's worth of thresholds (a*a + b*b pixels) is ever computed and
every row of the plate is a shifted copy of one of a few base rows. The
cost is that the requested LPI and angle are rounded to the nearest
achievable pair; screen() reports what was used.
"""

import math

DOT_SHAPES = ("round", "euclidean", "ellipse", "square", "diamond", "line")


def _spot(shape, x, y):
    """Spot function on cell coordinates x, y in [-1, 1).

    Smaller values ink first, so dots grow from the cell centre outward.
    Small extra terms break ties in shapes with flat regions so growth stays
    centred.
    """
    r2 = x * x + y * y
    if shape == "round":
        return r2
    if shape == "euclidean":
        # Round dots in the highlights, a checkerboard at 50%, round holes
        # in the shadows.
        ax, ay = abs(x), abs(y)
        if ax + ay <= 1.0:
            return r2
        return 2.0 - ((1.0 - ax) ** 2 + (1.0 - ay) ** 2)
    if shape == "ellipse":
        # Elliptical ("chain") dot: joins along one axis first, which
        # softens the tone jump where dots meet.
        return x * x + 1.8 * y * y + 1e-4 * r2
    if shape == "square":
        return max(abs(x), abs(y)) + 1e-4 * r2
    if shape == "diamond":
        return abs(x) + abs(y) + 1e-4 * r2
    if shape == "line":
        return abs(y) + 1e-4 * abs(x)
    raise ValueError("unknown dot shape: %r" % (shape,))


def compensate_dot_gain(c, gain50):
    """Plate coverage that prints as coverage c.

    The press (or etch) is modelled as printed = c + gain50 * 4c(1 - c), so a
    50% plate dot prints as 50% + gain50. A negative gain50 models dot loss,
    such as undercutting when a metal plate is etched.
    """
    g = max(-0.24, min(gain50, 0.24))
    if abs(g) < 1e-9:
        return c
    b = 1.0 + 4.0 * g
    return (b - math.sqrt(max(b * b - 16.0 * g * c, 0.0))) / (8.0 * g)


def tone_curve(c, gain50=0.0, min_dot=0.0, max_dot=1.0, hold_extremes=False):
    """Apply dot gain compensation and printable-range limits to coverage c."""
    c = compensate_dot_gain(c, gain50)
    if min_dot > 0.0 and c < min_dot:
        if hold_extremes:
            c = min_dot if c > 0.0 else 0.0
        else:
            # Below half the minimum dot, drop to clean paper.
            c = 0.0 if c < min_dot * 0.5 else min_dot
    if max_dot < 1.0 and c > max_dot:
        if hold_extremes:
            c = max_dot if c < 1.0 else 1.0
        else:
            # Holes smaller than half the minimum hole fill in to solid.
            c = 1.0 if c > (1.0 + max_dot) * 0.5 else max_dot
    return c


def coverage_lut(gain50=0.0, min_dot=0.0, max_dot=1.0, hold_extremes=False):
    """bytes(256): grey level (0 = black) -> ink coverage in 1/255 steps."""
    out = bytearray(256)
    for g in range(256):
        c = tone_curve(1.0 - g / 255.0, gain50, min_dot, max_dot, hold_extremes)
        out[g] = int(round(min(max(c, 0.0), 1.0) * 255.0))
    return bytes(out)


# Text edges: a pixel is treated as an anti-aliased edge of black line art
# when, within the search radius, the darkest pixel is at least this dark
# (grey level, 0 = black; thin lines never quite reach 0 once blurred) and
# the tones span at least this much.
EDGE_DARK = 48
EDGE_CONTRAST = 128


def edge_radius(scale):
    """Search radius in output pixels for snap_edges(), after resampling by `scale`.

    Anti-aliasing plus the resampling filter blur an edge over about three
    source pixels, so look one and a half source pixels each way.
    """
    return max(2, int(math.ceil(1.5 * scale)))


def snap_edges(grey, radius):
    """Snap the grey fringe of black text and line art to its neighbours (numpy).

    Within `radius` of dark line art, a pixel darker than the midpoint of
    the darkest and lightest pixels nearby becomes solid black, and any
    other takes the lightest value nearby (paper, or the tone behind the
    text). Black text becomes solid with clean edges at the 50% line,
    instead of its fringe being screened into a ragged, eaten-into edge.
    Elsewhere, including the soft tones of a photo, nothing changes. The plug-in does the same with GEGL (gegl_screen).
    """
    import numpy as np

    grey = np.asarray(grey, dtype=np.uint8)
    h, w = grey.shape

    def square_filter(a, fn):
        # A square window is a row pass then a column pass.
        p = np.pad(a, ((0, 0), (radius, radius)), mode="edge")
        out = a.copy()
        for d in range(2 * radius + 1):
            fn(out, p[:, d:d + w], out=out)
        p = np.pad(out, ((radius, radius), (0, 0)), mode="edge")
        for d in range(2 * radius + 1):
            fn(out, p[d:d + h], out=out)
        return out

    lo = square_filter(grey, np.minimum)
    hi = square_filter(grey, np.maximum)
    g, lo, hi = grey.astype(np.int16), lo.astype(np.int16), hi.astype(np.int16)
    edge = (lo <= EDGE_DARK) & (hi - lo >= EDGE_CONTRAST)
    snapped = np.where(lo + hi - 2 * g > 0, 0, hi)
    return np.where(edge, snapped, g).astype(np.uint8)


def _ext_gcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x, y = _ext_gcd(b, a % b)
    return g, y, x - (a // b) * y


class Screen(object):
    """A rational-tangent halftone screen with its threshold pattern.

    Attributes:
        a, b: the cell edge as a whole-pixel vector.
        lpi, angle: the frequency and angle actually used.
        period: the repeat length of every row, in pixels.
        base_rows: list of `rows` bytes objects, each `period` long. Device
            row y = q * rows + r is base row r rotated left by q * shift.
        Each threshold byte T is in 0..254; a pixel inks when coverage > T.
    """

    def __init__(self, lpi, dpi, angle, shape):
        if lpi <= 0 or dpi <= 0:
            raise ValueError("lpi and dpi must be positive")
        if shape not in DOT_SHAPES:
            raise ValueError("unknown dot shape: %r" % (shape,))
        cell = dpi / float(lpi)
        rad = math.radians(angle)
        a = int(round(cell * math.cos(rad)))
        b = int(round(cell * math.sin(rad)))
        if a == 0 and b == 0:
            a = 1
        # Keep a > 0 so the maths below stays in one quadrant; a cell edge
        # rotated by 90 degrees gives the same screen.
        while a <= 0:
            a, b = b, -a
        n = a * a + b * b
        g, m, k = _ext_gcd(a, abs(b))  # m*a + k*|b| = g
        self.a, self.b = a, b
        self.rows = g
        self.period = n // g
        # Find the lattice vector (dx, g) = c1*(a, b) + c2*(-b, a). The
        # pattern repeats along it, so row y + g is row y moved right by dx.
        c1, c2 = (k, m) if b >= 0 else (-k, m)
        dx = c1 * a - c2 * b
        self.shift = (-dx) % self.period
        self.lpi = dpi / math.sqrt(n)
        self.angle = math.degrees(math.atan2(b, a))

        ca, sa = a / float(n), b / float(n)
        keys = []
        for y in range(g):
            for x in range(self.period):
                px, py = x + 0.5, y + 0.5
                u = px * ca + py * sa
                v = py * ca - px * sa
                fu = (u - math.floor(u)) * 2.0 - 1.0
                fv = (v - math.floor(v)) * 2.0 - 1.0
                keys.append((_spot(shape, fu, fv), (x * 7919 + y * 104729) % n, y * self.period + x))
        keys.sort()
        thresh = bytearray(n)
        for rank, (_, _, idx) in enumerate(keys):
            thresh[idx] = int((rank + 0.5) * 255.0 / n)
        self.base_rows = [bytes(thresh[y * self.period:(y + 1) * self.period]) for y in range(g)]

    def row(self, y, width):
        """Threshold bytes for device row y, `width` pixels long."""
        q, r = divmod(y, self.rows)
        base = self.base_rows[r]
        s = (q * self.shift) % self.period
        reps = (s + width) // self.period + 1
        return (base * reps)[s:s + width]

    def rows_bytes(self, y0, y1, width):
        """Threshold bytes for device rows y0..y1-1, row-major."""
        return b"".join(self.row(y, width) for y in range(y0, y1))


def halftone(grey, lpi=85.0, dpi=1200.0, angle=45.0, shape="round",
             gain50=0.0, min_dot=0.0, max_dot=1.0, hold_extremes=False):
    """Screen an 8-bit greyscale numpy array (0 = black) into a 1-bit plate.

    Same result as the GIMP plug-in. Returns a uint8 array: 0 where ink
    prints, 255 where the plate is clear.
    """
    import numpy as np

    grey = np.asarray(grey, dtype=np.uint8)
    if grey.ndim != 2:
        raise ValueError("expected a 2-D greyscale array")
    h, w = grey.shape
    screen = Screen(lpi, dpi, angle, shape)
    lut = np.frombuffer(coverage_lut(gain50, min_dot, max_dot, hold_extremes), dtype=np.uint8)
    thresh = np.frombuffer(screen.rows_bytes(0, h, w), dtype=np.uint8).reshape(h, w)
    return np.where(lut[grey] > thresh, 0, 255).astype(np.uint8)
