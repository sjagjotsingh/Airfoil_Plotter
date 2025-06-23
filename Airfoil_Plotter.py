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
                normalized_key = re.sub(r'[^a-z0-9]', '', base_name_for_key.lower())
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
        self.current_airfoil_slug_at_site = None
        self.export_button.config(state=tk.DISABLED)
        self.export_svg_button.config(state=tk.DISABLED)
        self.fetch_aero_button.config(state=tk.DISABLED)
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
        self.airfoils_db = result.get('data', {})
        error = result.get('error')
        if error and not self.airfoils_db:
            msg = f"Error fetching airfoil list: {error}"
            self.update_status(msg)
            messagebox.showerror("Database Error", f"Could not retrieve airfoil list:\n{msg}", parent=self.master)
            self.set_ui_state_for_processing(False)
            return
        if not self.airfoils_db:
            msg = "Error: No airfoils found on airfoiltools.com. The site might be down or its structure may have changed."
            self.update_status(msg)
            messagebox.showerror("Database Error", msg, parent=self.master)
            self.set_ui_state_for_processing(False)
            return
        self.available_normalized_names = list(self.airfoils_db.keys())
        self.update_status(f"Loaded {len(self.airfoils_db)} airfoils. Ready.")
        self.set_ui_state_for_processing(False)
        self.search_button.config(state=tk.NORMAL)
        self.list_button.config(state=tk.NORMAL)

    def search_and_plot_airfoil(self, event=None):
        user_input = self.airfoil_entry_var.get().strip()
        if not user_input:
            self.update_status("Please enter an airfoil name to search.")
            return
        normalized_input = re.sub(r'[^a-z0-9]', '', user_input.lower())
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
        display_name = airfoil_info['display_name']
        self.update_status(f"Downloading coordinates for {display_name}...")
        self.set_ui_state_for_processing(True)
        self.current_airfoil_slug_at_site = airfoil_info['airfoil_slug_at_site']
        full_dat_url = urljoin(AIRFOILTOOLS_BASE_URL, airfoil_info['dat_file_url_suffix'])
        thread = threading.Thread(target=download_dat_file_content_threaded, args=(full_dat_url, display_name, self.download_queue))
        thread.daemon = True
        thread.start()
        self.master.after(100, self._check_download_completion, airfoil_info)

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
                    self._draw_airfoil_plot(airfoil_info['display_name'], name_int, xu, yu, xl, yl)
                    plot_was_successful = True
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
        names = sorted([d['display_name'] for d in self.airfoils_db.values()])
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
        if self.last_plotted_data:
            name_d, name_i, xu, yu, xl, yl = self.last_plotted_data
            self._draw_airfoil_plot(name_d, name_i, xu, yu, xl, yl)
            self.update_status(f"Markers {'shown' if self.markers_visible_var.get() else 'hidden'}.")

    def _draw_airfoil_plot(self, name_display, name_internal, xu, yu, xl, yl):
        self.ax.clear()
        self._style_plot_for_grey_bg()
        
        # Combine points into a single continuous line as per user suggestion
        if xu and xl and xu[-1] == xl[0]:
            full_x = xu + xl[1:]
            full_y = yu + yl[1:]
        else: # Fallback if points don't meet
            full_x = xu + xl
            full_y = yu + yl
            
        show_markers = self.markers_visible_var.get()
        style = 'o-' if show_markers else '-'
        marker_size = 3 if show_markers else 0

        self.ax.plot(full_x, full_y, style, label='Airfoil Outline', markersize=marker_size, color='blue')

        title = f'Airfoil: {name_display}'
        if name_internal and name_internal.lower().strip() != name_display.lower().strip():
            title += f' (File: {name_internal})'
        self.ax.set_title(title)
        
        legend = self.ax.legend()
        for text in legend.get_texts():
            text.set_color(UI_TEXT_COLOR)
        legend.get_frame().set_facecolor(UI_BACKGROUND_COLOR)
        legend.get_frame().set_edgecolor('gray')

        self.ax.set_xlabel('X-coordinate')
        self.ax.set_ylabel('Y-coordinate')
        self.ax.axis('equal')
        self.canvas.draw_idle()

        self.current_plotted_airfoil_name = name_display
        self.last_plotted_data = (name_display, name_internal, xu, yu, xl, yl) # Still save original components
        
        self.export_button.config(state=tk.NORMAL)
        self.export_svg_button.config(state=tk.NORMAL)
        if self.current_airfoil_slug_at_site:
            self.fetch_aero_button.config(state=tk.NORMAL)

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

            # Step 3: Define a target canvas and rescale the airfoil to fit.
            # This avoids all complex transforms and floating point viewBox issues.
            svg_canvas_width = 1000
            padding = 50 # 50px padding on each side
            
            # Calculate the scaling factor to fit the data into the canvas width
            scale_factor = (svg_canvas_width - 2 * padding) / data_width
            svg_canvas_height = (data_height * scale_factor) + (2 * padding)

            # Step 4: Create the new, scaled and transformed points.
            transformed_points = []
            for x, y in points:
                # Scale and translate X coordinate
                new_x = padding + (x - min_x) * scale_factor
                # Scale, flip Y, and translate Y coordinate
                new_y = (svg_canvas_height - padding) - (y - min_y) * scale_factor
                transformed_points.append(f"{new_x:.3f},{new_y:.3f}")

            # Step 5: Generate the SVG path data from the transformed points.
            path_d = "M " + " L ".join(transformed_points) + " Z"

            # Step 6: Create the final SVG content with a simple, fixed viewBox.
            svg_content = (
                f'<svg width="{svg_canvas_width}" height="{svg_canvas_height}" viewBox="0 0 {svg_canvas_width} {svg_canvas_height}" xmlns="http://www.w3.org/2000/svg">\n'
                f'  <path d="{path_d}" fill="none" stroke="black" stroke-width="2"/>\n'
                f'</svg>'
            )

            with open(filepath, 'w') as f:
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
        if not is_processing and self.current_plotted_airfoil_name:
             self.export_button.config(state=tk.NORMAL)
             self.export_svg_button.config(state=tk.NORMAL)
             self.fetch_aero_button.config(state=tk.NORMAL)
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