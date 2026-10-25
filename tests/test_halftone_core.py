import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "letterpress-halftone"))

import halftone_core as hc  # noqa: E402


@pytest.mark.parametrize("shape", hc.DOT_SHAPES)
@pytest.mark.parametrize("angle", [0.0, 15.0, 45.0])
def test_coverage_matches_tone(shape, angle):
    # A flat patch should print with ink area equal to its tone.
    for tone in (0.1, 0.3, 0.5, 0.7, 0.9):
        grey = np.full((400, 400), round((1.0 - tone) * 255), dtype=np.uint8)
        plate = hc.halftone(grey, lpi=60, dpi=1200, angle=angle, shape=shape)
        ink = np.mean(plate == 0)
        assert abs(ink - (1.0 - round((1.0 - tone) * 255) / 255.0)) < 0.01, (shape, tone, ink)


def test_output_is_binary():
    grey = np.tile(np.arange(256, dtype=np.uint8), (64, 1))
    plate = hc.halftone(grey, lpi=100, dpi=1200)
    assert set(np.unique(plate)) <= {0, 255}


def test_white_and_black_are_clean():
    assert np.all(hc.halftone(np.full((200, 200), 255, np.uint8)) == 255)
    assert np.all(hc.halftone(np.full((200, 200), 0, np.uint8)) == 0)


def test_dot_gain_compensation_round_trips():
    c = np.linspace(0, 1, 101)
    g = 0.15
    plate = hc.compensate_dot_gain(c, g)
    printed = plate + g * 4 * plate * (1 - plate)
    assert np.allclose(printed, c, atol=1e-9)
    assert np.all(np.diff(plate) >= 0)
    assert plate[50] < 0.5


def test_min_and_max_dot_limits():
    c = np.array([0.0, 0.01, 0.03, 0.5, 0.96, 0.99, 1.0])
    out = hc.tone_curve(c, min_dot=0.04, max_dot=0.95)
    assert out.tolist() == [0.0, 0.0, 0.04, 0.5, 0.95, 1.0, 1.0]
    held = hc.tone_curve(c, min_dot=0.04, max_dot=0.95, hold_extremes=True)
    assert held.tolist() == [0.0, 0.04, 0.04, 0.5, 0.95, 0.95, 1.0]
