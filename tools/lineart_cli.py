#!/usr/bin/env python3
"""Turn a photograph into 1-bit letterpress line art without GIMP.

Uses the same GEGL engine as the GIMP plug-in. Needs Pillow and GEGL's
Python bindings (gir1.2-gegl-0.4 and python3-gi on Debian/Ubuntu).

    python3 tools/lineart_cli.py photo.jpg plate.tif --weight 1 --detail 60
"""

import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "letterpress-lineart"))

import gegl_lineart as gl  # noqa: E402
import lineart_core as lc  # noqa: E402
from gegl_lineart import Gegl  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("output", help="1-bit output, e.g. plate.tif or plate.png")
    p.add_argument("--weight", type=float, default=1.0, help="line weight in points (default 1)")
    p.add_argument("--detail", type=float, default=60.0, help="0 to 100; higher draws fainter edges (default 60)")
    p.add_argument("--simplify", type=float, default=0.5, help="smooth away texture smaller than this, points (default 0.5)")
    p.add_argument("--shadows", type=float, default=0.0, help="fill tones at least this %% dark solid; 0 is off (default)")
    p.add_argument("--speck", type=float, default=2.0, help="remove isolated marks smaller than this, points (default 2)")
    p.add_argument("--min-width", type=float, default=0.5,
                   help="remove lines and fill gaps narrower than this, points (default 0.5)")
    p.add_argument("--dpi", type=float, default=1200.0, help="output resolution (default 1200)")
    p.add_argument("--input-ppi", type=float, help="input resolution; defaults to the file's, else 300")
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
    img = img.resize(size, Image.BICUBIC if scale > 1 else Image.LANCZOS)

    Gegl.init(None)
    w, h = size
    target = Gegl.Buffer.new("Y u8", 0, 0, w, h)
    settings = lc.Settings(a.dpi, weight=a.weight, detail=a.detail, simplify=a.simplify, shadows=a.shadows,
                           speck=a.speck, min_width=a.min_width)
    gl.line_art(img.tobytes(), w, h, target, settings)
    plate = Image.frombytes("L", size, target.get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.CLAMP))
    if a.negative:
        plate = plate.point(lambda v: 255 - v)
    if a.mirror:
        plate = plate.transpose(Image.FLIP_LEFT_RIGHT)
    plate.convert("1").save(a.output, dpi=(a.dpi, a.dpi))
    print("wrote %s: %dx%d px at %g dpi (%.2f x %.2f in)" % (a.output, w, h, a.dpi, w / a.dpi, h / a.dpi))


if __name__ == "__main__":
    main()
