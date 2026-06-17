<div align="center">

# Airfoil Plotter

**Search airfoils. Shape geometry. Export CAD-ready outlines.**

A lightweight desktop airfoil workbench for plotting, transforming, analyzing, and exporting airfoil profiles for CAD, CNC, laser cutting, and engineering design.

[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](#requirements)
[![Tkinter GUI](https://img.shields.io/badge/GUI-Tkinter-2B2B2B?style=for-the-badge)](#run)
[![SVG Export](https://img.shields.io/badge/Export-SVG%20%7C%20PNG-13AA52?style=for-the-badge)](#exports)
[![Data Source](https://img.shields.io/badge/Data-AirfoilTools-0A66C2?style=for-the-badge)](#data-source)

</div>

---

## Overview

Airfoil Plotter turns online airfoil coordinate data into practical geometry you can inspect, modify, and export. It fetches profiles from AirfoilTools, plots them in a responsive Tkinter interface, applies real-world transforms, and outputs clean SVG files in millimeter units.

> Built for fast iteration between airfoil selection, visual checking, and CAD-ready export.

---

## What It Does

| Area | Feature |
| --- | --- |
| Search | Fetch and search airfoil profiles from AirfoilTools |
| Plot | Display clean airfoil outlines with optional coordinate markers |
| Transform | Scale chord, adjust thickness, curve by radius, rotate pitch, mirror, and shift origin |
| Export | Save clean SVG outlines or annotated PNG plots |
| Analyze | Fetch XFOIL-based aerodynamic data where available |
| Presets | Includes a modified 30 mm flat-bottom Clark Y-style preset |

---

## Geometry Studio

Every loaded airfoil can be transformed without changing the original coordinate data.

| Control | Effect |
| --- | --- |
| `Chord (mm)` | Sets the final chord length |
| `Radius (mm)` | Curves the airfoil around a camber radius; `0` keeps it straight |
| `Thickness (%)` | Scales thickness around the camber reference |
| `Origin (%)` | Moves the transform origin along the chord |
| `Pitch (deg)` | Rotates the profile by angle of attack |
| `Reverse` | Mirrors the airfoil |
| `Camber line` | Shows the computed camber line |
| `Data box` | Adds geometry metadata to the plot |
| `X/Y grid (mm)` | Controls plot grid spacing |
| `Line width (%)` | Adjusts the outline stroke |

---

## Exports

| Format | Use it for |
| --- | --- |
| `SVG` | CAD import, laser cutting, CNC templates, profile tracing |
| `PNG` | Reports, build notes, screenshots, visual documentation |

SVG exports are designed to be fabrication-friendly:

- millimeter-based `width`, `height`, and `viewBox`
- closed airfoil path
- no axes, labels, grid, or plot decoration
- current transform settings preserved

---

## Quick Start

Install dependencies:

```bash
pip install requests beautifulsoup4 matplotlib numpy
```

Run the app:

```bash
python Airfoil_Plotter.py
```

On Windows with the included virtual environment:

```powershell
.\.venv\Scripts\python.exe .\Airfoil_Plotter.py
```

---

## Workflow

1. Enter an airfoil name, for example `NACA 2412`, `clarky-il`, or `modified clark y`.
2. Click **Search & Plot**.
3. Tune chord, thickness, pitch, radius, grid spacing, or display options.
4. Click **Apply Transform** or press `Enter` in a transform field.
5. Export with **Export SVG Shape** or **Export PNG**.

---

## Aerodynamic Data

When AirfoilTools has polar data for the selected profile and Reynolds number, the app can display:

| Metric | Meaning |
| --- | --- |
| `Re` | Reynolds number |
| `Cl_max` | Maximum lift coefficient |
| Stall angle | Approximate angle near maximum lift |
| Zero-lift angle | Angle where lift crosses zero |
| Moment coefficient | Pitching moment data |
| Best `Cl/Cd` | Lift-to-drag efficiency point |

---

## Built-In Preset

The app includes a generated **Modified Clark Y (30 mm flat bottom)** preset:

| Property | Value |
| --- | --- |
| Chord | `30 mm` |
| Max thickness | `2.0 mm` |
| Leading edge radius | `0.8 mm` |
| Trailing edge thickness | `0.5 mm` |
| Max thickness point | `9 mm from leading edge` |
| Flat bottom | `yes` |

Search for `modified clark y` to plot it.

---

## Requirements

- Python 3.7+
- `requests`
- `beautifulsoup4`
- `matplotlib`
- `numpy`

---

## Data Source

Airfoil coordinates and available aerodynamic data are retrieved from:

[https://airfoiltools.com](https://airfoiltools.com)

Data availability depends on the source site and selected Reynolds number.

---

## Author

Created by **Jagjot Sandhu**.

---

## License

For personal, educational, and engineering use. Refer to AirfoilTools for terms related to downloaded source data.
