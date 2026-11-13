"""Run the line-art filter with GEGL, so no numpy is needed.

Kept separate from the plug-in entry point so it can be tested with plain
GEGL bindings outside GIMP. Buffers are linear "Y u8"/"Y float", so GEGL
treats the grey bytes as plain numbers n / 255 with no gamma conversion.
"""

import gi

gi.require_version("Gegl", "0.4")
from gi.repository import Gegl  # noqa: E402

import lineart_core as lc  # noqa: E402

# Half a grey step, used so a "> 0" test never lands exactly on zero.
_HALF = 0.5 / 255.0


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
    """
    node = _node(graph, "gegl:threshold", value=1e-7, high=100.0)
    a.link(node)
    return node


def _blur(graph, a, sigma):
    node = _node(graph, "gegl:gaussian-blur", std_dev_x=sigma, std_dev_y=sigma)
    a.link(node)
    return node


def _run(graph, node, width, height):
    """Render node into a new linear "Y u8" buffer of the image size."""
    crop = _node(graph, "gegl:crop", x=0.0, y=0.0, width=float(width), height=float(height))
    node.link(crop)
    target = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    sink = _node(graph, "gegl:write-buffer", buffer=target)
    crop.link(sink)
    sink.process()
    return target


def find_edges(grey, width, height, s):
    """Simplify, find edges and fill shadows.

    grey: Gegl.Buffer of the grey image, 0 = black. s: lineart_core.Settings.
    Returns two Gegl.Buffers, 255 where ink prints: (all ink down to the low
    threshold, ink above the full threshold).
    """
    graph = Gegl.Node()
    src = _node(graph, "gegl:buffer-source", buffer=grey)
    if s.simplify_radius > 0:
        smooth = _node(graph, "gegl:median-blur", radius=s.simplify_radius, high_precision=True)
        src.link(smooth)
    else:
        smooth = src

    # Positive where a pixel is darker than its surroundings.
    dog = _math(graph, "gegl:subtract", _blur(graph, smooth, s.sigma_outer), _blur(graph, smooth, s.sigma))
    weak = _positive(graph, _math(graph, "gegl:subtract", dog, value=s.threshold_low))
    strong = _positive(graph, _math(graph, "gegl:subtract", dog, value=s.threshold))

    if s.fill_shadows:
        # Ink where smooth <= level, i.e. level - smooth + half a grey step > 0.
        dark = _positive(graph, _math(graph, "gegl:add", _math(graph, "gegl:multiply", smooth, value=-1.0),
                                      value=s.shadow_level + _HALF))

        def union(a, b):
            return _positive(graph, _math(graph, "gegl:subtract", _math(graph, "gegl:add", a, b), value=0.5))

        weak, strong = union(weak, dark), union(strong, dark)
    return _run(graph, weak, width, height), _run(graph, strong, width, height)


def select_marks(ink, strong, width, height, s):
    """Clear specks, and faint marks not joined to a strong edge, from ink, in place."""
    k = s.block
    lw, lh = -(-width // k), -(-height // k)
    rect = Gegl.Rectangle.new(0, 0, lw, lh)
    # At a power of two scale GEGL box-averages its mipmap, so a block with
    # any ink in it reads as nonzero.
    small = ink.get(rect, 1.0 / k, "Y u8", Gegl.AbyssPolicy.NONE)
    seeds = strong.get(rect, 1.0 / k, "Y u8", Gegl.AbyssPolicy.NONE)
    erase = lc.select_marks(small, seeds, lw, lh, s.speck_px / k)
    if not any(erase):
        return
    # Each block belongs to one mark, so clearing whole blocks of the
    # dropped marks touches no other mark.
    erase_buf = Gegl.Buffer.new("Y u8", 0, 0, lw, lh)
    erase_buf.set(rect, "Y u8", bytes(erase))
    graph = Gegl.Node()
    src = _node(graph, "gegl:buffer-source", buffer=ink)
    big = _node(graph, "gegl:buffer-source", buffer=erase_buf)
    if k > 1:
        up = _node(graph, "gegl:scale-ratio", x=float(k), y=float(k), sampler=Gegl.SamplerType.NEAREST)
        big.link(up)
        big = up
    keep = _math(graph, "gegl:add", _math(graph, "gegl:multiply", big, value=-1.0), value=1.0)
    out = _run(graph, _math(graph, "gegl:multiply", src, keep), width, height)
    full = Gegl.Rectangle.new(0, 0, width, height)
    out.copy(full, Gegl.AbyssPolicy.NONE, ink, full)


def finish(ink, width, height, target, s):
    """Smooth, enforce the minimum line and gap, and write paper (255) and ink (0) to target."""
    graph = Gegl.Node()
    node = _node(graph, "gegl:buffer-source", buffer=ink)
    node = _positive(graph, _math(graph, "gegl:subtract", _blur(graph, node, s.smooth_sigma), value=0.5))
    if s.min_radius > 0:
        # Closing (dilate, erode) then opening (erode, dilate) with a disc.
        for percentile in (100.0, 0.0, 0.0, 100.0):
            m = _node(graph, "gegl:median-blur", radius=s.min_radius, percentile=percentile)
            node.link(m)
            node = m
    # Paper = 1 - ink.
    paper = _positive(graph, _math(graph, "gegl:subtract", _math(graph, "gegl:multiply", node, value=-1.0),
                                   value=-0.5))
    crop = _node(graph, "gegl:crop", x=0.0, y=0.0, width=float(width), height=float(height))
    paper.link(crop)
    sink = _node(graph, "gegl:write-buffer", buffer=target)
    crop.link(sink)
    sink.process()
    target.flush()


def line_art(grey, width, height, target, settings, progress=None):
    """Draw 8-bit grey bytes (0 = black, row-major) as 1-bit line art into `target`.

    target: a Gegl.Buffer that receives the plate, 0 where ink prints, 255
    for paper.
    """
    src = Gegl.Buffer.new("Y u8", 0, 0, width, height)
    src.set(Gegl.Rectangle.new(0, 0, width, height), "Y u8", bytes(grey))
    ink, strong = find_edges(src, width, height, settings)
    if progress is not None:
        progress(0.5)
    select_marks(ink, strong, width, height, settings)
    if progress is not None:
        progress(0.7)
    finish(ink, width, height, target, settings)
    if progress is not None:
        progress(1.0)
