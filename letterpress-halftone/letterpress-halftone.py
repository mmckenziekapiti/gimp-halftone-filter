#!/usr/bin/env python3
"""GIMP 3 plug-in: screen an image into a 1-bit halftone for a letterpress plate.

Filters > Distorts > Letterpress Halftone...

The current image is flattened onto white, converted to greyscale, resampled
from its print resolution to the output resolution, screened (halftone_core
for the maths, GEGL for the per-pixel work, so numpy is not needed), and
opened as a new 1-bit (black/white indexed) image ready to export as TIFF
for platemaking.
"""

import os
import sys

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp, GimpUi, GLib, GObject  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROC_NAME = "plug-in-letterpress-halftone"

SHAPE_LABELS = (
    ("round", "Round"),
    ("euclidean", "Euclidean (round, checkerboard at 50%)"),
    ("ellipse", "Elliptical / chain"),
    ("square", "Square"),
    ("diamond", "Diamond"),
    ("line", "Line"),
)


def _fail(procedure, message):
    return procedure.new_return_values(
        Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error.new_literal(GLib.quark_from_string(PROC_NAME), message, 0)
    )


def _image_ppi(image):
    res = image.get_resolution()
    # Introspection returns (ok, x, y) or (x, y) depending on the binding.
    if len(res) == 3:
        res = res[1:]
    return float(res[0]) or 300.0


def _to_bitmap(image):
    """Convert to a black/white indexed image. Returns None, or the errors seen.

    Tries a few routes because the palette argument differs between GIMP 3
    releases: 3.0.x takes a palette name string, later releases an object.
    """
    errors = []

    def indexed():
        return image.get_base_type() == Gimp.ImageBaseType.INDEXED

    def direct_mono():
        image.convert_indexed(Gimp.ConvertDitherType.NONE, Gimp.ConvertPaletteType.MONO, 2, False, False, "")

    def pdb(palette_type, palette=""):
        proc = Gimp.get_pdb().lookup_procedure("gimp-image-convert-indexed")
        cfg = proc.create_config()
        cfg.set_property("image", image)
        cfg.set_property("dither-type", Gimp.ConvertDitherType.NONE)
        cfg.set_property("palette-type", palette_type)
        cfg.set_property("num-cols", 2)
        cfg.set_property("alpha-dither", False)
        cfg.set_property("remove-unused", False)
        cfg.set_property("palette", palette)
        result = proc.run(cfg)
        if result.index(0) != Gimp.PDBStatusType.SUCCESS:
            raise RuntimeError(Gimp.PDBStatusType(result.index(0)).value_nick)

    def pdb_custom():
        palette = Gimp.Palette.new("Letterpress black-white")
        palette.add_entry("black", Gegl.Color.new("black"))
        palette.add_entry("white", Gegl.Color.new("white"))
        try:
            try:
                pdb(Gimp.ConvertPaletteType.CUSTOM, palette.get_name())
            except TypeError:  # Releases where the argument is a GimpPalette.
                pdb(Gimp.ConvertPaletteType.CUSTOM, palette)
        finally:
            palette.delete()

    def direct_mono_object():
        image.convert_indexed(Gimp.ConvertDitherType.NONE, Gimp.ConvertPaletteType.MONO, 2, False, False, None)

    for attempt in (direct_mono, direct_mono_object, lambda: pdb(Gimp.ConvertPaletteType.MONO), pdb_custom):
        try:
            attempt()
        except Exception as e:
            errors.append(str(e) or type(e).__name__)
        if indexed():
            return None
    return "; ".join(errors) or "GIMP returned no error"


