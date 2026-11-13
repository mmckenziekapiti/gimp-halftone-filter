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
4. Optionally fill tones darker than a set percentage solid ("spot
   blacks"), as an illustrator would for deep shadows and black clothes.
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


class Settings(object):
    """Filter settings converted to pixels at the output resolution."""

    def __init__(self, dpi, weight=1.0, detail=60.0, simplify=0.5, shadows=0.0,
                 speck=2.0, min_width=0.5):
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
        self.min_radius = int(round(px(min_width, dpi) / 2.0))

