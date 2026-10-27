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


def _node(graph, op, **props):
    node = graph.create_child(op)
    for k, v in props.items():
        node.set_property(k.replace("_", "-"), v)
    return node


def _math(graph, op, a, b=None, value=None):
    """a <op> b, or a <op> value when b is None."""
    node = _node(graph, op) if value is None else _node(graph, op, value=value)
    a.link(node)
    if b is not None:
        b.connect_to("output", node, "aux")
    return node


def _positive(graph, a):
    """1 where a > 0, else 0.

    gegl:threshold compares in perceptual (gamma) space, where negative
    values are not reliable, so only "greater than zero" is asked of it.
    Callers offset `a` by half a grey step so it is never zero.
    """
    node = _node(graph, "gegl:threshold", value=1e-7, high=100.0)
    a.link(node)
    return node


def snap_edges(grey, width, height, radius):
    """GEGL version of halftone_core.snap_edges, on 8-bit grey bytes. Returns bytes.

    Works in linear "Y u8", so every value is plain n / 255 and the result
    matches the numpy reference exactly.
    """
    src_buf = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    src_buf.set(Gegl.Rectangle.new(0, 0, width, height), "Y u8", bytes(grey))
    graph = Gegl.Node()
    g = _node(graph, "gegl:buffer-source", buffer=src_buf)

    def extreme(percentile):
        node = _node(graph, "gegl:median-blur", radius=radius, percentile=percentile, high_precision=True)
        node.set_property("neighborhood", 0)  # Square, to match the reference.
        g.link(node)
        return node

    lo, hi = extreme(0.0), extreme(100.0)
    half = 0.5 / 255.0
    # Edge where lo <= EDGE_DARK and hi - lo >= EDGE_CONTRAST.
    minus_lo = _math(graph, "gegl:multiply", lo, value=-1.0)
    is_dark = _positive(graph, _math(graph, "gegl:add", minus_lo, value=hc.EDGE_DARK / 255.0 + half))
    span = _math(graph, "gegl:subtract", hi, lo)
    is_wide = _positive(graph, _math(graph, "gegl:subtract", span, value=hc.EDGE_CONTRAST / 255.0 - half))
    edge = _math(graph, "gegl:multiply", is_dark, is_wide)
    # Black when lo + hi - 2g > 0, else hi.
    twice = _math(graph, "gegl:multiply", g, value=2.0)
    excess = _math(graph, "gegl:subtract", _math(graph, "gegl:add", lo, hi), twice)
    dark = _positive(graph, _math(graph, "gegl:subtract", excess, value=half))
    snapped = _math(graph, "gegl:subtract", hi, _math(graph, "gegl:multiply", hi, dark))
    out = _math(graph, "gegl:add", g, _math(graph, "gegl:multiply", _math(graph, "gegl:subtract", snapped, g), edge))

    target = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    sink = _node(graph, "gegl:write-buffer", buffer=target)
    out.link(sink)
    sink.process()
    return target.get(Gegl.Rectangle.new(0, 0, width, height), 1.0, "Y u8", Gegl.AbyssPolicy.CLAMP)


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
