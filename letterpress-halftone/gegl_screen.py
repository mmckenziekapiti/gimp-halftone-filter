"""Run the halftone comparison with GEGL, so no numpy is needed.

Kept separate from the plug-in entry point so it can be tested with plain
GEGL bindings outside GIMP.
"""

import gi

gi.require_version("Gegl", "0.4")
from gi.repository import Gegl  # noqa: E402

import halftone_core as hc  # noqa: E402

# Rows per Gegl.Buffer.set call when filling the threshold pattern.
_STRIP_ROWS = 256


def screen_buffer(grey, width, height, target, lpi, dpi, angle, shape,
                  gain50=0.0, min_dot=0.0, max_dot=1.0, hold_extremes=False, progress=None):
    """Screen 8-bit grey bytes (0 = black, row-major) into `target`.

    target: a Gegl.Buffer that receives the plate, black where ink prints.
    Returns the halftone_core.Screen used, for its actual LPI and angle.
    """
    screen = hc.Screen(lpi, dpi, angle, shape)
    lut = hc.coverage_lut(gain50, min_dot, max_dot, hold_extremes)

    # Both buffers are linear "Y u8", so GEGL reads the bytes back as plain
    # numbers n / 255 with no gamma conversion.
    thresholds = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    for y0 in range(0, height, _STRIP_ROWS):
        y1 = min(height, y0 + _STRIP_ROWS)
        thresholds.set(Gegl.Rectangle.new(0, y0, width, y1 - y0), "Y u8", screen.rows_bytes(y0, y1, width))
        if progress is not None:
            progress(0.8 * y1 / float(height))
    coverage = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    coverage.set(Gegl.Rectangle.new(0, 0, width, height), "Y u8", bytes(grey).translate(lut))

    # Paper where threshold >= coverage, i.e. threshold - coverage >= 0.
    graph = Gegl.Node()
    src = graph.create_child("gegl:buffer-source")
    src.set_property("buffer", thresholds)
    aux = graph.create_child("gegl:buffer-source")
    aux.set_property("buffer", coverage)
    diff = graph.create_child("gegl:subtract")
    thr = graph.create_child("gegl:threshold")
    thr.set_property("value", -0.5 / 255.0)
    thr.set_property("high", 2.0)
    sink = graph.create_child("gegl:write-buffer")
    sink.set_property("buffer", target)
    src.link(diff)
    aux.connect_to("output", diff, "aux")
    diff.link(thr)
    thr.link(sink)
    sink.process()
    target.flush()
    if progress is not None:
        progress(1.0)
    return screen
