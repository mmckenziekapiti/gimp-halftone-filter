"""Settings maths for the letterpress line-art filter.

Pure Python with no GIMP or numpy dependency, so it runs inside the Python
that ships with GIMP on Windows. The per-pixel work is done by GEGL in
gegl_lineart.py; this module only turns the user's settings, given in
printer's points and percentages, into pixel sizes and thresholds at the
output resolution.

How a pixel is decided (all at the output resolution):

1. Simplify: a median filter flattens texture and noise smaller than the
   simplify size (skin pores, grass, film grain) while keeping the edges of
   larger shapes sharp.
2. Edges: a difference of Gaussians (DoG). A pixel that is darker than its
   surroundings at the scale of the line weight gets a positive response.
   This puts one line on the dark side of every edge, and turns thin dark
   features (hair, wires, cracks) into a single line rather than two.
3. Threshold: ink where the response is above a level set by Detail. Higher
   detail inks fainter edges. Where a line fades, it is carried on down to
   half that level as long as it stays joined to the stronger part, so
   outlines stay continuous instead of breaking into dashes.
4. Shade the darker tones with hatching: layers of parallel lines (45°,
   then -45°, then horizontal for cross-hatching) that come in one after
   another as the smoothed tone darkens, each thickening within its share
   of the tone range. Optionally also fill tones darker than a set
   percentage solid ("spot blacks").
5. Clean up for the plate: marks smaller than the speck size in both
   directions are dropped (lines are long, so they stay, while noise,
   texture and short dashes go), and the edges are smoothed. Then white
   gaps narrower than the minimum width are filled (they would be too
   shallow to stay clean) and black lines narrower than it are removed
   (they would be undercut and lost in etching). Every line left is at
   least that wide; the removal can leave a few narrow slivers of paper in
   corners.
"""

import math
import re


# Faint edges with a response above this fraction of the threshold are
# drawn too, but only where they join a line that passed the threshold
# (hysteresis, as in the Canny edge finder). This joins up the dashes that
# a single threshold leaves along a fading edge, without adding faint lines
# that stand alone.
HYSTERESIS = 0.5

# Ratio between the two Gaussians of the difference of Gaussians. 1.6
# approximates the Laplacian of Gaussian and is the usual choice.
DOG_RATIO = 1.6

# Blur of the DoG's inner Gaussian per point of line weight, in points.
# Calibrated so a full contrast step edge at the default detail gives a line
# about as wide as the line weight (see tests).
SIGMA_PER_WEIGHT = 0.24

# DoG response threshold at detail 0 and detail 100. Grey values are 0..1.
THRESHOLD_MAX = 0.08
THRESHOLD_MIN = 0.003


def px(points, dpi):
    """Points (1/72 inch) to pixels at dpi."""
    return points * dpi / 72.0


def dog_threshold(detail):
    """DoG response needed to ink, for detail in 0..100.

    Falls quadratically so the top half of the slider gives fine control
    over faint edges.
    """
    d = min(100.0, max(0.0, detail)) / 100.0
    return THRESHOLD_MIN + (THRESHOLD_MAX - THRESHOLD_MIN) * (1.0 - d) ** 2


def mark_block(size_px):
    """Block size (a power of two, 1 to 8 px) for sorting marks at reduced size.

    Marks are labelled on the ink mask shrunk by this factor, which keeps
    the pure Python labelling fast. size_px is the smallest feature that
    matters (the speck size or the line weight); 8 blocks across it is
    plenty.
    """
    k = 1
    while k < 8 and 2 * k * 8 <= size_px:
        k *= 2
    return k


