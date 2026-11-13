import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "letterpress-lineart"))

import lineart_core as lc  # noqa: E402


def test_points_to_pixels():
    assert lc.px(72, 1200) == 1200
    assert abs(lc.px(1, 1200) - 16.6667) < 1e-3


def test_detail_lowers_threshold_monotonically():
    levels = [lc.dog_threshold(d) for d in range(0, 101, 5)]
    assert all(a > b for a, b in zip(levels, levels[1:]))
    assert levels[0] == lc.THRESHOLD_MAX and levels[-1] == lc.THRESHOLD_MIN
    assert lc.dog_threshold(-10) == lc.THRESHOLD_MAX and lc.dog_threshold(150) == lc.THRESHOLD_MIN


def test_settings_scale_with_resolution():
    a, b = lc.Settings(600), lc.Settings(1200)
    assert abs(b.sigma - 2 * a.sigma) < 1e-9
    assert abs(b.speck_px - 2 * a.speck_px) < 1e-9
    assert b.min_radius in (2 * a.min_radius - 1, 2 * a.min_radius, 2 * a.min_radius + 1)


def test_zero_turns_steps_off():
    s = lc.Settings(1200, simplify=0, speck=0, min_width=0, shadows=0)
    assert s.simplify_radius == 0 and s.speck_px == 0 and s.min_radius == 0 and not s.fill_shadows
    s = lc.Settings(1200, shadows=100)
    assert s.fill_shadows and s.shadow_level == 0.0


def mask(rows):
    return bytes(255 if c == "#" else 0 for row in rows for c in row)


def test_find_rejects_drops_small_marks_by_extent():
    rows = [
        "#.........",
        "..........",
        "..######..",
        "..........",
        ".....#....",
        "......#...",
        ".......#..",
    ]
    out = lc.find_rejects(mask(rows), None, 10, 7, 3)
    dropped = ["".join("x" if out[y * 10 + x] else "." for x in range(10)) for y in range(7)]
    # The lone dot goes; the bar (6 wide) and the diagonal (3 tall, joined
    # corner to corner) stay.
    assert dropped[0] == "x........."
    assert not any(out[10:])


def test_find_rejects_keeps_only_seeded_marks():
    rows = ["##...##", "##...##"]
    seeds = mask(["#......", "......."])
    out = lc.find_rejects(mask(rows), seeds, 7, 2, 0)
    assert [out[i] for i in (0, 1, 7, 8)] == [0, 0, 0, 0]
    assert [out[i] for i in (5, 6, 12, 13)] == [255] * 4


def test_select_marks_ignores_speck_seeds():
    # Two faint lines, each 8 long. One has a strong stretch 4 long, the
    # other only a strong dot, which is a speck at max_extent 3.
    ink = mask(["########", "........", "########"])
    strong = mask(["..####..", "........", "...#...."])
    out = lc.select_marks(ink, strong, 8, 3, 3)
    assert not any(out[:8])
    assert all(out[16:])


def test_mark_block_is_a_small_power_of_two():
    assert lc.mark_block(1) == 1 and lc.mark_block(15) == 1
    assert lc.mark_block(16) == 2 and lc.mark_block(33) == 4
    assert lc.mark_block(1000) == 8


def test_hatch_layers_split_the_tone_range():
    layers = lc.hatch_layers("cross", 60.0, 0.4, 8.0)
    assert [h.angle for h in layers] == list(lc.HATCH_ANGLES)
    assert layers[0].start == 0.4 and abs(layers[-1].full - 1.0) < 1e-9
    for a, b in zip(layers, layers[1:]):
        assert abs(a.full - b.start) < 1e-9
    h = layers[0]
    assert h.coverage(0.39) == 0
    assert abs(h.coverage(0.41) * h.spacing - h.w_min) < 1.0
    assert abs(h.coverage(1.0) * h.spacing - h.w_max) < 1e-9
    # Lines and the gaps between them both stay wider than the minimum.
    assert h.w_min >= 8.0 and h.spacing - h.w_max >= 8.0
    assert lc.hatch_layers("none", 60.0, 0.4, 8.0) == []
    assert len(lc.hatch_layers("hatch", 60.0, 0.4, 8.0)) == 1


def test_hatch_rows_follow_the_angle():
    for angle, shift in ((45, 1), (-45, -1), (0, None)):
        h = lc.Hatch(angle, 20.0, 0.3, 1.0, 4.0, 6.0)
        w = 50
        rows = h.rows_bytes(5, 15, w)
        assert len(rows) == 10 * w
        # Fetching a band on its own gives the same rows.
        assert h.rows_bytes(8, 10, w) == rows[3 * w:5 * w]
        for y in range(9):
            r0, r1 = rows[y * w:(y + 1) * w], rows[(y + 1) * w:(y + 2) * w]
            if shift is None:
                assert len(set(r0)) == 1
            elif shift == 1:
                assert r1[:-1] == r0[1:]
            else:
                assert r1[1:] == r0[:-1]
