"""
Airfoil Plotter
================

A desktop application for fetching, plotting, and analyzing airfoil data.

Author: Jagjot Sandhu

Features:
---------
-   Online Database: Fetches an extensive list of airfoils directly from airfoiltools.com.
-   Dynamic Search: Search for airfoils by name with intelligent suggestions for close matches.
-   Interactive Plotting: Visualize airfoil shapes with options to show or hide coordinate points.
-   Aerodynamic Data: Fetch and display key aerodynamic performance metrics (Cl_max, Cm, etc.) for various Reynolds numbers using XFOIL data from airfoiltools.com.
-   Data Export:
    -   Export high-quality plots as PNG images with adjustable DPI.
    -   Export the clean airfoil shape (without axes or dots) as an SVG file, perfect for use in CAD or other design software.
-   Robust and Responsive: Uses multi-threading for network operations to keep the UI responsive.
-   User-Friendly Interface: Built with Tkinter for a simple and intuitive user experience.

Dependencies:
-------------
-   requests
-   beautifulsoup4
-   matplotlib
-   numpy
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, Toplevel, Listbox, Scrollbar, filedialog, simpledialog
from urllib.parse import unquote, quote, urljoin
import threading
from queue import Queue, Empty
import re
import io
import csv
import difflib
import numpy as np
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- Configuration ---
UI_BACKGROUND_COLOR = '#f0f0f0' # Standard UI grey
UI_TEXT_COLOR = 'black'
UI_FIELD_BACKGROUND = 'white'
UI_SELECT_BACKGROUND = '#cce6ff'

AIRFOILTOOLS_BASE_URL = "http://airfoiltools.com"
AIRFOILTOOLS_SEARCH_PAGE_URL = f"{AIRFOILTOOLS_BASE_URL}/search/airfoils"
MAX_AF_LIST_PAGES_TO_SCRAPE = 15 # Limit scraping to prevent excessive requests

CUSTOM_AIRFOIL_SPECS = {
    "modified_clark_y_30mm": {
        "display_name": "Modified Clark Y (30 mm flat bottom)",
        "internal_name": "Modified Clark Y 30mm Flat Bottom",
        "aliases": (
            "modified clark y",
            "clark y modified",
            "mod clark y",
            "custom clark y",
            "modified clark-y",
        ),
        "chord_mm": 30.0,
        "max_thickness_mm": 2.0,
        "max_camber_mm": 1.0,
        "leading_edge_radius_mm": 0.8,
        "trailing_edge_thickness_mm": 0.5,
        "max_thickness_x_mm": 9.0,
        "flat_bottom": True,
    }
}

PLOT_COLOR_OPTIONS = {
    "Blue": "blue",
    "Red": "red",
    "Black": "black",
    "Green": "green",
    "Purple": "purple",
}


def normalize_airfoil_key(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def build_custom_airfoil_entries():
    entries = {}
    for custom_id, spec in CUSTOM_AIRFOIL_SPECS.items():
        names = (spec["display_name"], custom_id, *spec.get("aliases", ()))
        airfoil_info = {
            "display_name": spec["display_name"],
            "details_page_suffix": None,
            "dat_file_url_suffix": None,
            "airfoil_slug_at_site": None,
            "custom_airfoil_id": custom_id,
        }
        for name in names:
            entries[normalize_airfoil_key(name)] = airfoil_info
    return entries


def generate_modified_clark_y_coordinates(spec):
    """
    Generates a flat-bottom modified Clark Y outline in millimeters.
    The lower surface is flat after the leading-edge radius.
    """
    chord = spec["chord_mm"]
    max_thickness = spec["max_thickness_mm"]
    leading_radius = spec["leading_edge_radius_mm"]
    trailing_edge_thickness = spec["trailing_edge_thickness_mm"]
    max_thickness_x = spec["max_thickness_x_mm"]

    def smoothstep(u):
        return (3 * u ** 2) - (2 * u ** 3)

    center_x = leading_radius
    center_y = leading_radius

    upper_arc_theta = np.linspace(np.pi, np.pi / 2, 18)
    upper_arc_x = center_x + leading_radius * np.cos(upper_arc_theta)
    upper_arc_y = center_y + leading_radius * np.sin(upper_arc_theta)

    upper_ramp_x = np.linspace(leading_radius, max_thickness_x, 42)[1:]
    upper_ramp_u = (upper_ramp_x - leading_radius) / (max_thickness_x - leading_radius)
    upper_ramp_y = (2 * leading_radius) + (max_thickness - 2 * leading_radius) * smoothstep(upper_ramp_u)

    upper_aft_x = np.linspace(max_thickness_x, chord, 82)[1:]
    upper_aft_u = (upper_aft_x - max_thickness_x) / (chord - max_thickness_x)
    upper_aft_y = trailing_edge_thickness + (max_thickness - trailing_edge_thickness) * (1 - smoothstep(upper_aft_u))

    upper_x_forward = np.concatenate([upper_arc_x, upper_ramp_x, upper_aft_x])
    upper_y_forward = np.concatenate([upper_arc_y, upper_ramp_y, upper_aft_y])

    lower_arc_theta = np.linspace(np.pi, 3 * np.pi / 2, 18)
    lower_arc_x = center_x + leading_radius * np.cos(lower_arc_theta)
    lower_arc_y = center_y + leading_radius * np.sin(lower_arc_theta)

    lower_flat_x = np.linspace(leading_radius, chord, 92)[1:]
    lower_flat_y = np.zeros_like(lower_flat_x)

    lower_x = np.concatenate([lower_arc_x, lower_flat_x]).tolist()
    lower_y = np.concatenate([lower_arc_y, lower_flat_y]).tolist()

    return (
        spec["internal_name"],
        upper_x_forward[::-1].tolist(),
        upper_y_forward[::-1].tolist(),
        lower_x,
        lower_y,
    )

# --- Core Data Fetching and Parsing Logic ---

def parse_airfoil_data(data_content, airfoil_name_for_context="file"):
    """
    Parses the text content of an airfoil .dat file into coordinates.
    Handles both blank-line separated and single-block file formats.
    """
    stripped_content = data_content.strip()
    if not stripped_content: return "Unknown (empty content)", [], [], [], []

    lines = stripped_content.split('\n')
    if not lines: return "Unknown (no lines)", [], [], [], []

    internal_name = lines[0].strip()
    upper_x, upper_y, lower_x, lower_y = [], [], [], []
    parsing_upper_surface, coordinate_lines_started = True, False

    start_line_index = 1
    # Heuristic to skip the line with point counts if it exists
    if len(lines) > start_line_index + 1:
        potential_counts_line_text = lines[start_line_index].strip()
        parts = potential_counts_line_text.split()
        if len(parts) == 2:
            try:
                float(parts[0])
                float(parts[1])
                if lines[start_line_index + 1].strip() == "":
                    start_line_index += 1
            except ValueError:
                pass

    for line_number in range(start_line_index, len(lines)):
        line = lines[line_number].strip()

        if not line:
            if coordinate_lines_started and parsing_upper_surface and upper_x:
                parsing_upper_surface = False
            continue

        try:
            parts = line.split()
            if len(parts) >= 2:
                x_coord, y_coord = float(parts[0]), float(parts[1])
                if not coordinate_lines_started:
                    coordinate_lines_started = True

                if parsing_upper_surface:
                    upper_x.append(x_coord)
                    upper_y.append(y_coord)
                else:
                    lower_x.append(x_coord)
                    lower_y.append(y_coord)
        except (ValueError, IndexError):
            pass
            
    if upper_x and not lower_x and len(upper_x) > 2:
        print(f"  Info: No blank line separator found for '{airfoil_name_for_context}'. Assuming single-block format.")
        try:
            min_x_val = min(upper_x)
            min_x_index = upper_x.index(min_x_val)
            
            lower_x = upper_x[min_x_index:]
            lower_y = upper_y[min_x_index:]
            
            upper_x = upper_x[:min_x_index + 1]
            upper_y = upper_y[:min_x_index + 1]
        except ValueError:
            print(f"  Warning: Could not perform leading-edge split for '{airfoil_name_for_context}'.")

    if not coordinate_lines_started:
        print(f"  Warning: No valid coordinate data parsed for {airfoil_name_for_context}.")

    return internal_name, upper_x, upper_y, lower_x, lower_y

# --- Other Helper Functions (unchanged) ---

def get_airfoil_list_from_airfoiltools_threaded(results_dict, key_name_in_results):
    print(f"Thread: Fetching airfoil list (up to {MAX_AF_LIST_PAGES_TO_SCRAPE} pages)...")
    airfoils_data = {}
    error_detail = None
    current_page_url = AIRFOILTOOLS_SEARCH_PAGE_URL
    page_count = 0
    while current_page_url and page_count < MAX_AF_LIST_PAGES_TO_SCRAPE:
        page_count += 1
        print(f"Thread: Scraping AirfoilTools page {page_count}")
        try:
            response = requests.get(current_page_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            for link in soup.find_all('a', href=re.compile(r'/airfoil/details\?airfoil=')):
                display_name = link.get_text(strip=True)
                if not display_name or "gif" in display_name.lower() or "image" in display_name.lower():
                    continue
                href = link['href']
                try:
                    slug = unquote(href.split('airfoil=')[1].split('&')[0])
                except IndexError:
                    continue
                base_name_for_key = slug
                if base_name_for_key.lower().endswith("-il"): base_name_for_key = base_name_for_key[:-3]
                elif base_name_for_key.lower().endswith("-uiuc"): base_name_for_key = base_name_for_key[:-5]
                normalized_key = normalize_airfoil_key(base_name_for_key)
                if normalized_key and normalized_key not in airfoils_data:
                    airfoils_data[normalized_key] = {
                        'display_name': display_name,
                        'details_page_suffix': href,
                        'dat_file_url_suffix': f"/airfoil/seligdatfile?airfoil={quote(slug)}",
                        'airfoil_slug_at_site': slug
                    }
            next_page_tag = soup.find('a', string=re.compile(r'Next Page\s*>>', re.I))
            current_page_url = urljoin(AIRFOILTOOLS_BASE_URL, next_page_tag['href']) if next_page_tag and next_page_tag.get('href') else None
        except requests.exceptions.RequestException as e:
            error_detail = f"Network error on page {page_count}: {e}"; break
        except Exception as e:
            error_detail = f"Error parsing page {page_count}: {e}"; break
    if not airfoils_data and not error_detail:
        error_detail = "No airfoils found on airfoiltools.com search."
    print(f"Thread: Scraped {len(airfoils_data)} airfoils from airfoiltools.com.")
    results_dict[key_name_in_results] = {'data': airfoils_data, 'error': error_detail}

def download_dat_file_content_threaded(full_dat_file_url, display_name, queue_for_result):
    print(f"Thread: Downloading DAT for {display_name}...")
    content, error = None, None
    try:
        response = requests.get(full_dat_file_url, timeout=15)
        response.raise_for_status()
        if '<!DOCTYPE html>' in response.text[:500].lower():
            error = f"Content for {display_name} is an HTML page, not DAT data."
        else:
            content = response.content.decode('latin-1', errors='ignore')
    except requests.exceptions.RequestException as e:
        error = f"Network error downloading {display_name}: {e}"
    except Exception as e:
        error = f"Unexpected error downloading {display_name}: {e}"
    if error: print(f"Thread: Download failed for {display_name} - {error}")
    queue_for_result.put({'content': content, 'error': error})

def process_csv_polar_data(csv_text):
    reynolds_from_header = "N/A"
    header_lines, data_rows_parsed = [], []
    try:
        f = io.StringIO(csv_text)
        reader = csv.reader(f)
        data_header_found, column_indices = False, {}
        for row in reader:
            if not row or not any(field.strip() for field in row): continue
            current_line_str = " ".join(row)
            if not data_header_found:
                potential_header = [field.strip().lower() for field in row]
                if "alpha" in potential_header and "cl" in potential_header:
                    try:
                        column_indices = {h: potential_header.index(h) for h in ["alpha", "cl", "cd", "cm"]}
                        data_header_found = True
                    except ValueError: return None, "CSV Header Error (Required columns missing)"
                    continue
                else: header_lines.append(current_line_str)
            else:
                try:
                    if len(row) > max(column_indices.values()):
                        data_rows_parsed.append([float(row[column_indices[c]]) for c in ["alpha", "cl", "cd", "cm"]])
                except (ValueError, IndexError): continue
        re_pattern = r"reynolds number\s*[:=]\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)"
        for h_line in header_lines:
            re_match = re.search(re_pattern, h_line.strip(), re.IGNORECASE)
            if re_match:
                re_val_str = re_match.group(1)
                try: reynolds_from_header = f"{float(re_val_str):.2e}"
                except ValueError: reynolds_from_header = re_val_str.strip()
                break
    except Exception as e: return None, f"CSV Parsing Error: {e}"
    if not data_rows_parsed: return None, reynolds_from_header
    data_np = np.array(data_rows_parsed)
    alphas, cls, cds, cms = data_np[:, 0], data_np[:, 1], data_np[:, 2], data_np[:, 3]
    results = {}
    if cls.size > 0:
        idx_cl_max = np.argmax(cls)
        results["Cl_max"] = f"{cls[idx_cl_max]:.4f}"
        results["alpha_stall"] = f"{alphas[idx_cl_max]:.2f}°"
    else: return None, reynolds_from_header
    sign_changes = np.where(np.diff(np.sign(cls)))[0]
    alpha0_found = False
    for idx in sign_changes:
        cl1, cl2 = cls[idx], cls[idx + 1]
        alpha1, alpha2 = alphas[idx], alphas[idx + 1]
        if (cl1 * cl2 < 0):
            alpha0_cand = np.interp(0, [cl1, cl2], [alpha1, alpha2])
            results["alpha_0"] = f"{alpha0_cand:.2f}°"
            results["Cm_at_alpha0"] = f"{np.interp(alpha0_cand, alphas, cms):.4f}"
            alpha0_found = True
            break
    if not alpha0_found:
        idx_min_abs_cl = np.argmin(np.abs(cls))
        results["alpha_0"] = f"~{alphas[idx_min_abs_cl]:.2f}° (Cl={cls[idx_min_abs_cl]:.3f})"
        results["Cm_at_alpha0"] = f"{cms[idx_min_abs_cl]:.4f}"
    valid_indices = cds > 1e-6
    if np.any(valid_indices):
        cls_v, cds_v = cls[valid_indices], cds[valid_indices]
        if cls_v.size == cds_v.size > 0:
            cl_cd_ratio = cls_v / cds_v
            idx_max_ratio = np.argmax(cl_cd_ratio)
            original_idx = np.where(valid_indices)[0][idx_max_ratio]
            results["Max_Cl_Cd"] = f"{cl_cd_ratio[idx_max_ratio]:.2f}"
            results["AoA_at_Max_Cl_Cd"] = f"{alphas[original_idx]:.2f}°"
            results["Cl_at_Max_Cl_Cd"] = f"{cls[original_idx]:.4f}"
            results["Cd_at_Max_Cl_Cd"] = f"{cds[original_idx]:.5f}"
    return results, reynolds_from_header

def fetch_aero_data_from_airfoiltools_threaded(airfoil_slug, reynolds_str, queue_for_result):
    csv_url = f"{AIRFOILTOOLS_BASE_URL}/polar/csv?polar=xf-{quote(airfoil_slug)}-{quote(reynolds_str)}"
    print(f"Thread: Attempting to fetch aero data CSV from: {csv_url}")
    error, processed_data, reynolds_confirmed = None, None, "N/A"
    try:
        response = requests.get(csv_url, timeout=15)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'csv' in content_type or 'text/plain' in content_type:
            csv_text = response.text
            if not csv_text.strip() or "<!DOCTYPE html>" in csv_text[:500].lower():
                error = "Content is HTML or empty, not valid CSV."
            else:
                processed_data, reynolds_confirmed = process_csv_polar_data(csv_text)
                if not processed_data and not error: error = "Could not process data from CSV."
        else: error = f"Unexpected Content-Type '{content_type}'. Expected CSV."
    except requests.exceptions.HTTPError as e: error = f"HTTP error {e.response.status_code}. Data for this Re might not exist."
    except requests.exceptions.RequestException as e: error = f"Request error fetching CSV: {e}"
    except Exception as e: error = f"Unexpected error fetching CSV: {e}"
    if error and not processed_data: print(f"Thread: Final error for aero data of {airfoil_slug} @Re {reynolds_str}: {error}")
    queue_for_result.put({'processed_data': processed_data, 'error': error, 'airfoil_name': airfoil_slug, 'Re_found': reynolds_confirmed})

# --- GUI Application Class ---

class AirfoilPlotterApp:
    def __init__(self, master):
        self.master = master
        master.title("Airfoil Plotter by Jagjot Sandhu")
        master.geometry("1100x800")
        master.configure(bg=UI_BACKGROUND_COLOR)
        self.airfoils_db = {}
        self.available_normalized_names = []
        self.download_queue = Queue()
        self.aero_data_queue = Queue()
        self.current_plotted_airfoil_name = None
        self.current_airfoil_slug_at_site = None
        self.last_plotted_data = None
        self.raw_plotted_data = None
        self.last_plotted_camber_line = None
        self.last_transform_settings = None
        self.setup_ui()
        self._initialize_plot_area()
        self.update_status("Initializing... Please wait.")
        self.load_database_in_thread()

    def setup_ui(self):
        controls_frame = ttk.Frame(self.master, padding="10")
        controls_frame.pack(side=tk.TOP, fill=tk.X)
        main_content_frame = ttk.Frame(self.master, padding="5")
        main_content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.left_panel = ttk.Frame(main_content_frame)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self.plot_frame = ttk.Frame(main_content_frame)
        self.plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(controls_frame, text="Airfoil:").grid(row=0, column=0, padx=2, pady=2, sticky="w")
        self.airfoil_entry_var = tk.StringVar()
        self.airfoil_entry = ttk.Entry(controls_frame, textvariable=self.airfoil_entry_var, width=20)
        self.airfoil_entry.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        self.airfoil_entry.bind("<Return>", self.search_and_plot_airfoil)
        self.search_button = ttk.Button(controls_frame, text="Search & Plot", command=self.search_and_plot_airfoil, state=tk.DISABLED)
        self.search_button.grid(row=0, column=2, padx=(5,2), pady=2)
        self.list_button = ttk.Button(controls_frame, text="List All Airfoils", command=self.list_all_airfoils, state=tk.DISABLED)
        self.list_button.grid(row=0, column=3, padx=2, pady=2)
        self.export_button = ttk.Button(controls_frame, text="Export PNG", command=self.export_plot_as_png, state=tk.DISABLED)
        self.export_button.grid(row=0, column=4, padx=(15, 2), pady=2)
        self.export_svg_button = ttk.Button(controls_frame, text="Export SVG Shape", command=self.export_plot_as_svg_shape, state=tk.DISABLED)
        self.export_svg_button.grid(row=0, column=5, padx=2, pady=2)
        ttk.Label(controls_frame, text="Reynolds No:").grid(row=1, column=0, padx=2, pady=2, sticky="w")
        self.reynolds_var = tk.StringVar()
        self.reynolds_options = ["50000", "100000", "200000", "500000", "1000000"]
        self.reynolds_combobox = ttk.Combobox(controls_frame, textvariable=self.reynolds_var, values=self.reynolds_options, width=15, state="readonly")
        self.reynolds_combobox.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        self.reynolds_combobox.set("200000")
        self.fetch_aero_button = ttk.Button(controls_frame, text="Fetch Aero Data", command=self.initiate_fetch_aero_data, state=tk.DISABLED)
        self.fetch_aero_button.grid(row=1, column=2, padx=(5,2), pady=2)
        self.markers_visible_var = tk.BooleanVar(value=False)
        self.toggle_dots_button = ttk.Checkbutton(controls_frame, text="Show Points", variable=self.markers_visible_var, command=self.on_toggle_markers)
        self.toggle_dots_button.grid(row=1, column=3, padx=2, pady=2, sticky="w")
        self.quit_button = ttk.Button(controls_frame, text="Quit", command=self.master.quit)
        self.quit_button.grid(row=0, column=6, rowspan=2, padx=(20, 2), pady=2, sticky="e")
        controls_frame.columnconfigure(6, weight=1)
        suggestions_frame = ttk.LabelFrame(self.left_panel, text="Suggestions", padding="5")
        suggestions_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 5))
        listbox_container = ttk.Frame(suggestions_frame)
        listbox_container.pack(fill=tk.BOTH, expand=True)
        suggestions_scrollbar = ttk.Scrollbar(listbox_container, orient=tk.VERTICAL)
        suggestions_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.suggestions_listbox = Listbox(listbox_container, width=35, height=10, exportselection=False, yscrollcommand=suggestions_scrollbar.set, bg=UI_FIELD_BACKGROUND, fg=UI_TEXT_COLOR, selectbackground=UI_SELECT_BACKGROUND, selectforeground=UI_TEXT_COLOR)
        self.suggestions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        suggestions_scrollbar.config(command=self.suggestions_listbox.yview)
        self.suggestions_listbox.bind("<Double-Button-1>", lambda e: self.plot_selected_suggestion())
        self.plot_suggestion_button = ttk.Button(suggestions_frame, text="Plot Selected Suggestion", command=self.plot_selected_suggestion, state=tk.DISABLED)
        self.plot_suggestion_button.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        transform_frame = ttk.LabelFrame(self.left_panel, text="Transform", padding="8")
        transform_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        self.chord_mm_var = tk.StringVar(value="30")
        self.camber_radius_mm_var = tk.StringVar(value="0")
        self.thickness_pct_var = tk.StringVar(value="100")
        self.origin_pct_var = tk.StringVar(value="0")
        self.pitch_deg_var = tk.StringVar(value="0")
        self.x_grid_mm_var = tk.StringVar(value="10")
        self.y_grid_mm_var = tk.StringVar(value="10")
        self.line_thickness_pct_var = tk.StringVar(value="100")
        self.color_var = tk.StringVar(value="Blue")
        transform_fields = [
            ("Chord (mm)", self.chord_mm_var),
            ("Radius (mm)", self.camber_radius_mm_var),
            ("Thickness (%)", self.thickness_pct_var),
            ("Origin (%)", self.origin_pct_var),
            ("Pitch (deg)", self.pitch_deg_var),
            ("X grid (mm)", self.x_grid_mm_var),
            ("Y grid (mm)", self.y_grid_mm_var),
            ("Line width (%)", self.line_thickness_pct_var),
        ]
        for row_index, (label_text, variable) in enumerate(transform_fields):
            ttk.Label(transform_frame, text=label_text).grid(row=row_index, column=0, sticky="e", padx=(0, 5), pady=2)
            entry = ttk.Entry(transform_frame, textvariable=variable, width=10)
            entry.grid(row=row_index, column=1, sticky="ew", pady=2)
            entry.bind("<Return>", lambda _event: self.redraw_current_airfoil())
        ttk.Label(transform_frame, text="Colour").grid(row=len(transform_fields), column=0, sticky="e", padx=(0, 5), pady=2)
        self.color_combobox = ttk.Combobox(transform_frame, textvariable=self.color_var, values=list(PLOT_COLOR_OPTIONS.keys()), width=10, state="readonly")
        self.color_combobox.grid(row=len(transform_fields), column=1, sticky="ew", pady=2)
        self.color_combobox.bind("<<ComboboxSelected>>", lambda _event: self.redraw_current_airfoil())
        self.reverse_var = tk.BooleanVar(value=False)
        self.data_box_visible_var = tk.BooleanVar(value=True)
        self.camber_line_visible_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(transform_frame, text="Reverse", variable=self.reverse_var, command=self.redraw_current_airfoil).grid(row=len(transform_fields) + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(transform_frame, text="Data box", variable=self.data_box_visible_var, command=self.redraw_current_airfoil).grid(row=len(transform_fields) + 2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(transform_frame, text="Camber line", variable=self.camber_line_visible_var, command=self.redraw_current_airfoil).grid(row=len(transform_fields) + 3, column=0, columnspan=2, sticky="w")
        self.transform_button = ttk.Button(transform_frame, text="Apply Transform", command=self.redraw_current_airfoil, state=tk.DISABLED)
        self.transform_button.grid(row=len(transform_fields) + 4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        transform_frame.columnconfigure(1, weight=1)

        aero_data_frame = ttk.LabelFrame(self.left_panel, text="Aerodynamic Data", padding="10")
        aero_data_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.aero_data_labels = {}
        self.aero_data_params = [("Re", "Re:"), ("Cl_max", "Cl_max:"), ("alpha_stall", "α_stall:"), ("alpha_0", "α₀:"), ("Cm_at_alpha0", "Cm₀ (at α₀):"), ("Max_Cl_Cd", "Max Cl/Cd:"), ("AoA_at_Max_Cl_Cd", "AoA @ Max Cl/Cd:"), ("Cl_at_Max_Cl_Cd", "Cl @ Max Cl/Cd:"), ("Cd_at_Max_Cl_Cd", "Cd @ Max Cl/Cd:")]
        for i, (key, text) in enumerate(self.aero_data_params):
            ttk.Label(aero_data_frame, text=text).grid(row=i, column=0, sticky="w", padx=2, pady=1)
            val_var = tk.StringVar(value="-")
            ttk.Label(aero_data_frame, textvariable=val_var, width=20, anchor="w").grid(row=i, column=1, sticky="ew", padx=2, pady=1)
            self.aero_data_labels[key] = val_var
        ttk.Label(aero_data_frame, text="Source: airfoiltools.com (XFOIL)", font=("Arial", 8)).grid(row=len(self.aero_data_params), column=0, columnspan=2, sticky="w", pady=(8, 0))
        aero_data_frame.columnconfigure(1, weight=1)
        self.fig = plt.Figure(figsize=(7, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self.master, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding="2")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _style_plot_for_grey_bg(self):
        self.ax.set_facecolor(UI_BACKGROUND_COLOR)
        self.fig.set_facecolor(UI_BACKGROUND_COLOR)
        for spine in self.ax.spines.values():
            spine.set_edgecolor(UI_TEXT_COLOR)
        self.ax.xaxis.label.set_color(UI_TEXT_COLOR)
        self.ax.yaxis.label.set_color(UI_TEXT_COLOR)
        self.ax.tick_params(axis='x', colors=UI_TEXT_COLOR)
        self.ax.tick_params(axis='y', colors=UI_TEXT_COLOR)
        self.ax.title.set_color(UI_TEXT_COLOR)
        self.ax.grid(True, color='darkgray')

    def _initialize_plot_area(self, clear_aero_data=True):
        self.ax.clear()
        self.ax.set_xlabel("X-coordinate")
        self.ax.set_ylabel("Y-coordinate")
        self.ax.set_title("Airfoil Plot Area")
        self._style_plot_for_grey_bg()
        self.ax.axis('equal')
        self.canvas.draw_idle()
        self.current_plotted_airfoil_name = None
        self.last_plotted_data = None
        self.raw_plotted_data = None
        self.last_plotted_camber_line = None
        self.last_transform_settings = None
        self.current_airfoil_slug_at_site = None
        self.export_button.config(state=tk.DISABLED)
        self.export_svg_button.config(state=tk.DISABLED)
        self.fetch_aero_button.config(state=tk.DISABLED)
        self.transform_button.config(state=tk.DISABLED)
        if clear_aero_data:
            self._clear_aero_data_display()

    def _clear_aero_data_display(self):
        for key in self.aero_data_labels:
            self.aero_data_labels[key].set("-")

    def update_status(self, msg):
        self.status_var.set(msg)
        print(f"Status: {msg}")

    def load_database_in_thread(self):
        self.update_status("Fetching airfoil list from airfoiltools.com...")
        self.set_ui_state_for_processing(True)
        self.threaded_db_results = {}
        thread = threading.Thread(target=get_airfoil_list_from_airfoiltools_threaded, args=(self.threaded_db_results, "airfoiltools"))
        thread.daemon = True
        thread.start()
        self.master.after(100, self.check_database_load_completion)

    def check_database_load_completion(self):
        result = self.threaded_db_results.get("airfoiltools")
        if result is None:
            self.master.after(100, self.check_database_load_completion)
            return
        fetched_airfoils = result.get('data', {})
        custom_airfoils = build_custom_airfoil_entries()
        self.airfoils_db = {**fetched_airfoils, **custom_airfoils}
        error = result.get('error')
        if error and not fetched_airfoils:
            msg = f"Error fetching airfoil list: {error}"
            self.update_status(msg)
            messagebox.showwarning("Database Warning", f"Could not retrieve online airfoils:\n{msg}\n\nBuilt-in presets are still available.", parent=self.master)
        if not self.airfoils_db:
            msg = "Error: No airfoils found on airfoiltools.com. The site might be down or its structure may have changed."
            self.update_status(msg)
            messagebox.showerror("Database Error", msg, parent=self.master)
            self.set_ui_state_for_processing(False)
            return
        self.available_normalized_names = list(self.airfoils_db.keys())
        self.update_status(f"Loaded {len(fetched_airfoils)} online airfoils and {len(CUSTOM_AIRFOIL_SPECS)} built-in preset(s). Ready.")
        self.set_ui_state_for_processing(False)
        self.search_button.config(state=tk.NORMAL)
        self.list_button.config(state=tk.NORMAL)

    def search_and_plot_airfoil(self, event=None):
        user_input = self.airfoil_entry_var.get().strip()
        if not user_input:
            self.update_status("Please enter an airfoil name to search.")
            return
        normalized_input = normalize_airfoil_key(user_input)
        self.suggestions_listbox.delete(0, tk.END)
        self.plot_suggestion_button.config(state=tk.DISABLED)
        self._initialize_plot_area(clear_aero_data=True)
        target_info = self.airfoils_db.get(normalized_input)
        if target_info:
            display_name = target_info['display_name']
            self.update_status(f"Exact match found for '{user_input}' (Display: {display_name}). Plotting...")
            self._initiate_airfoil_processing(target_info)
        else:
            suggestions = difflib.get_close_matches(normalized_input, self.available_normalized_names, n=15, cutoff=0.45)
            if suggestions:
                self.update_status(f"No exact match for '{user_input}'. Showing suggestions:")
                for s_norm_key in suggestions:
                    s_display_name = self.airfoils_db[s_norm_key]['display_name']
                    self.suggestions_listbox.insert(tk.END, f"{s_display_name} (key: {s_norm_key})")
                self.plot_suggestion_button.config(state=tk.NORMAL)
            else:
                self.update_status(f"No match or close suggestions found for '{user_input}'.")
                messagebox.showinfo("Not Found", f"The airfoil '{user_input}' was not found and no close matches could be suggested.", parent=self.master)

    def _initiate_airfoil_processing(self, airfoil_info):
        custom_airfoil_id = airfoil_info.get("custom_airfoil_id")
        if custom_airfoil_id:
            self._plot_custom_airfoil(custom_airfoil_id)
            return

        display_name = airfoil_info['display_name']
        self.update_status(f"Downloading coordinates for {display_name}...")
        self.set_ui_state_for_processing(True)
        self.current_airfoil_slug_at_site = airfoil_info['airfoil_slug_at_site']
        full_dat_url = urljoin(AIRFOILTOOLS_BASE_URL, airfoil_info['dat_file_url_suffix'])
        thread = threading.Thread(target=download_dat_file_content_threaded, args=(full_dat_url, display_name, self.download_queue))
        thread.daemon = True
        thread.start()
        self.master.after(100, self._check_download_completion, airfoil_info)

    def _plot_custom_airfoil(self, custom_airfoil_id):
        spec = CUSTOM_AIRFOIL_SPECS.get(custom_airfoil_id)
        if not spec:
            messagebox.showerror("Custom Airfoil Error", f"Unknown custom airfoil: {custom_airfoil_id}", parent=self.master)
            return

        self.update_status(f"Plotting built-in airfoil: {spec['display_name']}...")
        self.set_ui_state_for_processing(True)
        self.current_airfoil_slug_at_site = None
        name_int, xu, yu, xl, yl = generate_modified_clark_y_coordinates(spec)
        if self._draw_airfoil_plot(spec["display_name"], name_int, xu, yu, xl, yl):
            self.update_status(
                f"Displayed: {spec['display_name']} at chord {self.last_transform_settings['chord_mm']:g} mm."
            )
        self.set_ui_state_for_processing(False)

    def _check_download_completion(self, airfoil_info):
        try:
            result = self.download_queue.get_nowait()
            dat_content, dl_error = result.get('content'), result.get('error')
            plot_was_successful = False
            if dl_error:
                self.update_status(f"Error downloading {airfoil_info['display_name']}: {dl_error}")
                messagebox.showerror("Download Error", f"Failed to download data for {airfoil_info['display_name']}:\n{dl_error}", parent=self.master)
                self._initialize_plot_area()
            elif dat_content:
                self.update_status(f"Parsing {airfoil_info['display_name']}...")
                name_int, xu, yu, xl, yl = parse_airfoil_data(dat_content, airfoil_info['display_name'])
                if not xu or not xl:
                    self.update_status(f"Failed to parse coordinate data for {airfoil_info['display_name']}.")
                    messagebox.showwarning("Parse Error", f"Could not parse valid coordinates from the data file for {airfoil_info['display_name']}.", parent=self.master)
                    self._initialize_plot_area()
                else:
                    self.update_status(f"Plotting {airfoil_info['display_name']}...")
                    plot_was_successful = self._draw_airfoil_plot(airfoil_info['display_name'], name_int, xu, yu, xl, yl)
            else:
                self.update_status(f"Download for {airfoil_info['display_name']} yielded no content.")
                self._initialize_plot_area()
            if plot_was_successful:
                self.update_status(f"Displayed: {airfoil_info['display_name']}. Auto-fetching aero data...")
                self.initiate_fetch_aero_data(is_auto_fetch=True)
            else:
                self.set_ui_state_for_processing(False)
        except Empty:
            self.master.after(100, self._check_download_completion, airfoil_info)
        except Exception as e:
            msg = f"An internal error occurred: {e}"
            self.update_status(msg); print(repr(e))
            messagebox.showerror("Application Error", msg, parent=self.master)
            self.set_ui_state_for_processing(False)

    def list_all_airfoils(self):
        if not self.airfoils_db:
            messagebox.showinfo("No Data", "The airfoil database has not been loaded yet.", parent=self.master)
            return
        win = Toplevel(self.master)
        win.title("Available Airfoils (from airfoiltools.com)")
        win.geometry("700x500")
        win.configure(bg=UI_BACKGROUND_COLOR)
        sb = ttk.Scrollbar(win, orient=tk.VERTICAL)
        lb = Listbox(win, yscrollcommand=sb.set, width=80, height=25, exportselection=False, bg=UI_FIELD_BACKGROUND, fg=UI_TEXT_COLOR)
        sb.config(command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        names = sorted({d['display_name'] for d in self.airfoils_db.values()})
        for name in names:
            lb.insert(tk.END, name)
        def on_select(evt):
            selection = evt.widget.curselection()
            if selection:
                selected_name = evt.widget.get(selection[0])
                self.airfoil_entry_var.set(selected_name)
                self.update_status(f"Selected '{selected_name}'. Click 'Search & Plot' to continue.")
                win.destroy()
        lb.bind("<Double-Button-1>", on_select)
        ttk.Label(win, text="Double-click an airfoil to select it.").pack(side=tk.BOTTOM, pady=5)
        win.transient(self.master)
        win.grab_set()
        self.master.wait_window(win)

    def plot_selected_suggestion(self):
        selection = self.suggestions_listbox.curselection()
        if not selection:
            self.update_status("No suggestion selected.")
            return
        item_text = self.suggestions_listbox.get(selection[0])
        try:
            norm_name_key = item_text.split('(key: ')[1][:-1]
        except IndexError:
            self.update_status("Error: Could not parse suggestion text.")
            return
        if norm_name_key in self.airfoils_db:
            target_info = self.airfoils_db[norm_name_key]
            self._initialize_plot_area(clear_aero_data=True)
            self._initiate_airfoil_processing(target_info)
        else:
            self.update_status(f"Error: Suggested key '{norm_name_key}' not found in database.")

    def on_toggle_markers(self):
        if self.raw_plotted_data:
            name_d, name_i, xu, yu, xl, yl = self.raw_plotted_data
            if self._draw_airfoil_plot(name_d, name_i, xu, yu, xl, yl):
                self.update_status(f"Markers {'shown' if self.markers_visible_var.get() else 'hidden'}.")

    def redraw_current_airfoil(self):
        if not self.raw_plotted_data:
            return
        name_d, name_i, xu, yu, xl, yl = self.raw_plotted_data
        if self._draw_airfoil_plot(name_d, name_i, xu, yu, xl, yl):
            self.update_status("Transform applied.")

    def _get_transform_settings(self):
        def read_float(variable, label, minimum=None, allow_equal=True):
            raw_value = variable.get().strip()
            try:
                value = float(raw_value)
            except ValueError:
                messagebox.showerror("Invalid Transform Value", f"{label} must be a number.", parent=self.master)
                self.update_status(f"Invalid transform value: {label} must be a number.")
                return None

            if minimum is not None:
                is_too_small = value < minimum if allow_equal else value <= minimum
                if is_too_small:
                    comparator = "at least" if allow_equal else "greater than"
                    messagebox.showerror("Invalid Transform Value", f"{label} must be {comparator} {minimum}.", parent=self.master)
                    self.update_status(f"Invalid transform value: {label} is out of range.")
                    return None
            return value

        chord_mm = read_float(self.chord_mm_var, "Chord (mm)", minimum=0, allow_equal=False)
        camber_radius_mm = read_float(self.camber_radius_mm_var, "Radius (mm)")
        thickness_pct = read_float(self.thickness_pct_var, "Thickness (%)", minimum=0, allow_equal=False)
        origin_pct = read_float(self.origin_pct_var, "Origin (%)")
        pitch_deg = read_float(self.pitch_deg_var, "Pitch (deg)")
        x_grid_mm = read_float(self.x_grid_mm_var, "X grid (mm)", minimum=0)
        y_grid_mm = read_float(self.y_grid_mm_var, "Y grid (mm)", minimum=0)
        line_thickness_pct = read_float(self.line_thickness_pct_var, "Line width (%)", minimum=0, allow_equal=False)

        values = [chord_mm, camber_radius_mm, thickness_pct, origin_pct, pitch_deg, x_grid_mm, y_grid_mm, line_thickness_pct]
        if any(value is None for value in values):
            return None

        return {
            "chord_mm": chord_mm,
            "camber_radius_mm": camber_radius_mm,
            "thickness_pct": thickness_pct,
            "origin_pct": origin_pct,
            "pitch_deg": pitch_deg,
            "x_grid_mm": x_grid_mm,
            "y_grid_mm": y_grid_mm,
            "line_thickness_pct": line_thickness_pct,
            "color": PLOT_COLOR_OPTIONS.get(self.color_var.get(), "blue"),
            "reverse": self.reverse_var.get(),
            "data_box": self.data_box_visible_var.get(),
            "camber_line": self.camber_line_visible_var.get(),
        }

    def _sorted_unique_surface(self, x_values, y_values):
        grouped_y = {}
        grouped_x = {}
        for x_value, y_value in zip(x_values, y_values):
            key = round(float(x_value), 10)
            grouped_x[key] = float(x_value)
            grouped_y.setdefault(key, []).append(float(y_value))

        sorted_keys = sorted(grouped_y.keys())
        unique_x = [grouped_x[key] for key in sorted_keys]
        unique_y = [sum(grouped_y[key]) / len(grouped_y[key]) for key in sorted_keys]
        return np.array(unique_x), np.array(unique_y)

    def _curve_points_for_radius(self, x_mm, y_mm, radius_mm):
        x_mm = np.asarray(x_mm, dtype=float)
        y_mm = np.asarray(y_mm, dtype=float)

        if abs(radius_mm) < 1e-9:
            return x_mm, y_mm

        bend_sign = 1 if radius_mm > 0 else -1
        bend_radius = abs(radius_mm)
        theta = x_mm / bend_radius
        base_x = bend_radius * np.sin(theta)
        base_y = bend_sign * bend_radius * (1 - np.cos(theta))
        normal_x = -bend_sign * np.sin(theta)
        normal_y = np.cos(theta)
        return base_x + y_mm * normal_x, base_y + y_mm * normal_y

    def _apply_final_transforms(self, x_mm, y_mm, settings):
        curved_x, curved_y = self._curve_points_for_radius(x_mm, y_mm, settings["camber_radius_mm"])

        origin_x = settings["chord_mm"] * settings["origin_pct"] / 100.0
        origin_curve_x, origin_curve_y = self._curve_points_for_radius(
            np.array([origin_x]), np.array([0.0]), settings["camber_radius_mm"]
        )
        transformed_x = curved_x - origin_curve_x[0]
        transformed_y = curved_y - origin_curve_y[0]

        if settings["reverse"]:
            transformed_x = -transformed_x

        pitch_radians = np.deg2rad(settings["pitch_deg"])
        cos_pitch = np.cos(pitch_radians)
        sin_pitch = np.sin(pitch_radians)
        rotated_x = transformed_x * cos_pitch - transformed_y * sin_pitch
        rotated_y = transformed_x * sin_pitch + transformed_y * cos_pitch
        return rotated_x, rotated_y

    def _transform_airfoil_coordinates(self, xu, yu, xl, yl, settings):
        upper_x_unique, upper_y_unique = self._sorted_unique_surface(xu, yu)
        lower_x_unique, lower_y_unique = self._sorted_unique_surface(xl, yl)

        if len(upper_x_unique) < 2 or len(lower_x_unique) < 2:
            raise ValueError("Airfoil surfaces do not contain enough unique coordinate points.")

        all_raw_x = np.concatenate([upper_x_unique, lower_x_unique])
        min_x = float(np.min(all_raw_x))
        max_x = float(np.max(all_raw_x))
        raw_chord = max_x - min_x
        if raw_chord <= 0:
            raise ValueError("Airfoil chord length could not be calculated.")

        scale = settings["chord_mm"] / raw_chord
        thickness_factor = settings["thickness_pct"] / 100.0

        def camber_at(raw_x_values):
            upper_interp = np.interp(raw_x_values, upper_x_unique, upper_y_unique)
            lower_interp = np.interp(raw_x_values, lower_x_unique, lower_y_unique)
            return (upper_interp + lower_interp) / 2.0

        def transform_surface(raw_x_values, raw_y_values):
            raw_x_array = np.asarray(raw_x_values, dtype=float)
            raw_y_array = np.asarray(raw_y_values, dtype=float)
            raw_camber = camber_at(raw_x_array)
            adjusted_y = raw_camber + (raw_y_array - raw_camber) * thickness_factor
            x_mm = (raw_x_array - min_x) * scale
            y_mm = adjusted_y * scale
            transformed_x, transformed_y = self._apply_final_transforms(x_mm, y_mm, settings)
            return transformed_x.tolist(), transformed_y.tolist()

        transformed_upper_x, transformed_upper_y = transform_surface(xu, yu)
        transformed_lower_x, transformed_lower_y = transform_surface(xl, yl)

        camber_raw_x = np.linspace(min_x, max_x, 180)
        camber_raw_y = camber_at(camber_raw_x)
        camber_x_mm = (camber_raw_x - min_x) * scale
        camber_y_mm = camber_raw_y * scale
        camber_x, camber_y = self._apply_final_transforms(camber_x_mm, camber_y_mm, settings)

        return transformed_upper_x, transformed_upper_y, transformed_lower_x, transformed_lower_y, camber_x.tolist(), camber_y.tolist()

    def _apply_grid_spacing(self, settings):
        def apply_axis_ticks(get_limits, set_ticks, spacing):
            if spacing <= 0:
                return
            axis_min, axis_max = get_limits()
            start = np.floor(axis_min / spacing) * spacing
            end = np.ceil(axis_max / spacing) * spacing
            tick_count = int(round((end - start) / spacing)) + 1
            if tick_count <= 1 or tick_count > 200:
                return
            set_ticks(np.arange(start, end + spacing * 0.5, spacing))

        apply_axis_ticks(self.ax.get_xlim, self.ax.set_xticks, settings["x_grid_mm"])
        apply_axis_ticks(self.ax.get_ylim, self.ax.set_yticks, settings["y_grid_mm"])

    def _draw_airfoil_plot(self, name_display, name_internal, xu, yu, xl, yl):
        settings = self._get_transform_settings()
        if settings is None:
            return False

        try:
            txu, tyu, txl, tyl, camber_x, camber_y = self._transform_airfoil_coordinates(xu, yu, xl, yl, settings)
        except ValueError as exc:
            messagebox.showerror("Transform Error", str(exc), parent=self.master)
            self.update_status(f"Transform error: {exc}")
            return False

        self.ax.clear()
        self._style_plot_for_grey_bg()
        
        # Combine points into a single continuous line as per user suggestion
        if txu and txl and abs(txu[-1] - txl[0]) < 1e-9 and abs(tyu[-1] - tyl[0]) < 1e-9:
            full_x = txu + txl[1:]
            full_y = tyu + tyl[1:]
        else: # Fallback if points don't meet
            full_x = txu + txl
            full_y = tyu + tyl
            
        show_markers = self.markers_visible_var.get()
        style = 'o-' if show_markers else '-'
        marker_size = 3 if show_markers else 0
        line_width = max(0.2, 1.5 * settings["line_thickness_pct"] / 100.0)

        self.ax.plot(full_x, full_y, style, label='Airfoil Outline', markersize=marker_size, linewidth=line_width, color=settings["color"])

        if settings["camber_line"]:
            self.ax.plot(camber_x, camber_y, '--', label='Camber Line', linewidth=1, color='gray')

        title = f'Airfoil: {name_display}'
        if name_internal and name_internal.lower().strip() != name_display.lower().strip():
            title += f' (File: {name_internal})'
        self.ax.set_title(title)
        
        legend = self.ax.legend()
        for text in legend.get_texts():
            text.set_color(UI_TEXT_COLOR)
        legend.get_frame().set_facecolor(UI_BACKGROUND_COLOR)
        legend.get_frame().set_edgecolor('gray')

        if settings["data_box"]:
            details = (
                f"Name = {name_display}\n"
                f"Chord = {settings['chord_mm']:g}mm  Radius = {settings['camber_radius_mm']:g}mm  "
                f"Thickness = {settings['thickness_pct']:g}%\n"
                f"Origin = {settings['origin_pct']:g}%  Pitch = {settings['pitch_deg']:g} deg"
            )
            self.ax.text(0.01, 0.02, details, transform=self.ax.transAxes, fontsize=8, va='bottom', color=settings["color"])

        self.ax.set_xlabel('X (mm)')
        self.ax.set_ylabel('Y (mm)')
        self.ax.axis('equal')
        self._apply_grid_spacing(settings)
        self.canvas.draw_idle()

        self.current_plotted_airfoil_name = name_display
        self.raw_plotted_data = (name_display, name_internal, list(xu), list(yu), list(xl), list(yl))
        self.last_plotted_data = (name_display, name_internal, txu, tyu, txl, tyl)
        self.last_plotted_camber_line = (camber_x, camber_y)
        self.last_transform_settings = settings
        
        self.export_button.config(state=tk.NORMAL)
        self.export_svg_button.config(state=tk.NORMAL)
        self.transform_button.config(state=tk.NORMAL)
        if self.current_airfoil_slug_at_site:
            self.fetch_aero_button.config(state=tk.NORMAL)
        return True

    def export_plot_as_png(self):
        if not self.current_plotted_airfoil_name or not self.ax.lines:
            messagebox.showinfo("Export Error", "There is no plot to export.", parent=self.master)
            return
        dpi = simpledialog.askinteger("Image DPI", "Enter DPI for PNG export:", parent=self.master, initialvalue=300, minvalue=72, maxvalue=1200)
        if dpi is None:
            self.update_status("PNG export cancelled.")
            return
        safe_name = "".join(c for c in self.current_plotted_airfoil_name if c.isalnum() or c in (' ', '_', '-')).rstrip()
        suggested_filename = f"{safe_name.replace(' ', '_')}_{dpi}dpi.png"
        filepath = filedialog.asksaveasfilename(parent=self.master, defaultextension=".png", filetypes=[("PNG files", "*.png"), ("All files", "*.*")], initialfile=suggested_filename, title="Save Plot as PNG")
        if filepath:
            try:
                self.fig.savefig(filepath, dpi=dpi, bbox_inches='tight', facecolor=self.fig.get_facecolor())
                self.update_status(f"Plot saved as PNG: {filepath}")
                messagebox.showinfo("Export Successful", f"Plot saved as PNG:\n{filepath}", parent=self.master)
            except Exception as e:
                messagebox.showerror("Export Error", f"Could not save PNG file:\n{e}", parent=self.master)
        else:
            self.update_status("PNG export cancelled.")

    def export_plot_as_svg_shape(self):
        """Exports the airfoil shape as a clean SVG file using a robust rescaling method."""
        if not self.last_plotted_data:
            messagebox.showinfo("Export Error", "No airfoil data available to export as SVG.", parent=self.master)
            return

        _, _, xu, yu, xl, yl = self.last_plotted_data

        if not (len(xu) > 1 and len(xl) > 1):
            messagebox.showinfo("Export Error", "Incomplete airfoil data, cannot export SVG.", parent=self.master)
            return

        safe_name = "".join(c for c in self.current_plotted_airfoil_name if c.isalnum() or c in (' ', '_', '-')).rstrip()
        suggested_filename = f"{safe_name.replace(' ', '_')}_shape.svg"
        
        filepath = filedialog.asksaveasfilename(parent=self.master, defaultextension=".svg", filetypes=[("SVG files", "*.svg"), ("All files", "*.*")], initialfile=suggested_filename, title="Save Airfoil Shape as SVG")

        if not filepath:
            self.update_status("SVG export cancelled.")
            return
            
        try:
            # Step 1: Create a single, continuous list of (x, y) points for the outline.
            if xu[-1] == xl[0]:
                points = list(zip(xu, yu)) + list(zip(xl[1:], yl[1:]))
            else:
                points = list(zip(xu, yu)) + list(zip(xl, yl))
            
            if not points:
                 messagebox.showerror("Export Error", "Could not create a valid point list for the SVG.", parent=self.master)
                 return

            # Step 2: Calculate the bounding box of the original airfoil data.
            all_x = [p[0] for p in points]
            all_y = [p[1] for p in points]
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            data_width, data_height = max_x - min_x, max_y - min_y

            if data_width <= 0 or data_height <= 0:
                 messagebox.showwarning("Export Warning", "Cannot export SVG for an airfoil with no area.", parent=self.master)
                 return

            # Step 3: Move the already-transformed millimeter coordinates into
            # SVG space while preserving their real dimensions.
            transformed_points = []
            for x, y in points:
                new_x = x - min_x
                new_y = max_y - y
                transformed_points.append(f"{new_x:.3f},{new_y:.3f}")

            # Step 4: Generate the SVG path data from the transformed points.
            path_d = "M " + " L ".join(transformed_points) + " Z"

            stroke_width = 0.05
            if self.last_transform_settings:
                stroke_width = max(0.02, 0.05 * self.last_transform_settings["line_thickness_pct"] / 100.0)

            # Step 5: Create the final SVG content with millimeters as the size unit.
            svg_content = (
                f'<svg width="{data_width:.3f}mm" height="{data_height:.3f}mm" viewBox="0 0 {data_width:.3f} {data_height:.3f}" xmlns="http://www.w3.org/2000/svg">\n'
                f'  <path d="{path_d}" fill="none" stroke="black" stroke-width="{stroke_width:.3f}"/>\n'
                f'</svg>'
            )

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(svg_content)

            self.update_status(f"Airfoil shape saved as SVG: {filepath}")
            messagebox.showinfo("Export Successful", f"Airfoil shape saved as SVG:\n{filepath}", parent=self.master)
        except Exception as e:
            self.update_status(f"Error saving SVG: {e}")
            messagebox.showerror("Export SVG Error", f"Could not save SVG file:\n{e}", parent=self.master)

    def initiate_fetch_aero_data(self, is_auto_fetch=False):
        if not self.current_airfoil_slug_at_site:
            if not is_auto_fetch: messagebox.showwarning("No Airfoil", "An airfoil must be plotted first.", parent=self.master)
            if is_auto_fetch: self.set_ui_state_for_processing(False)
            return
        re_str = self.reynolds_var.get().strip()
        if not re_str:
            errmsg = "No Reynolds number selected."
            if not is_auto_fetch: messagebox.showerror("Invalid Input", errmsg, parent=self.master)
            else: self.update_status(f"{errmsg} Skipping auto-fetch.")
            if is_auto_fetch: self.set_ui_state_for_processing(False)
            return
        self.update_status(f"Fetching aero data for {self.current_plotted_airfoil_name} at Re={re_str}...")
        self._clear_aero_data_display()
        self.aero_data_labels["Re"].set(f"{re_str} (Fetching...)")
        self.fetch_aero_button.config(state=tk.DISABLED)
        thread = threading.Thread(target=fetch_aero_data_from_airfoiltools_threaded, args=(self.current_airfoil_slug_at_site, re_str, self.aero_data_queue))
        thread.daemon = True
        thread.start()
        self.master.after(100, self._check_aero_data_fetch_completion, is_auto_fetch)

    def _check_aero_data_fetch_completion(self, was_auto_fetch=False):
        try:
            result = self.aero_data_queue.get_nowait()
            p_data, error, re_confirmed = result.get('processed_data'), result.get('error'), result.get('Re_found', "N/A")
            if re_confirmed and re_confirmed.strip().lower() != "n/a":
                self.aero_data_labels["Re"].set(re_confirmed)
                re_context = f"(Data Re: {re_confirmed})"
            else:
                self.aero_data_labels["Re"].set(f"{self.reynolds_var.get()} (Not confirmed)")
                re_context = f"(Requested Re: {self.reynolds_var.get()})"
            if error and not p_data:
                msg = f"Aero data error for {result['airfoil_name']} {re_context}: {error}"
                self.update_status(msg)
                if not was_auto_fetch: messagebox.showwarning("Aero Data Error", msg, parent=self.master)
            elif p_data:
                self.update_status(f"Successfully loaded aero data for {result['airfoil_name']} {re_context}.")
                for key, val_str in p_data.items():
                    if key in self.aero_data_labels: self.aero_data_labels[key].set(val_str)
            else:
                msg = f"No specific aero data found for {result['airfoil_name']} {re_context}."
                self.update_status(msg)
                if not was_auto_fetch: messagebox.showinfo("No Aero Data", msg, parent=self.master)
            if was_auto_fetch: self.set_ui_state_for_processing(False)
            else: self.fetch_aero_button.config(state=tk.NORMAL if self.current_airfoil_slug_at_site else tk.DISABLED)
        except Empty:
            self.master.after(100, self._check_aero_data_fetch_completion, was_auto_fetch)
        except Exception as e:
            msg = f"Internal error during aero check: {e}"
            self.update_status(msg); print(repr(e))
            messagebox.showerror("Application Error", msg, parent=self.master)
            if was_auto_fetch: self.set_ui_state_for_processing(False)
            else: self.fetch_aero_button.config(state=tk.NORMAL)

    def set_ui_state_for_processing(self, is_processing):
        state = tk.DISABLED if is_processing else tk.NORMAL
        self.search_button.config(state=state)
        self.list_button.config(state=state)
        self.plot_suggestion_button.config(state=tk.DISABLED if is_processing else tk.NORMAL if self.suggestions_listbox.size() > 0 else tk.DISABLED)
        self.transform_button.config(state=tk.DISABLED if is_processing or not self.raw_plotted_data else tk.NORMAL)
        if not is_processing and self.current_plotted_airfoil_name:
             self.export_button.config(state=tk.NORMAL)
             self.export_svg_button.config(state=tk.NORMAL)
             self.fetch_aero_button.config(state=tk.NORMAL if self.current_airfoil_slug_at_site else tk.DISABLED)
        else:
             self.export_button.config(state=tk.DISABLED)
             self.export_svg_button.config(state=tk.DISABLED)
             self.fetch_aero_button.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    root.configure(bg=UI_BACKGROUND_COLOR)
    try:
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('TFrame', background=UI_BACKGROUND_COLOR)
        style.configure('TLabel', background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('TButton', background='#e0e0e0', foreground=UI_TEXT_COLOR)
        style.map('TButton', background=[('active', '#cccccc')])
        style.configure('TCheckbutton', background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('TLabelframe', background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('TLabelframe.Label', background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('TCombobox', fieldbackground=UI_FIELD_BACKGROUND, background=UI_BACKGROUND_COLOR, foreground=UI_TEXT_COLOR)
        style.configure('Vertical.TScrollbar', background='#cccccc', troughcolor=UI_BACKGROUND_COLOR)
        root.option_add('*TCombobox*Listbox.background', UI_FIELD_BACKGROUND)
        root.option_add('*TCombobox*Listbox.foreground', UI_TEXT_COLOR)
        root.option_add('*TCombobox*Listbox.selectBackground', UI_SELECT_BACKGROUND)
        root.option_add('*TCombobox*Listbox.selectForeground', UI_TEXT_COLOR)
    except tk.TclError:
        print("The 'clam' theme is not available. Using the default theme.")
        root.configure(bg=UI_BACKGROUND_COLOR)
    app = AirfoilPlotterApp(root)
    root.mainloop()