def find_rejects(mask, seeds, width, height, max_extent):
    """Mark the marks to drop: specks, and faint lines that touch no strong edge.

    mask: bytes, row-major, nonzero where there is ink. Marks are 8-connected
    groups of ink pixels. A mark is dropped when both its width and its
    height are below max_extent pixels (a speck; max_extent 0 keeps all),
    or when seeds (bytes like mask, or None for no check) is zero all over
    it. Returns a bytearray of the same size, 255 on dropped pixels and 0
    elsewhere.

    Works on runs of ink along each row, joined with a union-find, so it
    only touches ink and stays quick in plain Python.
    """
    find_runs = re.compile(b"[^\x00]+").finditer
    parent = []
    runs = []  # (row, x0, x1) per run id, x1 exclusive.

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    prev = []  # (x0, x1, id) in the previous row.
    for y in range(height):
        row = mask[y * width:(y + 1) * width]
        cur = []
        j = 0
        for m in find_runs(row):
            x0, x1 = m.start(), m.end()
            rid = len(parent)
            parent.append(rid)
            runs.append((y, x0, x1))
            # 8-connected: touching diagonally counts.
            while j < len(prev) and prev[j][1] < x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] <= x1:
                a, b = root(prev[k][2]), root(rid)
                if a != b:
                    parent[b] = a
                k += 1
            cur.append((x0, x1, rid))
        prev = cur

    box = {}
    seeded = set()
    for rid, (y, x0, x1) in enumerate(runs):
        r = root(rid)
        b = box.get(r)
        if b is None:
            box[r] = [x0, x1, y, y + 1]
        else:
            if x0 < b[0]:
                b[0] = x0
            if x1 > b[1]:
                b[1] = x1
            b[3] = y + 1
        if seeds is not None and r not in seeded and seeds[y * width + x0:y * width + x1].strip(b"\x00"):
            seeded.add(r)
    drop = set(r for r, b in box.items()
               if (b[1] - b[0] < max_extent and b[3] - b[2] < max_extent) or (seeds is not None and r not in seeded))

    out = bytearray(width * height)
    if drop:
        for rid, (y, x0, x1) in enumerate(runs):
            if root(rid) in drop:
                out[y * width + x0:y * width + x1] = b"\xff" * (x1 - x0)
    return out


def select_marks(ink, strong, width, height, max_extent):
    """Pick the marks to drop, with hysteresis and speck removal.

    ink: bytes, nonzero where the low threshold inks. strong: bytes, nonzero
    where the full threshold inks (a subset of ink). Strong marks smaller
    than max_extent are specks and are dropped first; then every mark of
    ink that does not contain what is left of the strong ink is dropped.
    So a faint stretch of line survives when it continues a real line, but
    texture made of small strong specks joined by faint ink does not.
    Returns a bytearray, 255 where ink is dropped.
    """
    if max_extent > 0:
        specks = find_rejects(strong, None, width, height, max_extent)
        strong = bytes(strong).translate(_NONZERO_TO_FF)
        if any(specks):
            # Clear the specks from the seeds, bytewise strong & ~specks, done
            # on whole buffers as big integers since that runs in C.
            n = len(strong)
            strong = (int.from_bytes(strong, "big") & ~int.from_bytes(specks, "big")).to_bytes(n, "big")
    return find_rejects(ink, strong, width, height, max_extent)


_NONZERO_TO_FF = bytes([0] + [255] * 255)


HATCH_STYLES = ("none", "hatch", "cross")

# Hatch layers in the order they come in as the tone darkens: angle in
# degrees from horizontal, 45 rising to the right on the page.
HATCH_ANGLES = (45, -45, 0)

# Widest a hatch line gets, as a fraction of the pitch. Kept thin so the
# layers read as drawn lines rather than a screen; darker tones come from
# adding layers, and solid shadows can take over at the darkest end.
MAX_HATCH_WIDTH = 0.3


