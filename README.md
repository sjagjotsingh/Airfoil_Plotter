# Airfoil Plotter

A desktop application designed to fetch, visualize, and **export clean SVG airfoil shapes** for use in CAD and engineering design workflows. Ideal for quickly obtaining precise airfoil geometry from online sources.

## 🎯 Main Purpose

The **primary goal** of this tool is to generate **clean, scale-consistent SVG files** of airfoil shapes that can be directly imported into CAD software (e.g., Fusion 360, SolidWorks, FreeCAD) for modeling and fabrication purposes.

## ✈️ Key Features

- **Airfoil Database Access**: Search and fetch airfoil shapes from [airfoiltools.com](http://airfoiltools.com).
- **Accurate Geometry Export**:
  - Export clean **SVG** files with properly scaled and closed paths — ideal for laser cutting, CNC, or 3D modeling.
  - Also supports exporting annotated PNG plots.
- **Interactive GUI**: Simple, user-friendly interface using Tkinter.
- **Aerodynamic Insights**:
  - Automatically fetch XFOIL-based performance metrics like Cl_max, α_stall, α₀, and Cl/Cd from airfoiltools.
- **Responsive & Robust**: Uses multithreading to keep the interface responsive during network operations.

## 📐 CAD-Ready SVG Output

The **SVG export**:
- Includes a closed airfoil path with consistent orientation.
- Is scaled appropriately with a viewBox and stroke for precise import.
- Avoids clutter — no axes, labels, or data points.

This makes it easy to:
- Sketch airfoils in Fusion 360 or SolidWorks.
- Cut airfoils on laser/CNC machines.
- Perform geometry-based simulations.

## 🛠 Requirements

Install dependencies:

```bash
pip install requests beautifulsoup4 matplotlib numpy
````

Python 3.7+ recommended.

## ▶️ Usage

```bash
python Airfoil_Plotter.py
```

1. Type an airfoil name (e.g., `NACA 2412`) and click **Search & Plot**.
2. View and interact with the plot.
3. Export the shape via **Export SVG Shape**.

## 📤 Export Options

| Format | Purpose                          |
| ------ | -------------------------------- |
| PNG    | Visual documentation and sharing |
| SVG    | CAD modeling and manufacturing   |

## 📊 Aerodynamic Data (Optional)

* Select a Reynolds number (e.g., `200000`).
* Click **Fetch Aero Data** to show:

  * Cl\_max
  * α\_stall
  * α₀ (zero-lift AoA)
  * Cl/Cd performance

## 👨‍💻 Author

**Jagjot Sandhu**

## 🌐 Data Source

All data is retrieved from:
[https://airfoiltools.com](https://airfoiltools.com)

## 📜 License

For personal, educational, and engineering use. Refer to airfoiltools.com for any licensing terms on airfoil data.