class LetterpressHalftone(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC_NAME]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        proc = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        proc.set_image_types("RGB*, GRAY*, INDEXED*")
        proc.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE | Gimp.ProcedureSensitivityMask.DRAWABLES)
        proc.set_menu_label("_Letterpress Halftone...")
        proc.add_menu_path("<Image>/Filters/Distorts")
        proc.set_documentation(
            "Make a 1-bit halftone for a letterpress plate",
            "Screens the image with an AM halftone at the chosen frequency, angle and dot shape, "
            "compensating for press dot gain and limiting dots to the printable range. "
            "The result opens as a new black/white image at the output resolution. "
            "Grey levels per cell are about (DPI / LPI)^2, so keep DPI at least 10x LPI. "
            "LPI and angle are rounded slightly so the screen lines up with whole pixels.",
            name,
        )
        proc.set_attribution("gimp-halftone-filter contributors", "gimp-halftone-filter contributors", "2026")

        rw = GObject.ParamFlags.READWRITE
        proc.add_double_argument("lpi", "Screen _frequency (LPI)", "Halftone lines per inch", 5.0, 300.0, 85.0, rw)
        proc.add_double_argument("dpi", "_Output resolution (DPI)", "Plate/film resolution in pixels per inch",
                                 72.0, 5080.0, 1200.0, rw)
        proc.add_double_argument("input-ppi", "_Input resolution (PPI)",
                                 "Resolution of the source image; filled in from Image > Print Size, 0 also uses it", 0.0, 9600.0, 0.0, rw)
        proc.add_double_argument("angle", "Screen _angle", "Screen angle in degrees", -90.0, 90.0, 45.0, rw)

        shapes = Gimp.Choice.new()
        for i, (nick, label) in enumerate(SHAPE_LABELS):
            shapes.add(nick, i, label, "")
        proc.add_choice_argument("dot-shape", "Dot _shape", "Halftone dot shape", shapes, "round", rw)

        proc.add_double_argument("dot-gain", "Dot _gain at 50% (%)",
                                 "Net gain at a 50% dot (press gain minus etch loss); negative if dots print smaller",
                                 -20.0, 24.0, 10.0, rw)
        proc.add_double_argument("min-dot", "_Minimum dot (%)", "Smallest dot that survives etching and inks reliably",
                                 0.0, 50.0, 5.0, rw)
        proc.add_double_argument("max-dot", "Ma_ximum dot (%)", "Largest dot that still keeps an open hole",
                                 50.0, 100.0, 90.0, rw)
        proc.add_boolean_argument("hold-extremes", "_Hold min/max dots",
                                  "Hold the minimum and maximum dot instead of dropping to paper or solid",
                                  False, rw)
        proc.add_boolean_argument("negative", "_Negative (for film)", "Invert the output", False, rw)
        proc.add_boolean_argument("mirror", "Mi_rror (wrong-reading)", "Flip the output horizontally", False, rw)
        return proc

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        import gegl_screen

        if run_mode == Gimp.RunMode.INTERACTIVE:
            GimpUi.init(PROC_NAME)
            # Start from this image's resolution rather than the value
            # remembered from the last image.
            config.set_property("input-ppi", _image_ppi(image))
            dialog = GimpUi.ProcedureDialog.new(procedure, config, "Letterpress Halftone")
            dialog.fill(None)
            if not dialog.run():
                dialog.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
            dialog.destroy()

        get = config.get_property
        lpi, dpi = get("lpi"), get("dpi")
        ppi = get("input-ppi") or _image_ppi(image)

        Gimp.context_push()
        try:
            Gimp.progress_init("Letterpress halftone")
            out = image.duplicate()
            out.undo_disable()
            Gimp.context_set_background(Gegl.Color.new("white"))
            layer = out.flatten()
            if out.get_base_type() != Gimp.ImageBaseType.GRAY:
                out.convert_grayscale()
            if out.get_precision() != Gimp.Precision.U8_NON_LINEAR:
                out.convert_precision(Gimp.Precision.U8_NON_LINEAR)

            scale = dpi / ppi
            w = max(1, int(round(out.get_width() * scale)))
            h = max(1, int(round(out.get_height() * scale)))
            Gimp.context_set_interpolation(Gimp.InterpolationType.NOHALO if scale < 1 else Gimp.InterpolationType.CUBIC)
            out.scale(w, h)
            out.set_resolution(dpi, dpi)
            layer = out.get_layers()[0]

            grey = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y' u8", Gegl.AbyssPolicy.CLAMP)
            shadow = layer.get_shadow_buffer()
            screen = gegl_screen.screen_buffer(
                grey, w, h, shadow, lpi=lpi, dpi=dpi, angle=get("angle"), shape=get("dot-shape"),
                gain50=get("dot-gain") / 100.0, min_dot=get("min-dot") / 100.0, max_dot=get("max-dot") / 100.0,
                hold_extremes=get("hold-extremes"), progress=Gimp.progress_update,
            )
            layer.merge_shadow(False)
            layer.update(0, 0, w, h)
            if get("negative"):
                layer.invert(False)
            if get("mirror"):
                out.flip(Gimp.OrientationType.HORIZONTAL)

            # Two-colour palette so it exports as a true 1-bit file.
            error = _to_bitmap(out)
            if error:  # The plate is already pure black/white.
                Gimp.message("Kept the plate as greyscale (0/255 only); indexed conversion failed: %s" % error)

            out.undo_enable()
            out.get_layers()[0].set_name("Plate %.1f LPI %.1f deg %s" % (screen.lpi, screen.angle, get("dot-shape")))
            Gimp.Display.new(out)
            Gimp.displays_flush()
            Gimp.progress_end()
        except Exception as e:
            return _fail(procedure, "Letterpress Halftone failed: %s" % e)
        finally:
            Gimp.context_pop()

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(LetterpressHalftone.__gtype__, sys.argv)
