#!/usr/bin/env python3
"""GIMP 3 plug-in: turn a photograph into 1-bit line art for a letterpress plate.

Filters > Artistic > Letterpress Line Art...

The current image is flattened onto white, converted to greyscale, resampled
from its print resolution to the output resolution, and drawn as black lines
on white with a difference of Gaussians edge finder (lineart_core for the
settings, GEGL for the per-pixel work, so numpy is not needed). Specks and
lines or gaps too fine to etch are cleaned up, and the result opens as a new
1-bit (black/white indexed) image ready to export as TIFF for platemaking.
"""

import os
import sys

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp, GimpUi, GLib, GObject  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROC_NAME = "plug-in-letterpress-lineart"

SHADING_LABELS = (
    ("none", "None (outlines only)"),
    ("hatch", "Hatching"),
    ("cross", "Cross-hatching"),
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
    """Convert to a black/white indexed image (same as the halftone plug-in). Returns None, or the errors seen.

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


class LetterpressLineArt(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC_NAME]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        proc = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        proc.set_image_types("RGB*, GRAY*, INDEXED*")
        proc.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE | Gimp.ProcedureSensitivityMask.DRAWABLES)
        proc.set_menu_label("Letterpress _Line Art...")
        proc.add_menu_path("<Image>/Filters/Artistic")
        proc.set_documentation(
            "Turn a photograph into 1-bit line art for a letterpress plate",
            "Draws the edges of the image as black lines on white, at the output resolution, "
            "and shades darker tones with hatching or cross-hatching. "
            "Line weight is roughly the width of the line along a strong edge; Detail sets how faint "
            "an edge still gets a line. Specks are removed, and lines and gaps narrower than the "
            "minimum width are cleaned up so the plate etches and inks cleanly. "
            "The result opens as a new black/white image.",
            name,
        )
        proc.set_attribution("gimp-halftone-filter contributors", "gimp-halftone-filter contributors", "2026")

        rw = GObject.ParamFlags.READWRITE
        proc.add_double_argument("line-weight", "Line _weight (pt)",
                                 "Width of the line along a strong edge, in points (1/72 inch)", 0.25, 12.0, 1.0, rw)
        proc.add_double_argument("detail", "_Detail", "Higher draws fainter edges; lower keeps only the strongest",
                                 0.0, 100.0, 60.0, rw)
        proc.add_double_argument("simplify", "_Simplify (pt)",
                                 "Smooth away texture and noise smaller than this before finding edges; 0 is off",
                                 0.0, 12.0, 0.5, rw)
        shading = Gimp.Choice.new()
        for i, (nick, label) in enumerate(SHADING_LABELS):
            shading.add(nick, i, label, "")
        proc.add_choice_argument("shading", "Sh_ading", "Shade darker tones with hatch lines", shading, "cross", rw)
        proc.add_double_argument("shade-from", "Shade _from (% dark)",
                                 "Tones darker than this get hatching; more layers come in as the tone darkens",
                                 0.0, 100.0, 45.0, rw)
        proc.add_double_argument("hatch-spacing", "_Hatch spacing (pt)", "Distance between hatch lines, in points",
                                 1.0, 24.0, 4.0, rw)
        proc.add_double_argument("shadows", "Solid s_hadows (% dark)",
                                 "Fill tones at least this dark with solid black; 0 is off", 0.0, 100.0, 0.0, rw)
        proc.add_double_argument("speck", "Remove spec_ks (pt)",
                                 "Drop isolated marks smaller than about this size; 0 is off", 0.0, 24.0, 2.0, rw)
        proc.add_double_argument("min-width", "_Minimum line and gap (pt)",
                                 "Remove lines and fill white gaps narrower than this, so the plate etches cleanly",
                                 0.0, 4.0, 0.5, rw)
        proc.add_double_argument("dpi", "_Output resolution (DPI)", "Plate/film resolution in pixels per inch",
                                 72.0, 5080.0, 1200.0, rw)
        proc.add_double_argument("input-ppi", "_Input resolution (PPI)",
                                 "Resolution of the source image; filled in from Image > Print Size, 0 also uses it",
                                 0.0, 9600.0, 0.0, rw)
        proc.add_boolean_argument("negative", "_Negative (for film)", "Invert the output", False, rw)
        proc.add_boolean_argument("mirror", "Mi_rror (wrong-reading)", "Flip the output horizontally", False, rw)
        return proc

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        import gegl_lineart
        import lineart_core

        if run_mode == Gimp.RunMode.INTERACTIVE:
            GimpUi.init(PROC_NAME)
            # Start from this image's resolution rather than the value
            # remembered from the last image.
            config.set_property("input-ppi", _image_ppi(image))
            dialog = GimpUi.ProcedureDialog.new(procedure, config, "Letterpress Line Art")
            dialog.fill(None)
            if not dialog.run():
                dialog.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
            dialog.destroy()

        get = config.get_property
        dpi = get("dpi")
        ppi = get("input-ppi") or _image_ppi(image)
        settings = lineart_core.Settings(
            dpi, weight=get("line-weight"), detail=get("detail"), simplify=get("simplify"),
            shadows=get("shadows"), speck=get("speck"), min_width=get("min-width"),
            shading=get("shading"), shade_from=get("shade-from"), hatch_spacing=get("hatch-spacing"),
        )

        Gimp.context_push()
        try:
            Gimp.progress_init("Letterpress line art")
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
            Gimp.progress_update(0.2)

            grey = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y' u8", Gegl.AbyssPolicy.CLAMP)
            shadow = layer.get_shadow_buffer()
            gegl_lineart.line_art(grey, w, h, shadow, settings)
            layer.merge_shadow(False)
            layer.update(0, 0, w, h)
            Gimp.progress_update(0.9)
            if get("negative"):
                layer.invert(False)
            if get("mirror"):
                out.flip(Gimp.OrientationType.HORIZONTAL)

            # Two-colour palette so it exports as a true 1-bit file.
            error = _to_bitmap(out)
            if error:  # The plate is already pure black/white.
                Gimp.message("Kept the plate as greyscale (0/255 only); indexed conversion failed: %s" % error)

            out.undo_enable()
            out.get_layers()[0].set_name("Line art %.2g pt detail %d" % (get("line-weight"), round(get("detail"))))
            Gimp.Display.new(out)
            Gimp.displays_flush()
            Gimp.progress_end()
        except Exception as e:
            return _fail(procedure, "Letterpress Line Art failed: %s" % e)
        finally:
            Gimp.context_pop()

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(LetterpressLineArt.__gtype__, sys.argv)
