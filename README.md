# Letterpress Halftone for GIMP

A GIMP 3 plug-in that turns a greyscale (or colour) image into a clean 1-bit
AM halftone suitable for making a letterpress plate, such as a photopolymer
plate exposed from film or a laser-imaged plate.

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
   dot drop to clean paper, and shadow holes that would fill in go solid,
   or both are held at the limit if you prefer.
5. Screens with a rotated spot-function threshold. Thresholds are ranked by
   area, so ink coverage matches the tone for every dot shape (within about
   0.5% in the tests).
6. Opens the result as a new black/white indexed image at the output DPI,
   ready for *File > Export As* to TIFF or PNG.

## Options

| Option | Default | Notes |
| --- | --- | --- |
| Screen frequency (LPI) | 85 | 65 to 100 LPI suits most photopolymer letterpress plates. Coarser holds up better on soft paper. |
| Output resolution (DPI) | 1200 | Match your imagesetter, film printer or platesetter. Keep DPI at least 10 times LPI: a cell gives about (DPI / LPI)² grey levels. |
| Input resolution (PPI) | 0 | 0 uses the image's print size. Set it to override. |
| Screen angle | 45° | 45° hides the pattern best for a single colour. |
| Dot shape | Round | Round, Euclidean, Elliptical/chain, Square, Diamond, Line. Euclidean and Elliptical give smoother midtones. |
| Dot gain at 50% (%) | 0 | Measure from a printed test strip. Letterpress commonly gains 10 to 20 points. |
| Minimum dot (%) | 3 | Smallest dot your plate holds and inks reliably. |
| Maximum dot (%) | 95 | Largest dot that still keeps a hole open on press. |
| Hold min/max dots | Off | On keeps the limit dot instead of dropping to paper or solid. |
| Negative (for film) | Off | Inverts the output, e.g. for a film negative to expose photopolymer. |
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

The plug-in needs **numpy** in the Python that GIMP uses. Linux distribution
and Flatpak builds usually use a Python that can have numpy installed;
some Windows and macOS bundles do not include it. If numpy is missing the
plug-in says so instead of running.

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
