# Letterpress Halftone for GIMP

A GIMP 3 plug-in that turns a greyscale (or colour) image into a clean 1-bit
AM halftone suitable for making a letterpress plate. It is tuned for etched
magnesium and zinc photoengravings, and works for photopolymer too.

GIMP's built-in *Newsprint* filter is meant for effects. This plug-in is
meant for production: it works at the plate's real resolution, prints the
tone value you ask for, and keeps dots inside the range a plate can hold.

## What it does

1. Flattens the image onto white and converts it to greyscale.
2. Resamples it from its print resolution (*Image > Print Size*) to the
   output DPI, so the dots land on real device pixels.
3. Pre-compensates for press dot gain, so a 50% grey prints as 50% rather
   than plate 50% plus gain.
4. Clamps tones to the printable range: highlight dots below the minimum
   dot and shadow holes that would fill in are held at the limit dot, or
   dropped to clean paper and solid if you prefer.
5. Screens with a rotated spot-function threshold. Thresholds are ranked by
   area, so ink coverage matches the tone for every dot shape (within 1% in
   the tests). The screen is snapped to whole pixels, as hardware RIPs do,
   so the LPI and angle you ask for may shift slightly; the output layer's
   name shows what was used (e.g. 84.9 LPI at 45°).
6. Opens the result as a new black/white indexed image at the output DPI,
   ready for *File > Export As* to TIFF (1-bit) to send to your platemaker.

## Options

| Option | Default | Notes |
| --- | --- | --- |
| Screen frequency (LPI) | 85 | 65 to 100 LPI suits etched magnesium; zinc and copper can hold a little finer. Coarser holds up better on soft paper. |
| Output resolution (DPI) | 1200 | Match your imagesetter, film printer or platesetter. Keep DPI at least 10 times LPI: a cell gives about (DPI / LPI)² grey levels. |
| Input resolution (PPI) | from image | Filled in from the image's print resolution each time the dialog opens. Change it to override. |
| Screen angle | 45° | 45° hides the pattern best for a single colour. |
| Dot shape | Round | Round, Euclidean, Elliptical/chain, Square, Diamond, Line. Euclidean and Elliptical give smoother midtones. |
| Dot gain at 50% (%) | 10 | Net change at a 50% dot from etching plus printing. Etching sharpens (shrinks) dots and printing spreads them, so measure from a printed test strip. Negative values grow the plate dots instead. |
| Minimum dot (%) | 5 | Smallest dot that survives etching without being undercut away. |
| Maximum dot (%) | 90 | Largest dot that still keeps a hole deep enough not to fill with ink. |
| Hold min/max dots | On | Keeps the limit dot instead of dropping to paper or solid. Off gives clean paper in the highlights and solid shadows, but crushed photo shadows can turn into black blotches. |
| Negative (for film) | Off | Inverts the output, if you print your own film negatives. Leave off when sending files to a platemaker. |
| Mirror (wrong-reading) | Off | Flips horizontally if your process needs it. |

## Install (GIMP 3.0 or later)

GIMP 3 loads Python plug-ins from a folder with the same name as the script.
Copy the whole `letterpress-halftone` folder into your plug-ins directory
(shown in *Edit > Preferences > Folders > Plug-ins*):

- Linux: `~/.config/GIMP/3.0/plug-ins/`
- macOS: `~/Library/Application Support/GIMP/3.0/plug-ins/`
- Windows: `%APPDATA%\GIMP\3.0\plug-ins\`

On Linux and macOS make sure `letterpress-halftone.py` is executable
(`chmod +x`). Restart GIMP and look under *Filters > Distorts > Letterpress
Halftone...*.

Nothing else needs installing: the plug-in uses only the Python and GEGL
that ship with GIMP, so it works with the standard Windows installer.
A 4 x 6 inch plate at 1200 DPI takes a few seconds.

## Without GIMP

The same engine is available from the command line (needs numpy and Pillow):

```
python3 tools/halftone_cli.py photo.png plate.tif --lpi 85 --dpi 1200 \
    --dot-gain 15 --min-dot 3 --max-dot 95 --shape euclidean
```

## Tests

```
pip install numpy pytest
python3 -m pytest tests
```

`tests/test_gegl_screen.py` also checks the GEGL path against the numpy
reference pixel for pixel; it is skipped unless GEGL's Python bindings are
installed (`gir1.2-gegl-0.4` and `python3-gi` on Debian/Ubuntu).
