# Letterpress Halftone and Line Art for GIMP

Two GIMP 3 plug-ins that turn a greyscale (or colour) image into a clean
1-bit image suitable for making a letterpress plate. They are tuned for
etched magnesium and zinc photoengravings, and work for photopolymer too.

- **Letterpress Halftone** screens the image into an AM halftone.
- **Letterpress Line Art** turns a photograph into a line drawing (see
  [below](#letterpress-line-art)).

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
5. Keeps black text and line art solid: the grey anti-aliased fringe around
   black type is snapped to solid black or to the tone beside it, so letters
   print with crisp edges instead of a screened, eaten-into edge.
6. Screens with a rotated spot-function threshold. Thresholds are ranked by
   area, so ink coverage matches the tone for every dot shape (within 1% in
   the tests). The screen is snapped to whole pixels, as hardware RIPs do,
   so the LPI and angle you ask for may shift slightly; the output layer's
   name shows what was used (e.g. 84.9 LPI at 45°).
7. Opens the result as a new black/white indexed image at the output DPI,
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
| Keep text solid | On | Within about 1.5 source pixels of black (darker than about 80%) type or rules, pixels darker than halfway between the nearby black and the nearby light tone become solid, and the rest take that light tone. Soft photo tones are left alone, though hard black edges inside a photo are sharpened the same way. Turn it off for a photo only image if you want every edge screened. |
| Negative (for film) | Off | Inverts the output, if you print your own film negatives. Leave off when sending files to a platemaker. |
| Mirror (wrong-reading) | Off | Flips horizontally if your process needs it. |

## Letterpress Line Art

*Filters > Artistic > Letterpress Line Art...* draws a photograph as black
lines on white, like an ink drawing, so it can be printed from a line plate
with no screen at all.

1. Flattens the image onto white, converts it to greyscale and resamples it
   to the output DPI, as the halftone does, so line widths are real sizes.
2. Simplifies the photo with a median filter, flattening texture and noise
   (skin, grass, film grain) while keeping the edges of shapes sharp.
3. Finds edges with a difference of Gaussians, which puts one line on the
   dark side of each edge and draws thin dark features (hair, wires) as a
   single line. A strong edge gets a line about as wide as the line weight;
   fainter edges get thinner lines.
4. Inks every edge stronger than the Detail setting. Where an edge fades
   out, its line carries on down to half that strength as long as it stays
   joined to the strong part, so outlines don't break up into dashes.
5. Optionally fills the darkest tones solid, for a bolder graphic look.
6. Removes specks: marks smaller than the speck size in both directions.
   Lines are long, so they stay.
7. Smooths the edges, fills white gaps narrower than the minimum width
   (too shallow to stay clean when etched) and removes lines narrower than
   it (they would be undercut and lost), so every line on the plate is at
   least that wide.
8. Opens the result as a new black/white indexed image, ready to export as
   a 1-bit TIFF.

| Option | Default | Notes |
| --- | --- | --- |
| Line weight (pt) | 1.0 | Width of the line along a strong edge, in points (1 pt = 0.35 mm). Larger weights also leave out finer detail, since edges are found at a coarser scale. |
| Detail | 60 | 0 to 100. Higher draws fainter edges (more lines, more texture); lower keeps only the strongest outlines. |
| Simplify (pt) | 0.5 | Smooths away texture and noise smaller than this before looking for edges. Raise it for busy textures like foliage or fabric; 0 is off. |
| Solid shadows (% dark) | 0 (off) | Fills tones at least this dark with solid black, as an illustrator would for deep shadows. 75 to 85 is a good start. |
| Remove specks (pt) | 2.0 | Drops isolated marks smaller than this across. Raise it to clean up texture further; 0 keeps everything. |
| Minimum line and gap (pt) | 0.5 | Lines narrower than this are removed and white gaps narrower than this are filled. 0.5 pt (0.18 mm) is safe for etched magnesium; photopolymer can go a little finer. |
| Output resolution (DPI) | 1200 | Match your imagesetter, film printer or platesetter. |
| Input resolution (PPI) | from image | Filled in from *Image > Print Size* each time the dialog opens. Set the print size first: line weights are measured on the printed size. |
| Negative (for film) | Off | Inverts the output. |
| Mirror (wrong-reading) | Off | Flips horizontally. |

Tips: start from a photo with clear lighting and a plain background. If
there are too many small lines, lower Detail or raise Simplify; if outlines
are broken, raise Detail. A 4 x 6 inch plate at 1200 DPI takes 10 to 20
seconds.

## Install (GIMP 3.0 or later)

GIMP 3 loads Python plug-ins from a folder with the same name as the script.
Copy the whole `letterpress-halftone` folder, and the `letterpress-lineart`
folder if you want the line art filter, into your plug-ins directory (shown
in *Edit > Preferences > Folders > Plug-ins*):

- Linux: `~/.config/GIMP/3.0/plug-ins/`
- macOS: `~/Library/Application Support/GIMP/3.0/plug-ins/`
- Windows: `%APPDATA%\GIMP\3.0\plug-ins\`

On Linux and macOS make sure `letterpress-halftone.py` and
`letterpress-lineart.py` are executable (`chmod +x`). Restart GIMP and look
under *Filters > Distorts > Letterpress Halftone...* and *Filters > Artistic
> Letterpress Line Art...*.

Nothing else needs installing: the plug-ins use only the Python and GEGL
that ship with GIMP, so it works with the standard Windows installer.
A 4 x 6 inch plate at 1200 DPI takes a few seconds.

## Without GIMP

The same engine is available from the command line (needs numpy and Pillow):

```
python3 tools/halftone_cli.py photo.png plate.tif --lpi 85 --dpi 1200 \
    --dot-gain 15 --min-dot 3 --max-dot 95 --shape euclidean
```

The line art filter has a command line version too. It runs the same GEGL
code as the plug-in, so it needs Pillow and GEGL's Python bindings
(`gir1.2-gegl-0.4` and `python3-gi` on Debian/Ubuntu):

```
python3 tools/lineart_cli.py photo.jpg plate.tif --weight 1 --detail 60 \
    --simplify 0.5 --shadows 80
```

## Tests

```
pip install numpy pytest
python3 -m pytest tests
```

`tests/test_gegl_screen.py` also checks the GEGL path against the numpy
reference pixel for pixel, and `tests/test_gegl_lineart.py` checks the line
art filter's line widths, speck removal and minimum line width; both are
skipped unless GEGL's Python bindings are installed (`gir1.2-gegl-0.4` and
`python3-gi` on Debian/Ubuntu).
