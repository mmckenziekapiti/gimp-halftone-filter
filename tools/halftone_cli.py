#!/usr/bin/env python3
"""Screen an image into a 1-bit letterpress halftone without GIMP.

Uses the same engine as the GIMP plug-in. Needs numpy and Pillow.

    python3 tools/halftone_cli.py photo.png plate.tif --lpi 85 --dpi 1200
"""

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "letterpress-halftone"))

import numpy as np  # noqa: E402

import halftone_core as hc  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("output", help="1-bit output, e.g. plate.tif or plate.png")
    p.add_argument("--lpi", type=float, default=85.0, help="screen frequency (default 85)")
    p.add_argument("--dpi", type=float, default=1200.0, help="output resolution (default 1200)")
    p.add_argument("--input-ppi", type=float, help="input resolution; defaults to the file's, else 300")
    p.add_argument("--angle", type=float, default=45.0, help="screen angle in degrees (default 45)")
    p.add_argument("--shape", choices=hc.DOT_SHAPES, default="round")
    p.add_argument("--dot-gain", type=float, default=10.0, help="net gain at 50%%, in percent; negative for dot loss (default 10)")
    p.add_argument("--min-dot", type=float, default=5.0, help="smallest printable dot, percent (default 5)")
    p.add_argument("--max-dot", type=float, default=90.0, help="largest dot that keeps a hole, percent (default 90)")
    p.add_argument("--hold-extremes", action=argparse.BooleanOptionalAction, default=True,
                   help="hold min/max dots instead of dropping to paper/solid (default on)")
    p.add_argument("--solid-text", action=argparse.BooleanOptionalAction, default=True,
                   help="snap the grey edges of black text to solid black or paper (default on)")
    p.add_argument("--negative", action="store_true", help="invert for film negatives")
    p.add_argument("--mirror", action="store_true", help="flip horizontally (wrong-reading)")
    a = p.parse_args(argv)

    img = Image.open(a.input)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")
    ppi = a.input_ppi or (img.info.get("dpi") or (300, 300))[0] or 300
    scale = a.dpi / float(ppi)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    # Like the plug-in: cubic when enlarging, since Lanczos rings into faint
    # halos around type that the screen would print as rows of dots.
    img = img.resize(size, Image.BICUBIC if scale > 1 else Image.LANCZOS)

    grey = np.asarray(img)
    if a.solid_text:
        grey = hc.snap_edges(grey, hc.edge_radius(scale))
    plate = hc.halftone(
        grey, lpi=a.lpi, dpi=a.dpi, angle=a.angle, shape=a.shape,
        gain50=a.dot_gain / 100.0, min_dot=a.min_dot / 100.0, max_dot=a.max_dot / 100.0,
        hold_extremes=a.hold_extremes,
    )
    if a.negative:
        plate = 255 - plate
    if a.mirror:
        plate = plate[:, ::-1]
    Image.fromarray(plate).convert("1").save(a.output, dpi=(a.dpi, a.dpi))
    screen = hc.Screen(a.lpi, a.dpi, a.angle, a.shape)
    print("wrote %s: %dx%d px at %g dpi (%.2f x %.2f in), screen %.1f LPI at %.1f deg" % (
        a.output, size[0], size[1], a.dpi, size[0] / a.dpi, size[1] / a.dpi, screen.lpi, screen.angle))


if __name__ == "__main__":
    main()