class Hatch(object):
    """One layer of parallel hatch lines whose width grows with darkness.

    Lines start at `start` darkness (0..1) at width w_min px and widen
    linearly to w_max px at `full` darkness. spacing is the line pitch in px.
    """

    def __init__(self, angle, spacing, start, full, w_min, w_max):
        self.angle, self.spacing = angle, spacing
        self.start, self.full = start, full
        self.w_min, self.w_max = w_min, w_max

    def coverage(self, darkness):
        """Line width as a fraction of the spacing, 0 where this layer is off."""
        if darkness <= self.start:
            return 0.0
        t = min(1.0, (darkness - self.start) / (self.full - self.start))
        return (self.w_min + t * (self.w_max - self.w_min)) / self.spacing

    def rows_bytes(self, y0, y1, width):
        """Distance pattern for rows y0..y1-1 as row-major bytes.

        Each byte is 255 x the distance from the nearest line centre as a
        fraction of the spacing, times 2: a line w px wide covers the pixels
        whose byte is below 255 * w / spacing. Pixels further out than the
        widest line ever gets are 255, so the line never grows past w_max.
        """
        if self.angle == 0:
            return b"".join(bytes([self._value(y, self.spacing)]) * width for y in range(y0, y1))
        if self.angle not in (45, -45):
            raise ValueError("unsupported hatch angle %r" % (self.angle,))
        # With y pointing down the page, x + y is constant along a line
        # rising to the right, x - y along one falling to the right; across
        # the lines that sum steps by spacing * sqrt(2) per pitch.
        pitch = self.spacing * math.sqrt(2.0)
        if self.angle == 45:
            base = bytes(self._value(n, pitch) for n in range(y0, y1 + width))
            return b"".join(base[y - y0:y - y0 + width] for y in range(y0, y1))
        base = bytes(self._value(n, pitch) for n in range(-y1, width - y0))
        return b"".join(base[y1 - y:y1 - y + width] for y in range(y0, y1))

    def _value(self, n, pitch):
        f = (n / pitch) % 1.0
        d = 2.0 * min(f, 1.0 - f)  # 0 on a line centre, 1 midway between lines.
        if d * self.spacing >= self.w_max + 1.0:
            return 255
        return min(254, int(d * 255.0 + 0.5))


def hatch_layers(style, spacing, start, min_width):
    """Hatch layers for a style, in px, splitting darkness start..1 between them.

    Lines are never narrower than about 1.3 x min_width, nor the gaps
    between parallel lines, so they survive the plate cleanup.
    """
    n = {"none": 0, "hatch": 1, "cross": 3}[style]
    if n == 0 or start >= 1.0:
        return []
    w_min = max(1.0, 1.3 * min_width)
    w_max = max(w_min, min(MAX_HATCH_WIDTH * spacing, spacing - 1.3 * min_width))
    band = (1.0 - start) / n
    return [Hatch(HATCH_ANGLES[i], spacing, start + i * band, start + (i + 1) * band, w_min, w_max)
            for i in range(n)]


class Settings(object):
    """Filter settings converted to pixels at the output resolution."""

    def __init__(self, dpi, weight=1.0, detail=60.0, simplify=0.5, shadows=0.0,
                 speck=2.0, min_width=0.5, shading="cross", shade_from=45.0, hatch_spacing=4.0):
        self.dpi = float(dpi)
        # Median radius in whole pixels; 0 skips the step.
        self.simplify_radius = int(round(px(simplify, dpi) / 2.0))
        self.sigma = max(0.5, px(weight * SIGMA_PER_WEIGHT, dpi))
        self.sigma_outer = self.sigma * DOG_RATIO
        self.threshold = dog_threshold(detail)
        self.threshold_low = self.threshold * HYSTERESIS
        self.block = mark_block(min(px(speck, dpi), px(weight, dpi)) if speck > 0 else px(weight, dpi))
        # Tones at least `shadows` percent dark (grey <= shadow_level, 0..1)
        # are filled solid; 0 turns it off.
        self.fill_shadows = shadows > 0
        self.shadow_level = 1.0 - min(100.0, shadows) / 100.0
        # Marks (connected groups of ink) narrower and shorter than this are
        # removed; 0 turns it off.
        self.speck_px = px(speck, dpi) if speck > 0 else 0.0
        # Edges are smoothed by blurring the 1-bit image a little and
        # thresholding at half. Then a morphological closing fills white gaps
        # narrower than the minimum, and an opening removes black lines
        # narrower than it, so everything left can be etched and inked.
        self.smooth_sigma = max(0.7, px(weight, dpi) / 8.0)
        # Shading: hatch lines over tones darker than shade_from percent,
        # following the tone smoothed over about a third of a hatch pitch.
        spacing = max(4.0, px(hatch_spacing, dpi))
        self.hatches = hatch_layers(shading, spacing, min(100.0, max(0.0, shade_from)) / 100.0, px(min_width, dpi))
        self.tone_sigma = spacing / 3.0
        self.min_radius = int(round(px(min_width, dpi) / 2.0))

