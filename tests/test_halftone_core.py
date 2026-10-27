import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "letterpress-halftone"))

import halftone_core as hc  # noqa: E402


@pytest.mark.parametrize("shape", hc.DOT_SHAPES)
@pytest.mark.parametrize("angle", [0.0, 15.0, 45.0, -30.0, 75.0])
def test_coverage_matches_tone(shape, angle):
    # A flat patch should print with ink area equal to its tone.
    for level in (230, 178, 128, 77, 25):
        grey = np.full((400, 400), level, dtype=np.uint8)
        plate = hc.halftone(grey, lpi=60, dpi=1200, angle=angle, shape=shape)
        ink = np.mean(plate == 0)
        assert abs(ink - (1.0 - level / 255.0)) < 0.01, (shape, level, ink)


@pytest.mark.parametrize("lpi,dpi,angle", [(85, 1200, 45), (85, 1200, 15), (100, 2400, -20), (65, 1200, 0), (133, 2540, 72)])
def test_threshold_pattern_follows_screen_lattice(lpi, dpi, angle):
    s = hc.Screen(lpi, dpi, angle, "round")
    h = w = 3 * (abs(s.a) + abs(s.b)) + 20
    t = np.frombuffer(s.rows_bytes(0, h + 200, w + 200), dtype=np.uint8).reshape(h + 200, w + 200)
    for dx, dy in ((s.a, s.b), (-s.b, s.a)):
        if dy < 0:
            dx, dy = -dx, -dy
        x0 = max(0, -dx)
        assert np.array_equal(t[0:h, x0:x0 + w], t[dy:dy + h, x0 + dx:x0 + dx + w])


def test_screen_rounds_close_to_request():
    s = hc.Screen(85, 1200, 45, "round")
    assert (s.a, s.b) == (10, 10)
    assert abs(s.lpi - 85) < 1 and abs(s.angle - 45) < 1e-9
    s = hc.Screen(85, 2400, 15, "round")
    assert abs(s.lpi - 85) < 2 and abs(s.angle - 15) < 1.5


def test_output_is_binary():
    grey = np.tile(np.arange(256, dtype=np.uint8), (64, 1))
    plate = hc.halftone(grey, lpi=100, dpi=1200)
    assert set(np.unique(plate)) <= {0, 255}


def test_white_and_black_are_clean():
    assert np.all(hc.halftone(np.full((200, 200), 255, np.uint8)) == 255)
    assert np.all(hc.halftone(np.full((200, 200), 0, np.uint8)) == 0)


@pytest.mark.parametrize("g", [0.15, -0.1])
def test_dot_gain_compensation_round_trips(g):
    cs = [i / 100.0 for i in range(101)]
    plate = [hc.compensate_dot_gain(c, g) for c in cs]
    printed = [p + g * 4 * p * (1 - p) for p in plate]
    assert np.allclose(printed, cs, atol=1e-9)
    assert all(b >= a for a, b in zip(plate, plate[1:]))
    assert (plate[50] < 0.5) == (g > 0)


def test_min_and_max_dot_limits():
    c = [0.0, 0.01, 0.03, 0.5, 0.96, 0.99, 1.0]
    assert [hc.tone_curve(x, min_dot=0.04, max_dot=0.95) for x in c] == [0.0, 0.0, 0.04, 0.5, 0.95, 1.0, 1.0]
    held = [hc.tone_curve(x, min_dot=0.04, max_dot=0.95, hold_extremes=True) for x in c]
    assert held == [0.0, 0.04, 0.04, 0.5, 0.95, 0.95, 1.0]


def test_numpy_is_optional():
    # The GIMP plug-in path must import and build screens without numpy.
    import subprocess
    code = (
        "import sys; sys.modules['numpy'] = None; sys.path.insert(0, %r); import halftone_core as hc; "
        "s = hc.Screen(85, 1200, 45, 'euclidean'); hc.coverage_lut(0.1, 0.05, 0.9); s.rows_bytes(0, 10, 100)"
        % os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "letterpress-halftone")
    )
    subprocess.check_call([sys.executable, "-c", code])


def _soft_text_on_photo():
    """Anti-aliased black bars upsampled 4x (like 300 -> 1200 PPI), beside a smooth ramp."""
    src = np.full((60, 120), 255.0)
    src[10:50, 10:14] = 0.0
    src[10:14, 10:50] = 0.0
    src[10:50, 20] = 0.0  # A hairline.
    src[30:50, 30] = 255 * 0.4  # A partly covered column, as anti-aliasing leaves.
    src[30:50, 29] = 0.0
    src[:, 70:] = np.linspace(255, 0, 50)  # The photo part.
    big = np.kron(src, np.ones((4, 4)))
    # Soften like a resampling filter.
    k = np.array([1, 4, 6, 4, 1], float) / 16
    for axis in (0, 1):
        big = np.apply_along_axis(lambda r: np.convolve(np.pad(r, 2, mode="edge"), k, "valid"), axis, big)
    return np.round(big).astype(np.uint8)


def test_snap_edges_makes_text_solid_and_clean():
    grey = _soft_text_on_photo()
    out = hc.snap_edges(grey, hc.edge_radius(4))
    text = out[:, :260]
    assert set(np.unique(text)) <= {0, 255}
    # Edges stay put: as much ink as the 50% line encloses, and the hairline survives.
    assert abs(np.mean(text == 0) - np.mean(grey[:, :260] < 128)) < 0.005
    assert np.all(out[50:190, 81] == 0)
    # The smooth ramp, away from any black, is untouched.
    assert np.array_equal(out[:, 290:], grey[:, 290:])


def test_snap_edges_leaves_photo_tones_alone():
    ramp = np.tile(np.linspace(255, 0, 400).astype(np.uint8), (50, 1))
    assert np.array_equal(hc.snap_edges(ramp, 6), ramp)
    patch = np.full((50, 50), 40, np.uint8)
    patch[20:30, 20:30] = 120  # Mid-tone detail in a shadow: too little contrast.
    assert np.array_equal(hc.snap_edges(patch, 6), patch)
