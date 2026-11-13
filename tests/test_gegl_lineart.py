import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "letterpress-lineart"))

try:
    import gi

    gi.require_version("Gegl", "0.4")
    from gi.repository import Gegl
except (ImportError, ValueError):
    pytest.skip("GEGL bindings not installed", allow_module_level=True)

import gegl_lineart as gl  # noqa: E402
import lineart_core as lc  # noqa: E402

Gegl.init(None)
DPI = 1200.0


def draw(grey, **kw):
    """Run the filter; returns a bool array, True where ink prints.

    Shading is off unless asked for, so the edge tests see only lines.
    """
    kw.setdefault("shading", "none")
    h, w = grey.shape
    target = Gegl.Buffer.new("Y u8", 0, 0, w, h)
    gl.line_art(np.ascontiguousarray(grey, dtype=np.uint8).tobytes(), w, h, target, lc.Settings(DPI, **kw))
    out = np.frombuffer(target.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.CLAMP),
                        dtype=np.uint8).reshape(h, w)
    assert set(np.unique(out)) <= {0, 255}
    return out == 0


def step(lo, hi, h=80, w=600):
    g = np.full((h, w), hi, np.uint8)
    g[:, : w // 2] = lo
    return g


def width_pt(ink):
    return ink[ink.shape[0] // 2].sum() * 72.0 / DPI


def disc(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return [(dy, dx) for dy, dx in zip(yy.ravel(), xx.ravel()) if dy * dy + dx * dx <= r * r + r]  # GEGL's circle


def morph(mask, r, op):
    """Binary erosion (np.logical_and) or dilation (np.logical_or) by a disc, edges clamped."""
    p = np.pad(mask, r, mode="edge")
    h, w = mask.shape
    out = mask.copy()
    for dy, dx in disc(r):
        out = op(out, p[r + dy:r + dy + h, r + dx:r + dx + w])
    return out


@pytest.mark.parametrize("weight", [1.0, 2.0, 4.0])
def test_strong_edge_line_matches_weight(weight):
    ink = draw(step(0, 255), weight=weight)
    assert abs(width_pt(ink) - weight) < 0.15 * weight
    # One line, on the dark side of the edge.
    cols = np.nonzero(ink[40])[0]
    assert cols.max() < 300 and np.all(np.diff(cols) == 1)


def test_detail_controls_faint_edges():
    faint = step(110, 150)
    assert not draw(faint, detail=20).any()
    assert draw(faint, detail=80).any()
    assert width_pt(draw(step(60, 200), detail=40)) < width_pt(draw(step(60, 200), detail=80))


def test_flat_and_gentle_tones_stay_clean():
    yy, xx = np.mgrid[0:300, 0:400]
    assert not draw(np.full((300, 400), 128, np.uint8)).any()
    assert not draw((xx * 255 // 399).astype(np.uint8)).any()


def test_isolated_speck_removed_but_kept_when_off():
    g = np.full((200, 200), 255, np.uint8)
    yy, xx = np.mgrid[0:200, 0:200]
    g[(yy - 100) ** 2 + (xx - 100) ** 2 <= 8 ** 2] = 0  # Dot 1 pt across.
    assert draw(g, speck=0).any()
    assert not draw(g, speck=2).any()


def test_fading_edge_is_drawn_further_than_a_faint_edge_alone():
    # Hysteresis: an edge that fades out keeps its line down to a contrast
    # that would get no line on its own.
    fading = np.full((200, 900), 230, np.uint8)
    fading[:100] = np.linspace(30, 225, 900).astype(np.uint8)
    ink = draw(fading, weight=2)
    end = np.nonzero(~ink[70:130].any(axis=0))[0][0]
    assert fading[0, end] >= 205
    alone = np.full((200, 900), 230, np.uint8)
    alone[:100] = 200
    assert not draw(alone, weight=2).any()


def test_long_thin_line_survives_speck_removal():
    g = np.full((200, 600), 255, np.uint8)
    g[98:103, 50:550] = 0  # A 0.3 pt hairline.
    ink = draw(g)
    assert ink[:, 100:500].any(axis=0).all()


@pytest.mark.parametrize("min_width", [0.5, 1.0])
def test_lines_and_gaps_are_at_least_min_width(min_width):
    rng = np.random.default_rng(5)
    g = (rng.random((40, 60)) * 255).astype(np.uint8)
    g = np.kron(g, np.ones((6, 6), np.uint8))  # Blocky noise: lots of edges.
    s = lc.Settings(DPI, min_width=min_width)
    ink = draw(g, detail=90, speck=0, min_width=min_width)
    r = s.min_radius
    assert ink.any() and (~ink).any()
    # Opening leaves it unchanged: every ink pixel lies in an all-ink disc.
    assert np.array_equal(morph(morph(ink, r, np.logical_and), r, np.logical_or), ink)
    # Gaps are filled first, so the later opening can leave a few slivers of
    # paper in corners, but nearly all paper lies in an all-paper disc.
    paper = ~ink
    assert np.mean(morph(morph(paper, r, np.logical_and), r, np.logical_or) != paper) < 0.06


def test_solid_shadows():
    g = np.full((300, 300), 230, np.uint8)
    g[100:200, 100:200] = 20  # 92% dark.
    off = draw(g)
    on = draw(g, shadows=80)
    assert not off[130:170, 130:170].any()
    assert on[110:190, 110:190].all()
    assert not on[:60].any()
    assert not draw(g, shadows=95)[130:170, 130:170].any()


def test_dropping_specks_leaves_other_marks_untouched():
    # Odd size, so the reduced grid does not divide the image evenly.
    g = np.full((203, 601), 240, np.uint8)
    g[40:46, 20:580] = 0  # A line.
    yy, xx = np.mgrid[0:203, 0:601]
    for cx in range(40, 580, 60):
        g[(yy - 75) ** 2 + (xx - cx) ** 2 <= 36] = 0  # Specks below it.
    with_specks, without = draw(g, speck=0), draw(g)
    assert with_specks[65:90].any() and not without[65:90].any()
    assert np.array_equal(with_specks[:62], without[:62])


def flat(darkness, size=400):
    return np.full((size, size), int(round(255 * (1 - darkness))), np.uint8)


def test_shading_darkens_with_tone():
    inner = (slice(60, 340), slice(60, 340))
    cover = [draw(flat(d), shading="cross")[inner].mean() for d in (0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)]
    assert cover[0] == 0 and cover[1] == 0  # Lighter than shade-from (45%).
    assert all(b >= a for a, b in zip(cover, cover[1:])), cover
    assert 0.1 < cover[2] < 0.35 and cover[-1] > 0.5
    # Hatching alone stops at one layer.
    assert draw(flat(1.0), shading="hatch")[inner].mean() < cover[-1]


def test_hatch_lines_run_diagonally_at_the_spacing():
    ink = draw(flat(0.55), shading="hatch", hatch_spacing=4.0)[60:340, 60:340]
    # Rising to the right: each row is the one below shifted left by one px.
    assert np.mean(ink[:-1, 1:] == ink[1:, :-1]) > 0.97
    starts = np.count_nonzero(ink[140, 1:] & ~ink[140, :-1])
    pitch_px = 4.0 * DPI / 72 * np.sqrt(2)  # Along a row.
    assert abs(starts - 279 / pitch_px) <= 1


def test_cross_hatching_adds_the_second_direction():
    # With shade-from 45%, the first (rising) layer is full width at about
    # 63% and the second (falling) layer starts there.
    cross = draw(flat(0.75), shading="cross")[60:340, 60:340]
    single = draw(flat(0.62), shading="cross")[60:340, 60:340]
    extra = cross & ~single
    assert extra.mean() > 0.05
    # The added lines fall to the right: each row is the one above shifted right.
    # Given an added ink pixel, the one 20 px diagonally below right (further
    # than a line is wide) is ink too, much more often than below left.
    k = 20
    falling = np.mean(extra[k:, k:][extra[:-k, :-k]])
    rising = np.mean(extra[k:, :-k][extra[:-k, k:]])
    assert falling > rising + 0.2, (falling, rising)


@pytest.mark.parametrize("darkness", [0.5, 0.7, 0.95])
def test_hatch_lines_are_at_least_min_width(darkness):
    s = lc.Settings(DPI)
    ink = draw(flat(darkness, 300), shading="cross")
    r = s.min_radius
    assert np.array_equal(morph(morph(ink, r, np.logical_and), r, np.logical_or), ink)
