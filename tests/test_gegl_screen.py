import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "letterpress-halftone"))

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gegl", "0.4")
    from gi.repository import Gegl
except (ImportError, ValueError):
    pytest.skip("GEGL bindings not installed", allow_module_level=True)

import gegl_screen  # noqa: E402
import halftone_core as hc  # noqa: E402

Gegl.init(None)


@pytest.mark.parametrize("shape,angle", [("round", 45.0), ("euclidean", 15.0), ("line", 0.0)])
def test_gegl_matches_reference(shape, angle):
    h, w = 300, 500
    yy, xx = np.mgrid[0:h, 0:w]
    grey = ((xx * 255) // (w - 1)).astype(np.uint8) ^ ((yy // 50) % 2 * 40).astype(np.uint8)
    target = Gegl.Buffer.new("Y u8", 0, 0, w, h)
    kw = dict(lpi=70, dpi=1200, angle=angle, shape=shape, gain50=0.12, min_dot=0.04, max_dot=0.93)
    gegl_screen.screen_buffer(grey.tobytes(), w, h, target, **kw)
    got = np.frombuffer(target.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.CLAMP),
                        dtype=np.uint8).reshape(h, w)
    want = hc.halftone(grey, **kw)
    assert np.array_equal(got, want)
