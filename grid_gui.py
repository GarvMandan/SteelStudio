import math
import re
import threading
import tkinter as tk
import webbrowser
import json
import sys
import copy
import subprocess
import tempfile
from datetime import datetime
import textwrap
from fractions import Fraction
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import ttkbootstrap as ttk_bs
from ttkbootstrap import Style as BootStyle
from ttkbootstrap.constants import *
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from calculation_engine import (
    InputValidationError,
    calculate_column_takeoff,
    calculate_girder_takeoff,
    calculate_joist_takeoff,
    calculate_mezzanine_takeoff,
)


MIN_SPACING_FT = 0.5
MIN_ZOOM_PX_PER_FT = 0.2
MAX_ZOOM_PX_PER_FT = 260.0


def axis_letter(index: int) -> str:
    """Convert 0-based index to spreadsheet-style letters: 0->A, 25->Z, 26->AA."""
    index += 1
    letters = []
    while index:
        index, rem = divmod(index - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def axis_index(label: str) -> int:
    token = str(label or "").strip().upper()
    if not token:
        raise ValueError("Axis label is empty.")
    total = 0
    for ch in token:
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"Invalid axis label: {label}")
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return total - 1


class GridModel:
    def __init__(self, x_spans=None, y_spans=None):
        self.x_spans = x_spans if x_spans is not None else []
        self.y_spans = y_spans if y_spans is not None else []

    @property
    def x_lines(self):
        pos = [0.0]
        running = 0.0
        for span in self.x_spans:
            running += span
            pos.append(running)
        return pos

    @property
    def y_lines(self):
        pos = [0.0]
        running = 0.0
        for span in self.y_spans:
            running += span
            pos.append(running)
        return pos

    def move_vertical_line(self, index: int, new_x: float):
        x_lines = self.x_lines
        if index <= 0 or index >= len(x_lines) - 1:
            return
        left = x_lines[index - 1]
        right = x_lines[index + 1]
        new_x = max(left + MIN_SPACING_FT, min(right - MIN_SPACING_FT, new_x))
        self.x_spans[index - 1] = round(new_x - left, 3)
        self.x_spans[index] = round(right - new_x, 3)

    def move_horizontal_line(self, index: int, new_y: float):
        y_lines = self.y_lines
        if index <= 0 or index >= len(y_lines) - 1:
            return
        top = y_lines[index - 1]
        bottom = y_lines[index + 1]
        new_y = max(top + MIN_SPACING_FT, min(bottom - MIN_SPACING_FT, new_y))
        self.y_spans[index - 1] = round(new_y - top, 3)
        self.y_spans[index] = round(bottom - new_y, 3)

    def as_dict(self):
        return {"x_spans_ft": self.x_spans, "y_spans_ft": self.y_spans}


# Earthy palette anchors
# Light: warm parchment, sand, sage, terracotta, deep walnut text
# Dark:  charcoal walnut, olive shadow, muted clay, warm bone text
_EARTH_LIGHT = {
    "bg":          "#efe7d7",  # parchment / app background
    "surface":     "#e6dcc6",  # raised panels
    "surface_alt": "#d9cdb2",  # secondary panels / table bg
    "border":      "#b8a87f",  # divider lines
    "header":      "#5a4a37",  # walnut header bar
    "header_fg":   "#f5ecd8",  # bone text on header
    "text":        "#3a2f24",  # primary text
    "text_muted":  "#6b5a45",  # secondary text
    "primary":     "#9c5a3c",  # terracotta accent (buttons, focus)
    "primary_fg":  "#f8f1e3",
    "success":     "#6b7c4a",  # sage
    "success_fg":  "#f8f1e3",
    "select_bg":   "#c8a878",  # tan selection
    "select_fg":   "#2a2118",
}

_EARTH_DARK = {
    "bg":          "#2b251e",  # deep walnut
    "surface":     "#352d24",
    "surface_alt": "#3f362b",
    "border":      "#574a3a",
    "header":      "#1f1a14",
    "header_fg":   "#e8dcc2",
    "text":        "#e8dcc2",  # warm bone
    "text_muted":  "#a89678",
    "primary":     "#c47a4f",  # warmer terracotta for dark
    "primary_fg":  "#1f1a14",
    "success":     "#8a9d63",  # lifted sage
    "success_fg":  "#1f1a14",
    "select_bg":   "#7a5a3a",  # warm tan selection
    "select_fg":   "#f5ecd8",
}


_CANVAS_LIGHT = {
    "grid_bg": "#f1e8d4", "controls_bg": "#e0d4b8",
    "major_line": "#3a2f24", "major_label_fill": "#3a2f24",
    "major_oval_fill": "#f5ecd8", "major_oval_out": "#3a2f24",
    "minor_line": "#bca983", "crosshair": "#5a4a37",
    "span_label": "#4a3c2c", "empty_text": "#6b5a45",
    "transition_line": "#6b7c4a", "transition_label": "#4f5e35",
    "joist_line": "#5e7a6a", "joist_label": "#3e5648",
    "column_fill": "#3a2f24", "column_outline": "#1f1a14",
    "lb_wall": "#9c5a3c",
    "speed_bay_fill": "#e6c89a", "collateral_fill": "#c5d1a8",
    "inactive_fill": "#a89678", "inactive_outline": "#6b5a45",
    "mezz_bg": "#f1e8d4", "mezz_active_bay": "#f5ecd8",
    "mezz_void_bay": "#a89678", "mezz_grid_line": "#5a4a37",
    "mezz_axis_label": "#3a2f24", "mezz_zone_text": "#2a2118",
    "mezz_dim_color": "#6b7c4a", "mezz_conn_color": "#8a7a5e",
    "mezz_col_fill": "#2a2118", "mezz_empty_text": "#6b5a45",
    "roof_bg": "#f1e8d4", "tilt_bg": "#f1e8d4",
    "text_bg": "#f5ecd8", "text_fg": "#3a2f24", "text_insert": "#3a2f24",
    "hazard_bg": "#f5ecd8", "hazard_fg": "#3a2f24", "hazard_insert": "#3a2f24",
    "canvas_hl_bg": "#b8a87f",
    # Roof section labels & accents
    "roof_section_title": "#3a2f24",
    "roof_ground_line": "#5a4a37",
    "roof_clear_line": "#6b5a45",
    "roof_profile_line": "#9c5a3c",
    "roof_grid_line": "#3a2f24",
    "roof_grid_line_int": "#6b5a45",
    "roof_label_text": "#3a2f24",
    "roof_axis_label": "#2a2118",
    "roof_chl_fill": "#f5ecd8", "roof_chl_outline": "#b8a87f", "roof_chl_text": "#3a2f24",
    "roof_toj_fill": "#f5e6e0", "roof_toj_outline": "#c47a4f", "roof_toj_text": "#7a3f25",
    "roof_depth_fill": "#eef0e0", "roof_depth_outline": "#9bb39a", "roof_depth_text": "#3e5648",
    "roof_trans_fill": "#eaf1d8", "roof_trans_outline": "#8a9d63", "roof_trans_text": "#4f5e35",
    "roof_ridge_fill": "#f5ecd8", "roof_ridge_outline": "#b8a87f", "roof_ridge_text": "#3a2f24",
    "roof_legend_fill": "#f5ecd8", "roof_legend_outline": "#b8a87f", "roof_legend_text": "#3a2f24",
    # Tilt wall colors
    "tilt_panel_outline": "#b8a87f",
    "tilt_title": "#3a2f24",
    "tilt_base_text": "#5a4a37",
    "tilt_north_fill": "#dfe8f3", "tilt_north_outline": "#5a7493", "tilt_north_text": "#2c4866",
    "tilt_south_fill": "#f3dfd2", "tilt_south_outline": "#9c5a3c", "tilt_south_text": "#7a3f25",
    "tilt_east_fill": "#e1ecd6", "tilt_east_outline": "#6b7c4a", "tilt_east_text": "#3e5236",
    "tilt_west_fill": "#e1ecd6", "tilt_west_outline": "#6b7c4a", "tilt_west_text": "#3e5236",
    # Selection-table tag colors (alternate row tints)
    "tree_main_bg": "#efe7d4",
    "tree_main_fg": "#3a2f24",
    "tree_mezz_bg": "#dfe8d4",
    "tree_mezz_fg": "#3a2f24",
}

_CANVAS_DARK = {
    "grid_bg": "#2b251e", "controls_bg": "#1f1a14",
    "major_line": "#e8dcc2", "major_label_fill": "#e8dcc2",
    "major_oval_fill": "#352d24", "major_oval_out": "#a89678",
    "minor_line": "#574a3a", "crosshair": "#8a7a5e",
    "span_label": "#a89678", "empty_text": "#8a7a5e",
    "transition_line": "#a3b87a", "transition_label": "#b6c98e",
    "joist_line": "#9bb39a", "joist_label": "#b8cdb6",
    "column_fill": "#d4c4a3", "column_outline": "#a89678",
    "lb_wall": "#c47a4f",
    "speed_bay_fill": "#5a4225", "collateral_fill": "#3e4a2a",
    "inactive_fill": "#4a3f30", "inactive_outline": "#574a3a",
    "mezz_bg": "#2b251e", "mezz_active_bay": "#3a3026",
    "mezz_void_bay": "#4a3f30", "mezz_grid_line": "#a89678",
    "mezz_axis_label": "#e8dcc2", "mezz_zone_text": "#f5ecd8",
    "mezz_dim_color": "#a3b87a", "mezz_conn_color": "#8a7a5e",
    "mezz_col_fill": "#e8dcc2", "mezz_empty_text": "#8a7a5e",
    "roof_bg": "#2b251e", "tilt_bg": "#2b251e",
    "text_bg": "#352d24", "text_fg": "#e8dcc2", "text_insert": "#e8dcc2",
    "hazard_bg": "#352d24", "hazard_fg": "#e8dcc2", "hazard_insert": "#e8dcc2",
    "canvas_hl_bg": "#574a3a",
    # Roof section labels & accents (dark)
    "roof_section_title": "#e8dcc2",
    "roof_ground_line": "#a89678",
    "roof_clear_line": "#a89678",
    "roof_profile_line": "#c47a4f",
    "roof_grid_line": "#e8dcc2",
    "roof_grid_line_int": "#a89678",
    "roof_label_text": "#e8dcc2",
    "roof_axis_label": "#f5ecd8",
    "roof_chl_fill": "#3f362b", "roof_chl_outline": "#a89678", "roof_chl_text": "#e8dcc2",
    "roof_toj_fill": "#4a3526", "roof_toj_outline": "#c47a4f", "roof_toj_text": "#e8c5a3",
    "roof_depth_fill": "#33402a", "roof_depth_outline": "#9bb39a", "roof_depth_text": "#c5d6a8",
    "roof_trans_fill": "#3a4a28", "roof_trans_outline": "#a3b87a", "roof_trans_text": "#c8d99a",
    "roof_ridge_fill": "#3f362b", "roof_ridge_outline": "#a89678", "roof_ridge_text": "#e8dcc2",
    "roof_legend_fill": "#3f362b", "roof_legend_outline": "#a89678", "roof_legend_text": "#e8dcc2",
    # Tilt wall colors (dark)
    "tilt_panel_outline": "#574a3a",
    "tilt_title": "#e8dcc2",
    "tilt_base_text": "#a89678",
    "tilt_north_fill": "#2f3d52", "tilt_north_outline": "#7a93b3", "tilt_north_text": "#b8cce4",
    "tilt_south_fill": "#4a2f24", "tilt_south_outline": "#c47a4f", "tilt_south_text": "#e8b89a",
    "tilt_east_fill": "#33402a", "tilt_east_outline": "#8a9d63", "tilt_east_text": "#c5d6a8",
    "tilt_west_fill": "#33402a", "tilt_west_outline": "#8a9d63", "tilt_west_text": "#c5d6a8",
    # Selection-table tag colors (dark; gentle warm + cool tint, readable text)
    "tree_main_bg": "#3f362b",
    "tree_main_fg": "#e8dcc2",
    "tree_mezz_bg": "#374030",
    "tree_mezz_fg": "#e8dcc2",
}


class SteelGridApp:
    def __init__(self, root: tk.Tk):
        self.root = root

        self.model = GridModel()
        self.current_project_path = None
        self.project_status_var = tk.StringVar(value="Unsaved project")
        self._project_loading = False
        self._autosave_job = None
        self._autosave_path = Path.home() / "AppData" / "Local" / "StructuralSteelTakeoff" / "autosave_project.json"
        self._dark_mode = False
        self._cv = dict(_CANVAS_LIGHT)
        self.zoom = 2.0  # pixels per foot
        self.offset_x = 220.0
        self.offset_y = 160.0
        self.auto_fit_on_bay_change = tk.BooleanVar(value=True)
        self.interaction_mode = tk.StringVar(value="edit")
        self.collateral_bays = set()
        self.inactive_bays = set()
        self.load_bearing_perimeter = set()
        self.joists_per_bay = {}

        self.dead_load_var = tk.StringVar(value="10")
        self.live_load_var = tk.StringVar(value="20")
        self.snow_load_var = tk.StringVar(value="25")
        self.snow_code_var = tk.StringVar(value="ASCE 7-16")
        self.reduced_snow_load_manual_var = tk.StringVar(value="22.5")
        self.reduced_snow_load_status_var = tk.StringVar(value="ASCE 7-16: Reduced snow load is auto-calculated.")
        self.location_city_var = tk.StringVar(value="")
        self.location_state_var = tk.StringVar(value="")
        self.hazard_parse_status_var = tk.StringVar(
            value="Enter City/State and run backend lookup, or use manual ASCE paste fallback."
        )
        self.collateral_addition_var = tk.StringVar(value="3")
        self.custom_load_addition_var = tk.StringVar(value="0")
        self.additional_load_name_var = tk.StringVar(value="Additional 1")
        self.additional_load_color_var = tk.StringVar(value="#f7d8a8")
        self.additional_load_status_var = tk.StringVar(value="No additional load layers defined.")
        self.clear_height_var = tk.StringVar(value="36")
        self.joist_seat_depth_var = tk.StringVar(value="2.5")
        self.girder_seat_depth_var = self.joist_seat_depth_var  # Backward-compatible alias
        self.metal_deck_thickness_var = tk.StringVar(value="1.5")
        self.insulation_depth_var = tk.StringVar(value="3")
        self.footing_depth_var = tk.StringVar(value="1")
        self.bearing_pressure_var = tk.StringVar(value="3000")
        self.joist_calc_status_var = tk.StringVar(value="No joist calculation run yet.")
        self.girder_calc_status_var = tk.StringVar(value="No girder calculation run yet.")
        self.column_calc_status_var = tk.StringVar(value="No column calculation run yet.")
        self.tilt_calc_status_var = tk.StringVar(value="No tilt wall calculation run yet.")
        self.footing_calc_status_var = tk.StringVar(value="No footing calculation run yet.")
        self.report_status_var = tk.StringVar(value="Ready to run all calculations and export company PDF.")
        self.roof_section_status_var = tk.StringVar(value="Roof section ready.")
        self.total_joist_weight_var = tk.StringVar(
            value=(
                "Total assigned joist weight: 0.00 lbs "
                "(main building only; includes shared-edge dedupe and perimeter LB wall rules)"
            )
        )
        self.total_girder_weight_var = tk.StringVar(value="Total assigned girder weight: 0.00 lbs (main building only)")
        self.total_column_weight_var = tk.StringVar(value="Total assigned column weight: 0.00 lbs (main building only)")
        self.selected_depth_var = tk.StringVar(value="24")
        self.selected_weight_plf_var = tk.StringVar(value="20")
        self.selected_girder_depth_var = tk.StringVar(value="30")
        self.selected_girder_weight_plf_var = tk.StringVar(value="20")
        self.selected_column_depth_var = tk.StringVar(value="18")
        self.selected_column_weight_plf_var = tk.StringVar(value="20")
        self.roof_type_var = tk.StringVar(value="Single Slope")
        self.single_slope_direction_var = tk.StringVar(value="North")
        self.break_clear_height_var = tk.BooleanVar(value=True)
        self.dock_line_var = tk.StringVar(value="")
        self.speed_bay_rows = set()
        self.speed_bay_rows_summary_var = tk.StringVar(value="None")
        self.speed_transition_summary_var = tk.StringVar(value="None")
        self.recommended_joist_spaces_var = tk.StringVar(value="Recommended Joist Spaces/Bay: -")
        self.mezzanine_enabled_var = tk.BooleanVar(value=False)
        self.mezz_name_var = tk.StringVar(value="Mezzanine 1")
        self.mezz_elevation_var = tk.StringVar(value="15")
        self.mezz_dead_load_var = tk.StringVar(value="80")
        self.mezz_live_load_var = tk.StringVar(value="100")
        self.mezz_joist_direction_var = tk.StringVar(value="Vertical")
        self.mezz_joist_spaces_var = tk.StringVar(value="7")
        self.mezz_panel_spacing_value_var = tk.StringVar(value="7")
        self.mezz_snap_enabled_var = tk.BooleanVar(value=True)
        self.mezz_snap_step_var = tk.StringVar(value="1.0")
        self.mezz_continuous_draw_var = tk.BooleanVar(value=True)
        self.mezz_zoom_var = tk.DoubleVar(value=2.4)
        self.mezz_origin_x_var = tk.StringVar(value="0")
        self.mezz_origin_y_var = tk.StringVar(value="0")
        self.mezz_width_var = tk.StringVar(value="50")
        self.mezz_length_var = tk.StringVar(value="50")
        self.mezz_new_x_bay_var = tk.StringVar(value="20")
        self.mezz_new_y_bay_var = tk.StringVar(value="20")
        self.mezz_internal_x_summary_var = tk.StringVar(value="X bays: auto (single bay)")
        self.mezz_internal_y_summary_var = tk.StringVar(value="Y bays: auto (single bay)")
        self.mezz_x_start_var = tk.StringVar(value="1")
        self.mezz_x_end_var = tk.StringVar(value="2")
        self.mezz_y_start_var = tk.StringVar(value="A")
        self.mezz_y_end_var = tk.StringVar(value="B")
        self.mezz_internal_x_var = tk.StringVar(value="")
        self.mezz_internal_y_var = tk.StringVar(value="")
        self.mezz_status_var = tk.StringVar(value="Mezzanines disabled.")
        self.mezz_calc_status_var = tk.StringVar(value="No mezzanine calculation run yet.")

        self.last_joist_result = None
        self.last_girder_result = None
        self.last_column_result = None
        self.last_tilt_result = None
        self.last_footing_result = None
        self.last_mezz_result = None
        self.last_mezz_footing_result = None
        self.joist_selection_by_group = {}
        self.girder_selection_by_group = {}
        self.column_selection_by_group = {}
        self.mezz_joist_selection_by_group = {}
        self.mezz_girder_selection_by_group = {}
        self.mezz_column_selection_by_group = {}
        self.joist_catalog_rows = None
        self.joist_catalog_source = None
        self.mezz_joist_catalog_rows = None
        self.mezz_joist_catalog_source = None
        self.girder_catalog_rows = None
        self.girder_catalog_source = None
        self.girder_catalog_index = None
        self.column_catalog_rows = None
        self.column_catalog_source = None
        self._girder_auto_assign_running = False
        self._girder_auto_assign_thread = None
        self._girder_auto_assign_result = None
        self._snow_lookup_running = False
        self._snow_lookup_thread = None
        self._snow_lookup_result = None
        self.additional_load_layers = []
        self.selected_additional_load_layer_id = None
        self._additional_load_layer_counter = 0
        self._additional_load_color_cycle = [
            "#f7d8a8",
            "#b8e0d2",
            "#d6c9f0",
            "#f8b6b6",
            "#c6d5f5",
            "#f7e8a8",
            "#bde5a7",
            "#f9c8e3",
        ]
        self.mezz_zones = []
        self._mezz_zone_counter = 0
        self.selected_mezz_zone_id = None
        self._mezz_draw_mode = False
        self._mezz_drag_start = None
        self._mezz_drag_end = None
        self._mezz_canvas_transform = None
        self._mezz_selected_panel_keys = set()
        self._mezz_loading_zone = False
        self._mezz_property_traces_ready = False

        self.drag_line = None
        self.pan_anchor = None

        self._configure_app_style()
        self._build_ui()
        self.redraw()
        self._schedule_autosave()
        self.root.after(600, self._prompt_autosave_recovery)

    def _configure_app_style(self):
        self._style = BootStyle()
        self._apply_custom_overrides()

    def _earth_palette(self):
        return _EARTH_DARK if self._dark_mode else _EARTH_LIGHT

    def _apply_custom_overrides(self):
        p = self._earth_palette()
        s = self._style

        # Base ttk surfaces
        try:
            self.root.configure(bg=p["bg"])
        except Exception:
            pass
        s.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["surface"])
        s.configure("TFrame", background=p["bg"])
        s.configure("TLabelframe", background=p["bg"], foreground=p["text"], bordercolor=p["border"])
        s.configure("TLabelframe.Label", background=p["bg"], foreground=p["text"], font=("Segoe UI", 9, "bold"))
        s.configure("TLabel", background=p["bg"], foreground=p["text"])
        s.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
        s.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
        s.configure("TEntry", fieldbackground=p["surface"], foreground=p["text"], bordercolor=p["border"])
        s.configure("TCombobox", fieldbackground=p["surface"], foreground=p["text"])
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", p["surface"])],
            foreground=[("readonly", p["text"])],
            selectbackground=[("readonly", p["select_bg"])],
            selectforeground=[("readonly", p["select_fg"])],
        )
        s.configure("TSpinbox", fieldbackground=p["surface"], foreground=p["text"])

        # Notebook
        s.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
        s.configure(
            "TNotebook.Tab",
            padding=(16, 9),
            font=("Segoe UI", 10, "bold"),
            background=p["surface_alt"],
            foreground=p["text_muted"],
            bordercolor=p["border"],
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", p["primary"]), ("active", p["surface"])],
            foreground=[("selected", p["primary_fg"]), ("active", p["text"])],
        )

        # Buttons — default
        s.configure(
            "TButton",
            background=p["primary"],
            foreground=p["primary_fg"],
            bordercolor=p["primary"],
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )
        s.map(
            "TButton",
            background=[("active", p["select_bg"]), ("pressed", p["select_bg"])],
            foreground=[("active", p["select_fg"]), ("pressed", p["select_fg"])],
            bordercolor=[("active", p["select_bg"])],
        )

        # ttkbootstrap bootstyle variants we use — ensure readable contrast in earthy palette
        for style_name in ("primary.TButton", "TButton"):
            s.configure(style_name, background=p["primary"], foreground=p["primary_fg"], bordercolor=p["primary"])
            s.map(
                style_name,
                background=[("active", p["select_bg"]), ("pressed", p["select_bg"])],
                foreground=[("active", p["select_fg"]), ("pressed", p["select_fg"])],
            )

        s.configure("success.TButton", background=p["success"], foreground=p["success_fg"], bordercolor=p["success"])
        s.map(
            "success.TButton",
            background=[("active", p["select_bg"]), ("pressed", p["select_bg"])],
            foreground=[("active", p["select_fg"]), ("pressed", p["select_fg"])],
        )

        # Header buttons (Save / Load / theme toggle) — use a custom style so they're legible on the walnut header
        s.configure(
            "Header.TButton",
            background=p["surface"],
            foreground=p["text"],
            bordercolor=p["border"],
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )
        s.map(
            "Header.TButton",
            background=[("active", p["primary"]), ("pressed", p["primary"])],
            foreground=[("active", p["primary_fg"]), ("pressed", p["primary_fg"])],
        )

        # Outline-light variants used in the header — repaint so they aren't white-on-white
        for ob_style in ("outline-light.TButton", "Outline.Light.TButton"):
            s.configure(
                ob_style,
                background=p["surface"],
                foreground=p["text"],
                bordercolor=p["border"],
            )
            s.map(
                ob_style,
                background=[("active", p["primary"])],
                foreground=[("active", p["primary_fg"])],
            )

        # Header frame + labels
        s.configure("Header.TFrame", background=p["header"])
        s.configure("Header.TLabel", background=p["header"], foreground=p["header_fg"], font=("Segoe UI", 13, "bold"))
        s.configure("HeaderStatus.TLabel", background=p["header"], foreground=p["header_fg"], font=("Segoe UI", 9))

        # Muted label
        s.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"], font=("Segoe UI", 9))

        # Resizable sash between paned panels — keep the paned background tinted with the border colour
        # so the drag handle is visible against the surrounding panels.
        s.configure("TPanedwindow", background=p["border"])

        # Treeview (selection tables) — fix white-on-white in dark mode
        s.configure(
            "Treeview",
            background=p["surface"],
            fieldbackground=p["surface"],
            foreground=p["text"],
            rowheight=24,
            font=("Segoe UI", 9),
            bordercolor=p["border"],
        )
        s.map(
            "Treeview",
            background=[("selected", p["select_bg"])],
            foreground=[("selected", p["select_fg"])],
        )
        s.configure(
            "Treeview.Heading",
            background=p["surface_alt"],
            foreground=p["text"],
            font=("Segoe UI", 9, "bold"),
            bordercolor=p["border"],
            relief="flat",
        )
        s.map(
            "Treeview.Heading",
            background=[("active", p["primary"])],
            foreground=[("active", p["primary_fg"])],
        )

        # ttkbootstrap creates per-color Treeview variants (e.g. primary.Treeview);
        # repaint them so the body of selection tables doesn't render white-on-white.
        for variant in ("primary.Treeview", "info.Treeview", "secondary.Treeview", "success.Treeview"):
            s.configure(
                variant,
                background=p["surface"],
                fieldbackground=p["surface"],
                foreground=p["text"],
                rowheight=24,
                font=("Segoe UI", 9),
                bordercolor=p["border"],
            )
            s.map(
                variant,
                background=[("selected", p["select_bg"])],
                foreground=[("selected", p["select_fg"])],
            )
            heading = variant.replace(".Treeview", ".Treeview.Heading")
            s.configure(
                heading,
                background=p["surface_alt"],
                foreground=p["text"],
                font=("Segoe UI", 9, "bold"),
                bordercolor=p["border"],
                relief="flat",
            )
            s.map(
                heading,
                background=[("active", p["primary"])],
                foreground=[("active", p["primary_fg"])],
            )


    def toggle_theme(self):
        self._dark_mode = not self._dark_mode
        if self._dark_mode:
            self._style.theme_use("darkly")
            self._cv = dict(_CANVAS_DARK)
            self._theme_btn.configure(text="☀  Light Mode")
        else:
            self._style.theme_use("litera")
            self._cv = dict(_CANVAS_LIGHT)
            self._theme_btn.configure(text="🌙  Dark Mode")
        self._apply_custom_overrides()
        self._apply_canvas_colors()
        self.redraw()
        self.redraw_mezzanine_preview()
        self.redraw_roof_section()
        self.redraw_tilt_wall_preview()

    def _apply_canvas_colors(self):
        cv = self._cv
        for attr, key in [
            ("canvas", "grid_bg"), ("controls_canvas", "controls_bg"),
            ("mezz_canvas", "mezz_bg"), ("roof_canvas", "roof_bg"),
            ("tilt_canvas", "tilt_bg"),
        ]:
            if hasattr(self, attr):
                getattr(self, attr).configure(bg=cv[key], highlightbackground=cv["canvas_hl_bg"])

        for attr, bg, fg, ins in [
            ("hazard_paste_text", "hazard_bg", "hazard_fg", "hazard_insert"),
            ("joist_results_text", "text_bg", "text_fg", "text_insert"),
            ("girder_results_text", "text_bg", "text_fg", "text_insert"),
            ("column_results_text", "text_bg", "text_fg", "text_insert"),
            ("footing_results_text", "text_bg", "text_fg", "text_insert"),
            ("mezz_results_text", "text_bg", "text_fg", "text_insert"),
            ("tilt_results_text", "text_bg", "text_fg", "text_insert"),
            ("report_log_text", "text_bg", "text_fg", "text_insert"),
        ]:
            if hasattr(self, attr):
                getattr(self, attr).configure(bg=cv[bg], fg=cv[fg], insertbackground=cv[ins])

        # Selection-table alt-row tag colors (theme-aware so they're readable in dark mode)
        for tree_attr in ("joist_select_tree", "girder_select_tree", "column_select_tree"):
            tree = getattr(self, tree_attr, None)
            if tree is not None:
                try:
                    tree.tag_configure("main", background=cv["tree_main_bg"], foreground=cv["tree_main_fg"])
                    tree.tag_configure("mezz", background=cv["tree_mezz_bg"], foreground=cv["tree_mezz_fg"])
                except Exception:
                    pass

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)

        # Header bar
        header = ttk_bs.Frame(self.root, style="Header.TFrame", padding=(16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk_bs.Label(
            header,
            text="  Structural Steel Takeoff",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")

        project_bar = ttk_bs.Frame(header, style="Header.TFrame")
        project_bar.grid(row=0, column=1, sticky="e", padx=(12, 8))
        ttk_bs.Button(
            project_bar,
            text="Save Project",
            style="Header.TButton",
            command=self.save_project,
        ).grid(row=0, column=0, padx=(0, 6))
        ttk_bs.Button(
            project_bar,
            text="Load Project",
            style="Header.TButton",
            command=self.load_project,
        ).grid(row=0, column=1, padx=(0, 6))
        ttk_bs.Button(
            project_bar,
            text="Recalculate All",
            bootstyle="success",
            command=self.recalculate_all_no_export,
            padding=(10, 5),
        ).grid(row=0, column=2, padx=(0, 8))
        ttk_bs.Button(
            project_bar,
            text="Open 3D Studio",
            bootstyle="info",
            command=self.open_3d_studio,
            padding=(10, 5),
        ).grid(row=0, column=3, padx=(0, 8))
        ttk_bs.Label(
            project_bar,
            textvariable=self.project_status_var,
            style="HeaderStatus.TLabel",
        ).grid(row=0, column=4, sticky="e")

        self._theme_btn = ttk_bs.Button(
            header,
            text="🌙  Dark Mode",
            style="Header.TButton",
            command=self.toggle_theme,
        )
        self._theme_btn.grid(row=0, column=2, sticky="e")

        notebook = ttk_bs.Notebook(self.root, bootstyle="primary")
        notebook.grid(row=1, column=0, sticky="nsew")

        grid_tab = ttk_bs.Frame(notebook, padding=8)
        mezz_tab = ttk_bs.Frame(notebook, padding=14)
        input_tab = ttk_bs.Frame(notebook, padding=14)
        roof_tab = ttk_bs.Frame(notebook, padding=14)
        joist_tab = ttk_bs.Frame(notebook, padding=14)
        girder_tab = ttk_bs.Frame(notebook, padding=14)
        column_tab = ttk_bs.Frame(notebook, padding=14)
        footing_tab = ttk_bs.Frame(notebook, padding=14)
        report_tab = ttk_bs.Frame(notebook, padding=14)
        tilt_wall_tab = ttk_bs.Frame(notebook, padding=14)
        notebook.add(grid_tab, text="Grid Layout")
        notebook.add(mezz_tab, text="Mezzanines")
        notebook.add(input_tab, text="Load Inputs (psf)")
        notebook.add(roof_tab, text="Roof Slope")
        notebook.add(joist_tab, text="Joist Calculation")
        notebook.add(girder_tab, text="Girder Calculation")
        notebook.add(column_tab, text="Column Calculation")
        notebook.add(footing_tab, text="Pad Footings")
        notebook.add(tilt_wall_tab, text="Tilt Wall")
        notebook.add(report_tab, text="Company PDF Report")

        self._build_grid_tab(grid_tab)
        self._build_mezzanine_tab(mezz_tab)
        self._build_load_tab(input_tab)
        self._build_roof_tab(roof_tab)
        self._build_joist_tab(joist_tab)
        self._build_girder_tab(girder_tab)
        self._build_column_tab(column_tab)
        self._build_footing_tab(footing_tab)
        self._build_tilt_wall_tab(tilt_wall_tab)
        self._build_report_tab(report_tab)

    def _json_safe(self, value):
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(v) for v in value]
        if isinstance(value, set):
            return [self._json_safe(v) for v in sorted(value)]
        if isinstance(value, Path):
            return str(value)
        return value

    def _serialize_bay_set(self, bays):
        return [
            {"x_bay": int(x_idx) + 1, "y_bay": axis_letter(int(y_idx))}
            for x_idx, y_idx in sorted(bays, key=lambda item: (item[1], item[0]))
        ]

    def _bay_ref_to_tuple(self, item):
        if isinstance(item, dict):
            if "x_idx" in item:
                x_idx = int(item.get("x_idx", 0))
            else:
                x_idx = int(item.get("x_bay", item.get("x", 1))) - 1
            if "y_idx" in item:
                y_idx = int(item.get("y_idx", 0))
            elif "row_index" in item:
                y_idx = int(item.get("row_index", 1)) - 1
            else:
                y_val = item.get("y_bay", item.get("y", "A"))
                y_idx = axis_index(str(y_val)) if not isinstance(y_val, (int, float)) else int(y_val) - 1
            return int(x_idx), int(y_idx)
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return int(item[0]), int(item[1])
        raise ValueError("Invalid bay reference.")

    def _bay_set_from_saved(self, items):
        out = set()
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        for item in items or []:
            try:
                x_idx, y_idx = self._bay_ref_to_tuple(item)
            except Exception:
                continue
            if 0 <= x_idx < max_x and 0 <= y_idx < max_y:
                out.add((x_idx, y_idx))
        return out

    def _serialize_edge_set(self, edges):
        return [
            {"orientation": orient, "line_index": int(line_idx) + 1, "segment_index": int(seg_idx) + 1}
            for orient, line_idx, seg_idx in sorted(edges)
        ]

    def _edge_set_from_saved(self, items):
        out = set()
        for item in items or []:
            try:
                if isinstance(item, dict):
                    orient = str(item.get("orientation", item.get("orient", ""))).strip().upper()
                    line_idx = int(item.get("line_index", 1)) - 1
                    seg_idx = int(item.get("segment_index", 1)) - 1
                else:
                    orient, line_idx, seg_idx = item
                    orient = str(orient).strip().upper()
                    line_idx = int(line_idx)
                    seg_idx = int(seg_idx)
                if orient in {"H", "V"}:
                    out.add((orient, line_idx, seg_idx))
            except Exception:
                continue
        valid = self._current_boundary_segments()
        return {edge for edge in out if edge in valid}

    def _project_inputs_state(self):
        return {
            "x_spacing_ft": self.x_spacing_var.get() if hasattr(self, "x_spacing_var") else "54",
            "y_spacing_ft": self.y_spacing_var.get() if hasattr(self, "y_spacing_var") else "50",
            "joist_spaces_default": self.joist_count_var.get() if hasattr(self, "joist_count_var") else "7",
            "dead_load_psf": self.dead_load_var.get(),
            "live_load_psf": self.live_load_var.get(),
            "snow_load_psf": self.snow_load_var.get(),
            "snow_code": self.snow_code_var.get(),
            "reduced_snow_load_manual_psf": self.reduced_snow_load_manual_var.get(),
            "collateral_addition_psf": self.collateral_addition_var.get(),
            "clear_height_ft": self.clear_height_var.get(),
            "joist_seat_depth_in": self.joist_seat_depth_var.get(),
            "metal_deck_thickness_in": self.metal_deck_thickness_var.get(),
            "insulation_depth_in": self.insulation_depth_var.get(),
            "footing_depth_ft": self.footing_depth_var.get(),
            "bearing_pressure_psi": self.bearing_pressure_var.get(),
            "location_city": self.location_city_var.get(),
            "location_state": self.location_state_var.get(),
            "roof_type": self.roof_type_var.get(),
            "single_slope_direction": self.single_slope_direction_var.get(),
            "break_clear_height": bool(self.break_clear_height_var.get()),
            "mezzanine_enabled": bool(self.mezzanine_enabled_var.get()),
        }

    def _build_project_state(self):
        additional_layers = []
        for layer in self.additional_load_layers:
            additional_layers.append(
                {
                    "id": str(layer.get("id", "")),
                    "name": str(layer.get("name", "Additional")),
                    "psf": float(layer.get("psf", 0.0) or 0.0),
                    "color": self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8"),
                    "bays": self._serialize_bay_set(layer.get("bays", set())),
                }
            )
        return self._json_safe(
            {
                "app": "Structural Steel Takeoff",
                "project_version": 1,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "inputs": self._project_inputs_state(),
                "grid": {
                    "x_spans_ft": list(self.model.x_spans),
                    "y_spans_ft": list(self.model.y_spans),
                    "inactive_bays": self._serialize_bay_set(self.inactive_bays),
                    "collateral_bays": self._serialize_bay_set(self.collateral_bays),
                    "joists_per_bay": [
                        {"x_bay": int(x_idx) + 1, "y_bay": axis_letter(int(y_idx)), "joist_spaces": int(count)}
                        for (x_idx, y_idx), count in sorted(self.joists_per_bay.items(), key=lambda item: (item[0][1], item[0][0]))
                    ],
                    "speed_bay_rows": [int(v) for v in sorted(self._get_selected_speed_bay_rows())],
                    "load_bearing_wall_segments": self._serialize_edge_set(self.load_bearing_perimeter),
                    "additional_load_layers": additional_layers,
                },
                "mezzanines": copy.deepcopy(self.mezz_zones),
                "assignments": {
                    "joists": self.joist_selection_by_group,
                    "girders": self.girder_selection_by_group,
                    "columns": self.column_selection_by_group,
                    "mezz_joists": self.mezz_joist_selection_by_group,
                    "mezz_girders": self.mezz_girder_selection_by_group,
                    "mezz_columns": self.mezz_column_selection_by_group,
                },
            }
        )

    def open_3d_studio(self):
        """Send the current, including unsaved, project to a local 3D session."""
        if getattr(self, "_studio_opening", False):
            return
        if getattr(sys, "frozen", False):
            source_dir = Path(sys.executable).resolve().parent
            standalone = source_dir / "visualizer.exe"
            if not standalone.is_file():
                messagebox.showinfo(
                    "Open 3D Studio",
                    "This packaged desktop edition does not include the 3D Studio launcher. "
                    "Save your project, run Start Steel Studio.cmd from the source distribution, "
                    "and import the saved JSON in Studio.",
                )
                return
            command = [str(standalone)]
        else:
            source_dir = Path(__file__).resolve().parent
            launcher = source_dir / "visualizer.py"
            if not launcher.is_file():
                messagebox.showerror("Open 3D Studio", f"The Studio launcher was not found:\n{launcher}")
                return
            command = [sys.executable, str(launcher)]

        temporary_dir = None
        process = None

        def cleanup():
            if temporary_dir is not None:
                for filename in ("project.json", "status.json", "status.json.tmp"):
                    try:
                        (temporary_dir / filename).unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    temporary_dir.rmdir()
                except OSError:
                    pass

        try:
            project = self._build_project_state()
            temporary_dir = Path(tempfile.mkdtemp(prefix="steel-studio-"))
            project_path = temporary_dir / "project.json"
            status_path = temporary_dir / "status.json"
            project_path.write_text(json.dumps(project, allow_nan=False), encoding="utf-8")
            command.extend(["--project", str(project_path), "--status-file", str(status_path)])
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            process = subprocess.Popen(
                command,
                cwd=str(source_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except Exception as exc:
            cleanup()
            messagebox.showerror("Open 3D Studio", f"Could not start Studio:\n{exc}")
            return

        self._studio_opening = True
        self.project_status_var.set("Opening 3D Studio...")

        def check_startup(attempt=0):
            result = None
            if status_path.is_file():
                try:
                    result = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            if result is not None:
                self._studio_opening = False
                cleanup()
                if result.get("status") == "ready":
                    self.project_status_var.set(f"3D Studio: {result.get('url', 'opened')}")
                else:
                    self.project_status_var.set("3D Studio could not start")
                    messagebox.showerror("Open 3D Studio", result.get("error", "Studio could not start."))
                return
            if process.poll() is not None or attempt >= 400:
                if process.poll() is None:
                    process.terminate()
                self._studio_opening = False
                cleanup()
                self.project_status_var.set("3D Studio could not start")
                messagebox.showerror(
                    "Open 3D Studio",
                    "Studio did not start successfully. Run Start Steel Studio.cmd "
                    "from the project folder to see the startup details.",
                )
                return
            self.root.after(150, lambda: check_startup(attempt + 1))

        self.root.after(150, check_startup)

    def _write_project_file(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self._build_project_state(), handle, indent=2)

    def save_project(self, path=None, silent: bool = False):
        target = Path(path) if path else self.current_project_path
        if target is None and not silent:
            chosen = filedialog.asksaveasfilename(
                title="Save Structural Steel Project",
                defaultextension=".json",
                filetypes=[("Project JSON", "*.json"), ("All Files", "*.*")],
            )
            if not chosen:
                return None
            target = Path(chosen)
        if target is None:
            target = self._autosave_path
        try:
            self._write_project_file(target)
        except Exception as exc:
            if not silent:
                messagebox.showerror("Save failed", f"Could not save project:\n{exc}")
            return None
        if not silent:
            self.current_project_path = target
            self.project_status_var.set(f"Saved: {target.name}")
            messagebox.showinfo("Project saved", f"Project saved:\n{target}")
        return target

    def _apply_project_inputs(self, inputs):
        def set_if(var, key):
            if key in inputs:
                var.set(str(inputs.get(key, "")))

        if hasattr(self, "x_spacing_var"):
            set_if(self.x_spacing_var, "x_spacing_ft")
        if hasattr(self, "y_spacing_var"):
            set_if(self.y_spacing_var, "y_spacing_ft")
        if hasattr(self, "joist_count_var"):
            set_if(self.joist_count_var, "joist_spaces_default")
        set_if(self.dead_load_var, "dead_load_psf")
        set_if(self.live_load_var, "live_load_psf")
        set_if(self.snow_load_var, "snow_load_psf")
        set_if(self.snow_code_var, "snow_code")
        set_if(self.reduced_snow_load_manual_var, "reduced_snow_load_manual_psf")
        set_if(self.collateral_addition_var, "collateral_addition_psf")
        set_if(self.clear_height_var, "clear_height_ft")
        set_if(self.joist_seat_depth_var, "joist_seat_depth_in")
        set_if(self.metal_deck_thickness_var, "metal_deck_thickness_in")
        set_if(self.insulation_depth_var, "insulation_depth_in")
        set_if(self.footing_depth_var, "footing_depth_ft")
        set_if(self.bearing_pressure_var, "bearing_pressure_psi")
        set_if(self.location_city_var, "location_city")
        set_if(self.location_state_var, "location_state")
        set_if(self.roof_type_var, "roof_type")
        set_if(self.single_slope_direction_var, "single_slope_direction")
        if "break_clear_height" in inputs:
            self.break_clear_height_var.set(bool(inputs.get("break_clear_height")))
        if "mezzanine_enabled" in inputs:
            self.mezzanine_enabled_var.set(bool(inputs.get("mezzanine_enabled")))

    def _apply_project_state(self, state):
        if not isinstance(state, dict):
            raise InputValidationError("Project file is not a valid JSON object.")
        grid = state.get("grid", {}) if isinstance(state.get("grid", {}), dict) else {}
        inputs = state.get("inputs", {}) if isinstance(state.get("inputs", {}), dict) else {}

        self._project_loading = True
        try:
            self.model.x_spans = [round(float(v), 3) for v in grid.get("x_spans_ft", []) if float(v) > 0]
            self.model.y_spans = [round(float(v), 3) for v in grid.get("y_spans_ft", []) if float(v) > 0]
            self._apply_project_inputs(inputs)

            if "inactive_bays" in grid:
                self.inactive_bays = self._bay_set_from_saved(grid.get("inactive_bays", []))
            elif "active_bays" in grid:
                active = self._bay_set_from_saved(grid.get("active_bays", []))
                self.inactive_bays = {
                    (x_idx, y_idx)
                    for x_idx in range(len(self.model.x_spans))
                    for y_idx in range(len(self.model.y_spans))
                    if (x_idx, y_idx) not in active
                }
            else:
                self.inactive_bays = set()
            self.collateral_bays = self._bay_set_from_saved(grid.get("collateral_bays", []))
            self.joists_per_bay = {}
            for item in grid.get("joists_per_bay", []) or []:
                try:
                    x_idx, y_idx = self._bay_ref_to_tuple(item)
                    count = int(item.get("joist_spaces", item.get("joist_count", 1)))
                    if 0 <= x_idx < len(self.model.x_spans) and 0 <= y_idx < len(self.model.y_spans) and count >= 1:
                        self.joists_per_bay[(x_idx, y_idx)] = count
                except Exception:
                    continue

            self.speed_bay_rows = set()
            for raw in grid.get("speed_bay_rows", []) or []:
                try:
                    idx = int(raw.get("row_index", 1)) - 1 if isinstance(raw, dict) else int(raw)
                    if 0 <= idx < len(self.model.y_spans):
                        self.speed_bay_rows.add(idx)
                except Exception:
                    continue
            self.load_bearing_perimeter = self._edge_set_from_saved(grid.get("load_bearing_wall_segments", []))

            self.additional_load_layers = []
            for idx, layer in enumerate(grid.get("additional_load_layers", []) or [], start=1):
                if not isinstance(layer, dict):
                    continue
                layer_id = str(layer.get("id", f"AL{idx:03d}")) or f"AL{idx:03d}"
                self.additional_load_layers.append(
                    {
                        "id": layer_id,
                        "name": str(layer.get("name", f"Additional {idx}")),
                        "psf": float(layer.get("psf", 0.0) or 0.0),
                        "color": self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8"),
                        "bays": self._bay_set_from_saved(layer.get("bays", [])),
                    }
                )
            self._additional_load_layer_counter = max(
                [int(m.group(1)) for layer in self.additional_load_layers for m in [re.search(r"(\d+)$", str(layer.get("id", "")))] if m]
                or [len(self.additional_load_layers)]
            )
            self.selected_additional_load_layer_id = (
                str(self.additional_load_layers[0].get("id")) if self.additional_load_layers else None
            )

            self.mezz_zones = copy.deepcopy(state.get("mezzanines", []) or [])
            for zone in self.mezz_zones:
                if isinstance(zone, dict):
                    self._sanitize_mezz_zone_joist_overrides(zone)
            self._mezz_zone_counter = max(
                [int(m.group(1)) for zone in self.mezz_zones for m in [re.search(r"(\d+)$", str(zone.get("id", "")))] if m]
                or [len(self.mezz_zones)]
            )
            self.selected_mezz_zone_id = str(self.mezz_zones[0].get("id")) if self.mezz_zones else None

            assignments = state.get("assignments", {}) if isinstance(state.get("assignments", {}), dict) else {}
            self.joist_selection_by_group = dict(assignments.get("joists", {}) or {})
            self.girder_selection_by_group = dict(assignments.get("girders", {}) or {})
            self.column_selection_by_group = dict(assignments.get("columns", {}) or {})
            self.mezz_joist_selection_by_group = dict(assignments.get("mezz_joists", {}) or {})
            self.mezz_girder_selection_by_group = dict(assignments.get("mezz_girders", {}) or {})
            self.mezz_column_selection_by_group = dict(assignments.get("mezz_columns", {}) or {})
        finally:
            self._project_loading = False

        self._clear_calculation_results_after_project_change(clear_assignments=False)
        self._on_snow_code_changed()
        self._refresh_dock_line_options()
        self._refresh_mezz_line_options()
        self._refresh_additional_load_layer_tree()
        self._refresh_mezz_zone_tree()
        self._refresh_mezz_panel_spacing_tree()
        self._refresh_mezz_internal_spacing_labels()
        self._on_mezz_enabled_changed()
        self.redraw_roof_section()
        self.redraw_tilt_wall_preview()
        self.redraw_mezzanine_preview()
        self.fit_to_view()

    def _clear_calculation_results_after_project_change(self, clear_assignments: bool = False):
        self.last_joist_result = None
        self.last_girder_result = None
        self.last_column_result = None
        self.last_tilt_result = None
        self.last_footing_result = None
        self.last_mezz_result = None
        self.last_mezz_footing_result = None
        if clear_assignments:
            self.joist_selection_by_group = {}
            self.girder_selection_by_group = {}
            self.column_selection_by_group = {}
            self.mezz_joist_selection_by_group = {}
            self.mezz_girder_selection_by_group = {}
            self.mezz_column_selection_by_group = {}
        self.joist_calc_status_var.set("Project loaded. Recalculate joists.")
        self.girder_calc_status_var.set("Project loaded. Recalculate girders.")
        self.column_calc_status_var.set("Project loaded. Recalculate columns.")
        self.tilt_calc_status_var.set("Project loaded. Recalculate tilt walls.")
        self.footing_calc_status_var.set("Project loaded. Recalculate footings.")
        self.mezz_calc_status_var.set("Project loaded. Recalculate mezzanines.")
        self.report_status_var.set("Project loaded. Use Recalculate All or export a fresh PDF.")
        self._set_joist_results_text("")
        self._set_girder_results_text("")
        self._set_column_results_text("")
        self._set_tilt_results_text("")
        self._set_footing_results_text("")
        self._set_mezz_results_text("")
        self._clear_report_log()
        self._refresh_joist_selection_table()
        self._refresh_girder_selection_table()
        self._refresh_column_selection_table()

    def load_project(self, path=None):
        chosen = path
        if chosen is None:
            chosen = filedialog.askopenfilename(
                title="Load Structural Steel Project",
                filetypes=[("Project JSON", "*.json"), ("All Files", "*.*")],
            )
            if not chosen:
                return
        try:
            with Path(chosen).open("r", encoding="utf-8") as handle:
                state = json.load(handle)
            self._apply_project_state(state)
        except InputValidationError as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not load project:\n{exc}")
            return
        self.current_project_path = Path(chosen) if Path(chosen) != self._autosave_path else None
        self.project_status_var.set(
            f"Loaded: {Path(chosen).name}" if Path(chosen) != self._autosave_path else "Recovered autosave"
        )

    def _schedule_autosave(self):
        if self._autosave_job:
            try:
                self.root.after_cancel(self._autosave_job)
            except Exception:
                pass
        self._autosave_job = self.root.after(15000, self._autosave_tick)

    def _autosave_tick(self):
        if not self._project_loading:
            self.save_project(self._autosave_path, silent=True)
        self._schedule_autosave()

    def _prompt_autosave_recovery(self):
        if self.current_project_path or not self._autosave_path.exists():
            return
        try:
            modified = datetime.fromtimestamp(self._autosave_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            modified = "recently"
        if messagebox.askyesno(
            "Recover autosaved project",
            f"An autosaved project was found from {modified}.\n\nLoad it now?",
        ):
            self.load_project(self._autosave_path)

    def _arm_paned_init(self, paned: ttk.PanedWindow, placer):
        """Run `placer(paned)` the first time `paned` actually has a real width.

        Notebook tabs are only laid out when first shown, so a plain `after()` retry
        loop times out before the user opens the Mezzanines tab. We instead bind to
        <Map> + <Configure> on the paned itself so the placement fires exactly once,
        whenever the tab finally becomes visible.
        """
        state = {"done": False}

        def attempt(_evt=None):
            if state["done"]:
                return
            try:
                paned.update_idletasks()
                total = int(paned.winfo_width())
                if total <= 50:
                    return
                placer(paned, total)
                state["done"] = True
            except Exception:
                state["done"] = True

        paned.bind("<Map>", attempt, add="+")
        paned.bind("<Configure>", attempt, add="+")
        # First-shot try in case the pane already has a size at construction time.
        self.root.after(50, attempt)

    def _init_paned_split(self, paned: ttk.PanedWindow, sash_x: int):
        """Place the first sash at sash_x px once the pane has been laid out."""
        def place(p, total):
            target = max(220, min(sash_x, max(220, total // 2)))
            p.sashpos(0, target)
        self._arm_paned_init(paned, place)

    def _init_3pane_split(self, paned: ttk.PanedWindow, left_px: int, right_panel_px: int):
        """Initialize two-sash placement so left rail = `left_px`, right inspector = `right_panel_px`."""
        def place(p, total):
            left = max(200, min(left_px, max(200, total // 4)))
            right_target = total - max(260, min(right_panel_px, max(260, total // 3)))
            right_target = max(left + 240, right_target)
            p.sashpos(0, left)
            p.sashpos(1, right_target)
        self._arm_paned_init(paned, place)

    def _build_grid_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Resizable split between left controls and right canvas
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")
        self._grid_paned = paned

        controls_wrap = ttk.Frame(paned)
        controls_wrap.rowconfigure(0, weight=1)
        controls_wrap.columnconfigure(0, weight=1)
        paned.add(controls_wrap, weight=0)

        self.controls_canvas = tk.Canvas(
            controls_wrap,
            bg=self._cv["controls_bg"],
            highlightthickness=1,
            highlightbackground=self._cv["canvas_hl_bg"],
            width=360,
        )
        self.controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar = ttk.Scrollbar(controls_wrap, orient="vertical", command=self.controls_canvas.yview)
        controls_scrollbar.grid(row=0, column=1, sticky="ns")
        self.controls_canvas.configure(yscrollcommand=controls_scrollbar.set)

        panel = ttk_bs.Frame(self.controls_canvas, padding=14)
        self._controls_panel_window = self.controls_canvas.create_window((0, 0), window=panel, anchor="nw")

        def _on_controls_frame_configure(_event):
            self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all"))

        def _on_controls_canvas_configure(event):
            self.controls_canvas.itemconfigure(self._controls_panel_window, width=event.width)

        panel.bind("<Configure>", _on_controls_frame_configure)
        self.controls_canvas.bind("<Configure>", _on_controls_canvas_configure)

        canvas_wrap = ttk.Frame(paned)
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        paned.add(canvas_wrap, weight=1)
        # Set a sensible initial split position once the tab has a real width
        parent.after(50, lambda: self._init_paned_split(paned, 380))

        self.canvas = tk.Canvas(
            canvas_wrap,
            bg=self._cv["grid_bg"],
            highlightthickness=1,
            highlightbackground=self._cv["canvas_hl_bg"],
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        ttk.Label(panel, text="Grid Controls", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        ttk.Label(panel, text="New X Bay (ft)").grid(row=1, column=0, sticky="w")
        self.x_spacing_var = tk.StringVar(value="54")
        ttk.Entry(panel, textvariable=self.x_spacing_var, width=10).grid(
            row=1, column=1, sticky="ew", padx=(6, 0)
        )
        ttk_bs.Button(panel, text="Add X Bay", command=self.add_x_bay, bootstyle="outline").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk_bs.Button(panel, text="Remove Last X Bay", command=self.remove_x_bay, bootstyle="danger-outline").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        ttk.Label(panel, text="New Y Bay (ft)").grid(row=4, column=0, sticky="w", pady=(14, 0))
        self.y_spacing_var = tk.StringVar(value="50")
        ttk.Entry(panel, textvariable=self.y_spacing_var, width=10).grid(
            row=4, column=1, sticky="ew", padx=(6, 0), pady=(14, 0)
        )
        ttk_bs.Button(panel, text="Add Y Bay", command=self.add_y_bay, bootstyle="outline").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk_bs.Button(panel, text="Remove Last Y Bay", command=self.remove_y_bay, bootstyle="danger-outline").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        ttk.Separator(panel).grid(row=7, column=0, columnspan=2, sticky="ew", pady=12)

        ttk_bs.Button(panel, text="Clear Grid", command=self.clear_grid, bootstyle="danger-outline").grid(
            row=8, column=0, columnspan=2, sticky="ew"
        )
        ttk_bs.Button(panel, text="Fit To View", command=self.fit_to_view, bootstyle="outline").grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk.Checkbutton(
            panel,
            text="Auto-fit on bay edits",
            variable=self.auto_fit_on_bay_change,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(panel, text="Left-click mode", font=("Segoe UI", 9, "bold")).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        ttk.Radiobutton(panel, text="Edit Grid Lines", variable=self.interaction_mode, value="edit").grid(
            row=12, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(panel, text="Mark Collateral Bays", variable=self.interaction_mode, value="collateral").grid(
            row=13, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(panel, text="Mark Additional Load Bays", variable=self.interaction_mode, value="custom_load").grid(
            row=14, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(panel, text="Assign Joist Spaces/Bay", variable=self.interaction_mode, value="joists").grid(
            row=15, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(panel, text="Toggle Void Bays (Shape)", variable=self.interaction_mode, value="shape").grid(
            row=16, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(panel, text="Toggle Speed Bay Row", variable=self.interaction_mode, value="speed_rows").grid(
            row=17, column=0, columnspan=2, sticky="w"
        )
        ttk.Radiobutton(
            panel,
            text="Toggle Load-Bearing Perimeter",
            variable=self.interaction_mode,
            value="lb_walls",
        ).grid(row=18, column=0, columnspan=2, sticky="w")
        ttk.Label(panel, text="Additional Layer PSF (psf)").grid(row=19, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(panel, textvariable=self.custom_load_addition_var, width=10).grid(
            row=19, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        ttk.Label(panel, text="Joist spaces per bay").grid(row=20, column=0, sticky="w", pady=(8, 0))
        self.joist_count_var = tk.StringVar(value="7")
        ttk.Spinbox(panel, from_=1, to=50, textvariable=self.joist_count_var, width=8).grid(
            row=20, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        ttk.Label(panel, textvariable=self.recommended_joist_spaces_var, style="Muted.TLabel", wraplength=220).grid(
            row=21, column=0, columnspan=2, sticky="w", pady=(3, 0)
        )
        ttk_bs.Button(panel, text="Apply Joist Spaces To All Bays", command=self.apply_joists_to_all_bays, bootstyle="outline").grid(
            row=22, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk_bs.Button(panel, text="Clear Collateral Bays", command=self.clear_collateral_bays, bootstyle="danger-outline").grid(
            row=23, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(panel, text="Clear Selected Additional Bays", command=self.clear_custom_load_bays, bootstyle="danger-outline").grid(
            row=24, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(panel, text="Clear Joist Assignments", command=self.clear_joist_assignments, bootstyle="danger-outline").grid(
            row=25, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(panel, text="Clear Void Bays", command=self.clear_inactive_bays, bootstyle="danger-outline").grid(
            row=26, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk.Label(panel, text="Speed Bay Rows").grid(row=27, column=0, sticky="w", pady=(10, 0))
        ttk.Label(panel, textvariable=self.speed_bay_rows_summary_var, style="Muted.TLabel").grid(
            row=27, column=1, sticky="w", padx=(6, 0), pady=(10, 0)
        )
        ttk.Label(panel, text="Speed Transitions").grid(row=28, column=0, sticky="w", pady=(2, 0))
        ttk.Label(panel, textvariable=self.speed_transition_summary_var, style="Muted.TLabel").grid(
            row=28, column=1, sticky="w", padx=(6, 0), pady=(2, 0)
        )
        ttk_bs.Button(panel, text="Clear Speed Bay Rows", command=self.clear_speed_bay_rows, bootstyle="danger-outline").grid(
            row=29, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(panel, text="Set All Boundary LB", command=self.set_all_load_bearing_perimeter, bootstyle="outline").grid(
            row=30, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(panel, text="Clear Boundary LB", command=self.clear_load_bearing_perimeter, bootstyle="danger-outline").grid(
            row=31, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        ttk.Separator(panel).grid(row=32, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(panel, text="Additional Load Layers", font=("Segoe UI", 9, "bold")).grid(
            row=33, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(panel, text="Layer Name").grid(row=34, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(panel, textvariable=self.additional_load_name_var, width=16).grid(
            row=34, column=1, sticky="ew", padx=(6, 0), pady=(4, 0)
        )
        ttk.Label(panel, text="Layer Color").grid(row=35, column=0, sticky="w", pady=(4, 0))
        color_row = ttk.Frame(panel)
        color_row.grid(row=35, column=1, sticky="ew", padx=(6, 0), pady=(4, 0))
        color_row.columnconfigure(0, weight=1)
        ttk.Entry(color_row, textvariable=self.additional_load_color_var, width=10).grid(row=0, column=0, sticky="ew")
        ttk_bs.Button(color_row, text="Pick", command=self.pick_additional_load_color, bootstyle="outline").grid(row=0, column=1, padx=(6, 0))

        addl_btns = ttk_bs.Frame(panel)
        addl_btns.grid(row=36, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        addl_btns.columnconfigure(0, weight=1)
        addl_btns.columnconfigure(1, weight=1)
        ttk_bs.Button(addl_btns, text="Add Layer", command=self.add_additional_load_layer, bootstyle="outline").grid(row=0, column=0, sticky="ew")
        ttk_bs.Button(addl_btns, text="Update Selected", command=self.update_selected_additional_load_layer, bootstyle="outline").grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        ttk_bs.Button(addl_btns, text="Delete Selected", command=self.delete_selected_additional_load_layer, bootstyle="danger-outline").grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )
        ttk_bs.Button(addl_btns, text="Clear All Layers", command=self.clear_all_additional_load_layers, bootstyle="danger-outline").grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 0)
        )

        layer_cols = ("name", "psf", "color", "bays")
        self.additional_load_tree = ttk_bs.Treeview(panel, columns=layer_cols, show="headings", height=5, bootstyle="primary")
        self.additional_load_tree.heading("name", text="Layer")
        self.additional_load_tree.heading("psf", text="psf")
        self.additional_load_tree.heading("color", text="Color")
        self.additional_load_tree.heading("bays", text="Bays")
        self.additional_load_tree.column("name", width=92, anchor="w")
        self.additional_load_tree.column("psf", width=52, anchor="e")
        self.additional_load_tree.column("color", width=82, anchor="center")
        self.additional_load_tree.column("bays", width=48, anchor="e")
        self.additional_load_tree.grid(row=37, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.additional_load_tree.bind("<<TreeviewSelect>>", self._on_additional_load_layer_selected)
        ttk.Label(panel, textvariable=self.additional_load_status_var, style="Muted.TLabel", wraplength=220).grid(
            row=38, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self._refresh_additional_load_layer_tree()

        self.info_var = tk.StringVar(
            value=(
                "Controls:\n"
                "- Mouse wheel: Scroll up/down\n"
                "- Shift + wheel: Scroll left/right\n"
                "- Ctrl + wheel: Zoom\n"
                "- Middle-drag: Pan\n"
                "- Mode Edit Grid Lines: Left-drag interior lines\n"
                "- Mode Mark Collateral Bays: Left-click to toggle green\n"
                "- Mode Mark Additional Load Bays: Left-click to toggle selected layer color\n"
                "- Mode Assign Joist Spaces/Bay: Left-click to set joist spaces per bay\n"
                "- Mode Toggle Void Bays: Left-click to cut/add bays\n"
                "- Mode Toggle Speed Bay Row: click any bay in a row to toggle that full row\n"
                "- Mode Toggle Load-Bearing Perimeter: click any active-boundary segment\n"
                "- Apply Joist Spaces To All Bays: set one space-count across full grid\n"
                "- Joist spaces define spacing; joist lines = spaces + 1\n"
                "- Red boundary segments = load-bearing walls\n"
                "- Speed bay rows define dock zones; transitions into these rows trigger CH break logic\n"
                "- Units: ft"
            )
        )
        ttk.Label(panel, textvariable=self.info_var, justify="left").grid(
            row=39, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)

        def _on_controls_mouse_wheel(event):
            direction = 0
            if getattr(event, "num", None) == 4:
                direction = -1
            elif getattr(event, "num", None) == 5:
                direction = 1
            else:
                delta = int(getattr(event, "delta", 0))
                if delta > 0:
                    direction = -1
                elif delta < 0:
                    direction = 1
            if direction:
                self.controls_canvas.yview_scroll(direction, "units")
                return "break"
            return None

        def _bind_controls_scroll(widget):
            widget.bind("<MouseWheel>", _on_controls_mouse_wheel, add="+")
            widget.bind("<Button-4>", _on_controls_mouse_wheel, add="+")
            widget.bind("<Button-5>", _on_controls_mouse_wheel, add="+")
            for child in widget.winfo_children():
                _bind_controls_scroll(child)

        _bind_controls_scroll(panel)
        self.controls_canvas.bind("<MouseWheel>", _on_controls_mouse_wheel, add="+")
        self.controls_canvas.bind("<Button-4>", _on_controls_mouse_wheel, add="+")
        self.controls_canvas.bind("<Button-5>", _on_controls_mouse_wheel, add="+")

        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Enter>", lambda _e: self.canvas.focus_set())
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Control-MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-Button-5>", self.on_mouse_wheel)
        self.canvas.bind("<Control-Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Control-Button-5>", self.on_mouse_wheel)
        self.canvas.bind("<Button-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_drag)
        self.canvas.bind("<ButtonPress-1>", self.on_left_down)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_up)
        self._refresh_dock_line_options()

    def _build_mezzanine_tab(self, parent: ttk.Frame):
        """Three-pane layout: left rail (zones list), center (plan canvas), right (inspector).

        UX rules:
          - "+ Add Mezzanine" seeds a zone at a safe spot inside the active grid and selects it.
          - Click+drag on empty canvas draws a free-size rectangle (always-on, no mode toggle).
          - Clicking inside an existing zone selects it; the Inspector pane on the right edits
            the selected zone's properties live.
          - Internal bays / per-panel overrides live in a collapsible Advanced disclosure.
        """
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(2, weight=0)

        # ---- Header bar ----------------------------------------------------------------
        header = ttk_bs.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(2, weight=1)
        ttk_bs.Label(
            header, text="Mezzanines", font=("Segoe UI", 14, "bold")
        ).grid(row=0, column=0, sticky="w")
        ttk_bs.Checkbutton(
            header,
            text="Enabled",
            variable=self.mezzanine_enabled_var,
            command=self._on_mezz_enabled_changed,
            bootstyle="primary-round-toggle",
        ).grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk_bs.Label(
            header,
            text="Click + drag on the plan to draw, or click +Add Mezzanine.",
            style="Muted.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk_bs.Button(
            header,
            text="Calculate",
            command=self.calculate_mezzanines,
            bootstyle="success",
        ).grid(row=0, column=3, sticky="e", padx=(8, 0))

        # ---- Three-pane layout: zones list | canvas | inspector -----------------------
        mezz_paned = ttk.PanedWindow(parent, orient="horizontal")
        mezz_paned.grid(row=1, column=0, sticky="nsew")
        self._mezz_paned = mezz_paned

        # ===== LEFT RAIL: zones list =====
        rail = ttk_bs.Frame(mezz_paned, padding=(8, 6, 8, 6))
        rail.columnconfigure(0, weight=1)
        rail.rowconfigure(2, weight=1)
        mezz_paned.add(rail, weight=0)

        ttk_bs.Label(rail, text="Mezzanines", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        ttk_bs.Button(
            rail,
            text="+  Add Mezzanine",
            command=self.add_mezz_zone,
            bootstyle="primary",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 8))

        # Scrollable cards container for zone rows
        zones_outer = ttk_bs.Frame(rail)
        zones_outer.grid(row=2, column=0, sticky="nsew")
        zones_outer.columnconfigure(0, weight=1)
        zones_outer.rowconfigure(0, weight=1)
        self.mezz_zones_canvas = tk.Canvas(
            zones_outer,
            bg=self._cv["controls_bg"],
            highlightthickness=0,
            width=240,
        )
        self.mezz_zones_canvas.grid(row=0, column=0, sticky="nsew")
        zones_scroll = ttk.Scrollbar(zones_outer, orient="vertical", command=self.mezz_zones_canvas.yview)
        zones_scroll.grid(row=0, column=1, sticky="ns")
        self.mezz_zones_canvas.configure(yscrollcommand=zones_scroll.set)
        self._mezz_zones_list = ttk_bs.Frame(self.mezz_zones_canvas)
        self._mezz_zones_list.columnconfigure(0, weight=1)
        self._mezz_zones_list_window = self.mezz_zones_canvas.create_window(
            (0, 0), window=self._mezz_zones_list, anchor="nw"
        )

        def _sync_zones_scroll(_e=None):
            if not hasattr(self, "mezz_zones_canvas"):
                return
            self.mezz_zones_canvas.configure(scrollregion=self.mezz_zones_canvas.bbox("all"))
            self.mezz_zones_canvas.itemconfigure(
                self._mezz_zones_list_window,
                width=max(180, self.mezz_zones_canvas.winfo_width()),
            )

        self._mezz_zones_list.bind("<Configure>", _sync_zones_scroll)
        self.mezz_zones_canvas.bind("<Configure>", _sync_zones_scroll)

        def _on_zones_wheel(event):
            delta = int(getattr(event, "delta", 0))
            num = getattr(event, "num", None)
            direction = -1 if (num == 4 or delta > 0) else (1 if (num == 5 or delta < 0) else 0)
            if direction:
                self.mezz_zones_canvas.yview_scroll(direction, "units")
                return "break"
            return None

        self.mezz_zones_canvas.bind("<MouseWheel>", _on_zones_wheel, add="+")
        self.mezz_zones_canvas.bind("<Button-4>", _on_zones_wheel, add="+")
        self.mezz_zones_canvas.bind("<Button-5>", _on_zones_wheel, add="+")
        self._mezz_zones_wheel_handler = _on_zones_wheel

        # Footer of rail: Clear All
        ttk_bs.Button(
            rail,
            text="Clear All",
            command=self.clear_mezz_zones,
            bootstyle="danger-outline",
        ).grid(row=3, column=0, sticky="ew", pady=(8, 0))

        # ===== CENTER: canvas + bottom toolbar =====
        center = ttk_bs.Frame(mezz_paned, padding=(0, 0, 0, 0))
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=1)
        center.rowconfigure(1, weight=0)
        mezz_paned.add(center, weight=4)

        canvas_wrap = ttk_bs.Frame(center)
        canvas_wrap.grid(row=0, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        self.mezz_canvas = tk.Canvas(
            canvas_wrap,
            bg=self._cv["mezz_bg"],
            highlightthickness=1,
            highlightbackground=self._cv["canvas_hl_bg"],
        )
        self.mezz_canvas.grid(row=0, column=0, sticky="nsew")
        mezz_y_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.mezz_canvas.yview)
        mezz_y_scroll.grid(row=0, column=1, sticky="ns")
        mezz_x_scroll = ttk.Scrollbar(canvas_wrap, orient="horizontal", command=self.mezz_canvas.xview)
        mezz_x_scroll.grid(row=1, column=0, sticky="ew")
        self.mezz_canvas.configure(xscrollcommand=mezz_x_scroll.set, yscrollcommand=mezz_y_scroll.set)
        self.mezz_canvas.bind("<Configure>", lambda _e: self.redraw_mezzanine_preview())
        self.mezz_canvas.bind("<ButtonPress-1>", self.on_mezz_canvas_down)
        self.mezz_canvas.bind("<B1-Motion>", self.on_mezz_canvas_drag)
        self.mezz_canvas.bind("<ButtonRelease-1>", self.on_mezz_canvas_up)
        self.mezz_canvas.bind("<MouseWheel>", self.on_mezz_canvas_mouse_wheel)
        self.mezz_canvas.bind("<Shift-MouseWheel>", self.on_mezz_canvas_mouse_wheel)
        self.mezz_canvas.bind("<Control-MouseWheel>", self.on_mezz_canvas_mouse_wheel)
        self.mezz_canvas.bind("<Button-4>", self.on_mezz_canvas_mouse_wheel)
        self.mezz_canvas.bind("<Button-5>", self.on_mezz_canvas_mouse_wheel)

        # Thin canvas toolbar — zoom, fit, snap controls
        canvas_bar = ttk_bs.Frame(center, padding=(6, 6, 6, 0))
        canvas_bar.grid(row=1, column=0, sticky="ew")
        canvas_bar.columnconfigure(2, weight=1)
        ttk_bs.Label(canvas_bar, text="Zoom").grid(row=0, column=0, sticky="w")
        ttk_bs.Scale(
            canvas_bar,
            from_=1.0,
            to=6.0,
            variable=self.mezz_zoom_var,
            orient="horizontal",
            command=lambda _v: self.redraw_mezzanine_preview(),
            bootstyle="primary",
            length=180,
        ).grid(row=0, column=1, sticky="w", padx=(8, 8))
        ttk_bs.Button(canvas_bar, text="Fit", command=self.reset_mezz_zoom, bootstyle="outline").grid(
            row=0, column=2, sticky="w"
        )
        ttk_bs.Checkbutton(
            canvas_bar,
            text="Snap",
            variable=self.mezz_snap_enabled_var,
        ).grid(row=0, column=3, sticky="e", padx=(8, 4))
        ttk_bs.Label(canvas_bar, text="step ft").grid(row=0, column=4, sticky="e")
        ttk_bs.Entry(canvas_bar, textvariable=self.mezz_snap_step_var, width=4).grid(
            row=0, column=5, sticky="e", padx=(4, 0)
        )

        # ===== RIGHT: inspector + results =====
        right = ttk_bs.Frame(mezz_paned)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        mezz_paned.add(right, weight=1)
        parent.after(50, lambda: self._init_3pane_split(mezz_paned, 240, 360))

        inspector_outer = ttk_bs.Frame(right)
        inspector_outer.grid(row=0, column=0, sticky="nsew")
        inspector_outer.columnconfigure(0, weight=1)
        inspector_outer.rowconfigure(0, weight=1)

        self.mezz_inspector_canvas = tk.Canvas(
            inspector_outer,
            bg=self._cv["controls_bg"],
            highlightthickness=0,
            width=320,
        )
        self.mezz_inspector_canvas.grid(row=0, column=0, sticky="nsew")
        inspector_scroll = ttk.Scrollbar(inspector_outer, orient="vertical", command=self.mezz_inspector_canvas.yview)
        inspector_scroll.grid(row=0, column=1, sticky="ns")
        self.mezz_inspector_canvas.configure(yscrollcommand=inspector_scroll.set)
        inspector = ttk_bs.Frame(self.mezz_inspector_canvas, padding=12)
        self._mezz_inspector_window = self.mezz_inspector_canvas.create_window(
            (0, 0), window=inspector, anchor="nw"
        )
        inspector.columnconfigure(0, weight=1)

        def _sync_inspector_scroll(_e=None):
            if not hasattr(self, "mezz_inspector_canvas"):
                return
            self.mezz_inspector_canvas.configure(scrollregion=self.mezz_inspector_canvas.bbox("all"))
            self.mezz_inspector_canvas.itemconfigure(
                self._mezz_inspector_window,
                width=max(260, self.mezz_inspector_canvas.winfo_width()),
            )

        inspector.bind("<Configure>", _sync_inspector_scroll)
        self.mezz_inspector_canvas.bind("<Configure>", _sync_inspector_scroll)

        def _on_inspector_wheel(event):
            delta = int(getattr(event, "delta", 0))
            num = getattr(event, "num", None)
            direction = -1 if (num == 4 or delta > 0) else (1 if (num == 5 or delta < 0) else 0)
            if direction:
                self.mezz_inspector_canvas.yview_scroll(direction, "units")
                return "break"
            return None

        def _bind_inspector_wheel(widget):
            widget.bind("<MouseWheel>", _on_inspector_wheel, add="+")
            widget.bind("<Button-4>", _on_inspector_wheel, add="+")
            widget.bind("<Button-5>", _on_inspector_wheel, add="+")
            for child in widget.winfo_children():
                _bind_inspector_wheel(child)

        # Inspector header
        self.mezz_inspector_title_var = tk.StringVar(value="No mezzanine selected")
        ttk_bs.Label(
            inspector,
            textvariable=self.mezz_inspector_title_var,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk_bs.Label(
            inspector,
            text="Click +Add Mezzanine, draw on the plan, or pick one from the list.",
            style="Muted.TLabel",
            wraplength=280,
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        # The inspector body holds all editable fields. It will be hidden when nothing is selected.
        self._mezz_inspector_body = ttk_bs.Frame(inspector)
        self._mezz_inspector_body.grid(row=2, column=0, sticky="ew")
        self._mezz_inspector_body.columnconfigure(0, weight=1)
        self._mezz_props_frame = self._mezz_inspector_body  # legacy alias

        # --- Identity & loads ---
        ident = ttk.LabelFrame(self._mezz_inspector_body, text="Identity & Loads", padding=10)
        ident.grid(row=0, column=0, sticky="ew")
        ident.columnconfigure(1, weight=1)
        ttk_bs.Label(ident, text="Name").grid(row=0, column=0, sticky="w")
        self.mezz_name_entry = ttk_bs.Entry(ident, textvariable=self.mezz_name_var)
        self.mezz_name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk_bs.Label(ident, text="Elevation (ft)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk_bs.Entry(ident, textvariable=self.mezz_elevation_var, width=10).grid(
            row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0)
        )
        ttk_bs.Label(ident, text="DL / LL (psf)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        loads_row = ttk_bs.Frame(ident)
        loads_row.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk_bs.Entry(loads_row, textvariable=self.mezz_dead_load_var, width=7).grid(row=0, column=0)
        ttk_bs.Label(loads_row, text="/").grid(row=0, column=1, padx=4)
        ttk_bs.Entry(loads_row, textvariable=self.mezz_live_load_var, width=7).grid(row=0, column=2)

        # --- Geometry ---
        geom = ttk.LabelFrame(self._mezz_inspector_body, text="Geometry", padding=10)
        geom.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        geom.columnconfigure(1, weight=1)
        ttk_bs.Label(geom, text="Origin (ft)").grid(row=0, column=0, sticky="w")
        origin_row = ttk_bs.Frame(geom)
        origin_row.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk_bs.Label(origin_row, text="X").grid(row=0, column=0, sticky="w")
        ttk_bs.Entry(origin_row, textvariable=self.mezz_origin_x_var, width=7).grid(row=0, column=1, padx=(4, 10))
        ttk_bs.Label(origin_row, text="Y").grid(row=0, column=2, sticky="w")
        ttk_bs.Entry(origin_row, textvariable=self.mezz_origin_y_var, width=7).grid(row=0, column=3, padx=(4, 0))
        ttk_bs.Label(geom, text="Size (ft)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        size_row = ttk_bs.Frame(geom)
        size_row.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk_bs.Label(size_row, text="W").grid(row=0, column=0, sticky="w")
        ttk_bs.Entry(size_row, textvariable=self.mezz_width_var, width=7).grid(row=0, column=1, padx=(4, 10))
        ttk_bs.Label(size_row, text="L").grid(row=0, column=2, sticky="w")
        ttk_bs.Entry(size_row, textvariable=self.mezz_length_var, width=7).grid(row=0, column=3, padx=(4, 0))

        # --- Joists ---
        joist_box = ttk.LabelFrame(self._mezz_inspector_body, text="Joists", padding=10)
        joist_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        joist_box.columnconfigure(1, weight=1)
        ttk_bs.Label(joist_box, text="Direction").grid(row=0, column=0, sticky="w")
        ttk_bs.Combobox(
            joist_box,
            textvariable=self.mezz_joist_direction_var,
            values=["Vertical", "Horizontal"],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk_bs.Label(joist_box, text="Spaces / bay").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(
            joist_box, from_=1, to=60, textvariable=self.mezz_joist_spaces_var, width=8
        ).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))

        # --- Per-zone actions ---
        actions = ttk_bs.Frame(self._mezz_inspector_body)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.mezz_duplicate_btn = ttk_bs.Button(
            actions, text="Duplicate", command=self.duplicate_selected_mezz_zone, bootstyle="outline"
        )
        self.mezz_duplicate_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.mezz_delete_btn = ttk_bs.Button(
            actions, text="Delete", command=self.delete_mezz_zone, bootstyle="danger-outline"
        )
        self.mezz_delete_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        # Legacy alias — _update_mezz_props_state still toggles this name
        self.mezz_update_btn = self.mezz_duplicate_btn

        # --- Advanced disclosure: internal bays + per-panel overrides ---
        self._mezz_advanced_visible = tk.BooleanVar(value=False)
        self._mezz_advanced_btn = ttk_bs.Button(
            self._mezz_inspector_body,
            text="▶  Advanced (Internal Bays & Panel Overrides)",
            command=self._toggle_mezz_advanced,
            bootstyle="link",
        )
        self._mezz_advanced_btn.grid(row=4, column=0, sticky="w", pady=(14, 4))

        self._mezz_advanced_frame = ttk_bs.Frame(self._mezz_inspector_body)
        self._mezz_advanced_frame.grid(row=5, column=0, sticky="ew")
        self._mezz_advanced_frame.columnconfigure(0, weight=1)
        self._mezz_advanced_frame.grid_remove()

        bays = ttk.LabelFrame(self._mezz_advanced_frame, text="Internal Bays", padding=10)
        bays.grid(row=0, column=0, sticky="ew")
        bays.columnconfigure(0, weight=1)

        xb_row = ttk_bs.Frame(bays)
        xb_row.grid(row=0, column=0, sticky="ew")
        xb_row.columnconfigure(3, weight=1)
        ttk_bs.Label(xb_row, text="X bay (ft)").grid(row=0, column=0, sticky="w")
        ttk_bs.Entry(xb_row, textvariable=self.mezz_new_x_bay_var, width=6).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk_bs.Button(xb_row, text="Add", command=self.add_mezz_internal_x_bay, bootstyle="outline").grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk_bs.Button(xb_row, text="Undo", command=self.remove_last_mezz_internal_x_bay, bootstyle="outline").grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk_bs.Label(
            bays, textvariable=self.mezz_internal_x_summary_var, style="Muted.TLabel", wraplength=280
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        yb_row = ttk_bs.Frame(bays)
        yb_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        yb_row.columnconfigure(3, weight=1)
        ttk_bs.Label(yb_row, text="Y bay (ft)").grid(row=0, column=0, sticky="w")
        ttk_bs.Entry(yb_row, textvariable=self.mezz_new_y_bay_var, width=6).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk_bs.Button(yb_row, text="Add", command=self.add_mezz_internal_y_bay, bootstyle="outline").grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk_bs.Button(yb_row, text="Undo", command=self.remove_last_mezz_internal_y_bay, bootstyle="outline").grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk_bs.Label(
            bays, textvariable=self.mezz_internal_y_summary_var, style="Muted.TLabel", wraplength=280
        ).grid(row=3, column=0, sticky="w", pady=(2, 0))

        bay_btns = ttk_bs.Frame(bays)
        bay_btns.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        bay_btns.columnconfigure(0, weight=1)
        bay_btns.columnconfigure(1, weight=1)
        ttk_bs.Button(
            bay_btns, text="Apply Bays To W/L",
            command=self.apply_bay_builder_to_mezz_dimensions, bootstyle="outline",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk_bs.Button(
            bay_btns, text="Clear Bays",
            command=self.clear_mezz_internal_bays, bootstyle="outline-secondary",
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        panel_box = ttk.LabelFrame(
            self._mezz_advanced_frame, text="Per-Panel Joist Overrides", padding=10
        )
        panel_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        panel_box.columnconfigure(0, weight=1)
        pp_ctrl = ttk_bs.Frame(panel_box)
        pp_ctrl.grid(row=0, column=0, sticky="ew")
        ttk_bs.Label(pp_ctrl, text="Spaces").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            pp_ctrl, from_=1, to=60, textvariable=self.mezz_panel_spacing_value_var, width=5
        ).grid(row=0, column=1, padx=(6, 8))
        self.mezz_panel_set_btn = ttk_bs.Button(
            pp_ctrl, text="Set", command=self.set_selected_mezz_panel_spacing, bootstyle="outline"
        )
        self.mezz_panel_set_btn.grid(row=0, column=2)
        self.mezz_panel_clear_btn = ttk_bs.Button(
            pp_ctrl, text="Clear", command=self.clear_selected_mezz_panel_spacing, bootstyle="outline"
        )
        self.mezz_panel_clear_btn.grid(row=0, column=3, padx=(6, 0))
        self.mezz_panel_reset_btn = ttk_bs.Button(
            pp_ctrl, text="Reset All",
            command=self.clear_all_mezz_panel_spacing_overrides, bootstyle="danger-outline",
        )
        self.mezz_panel_reset_btn.grid(row=0, column=4, padx=(6, 0))

        panel_cols = ("panel", "size", "spaces", "mode")
        self.mezz_panel_tree = ttk_bs.Treeview(
            panel_box,
            columns=panel_cols,
            show="headings",
            height=6,
            bootstyle="primary",
            selectmode="extended",
        )
        for col, lbl, w, anch in (
            ("panel", "Panel", 60, "center"),
            ("size", "Size (XxY ft)", 120, "center"),
            ("spaces", "J", 40, "e"),
            ("mode", "Mode", 70, "center"),
        ):
            self.mezz_panel_tree.heading(col, text=lbl)
            self.mezz_panel_tree.column(col, width=w, anchor=anch)
        self.mezz_panel_tree.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.mezz_panel_tree.bind("<<TreeviewSelect>>", self._on_mezz_panel_tree_selected)
        panel_scroll = ttk.Scrollbar(panel_box, orient="vertical", command=self.mezz_panel_tree.yview)
        panel_scroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.mezz_panel_tree.configure(yscrollcommand=panel_scroll.set)

        # Calculation output sits below inspector
        results = ttk.LabelFrame(right, text="Calculation Output", padding=6)
        results.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.mezz_results_text = tk.Text(results, height=8, wrap="none")
        self.mezz_results_text.grid(row=0, column=0, sticky="nsew")
        self.mezz_results_text.configure(
            bg=self._cv["text_bg"],
            fg=self._cv["text_fg"],
            insertbackground=self._cv["text_insert"],
            state="disabled",
        )
        rs_y = ttk.Scrollbar(results, orient="vertical", command=self.mezz_results_text.yview)
        rs_y.grid(row=0, column=1, sticky="ns")
        rs_x = ttk.Scrollbar(results, orient="horizontal", command=self.mezz_results_text.xview)
        rs_x.grid(row=1, column=0, sticky="ew")
        self.mezz_results_text.configure(xscrollcommand=rs_x.set, yscrollcommand=rs_y.set)

        # ===== FOOTER: status =====
        footer = ttk_bs.Frame(parent)
        footer.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        ttk_bs.Label(
            footer, textvariable=self.mezz_status_var, style="Muted.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk_bs.Label(
            footer, textvariable=self.mezz_calc_status_var, style="Muted.TLabel"
        ).grid(row=0, column=1, sticky="e")

        # Bind inspector mousewheel after all widgets are created
        _bind_inspector_wheel(inspector)
        self.mezz_inspector_canvas.bind("<MouseWheel>", _on_inspector_wheel, add="+")
        self.mezz_inspector_canvas.bind("<Button-4>", _on_inspector_wheel, add="+")
        self.mezz_inspector_canvas.bind("<Button-5>", _on_inspector_wheel, add="+")

        self._setup_mezz_property_traces()
        self._refresh_mezz_line_options()
        self._refresh_mezz_internal_spacing_labels()
        self._refresh_mezz_zone_list()
        self._refresh_mezz_panel_spacing_tree()
        self._on_mezz_enabled_changed()
        self._update_mezz_props_state()
        self.redraw_mezzanine_preview()
        self.root.bind("<Escape>", lambda _e: self._cancel_mezz_draw(), add="+")

    def _build_load_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(30, weight=1)

        ttk.Label(parent, text="User Inputs", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            parent,
            text=(
                "Enter service loads (psf) and roof support inputs.\n"
                "Use the Joist Calculation tab to run joist takeoff and assignments."
            ),
            wraplength=620,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        ttk.Label(parent, text="Loads (psf)", font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self._add_load_row(parent, "Dead Load (psf)", self.dead_load_var, 3)
        self._add_load_row(parent, "Live Load (psf)", self.live_load_var, 4)
        self._add_load_row(parent, "Snow Load (psf)", self.snow_load_var, 5)
        self._add_load_row(parent, "Collateral Load Addition (psf)", self.collateral_addition_var, 6)
        ttk.Label(parent, text="Snow Code").grid(row=7, column=0, sticky="w", pady=(4, 0))
        snow_code_combo = ttk.Combobox(
            parent,
            textvariable=self.snow_code_var,
            values=["ASCE 7-16", "ASCE 7-22"],
            state="readonly",
            width=18,
        )
        snow_code_combo.grid(row=7, column=1, sticky="w", pady=(4, 0), padx=(8, 0))
        snow_code_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_snow_code_changed())
        self._add_load_row(parent, "Reduced Snow Load (manual, psf)", self.reduced_snow_load_manual_var, 8)
        self.reduced_snow_load_manual_entry = parent.grid_slaves(row=8, column=1)[0]
        ttk.Label(parent, textvariable=self.reduced_snow_load_status_var, style="Muted.TLabel", wraplength=680).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        ttk.Separator(parent, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(parent, text="Roof Inputs", font=("Segoe UI", 10, "bold")).grid(
            row=11, column=0, columnspan=2, sticky="w"
        )
        self._add_load_row(parent, "Clear Height (ft)", self.clear_height_var, 12)
        self._add_load_row(parent, "Joist Seat Depth (in)", self.joist_seat_depth_var, 13)
        self._add_load_row(parent, "Metal Deck Thickness (in)", self.metal_deck_thickness_var, 14)
        self._add_load_row(parent, "Insulation Depth (in)", self.insulation_depth_var, 15)
        ttk.Separator(parent, orient="horizontal").grid(row=16, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(parent, text="Foundation Inputs", font=("Segoe UI", 10, "bold")).grid(
            row=17, column=0, columnspan=2, sticky="w"
        )
        self._add_load_row(parent, "Footing Depth (ft)", self.footing_depth_var, 18)
        self._add_load_row(parent, "Bearing Pressure (psi)", self.bearing_pressure_var, 19)

        ttk.Separator(parent, orient="horizontal").grid(row=20, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(parent, text="ASCE Hazard Tool Assist", font=("Segoe UI", 10, "bold")).grid(
            row=21, column=0, columnspan=2, sticky="w"
        )
        self._add_load_row(parent, "City", self.location_city_var, 22)
        self._add_load_row(parent, "State", self.location_state_var, 23)

        assist_btns = ttk.Frame(parent)
        assist_btns.grid(row=24, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        assist_btns.columnconfigure(2, weight=1)
        self.lookup_snow_btn = ttk_bs.Button(
            assist_btns,
            text="Lookup Snow Load (Backend)",
            command=self.lookup_snow_load_backend,
            bootstyle="outline",
        )
        self.lookup_snow_btn.grid(row=0, column=0, sticky="w")
        ttk_bs.Button(assist_btns, text="Open ASCE Hazard Tool", command=self._open_asce_hazard_tool, bootstyle="outline").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk_bs.Button(assist_btns, text="Extract Snow Load From Paste", command=self._apply_snow_load_from_paste, bootstyle="outline").grid(
            row=0, column=2, sticky="e"
        )

        ttk.Label(parent, text="Paste ASCE output text").grid(row=25, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.hazard_paste_text = tk.Text(parent, height=5, wrap="word")
        self.hazard_paste_text.grid(row=26, column=0, columnspan=2, sticky="ew")
        self.hazard_paste_text.configure(bg=self._cv["hazard_bg"], fg=self._cv["hazard_fg"], insertbackground=self._cv["hazard_insert"])
        ttk.Label(parent, textvariable=self.hazard_parse_status_var, style="Muted.TLabel", wraplength=680).grid(
            row=27, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self._on_snow_code_changed()

    def _build_calc_tab_shell(
        self,
        parent: ttk.Frame,
        *,
        title: str,
        hint: str,
        primary_btn_text: str,
        primary_cmd,
        auto_btn_text: str,
        auto_cmd,
        status_var: tk.StringVar,
        return_buttons: bool = False,
    ):
        """Shared chrome for Joist/Girder/Column tabs.

        Returns a dict with the slots the caller can fill in:
          - results_host: parent Frame for the results Text widget
          - table_host:   parent Frame for the selection Treeview
          - assign_host:  parent Frame for the chosen-depth/weight + assign/clear buttons
          - footer_host:  parent Frame for the totals label
        Layout: header (title+hint+actions+status) / vertical PanedWindow split
        between results-text and the table+assign+footer column.
        """
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # --- Header row ------------------------------------------------------------
        header = ttk_bs.Frame(parent, padding=(0, 0, 0, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk_bs.Label(header, text=title, font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk_bs.Label(header, text=hint, style="Muted.TLabel", wraplength=760).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 8)
        )
        primary_btn = ttk_bs.Button(
            header, text=primary_btn_text, command=primary_cmd, bootstyle="primary",
            padding=(14, 6),
        )
        primary_btn.grid(row=0, column=1, sticky="e", padx=(8, 6))
        auto_btn = ttk_bs.Button(
            header, text=auto_btn_text, command=auto_cmd, bootstyle="outline-primary",
            padding=(14, 6),
        )
        auto_btn.grid(row=0, column=2, sticky="e")
        ttk_bs.Label(header, textvariable=status_var, style="Muted.TLabel", wraplength=1100).grid(
            row=2, column=0, columnspan=3, sticky="w"
        )

        # --- Body: horizontal paned window (Results left, Selection table right) ---
        body_paned = ttk.PanedWindow(parent, orient="horizontal")
        body_paned.grid(row=1, column=0, sticky="nsew")

        results_host = ttk.LabelFrame(body_paned, text="Results", padding=8)
        results_host.columnconfigure(0, weight=1)
        results_host.rowconfigure(0, weight=1)
        body_paned.add(results_host, weight=2)

        right = ttk_bs.Frame(body_paned)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        body_paned.add(right, weight=3)

        table_host = ttk.LabelFrame(right, text="Selection Table", padding=(8, 6, 8, 6))
        table_host.grid(row=0, column=0, sticky="nsew")
        table_host.columnconfigure(0, weight=1)
        table_host.rowconfigure(0, weight=1)

        assign_host = ttk_bs.Frame(right, padding=(2, 8, 2, 0))
        assign_host.grid(row=1, column=0, sticky="ew")

        footer_host = ttk_bs.Frame(right, padding=(2, 6, 2, 0))
        footer_host.grid(row=2, column=0, sticky="ew")

        # Default split: give Results enough width to show its full pipe-delimited table
        # without horizontal scrolling (~13 columns at 9pt monospace ≈ 780 px).
        self._init_paned_split(body_paned, 780)

        result = {
            "results_host": results_host,
            "table_host": table_host,
            "assign_host": assign_host,
            "footer_host": footer_host,
        }
        if return_buttons:
            result["primary_btn"] = primary_btn
            result["auto_btn"] = auto_btn
        return result

    def _init_vert_split(self, paned: ttk.PanedWindow, *, top_frac: float = 0.35):
        """Place a single vertical sash at the given fractional height once the pane is laid out."""
        state = {"done": False}

        def attempt(_evt=None):
            if state["done"]:
                return
            try:
                paned.update_idletasks()
                total = int(paned.winfo_height())
                if total <= 60:
                    return
                sash_y = max(120, int(total * top_frac))
                paned.sashpos(0, sash_y)
                state["done"] = True
            except Exception:
                state["done"] = True

        paned.bind("<Map>", attempt, add="+")
        paned.bind("<Configure>", attempt, add="+")
        self.root.after(50, attempt)

    def _build_assign_row(self, host, *, depth_var, weight_var, assign_cmd, clear_cmd, clear_text):
        """Compact row: Depth | Weight | [Assign To Selected] [Clear]."""
        host.columnconfigure(4, weight=1)
        ttk_bs.Label(host, text="Chosen Depth (in)").grid(row=0, column=0, sticky="w")
        ttk_bs.Entry(host, textvariable=depth_var, width=8).grid(row=0, column=1, sticky="w", padx=(6, 16))
        ttk_bs.Label(host, text="Chosen Weight (plf)").grid(row=0, column=2, sticky="w")
        ttk_bs.Entry(host, textvariable=weight_var, width=8).grid(row=0, column=3, sticky="w", padx=(6, 16))
        ttk_bs.Button(host, text="Assign To Selected", command=assign_cmd, bootstyle="success", padding=(12, 5)).grid(
            row=0, column=4, sticky="w"
        )
        ttk_bs.Button(host, text=clear_text, command=clear_cmd, bootstyle="danger-outline", padding=(12, 5)).grid(
            row=0, column=5, sticky="e"
        )

    def _build_joist_tab(self, parent: ttk.Frame):
        slots = self._build_calc_tab_shell(
            parent,
            title="Joists",
            hint=(
                "Run joist takeoff and assign depth/weight groups. The selection table covers "
                "Main + Mezz scopes; auto-assign reads from the Joist & LH Joist Excel catalogs."
            ),
            primary_btn_text="Calculate Joists",
            primary_cmd=self.calculate_joists,
            auto_btn_text="Auto Assign From Excel",
            auto_cmd=self.auto_assign_joists_from_catalog,
            status_var=self.joist_calc_status_var,
        )

        # Results text
        self.joist_results_text = tk.Text(slots["results_host"], height=8, wrap="none", font=("Consolas", 9))
        self.joist_results_text.grid(row=0, column=0, sticky="nsew")
        self.joist_results_text.configure(state="disabled")
        rs_y = ttk.Scrollbar(slots["results_host"], orient="vertical", command=self.joist_results_text.yview)
        rs_y.grid(row=0, column=1, sticky="ns")
        rs_x = ttk.Scrollbar(slots["results_host"], orient="horizontal", command=self.joist_results_text.xview)
        rs_x.grid(row=1, column=0, sticky="ew")
        self.joist_results_text.configure(xscrollcommand=rs_x.set, yscrollcommand=rs_y.set)

        # Selection table
        cols = ("scope", "req", "count", "load", "len", "name", "depth", "plf", "wt")
        self.joist_select_tree = ttk_bs.Treeview(
            slots["table_host"], columns=cols, show="headings", height=8, bootstyle="primary"
        )
        for col, lbl, w, anch, minw in (
            ("scope", "Scope", 70, "center", 60),
            ("req", "Requirement", 380, "w", 240),
            ("count", "Qty", 56, "center", 50),
            ("load", "Req (plf)", 92, "e", 80),
            ("len", "Len (ft)", 92, "e", 80),
            ("name", "Joist", 120, "w", 90),
            ("depth", "Depth (in)", 92, "center", 80),
            ("plf", "Wt (plf)", 92, "e", 80),
            ("wt", "Group Wt (lbs)", 120, "e", 100),
        ):
            self.joist_select_tree.heading(col, text=lbl)
            self.joist_select_tree.column(col, width=w, anchor=anch, minwidth=minw, stretch=True)
        self.joist_select_tree.grid(row=0, column=0, sticky="nsew")
        tree_yscroll = ttk.Scrollbar(slots["table_host"], orient="vertical", command=self.joist_select_tree.yview)
        tree_yscroll.grid(row=0, column=1, sticky="ns")
        tree_xscroll = ttk.Scrollbar(slots["table_host"], orient="horizontal", command=self.joist_select_tree.xview)
        tree_xscroll.grid(row=1, column=0, sticky="ew")
        self.joist_select_tree.configure(yscrollcommand=tree_yscroll.set, xscrollcommand=tree_xscroll.set)
        cv = self._cv
        self.joist_select_tree.tag_configure("main", background=cv["tree_main_bg"], foreground=cv["tree_main_fg"])
        self.joist_select_tree.tag_configure("mezz", background=cv["tree_mezz_bg"], foreground=cv["tree_mezz_fg"])

        # Assignment row
        self._build_assign_row(
            slots["assign_host"],
            depth_var=self.selected_depth_var,
            weight_var=self.selected_weight_plf_var,
            assign_cmd=self.assign_selected_joist,
            clear_cmd=self.clear_selected_joists,
            clear_text="Clear Assigned",
        )

        # Footer total
        ttk_bs.Label(
            slots["footer_host"],
            textvariable=self.total_joist_weight_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")

    def _build_girder_tab(self, parent: ttk.Frame):
        slots = self._build_calc_tab_shell(
            parent,
            title="Girders",
            hint=(
                "Girders run on each line (A/B/C…) between columns. "
                "At = Tributary Strip × Bay Width; R1 reduces LL between 200–600 ft²; "
                "Required Cap = Strip × Avg Joist Spacing × TL. Groups split by capacity and depth."
            ),
            primary_btn_text="Calculate Girders",
            primary_cmd=self.calculate_girders,
            auto_btn_text="Auto Assign From Excel",
            auto_cmd=self.auto_assign_girders_from_excel,
            status_var=self.girder_calc_status_var,
            return_buttons=True,
        )
        # Background-thread workers disable this button to prevent re-entry
        self.auto_assign_girder_btn = slots["auto_btn"]

        # Results text
        self.girder_results_text = tk.Text(slots["results_host"], height=8, wrap="none", font=("Consolas", 9))
        self.girder_results_text.grid(row=0, column=0, sticky="nsew")
        self.girder_results_text.configure(state="disabled")
        rs_y = ttk.Scrollbar(slots["results_host"], orient="vertical", command=self.girder_results_text.yview)
        rs_y.grid(row=0, column=1, sticky="ns")
        rs_x = ttk.Scrollbar(slots["results_host"], orient="horizontal", command=self.girder_results_text.xview)
        rs_x.grid(row=1, column=0, sticky="ew")
        self.girder_results_text.configure(xscrollcommand=rs_x.set, yscrollcommand=rs_y.set)

        # Selection table
        cols = ("scope", "req", "count", "cap", "len", "n", "maxd", "name", "depth", "plf", "wt")
        self.girder_select_tree = ttk_bs.Treeview(
            slots["table_host"], columns=cols, show="headings", height=8, bootstyle="primary"
        )
        for col, lbl, w, anch, minw in (
            ("scope", "Scope", 70, "center", 60),
            ("req", "Requirement", 420, "w", 240),
            ("count", "Qty", 56, "center", 50),
            ("cap", "Req Cap (lbs)", 110, "e", 92),
            ("len", "Len (ft)", 92, "e", 80),
            ("n", "N", 56, "center", 48),
            ("maxd", "Depth Ref (in)", 110, "center", 90),
            ("name", "Girder", 140, "w", 100),
            ("depth", "Chosen Depth (in)", 130, "center", 100),
            ("plf", "Wt (plf)", 92, "e", 80),
            ("wt", "Group Wt (lbs)", 120, "e", 100),
        ):
            self.girder_select_tree.heading(col, text=lbl)
            self.girder_select_tree.column(col, width=w, anchor=anch, minwidth=minw, stretch=True)
        self.girder_select_tree.grid(row=0, column=0, sticky="nsew")
        tree_yscroll = ttk.Scrollbar(slots["table_host"], orient="vertical", command=self.girder_select_tree.yview)
        tree_yscroll.grid(row=0, column=1, sticky="ns")
        tree_xscroll = ttk.Scrollbar(slots["table_host"], orient="horizontal", command=self.girder_select_tree.xview)
        tree_xscroll.grid(row=1, column=0, sticky="ew")
        self.girder_select_tree.configure(yscrollcommand=tree_yscroll.set, xscrollcommand=tree_xscroll.set)
        cv = self._cv
        self.girder_select_tree.tag_configure("main", background=cv["tree_main_bg"], foreground=cv["tree_main_fg"])
        self.girder_select_tree.tag_configure("mezz", background=cv["tree_mezz_bg"], foreground=cv["tree_mezz_fg"])


        # Assignment row
        self._build_assign_row(
            slots["assign_host"],
            depth_var=self.selected_girder_depth_var,
            weight_var=self.selected_girder_weight_plf_var,
            assign_cmd=self.assign_selected_girder,
            clear_cmd=self.clear_selected_girders,
            clear_text="Clear Assigned",
        )

        # Footer total
        ttk_bs.Label(
            slots["footer_host"],
            textvariable=self.total_girder_weight_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")

    def _build_column_tab(self, parent: ttk.Frame):
        slots = self._build_calc_tab_shell(
            parent,
            title="Columns",
            hint=(
                "Generated at steel-supported intersections (interior + non-LB perimeter). "
                "At = Avg Bay W × Avg Bay L; TL = DL + max(Reduced LL, Reduced SL) + collateral share. "
                "Required Cap = At × TL (kips). Selection table covers Main + Mezz."
            ),
            primary_btn_text="Calculate Columns",
            primary_cmd=self.calculate_columns,
            auto_btn_text="Auto Assign From Excel",
            auto_cmd=self.auto_assign_columns_from_excel,
            status_var=self.column_calc_status_var,
        )

        # Results text
        self.column_results_text = tk.Text(slots["results_host"], height=8, wrap="none", font=("Consolas", 9))
        self.column_results_text.grid(row=0, column=0, sticky="nsew")
        self.column_results_text.configure(state="disabled")
        rs_y = ttk.Scrollbar(slots["results_host"], orient="vertical", command=self.column_results_text.yview)
        rs_y.grid(row=0, column=1, sticky="ns")
        rs_x = ttk.Scrollbar(slots["results_host"], orient="horizontal", command=self.column_results_text.xview)
        rs_x.grid(row=1, column=0, sticky="ew")
        self.column_results_text.configure(xscrollcommand=rs_x.set, yscrollcommand=rs_y.set)

        # Selection table
        cols = ("scope", "req", "count", "kips", "hgt", "name", "depth", "plf", "wt")
        self.column_select_tree = ttk_bs.Treeview(
            slots["table_host"], columns=cols, show="headings", height=8, bootstyle="primary"
        )
        for col, lbl, w, anch, minw in (
            ("scope", "Scope", 70, "center", 60),
            ("req", "Requirement", 400, "w", 240),
            ("count", "Qty", 56, "center", 50),
            ("kips", "Req (kips)", 100, "e", 88),
            ("hgt", "Avg Ht (ft)", 96, "e", 84),
            ("name", "Column", 140, "w", 100),
            ("depth", "Chosen Depth (in)", 130, "center", 100),
            ("plf", "Wt (plf)", 92, "e", 80),
            ("wt", "Group Wt (lbs)", 120, "e", 100),
        ):
            self.column_select_tree.heading(col, text=lbl)
            self.column_select_tree.column(col, width=w, anchor=anch, minwidth=minw, stretch=True)
        self.column_select_tree.grid(row=0, column=0, sticky="nsew")
        tree_yscroll = ttk.Scrollbar(slots["table_host"], orient="vertical", command=self.column_select_tree.yview)
        tree_yscroll.grid(row=0, column=1, sticky="ns")
        tree_xscroll = ttk.Scrollbar(slots["table_host"], orient="horizontal", command=self.column_select_tree.xview)
        tree_xscroll.grid(row=1, column=0, sticky="ew")
        self.column_select_tree.configure(yscrollcommand=tree_yscroll.set, xscrollcommand=tree_xscroll.set)
        cv = self._cv
        self.column_select_tree.tag_configure("main", background=cv["tree_main_bg"], foreground=cv["tree_main_fg"])
        self.column_select_tree.tag_configure("mezz", background=cv["tree_mezz_bg"], foreground=cv["tree_mezz_fg"])

        # Assignment row
        self._build_assign_row(
            slots["assign_host"],
            depth_var=self.selected_column_depth_var,
            weight_var=self.selected_column_weight_plf_var,
            assign_cmd=self.assign_selected_column,
            clear_cmd=self.clear_selected_columns,
            clear_text="Clear Assigned",
        )

        # Footer total
        ttk_bs.Label(
            slots["footer_host"],
            textvariable=self.total_column_weight_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")

    def _build_tilt_wall_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)
        parent.rowconfigure(6, weight=1)

        ttk.Label(parent, text="Tilt Wall Calculation", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            parent,
            text=(
                "Estimate North/South/East/West tilt wall square footage.\n"
                "Wall top uses Top of Roof = Top of Joist + deck + insulation.\n"
                "East/West base elevation = -1 ft.\n"
                "North and/or South become dock walls when their adjacent speed-bay rows are marked:\n"
                "dock wall center base = -4 ft, with half-bay edges at -1 ft."
            ),
            justify="left",
            wraplength=1000,
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        ttk_bs.Button(parent, text="Calculate Tilt Walls", command=self.calculate_tilt_walls, bootstyle="primary").grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(parent, textvariable=self.tilt_calc_status_var, justify="left", wraplength=1000).grid(
            row=3, column=0, sticky="w", pady=(0, 8)
        )

        self.tilt_results_text = tk.Text(parent, height=10, wrap="none")
        self.tilt_results_text.grid(row=4, column=0, sticky="nsew", pady=(0, 8))
        self.tilt_results_text.configure(state="disabled")

        ttk.Label(parent, text="Tilt Wall Graphic", font=("Segoe UI", 10, "bold")).grid(
            row=5, column=0, sticky="w", pady=(6, 4)
        )
        self.tilt_canvas = tk.Canvas(parent, bg=self._cv["tilt_bg"], highlightthickness=1, highlightbackground=self._cv["canvas_hl_bg"])
        self.tilt_canvas.grid(row=6, column=0, sticky="nsew")
        self.tilt_canvas.bind("<Configure>", lambda _e: self.redraw_tilt_wall_preview())

    def _build_footing_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)

        ttk.Label(parent, text="Pad Footing Calculation", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            parent,
            text=(
                "Pad footing size uses column required capacity.\n"
                "Size(ft) = sqrt(Column Load kips) / sqrt(Bearing Pressure psi / 1000).\n"
                "Size is rounded up to nearest 0.25 ft, then CY = (Size^2 * Footing Depth) / 27.\n"
                "Final quantity adds 10% waste."
            ),
            justify="left",
            wraplength=1000,
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        ttk_bs.Button(parent, text="Calculate Pad Footings", command=self.calculate_pad_footings, bootstyle="primary").grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(parent, textvariable=self.footing_calc_status_var, justify="left", wraplength=1000).grid(
            row=3, column=0, sticky="w", pady=(0, 8)
        )

        self.footing_results_text = tk.Text(parent, height=24, wrap="none")
        self.footing_results_text.grid(row=4, column=0, sticky="nsew")
        self.footing_results_text.configure(state="disabled")

    def _build_report_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)

        ttk.Label(parent, text="Company Report Export", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            parent,
            text=(
                "Run all calculations with auto-assign (joists, girders, columns), then export a professional PDF.\n"
                "The report includes grid/roof/tilt wall graphics, assignment tables, exact component weights, total steel weight,\n"
                "tilt wall areas, footing concrete quantities, plus a dedicated mezzanine section with zone drawings."
            ),
            justify="left",
            wraplength=1040,
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        self.run_all_report_btn = ttk_bs.Button(
            parent,
            text="Run All + Auto-Assign + Export PDF",
            command=self.run_all_calculations_and_export_pdf,
            bootstyle="primary",
        )
        self.run_all_report_btn.grid(row=2, column=0, sticky="w", pady=(0, 8))

        ttk.Label(parent, textvariable=self.report_status_var, justify="left", wraplength=1040).grid(
            row=3, column=0, sticky="w", pady=(0, 8)
        )

        self.report_log_text = tk.Text(parent, height=18, wrap="word")
        self.report_log_text.grid(row=4, column=0, sticky="nsew")
        self.report_log_text.configure(bg=self._cv["text_bg"], fg=self._cv["text_fg"], insertbackground=self._cv["text_insert"])
        self.report_log_text.configure(state="disabled")

    def _build_roof_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        ttk.Label(parent, text="Roof Slope (X-X Section)", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(10, weight=1)

        ttk.Label(controls, text="Roof Type").grid(row=0, column=0, sticky="w")
        roof_type_combo = ttk.Combobox(
            controls,
            textvariable=self.roof_type_var,
            values=["Single Slope", "Double Slope"],
            state="readonly",
            width=14,
        )
        roof_type_combo.grid(row=0, column=1, sticky="w", padx=(6, 14))
        roof_type_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_roof_type_changed())

        ttk.Label(controls, text="Single-Slope Rise Toward").grid(row=0, column=2, sticky="w")
        self.single_slope_direction_combo = ttk.Combobox(
            controls,
            textvariable=self.single_slope_direction_var,
            values=["North", "South"],
            state="readonly",
            width=10,
        )
        self.single_slope_direction_combo.grid(row=0, column=3, sticky="w", padx=(6, 14))
        self.single_slope_direction_combo.bind("<<ComboboxSelected>>", lambda _e: self.redraw_roof_section())

        ttk.Checkbutton(
            controls,
            text="Break Clear Height At Speed-Bay Transition(s)",
            variable=self.break_clear_height_var,
            command=self.redraw_roof_section,
        ).grid(row=0, column=4, sticky="w")

        ttk.Label(controls, text="Speed Rows").grid(row=0, column=5, sticky="w", padx=(14, 0))
        self.roof_speed_rows_value = ttk.Label(controls, textvariable=self.speed_bay_rows_summary_var, width=20)
        self.roof_speed_rows_value.grid(row=0, column=6, sticky="w", padx=(6, 14))

        ttk.Label(controls, text="Transitions").grid(row=0, column=7, sticky="w", padx=(0, 0))
        self.roof_transition_value = ttk.Label(controls, textvariable=self.speed_transition_summary_var, width=14)
        self.roof_transition_value.grid(row=0, column=8, sticky="w", padx=(6, 14))

        ttk.Button(controls, text="Update Section", command=self.redraw_roof_section).grid(
            row=0, column=9, sticky="w"
        )

        ttk.Label(
            parent,
            textvariable=self.roof_section_status_var,
            justify="left",
            wraplength=1160,
            style="Muted.TLabel",
        ).grid(
            row=2, column=0, sticky="w", pady=(6, 8)
        )

        self.roof_canvas = tk.Canvas(parent, bg=self._cv["roof_bg"], highlightthickness=1, highlightbackground=self._cv["canvas_hl_bg"])
        self.roof_canvas.grid(row=3, column=0, sticky="nsew")
        self.roof_canvas.bind("<Configure>", lambda _e: self.redraw_roof_section())
        self._on_roof_type_changed()

    def _on_roof_type_changed(self):
        is_single = str(self.roof_type_var.get()).strip().lower() == "single slope"
        if hasattr(self, "single_slope_direction_combo"):
            self.single_slope_direction_combo.configure(state="readonly" if is_single else "disabled")
        self.redraw_roof_section()

    def _add_load_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(parent, textvariable=var, width=18).grid(
            row=row, column=1, sticky="w", pady=(4, 0), padx=(8, 0)
        )

    def _on_snow_code_changed(self):
        code = self._normalize_snow_code(self.snow_code_var.get())
        if str(self.snow_code_var.get() or "").strip() != code:
            self.snow_code_var.set(code)
        manual_mode = code == "ASCE 7-22"
        if hasattr(self, "reduced_snow_load_manual_entry"):
            self.reduced_snow_load_manual_entry.configure(state="normal" if manual_mode else "disabled")
        if manual_mode:
            self.reduced_snow_load_status_var.set(
                "ASCE 7-22 selected: enter Reduced Snow Load manually (psf)."
            )
        else:
            self.reduced_snow_load_status_var.set(
                "ASCE 7-16 selected: Reduced SL auto = 0.7*SL+5 (SL<=20), else max(0.7*SL, 20)."
            )

    def _http_get_json(self, base_url: str, params=None, headers=None, timeout_sec: float = 18.0):
        query = urlencode(params or {})
        url = f"{base_url}?{query}" if query else base_url
        req_headers = {
            "User-Agent": "StructuralSteelGridDesigner/1.0 (snow-lookup)",
            "Accept": "application/json, text/plain, */*",
        }
        if headers:
            req_headers.update(headers)
        request = Request(url, headers=req_headers)
        try:
            with urlopen(request, timeout=timeout_sec) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
        except HTTPError as exc:
            raise InputValidationError(f"Backend request failed ({exc.code}) for: {base_url}") from exc
        except URLError as exc:
            raise InputValidationError(f"Backend request failed for: {base_url} ({exc.reason})") from exc
        except Exception as exc:
            raise InputValidationError(f"Backend request failed for: {base_url}") from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputValidationError(f"Backend returned invalid JSON for: {base_url}") from exc

    def _to_float_or_none(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        token = str(value).strip().replace(",", "")
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            return None

    def _extract_first_numeric_attr(self, attrs: dict, keys):
        for key in keys:
            val = self._to_float_or_none(attrs.get(key))
            if val is not None:
                return val, key
        return None, None

    def _arcgis_point_query(self, map_server_url: str, layer_id: int, lat: float, lon: float):
        point = {
            "x": float(lon),
            "y": float(lat),
            "spatialReference": {"wkid": 4326},
        }
        payload = self._http_get_json(
            f"{map_server_url.rstrip('/')}/{int(layer_id)}/query",
            params={
                "f": "json",
                "geometry": json.dumps(point, separators=(",", ":")),
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "inSR": "4326",
                "outFields": "*",
                "returnGeometry": "false",
            },
        )
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            msg = payload.get("error", {}).get("message") or "ArcGIS query failed."
            raise InputValidationError(msg)
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            return []
        attrs_list = []
        for feature in features:
            if isinstance(feature, dict) and isinstance(feature.get("attributes"), dict):
                attrs_list.append(feature["attributes"])
        return attrs_list

    def _geocode_city_state(self, city: str, state: str):
        city_text = str(city or "").strip()
        state_text = str(state or "").strip()
        if not city_text and not state_text:
            raise InputValidationError("Enter at least City or State for backend lookup.")
        query = ", ".join(part for part in [city_text, state_text, "USA"] if part)
        result = self._http_get_json(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "us",
            },
            headers={"Accept-Language": "en-US,en;q=0.8"},
        )
        if not isinstance(result, list) or not result:
            raise InputValidationError(f"No location match found for '{query}'.")
        first = result[0]
        lat = self._to_float_or_none(first.get("lat"))
        lon = self._to_float_or_none(first.get("lon"))
        if lat is None or lon is None:
            raise InputValidationError(f"Could not geocode '{query}'.")
        display_name = str(first.get("display_name") or query)
        return lat, lon, display_name

    def _lookup_snow_load_asce_716(self, lat: float, lon: float):
        base = "https://gis.asce.org/arcgis/rest/services/ASCE/Snow_2016_Tile/MapServer"
        lookup_fields = ("Load1_1", "Load1", "Load", "SI", "value")
        for layer_id in (1, 2):
            attrs_list = self._arcgis_point_query(base, layer_id, lat, lon)
            if not attrs_list:
                continue

            positive_candidates = []
            details_url = ""
            for attrs in attrs_list:
                value, field_name = self._extract_first_numeric_attr(attrs, lookup_fields)
                if value is not None and value > 0:
                    positive_candidates.append((float(value), field_name))
                detail_val = str(attrs.get("Details_1") or attrs.get("Details") or "").strip()
                if detail_val:
                    details_url = detail_val

            if positive_candidates:
                best_val, from_field = max(positive_candidates, key=lambda item: item[0])
                source = f"ASCE 7-16 (layer {layer_id}, field {from_field})"
                return best_val, source

            for attrs in attrs_list:
                display = str(attrs.get("Display_1") or attrs.get("Display") or "").lower()
                if "case" in display and "study" in display:
                    suffix = f" Details: {details_url}" if details_url else ""
                    raise InputValidationError(
                        f"Location falls in ASCE 7-16 case-study zone; no direct pg value available.{suffix}"
                    )

        raise InputValidationError("No ASCE 7-16 snow value found for that location.")

    def _lookup_snow_load_asce_722(self, lat: float, lon: float):
        base = "https://gis.asce.org/arcgis/rest/services/ASCE722/s2022_Tile_RC_II/MapServer"
        attrs_list = self._arcgis_point_query(base, 0, lat, lon)
        if not attrs_list:
            raise InputValidationError("No ASCE 7-22 snow value found for that location.")

        lookup_fields = ("SI", "value", "Load1_1", "Load", "Pg")
        positive_candidates = []
        from_label = ""
        for attrs in attrs_list:
            value, from_field = self._extract_first_numeric_attr(attrs, lookup_fields)
            if value is not None and value > 0:
                positive_candidates.append((float(value), from_field))
                from_label = str(attrs.get("SI_Label") or attrs.get("A1A_label") or "").strip()
        if not positive_candidates:
            raise InputValidationError("ASCE 7-22 response had no usable positive snow value at this point.")

        best_val, from_field = max(positive_candidates, key=lambda item: item[0])
        source = f"ASCE 7-22 RC II (layer 0, field {from_field})"
        if from_label:
            source = f"{source}, {from_label}"
        return best_val, source

    def _backend_lookup_snow_load(self, city: str, state: str, snow_code: str):
        lat, lon, display_name = self._geocode_city_state(city, state)
        normalized_code = self._normalize_snow_code(snow_code)
        if normalized_code == "ASCE 7-22":
            snow_psf, source = self._lookup_snow_load_asce_722(lat, lon)
        else:
            snow_psf, source = self._lookup_snow_load_asce_716(lat, lon)
        return {
            "snow_psf": float(snow_psf),
            "source": source,
            "location_display": display_name,
            "lat": float(lat),
            "lon": float(lon),
            "code": normalized_code,
        }

    def _lookup_snow_load_worker(self, city: str, state: str, snow_code: str):
        output = {"error": None}
        try:
            output.update(self._backend_lookup_snow_load(city, state, snow_code))
        except InputValidationError as exc:
            output["error"] = str(exc)
        except Exception as exc:
            output["error"] = f"Unexpected snow lookup error: {exc}"
        self._snow_lookup_result = output

    def _finish_snow_lookup(self, result: dict):
        self._snow_lookup_running = False
        if hasattr(self, "lookup_snow_btn"):
            self.lookup_snow_btn.configure(state="normal")

        err = str(result.get("error") or "").strip()
        if err:
            self.hazard_parse_status_var.set(err)
            messagebox.showerror("Snow Lookup Failed", err)
            return

        snow_psf = float(result.get("snow_psf", 0.0) or 0.0)
        snow_text = f"{snow_psf:.3f}".rstrip("0").rstrip(".")
        self.snow_load_var.set(snow_text)
        self.hazard_parse_status_var.set(
            "Snow Load set to {snow} psf via backend lookup ({code}) from {source} at {loc} "
            "[{lat:.5f}, {lon:.5f}].".format(
                snow=snow_text,
                code=str(result.get("code") or self.snow_code_var.get()),
                source=str(result.get("source") or "service"),
                loc=str(result.get("location_display") or "location"),
                lat=float(result.get("lat", 0.0)),
                lon=float(result.get("lon", 0.0)),
            )
        )

    def _poll_snow_lookup(self):
        thread = self._snow_lookup_thread
        if thread is not None and thread.is_alive():
            self.root.after(120, self._poll_snow_lookup)
            return

        result = self._snow_lookup_result or {"error": "Snow lookup did not return a result."}
        self._snow_lookup_thread = None
        self._snow_lookup_result = None
        self._finish_snow_lookup(result)

    def lookup_snow_load_backend(self):
        if self._snow_lookup_running:
            return

        city = str(self.location_city_var.get() or "").strip()
        state = str(self.location_state_var.get() or "").strip()
        if not city and not state:
            messagebox.showerror("Location required", "Enter City and/or State before backend lookup.")
            return

        snow_code = self._normalize_snow_code(self.snow_code_var.get())
        if str(self.snow_code_var.get() or "").strip() != snow_code:
            self.snow_code_var.set(snow_code)
        self._snow_lookup_running = True
        if hasattr(self, "lookup_snow_btn"):
            self.lookup_snow_btn.configure(state="disabled")
        self.hazard_parse_status_var.set(
            f"Looking up snow load for {', '.join(part for part in [city, state] if part)} ({snow_code})..."
        )
        self._snow_lookup_result = None
        self._snow_lookup_thread = threading.Thread(
            target=self._lookup_snow_load_worker,
            args=(city, state, snow_code),
            daemon=True,
        )
        self._snow_lookup_thread.start()
        self.root.after(120, self._poll_snow_lookup)

    def _open_asce_hazard_tool(self):
        city = str(self.location_city_var.get() or "").strip()
        state = str(self.location_state_var.get() or "").strip()
        location_text = ", ".join(part for part in [city, state] if part)
        try:
            webbrowser.open("https://ascehazardtool.org/", new=2)
        except Exception:
            self.hazard_parse_status_var.set("Could not open browser automatically. Open https://ascehazardtool.org/ manually.")
            return
        if location_text:
            self.hazard_parse_status_var.set(
                f"Opened ASCE Hazard Tool. Look up {location_text}, copy the output text, then paste below."
            )
        else:
            self.hazard_parse_status_var.set(
                "Opened ASCE Hazard Tool. Enter location there, copy output text, then paste below."
            )

    def _extract_snow_psf_from_text(self, text: str) -> float:
        source = str(text or "").strip()
        if not source:
            raise InputValidationError("Paste ASCE output text first.")
        flat = source.replace(",", " ")

        primary_patterns = [
            r"(?:ground\s+snow\s+load|snow\s+load|p_g|pg|p\s*g)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:psf)?",
            r"(?:ground\s+snow|snow)\s*\(?\s*pg\s*\)?\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:psf)?",
            r"(?:pg)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:psf)?",
        ]
        for pattern in primary_patterns:
            match = re.search(pattern, flat, flags=re.IGNORECASE)
            if match:
                return self._parse_non_negative_load("Snow Load", match.group(1))

        for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*psf", flat, flags=re.IGNORECASE):
            start = max(0, match.start() - 60)
            end = min(len(flat), match.end() + 60)
            context = flat[start:end].lower()
            if "snow" in context or "ground" in context or "pg" in context:
                return self._parse_non_negative_load("Snow Load", match.group(1))

        raise InputValidationError(
            "Could not detect snow load from pasted text. Include a line containing Ground Snow Load / pg in psf."
        )

    def _apply_snow_load_from_paste(self):
        if not hasattr(self, "hazard_paste_text"):
            return
        pasted = self.hazard_paste_text.get("1.0", "end").strip()
        try:
            snow_psf = self._extract_snow_psf_from_text(pasted)
        except InputValidationError as exc:
            messagebox.showerror("Snow load parse failed", str(exc))
            self.hazard_parse_status_var.set(str(exc))
            return

        snow_text = f"{snow_psf:.3f}".rstrip("0").rstrip(".")
        self.snow_load_var.set(snow_text)
        self.hazard_parse_status_var.set(
            f"Snow Load set to {snow_text} psf from pasted ASCE text. Re-run calculations to apply."
        )

    def _refresh_dock_line_options(self):
        # Backward-compatible entrypoint: now refreshes speed-bay row/transition summaries.
        self._sync_speed_bay_summary_vars()
        self.redraw()

    def _sync_speed_bay_summary_vars(self):
        speed_rows = sorted(self._get_selected_speed_bay_rows())
        transition_lines = self._get_speed_bay_transition_line_indices()

        if speed_rows:
            self.speed_bay_rows_summary_var.set(
                ", ".join(f"{axis_letter(r)}-{axis_letter(r + 1)}" for r in speed_rows)
            )
        else:
            self.speed_bay_rows_summary_var.set("None")

        if transition_lines:
            self.speed_transition_summary_var.set(", ".join(axis_letter(i) for i in transition_lines))
        else:
            self.speed_transition_summary_var.set("None")

        # Keep the legacy dock-line variable populated with the first transition line,
        # so existing text/report code still has a deterministic single-line fallback.
        self.dock_line_var.set(axis_letter(transition_lines[0]) if transition_lines else "")

    def _get_selected_speed_bay_rows(self):
        row_count = len(self.model.y_spans)
        cleaned = {
            int(idx)
            for idx in self.speed_bay_rows
            if isinstance(idx, (int, float)) and 0 <= int(idx) < row_count
        }
        if cleaned != self.speed_bay_rows:
            self.speed_bay_rows = cleaned
        return set(cleaned)

    def _get_speed_bay_transition_line_indices(self):
        speed_rows = self._get_selected_speed_bay_rows()
        row_count = len(self.model.y_spans)
        if row_count <= 0:
            return []
        transitions = []
        for line_idx in range(1, row_count):
            north_is_speed = (line_idx - 1) in speed_rows
            south_is_speed = line_idx in speed_rows
            if north_is_speed != south_is_speed:
                transitions.append(line_idx)
        return transitions

    def _update_recommended_joist_spacing(self):
        if not hasattr(self, "recommended_joist_spaces_var"):
            return

        active_bays = self.get_active_bays()
        used_x_indices = sorted({x for (x, _y) in active_bays if 0 <= x < len(self.model.x_spans)})
        if used_x_indices:
            spans = [float(self.model.x_spans[idx]) for idx in used_x_indices]
        else:
            spans = [float(span) for span in self.model.x_spans]

        if not spans:
            self.recommended_joist_spaces_var.set("Recommended Joist Spaces/Bay: - (add X bays)")
            return

        controlling_span_ft = max(spans)
        recommended_spaces = max(1, int(math.floor(controlling_span_ft / 6.0)))
        est_oc_ft = controlling_span_ft / recommended_spaces
        self.recommended_joist_spaces_var.set(
            "Recommended Joist Spaces/Bay: {spaces} (max X {span} -> {oc} O.C)".format(
                spaces=recommended_spaces,
                span=self._fmt_ft_arch(controlling_span_ft),
                oc=self._fmt_ft_arch(est_oc_ft),
            )
        )

    def _on_mezz_enabled_changed(self):
        if self.mezzanine_enabled_var.get():
            self.mezz_status_var.set(
                "Click + Add Mezzanine, or drag on the plan to draw a free-size zone. "
                "Click an existing mezzanine to edit it."
            )
        else:
            self.mezz_status_var.set("Mezzanines disabled.")
            self._mezz_draw_mode = False
            self._mezz_drag_start = None
            self._mezz_drag_end = None
            self.last_mezz_result = None
            self.last_mezz_footing_result = None
            self.mezz_joist_selection_by_group = {}
            self.mezz_girder_selection_by_group = {}
            self.mezz_column_selection_by_group = {}
        self._update_mezz_props_state()
        self._refresh_joist_selection_table()
        self._refresh_girder_selection_table()
        self._refresh_column_selection_table()
        self._refresh_mezz_panel_spacing_tree()
        self.redraw_mezzanine_preview()

    def toggle_mezz_draw_mode(self):
        """Legacy alias kept for backward compatibility — UI no longer exposes a draw-mode toggle.
        Calling this just adds a new mezzanine via the smart-placement path."""
        self.add_mezz_zone()

    def _cancel_mezz_draw(self):
        """Cancel an in-progress draft rectangle (bound to Esc key)."""
        if self._mezz_drag_start is None and not self._mezz_draw_mode:
            return
        self._mezz_draw_mode = False
        self._mezz_drag_start = None
        self._mezz_drag_end = None
        self.redraw_mezzanine_preview()

    def on_mezz_canvas_mouse_wheel(self, event):
        if not hasattr(self, "mezz_canvas"):
            return None
        c = self.mezz_canvas

        # Linux wheel support.
        if getattr(event, "num", None) in (4, 5):
            delta = 120 if int(getattr(event, "num", 0)) == 4 else -120
        else:
            delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return None

        shift_down = bool(getattr(event, "state", 0) & 0x0001)
        ctrl_down = bool(getattr(event, "state", 0) & 0x0004)

        if ctrl_down:
            step = 0.2 if delta > 0 else -0.2
            new_zoom = max(1.0, min(6.0, float(self.mezz_zoom_var.get() or 1.0) + step))
            if abs(new_zoom - float(self.mezz_zoom_var.get() or 1.0)) > 1e-9:
                self.mezz_zoom_var.set(new_zoom)
                self.redraw_mezzanine_preview()
            return "break"

        units = -3 if delta > 0 else 3
        if shift_down:
            c.xview_scroll(units, "units")
        else:
            c.yview_scroll(units, "units")
        return "break"

    def _mezz_canvas_to_world(self, px: float, py: float):
        tf = self._mezz_canvas_transform or {}
        scale = float(tf.get("scale", 0.0))
        if scale <= 0:
            return None
        ox = float(tf.get("ox", 0.0))
        oy = float(tf.get("oy", 0.0))
        x0 = float(tf.get("x0", 0.0))
        y0 = float(tf.get("y0", 0.0))
        wx = ((float(px) - ox) / scale) + x0
        wy = ((float(py) - oy) / scale) + y0
        return wx, wy

    def _snap_mezz_world(self, wx: float, wy: float):
        if not self.model.x_spans or not self.model.y_spans:
            return float(wx), float(wy)
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        x_min, x_max = float(x_lines[0]), float(x_lines[-1])
        y_min, y_max = float(y_lines[0]), float(y_lines[-1])
        x = max(x_min, min(float(wx), x_max))
        y = max(y_min, min(float(wy), y_max))
        if not self.mezz_snap_enabled_var.get():
            return x, y
        try:
            step_ft = float(self.mezz_snap_step_var.get())
            if step_ft <= 0:
                step_ft = 1.0
        except Exception:
            step_ft = 1.0
        x = round(x / step_ft) * step_ft
        y = round(y / step_ft) * step_ft
        x = max(x_min, min(x, x_max))
        y = max(y_min, min(y, y_max))

        tf = self._mezz_canvas_transform or {}
        scale = float(tf.get("scale", 1.0) or 1.0)
        tol_ft = max(step_ft * 0.75, 12.0 / max(0.001, scale))
        snap_x_candidates = [float(v) for v in x_lines]
        snap_y_candidates = [float(v) for v in y_lines]
        if self._mezz_drag_start is not None:
            snap_x_candidates.append(float(self._mezz_drag_start[0]))
            snap_y_candidates.append(float(self._mezz_drag_start[1]))
        for zone in self.mezz_zones:
            try:
                zx0 = float(zone.get("x_start_ft", 0.0))
                zx1 = float(zone.get("x_end_ft", 0.0))
                zy0 = float(zone.get("y_start_ft", 0.0))
                zy1 = float(zone.get("y_end_ft", 0.0))
            except (TypeError, ValueError):
                continue
            snap_x_candidates.extend([zx0, zx1])
            snap_y_candidates.extend([zy0, zy1])
        nearest_x = min(snap_x_candidates, key=lambda xv: abs(float(xv) - x))
        nearest_y = min(snap_y_candidates, key=lambda yv: abs(float(yv) - y))
        if abs(float(nearest_x) - x) <= tol_ft:
            x = float(nearest_x)
        if abs(float(nearest_y) - y) <= tol_ft:
            y = float(nearest_y)
        return x, y

    def _snap_world_to_main_node(self, wx: float, wy: float):
        if not self.model.x_spans or not self.model.y_spans:
            return None
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        best_x_idx = min(range(len(x_lines)), key=lambda i: abs(x_lines[i] - wx))
        best_y_idx = min(range(len(y_lines)), key=lambda i: abs(y_lines[i] - wy))
        return best_x_idx, best_y_idx, float(x_lines[best_x_idx]), float(y_lines[best_y_idx])

    def _hit_test_mezz_zone(self, wx: float, wy: float):
        """Return the topmost mezzanine zone at world coords (wx, wy), or None."""
        for zone in reversed(self.mezz_zones):
            if not bool(zone.get("enabled", True)):
                continue
            try:
                zx0 = float(zone.get("x_start_ft", 0.0))
                zx1 = float(zone.get("x_end_ft", 0.0))
                zy0 = float(zone.get("y_start_ft", 0.0))
                zy1 = float(zone.get("y_end_ft", 0.0))
            except (TypeError, ValueError):
                continue
            if zx0 <= float(wx) <= zx1 and zy0 <= float(wy) <= zy1:
                return zone
        return None

    def on_mezz_canvas_down(self, event):
        """Always-on canvas interaction.

        - Click inside an existing zone -> select it (and select the panel for per-panel ops).
        - Click on empty space -> begin drawing a new mezzanine rectangle.
        """
        if not self.mezzanine_enabled_var.get():
            return
        world = self._mezz_canvas_to_world(event.x, event.y)
        if world is None:
            return
        wx, wy = float(world[0]), float(world[1])
        hit = self._hit_test_mezz_zone(wx, wy)
        if hit is not None:
            # Select the existing zone (and pick the panel inside it for per-panel overrides)
            self._select_mezz_zone_panel_at(wx, wy)
            self.redraw_mezzanine_preview()
            self._mezz_drag_start = None
            self._mezz_drag_end = None
            self._mezz_draw_mode = False
            return
        # Empty space -> start a draft rectangle
        sx, sy = self._snap_mezz_world(wx, wy)
        self._mezz_drag_start = (sx, sy)
        self._mezz_drag_end = (sx, sy)
        self._mezz_draw_mode = True
        self.redraw_mezzanine_preview()

    def on_mezz_canvas_drag(self, event):
        if self._mezz_drag_start is None:
            return
        world = self._mezz_canvas_to_world(event.x, event.y)
        if world is None:
            return
        sx, sy = self._snap_mezz_world(float(world[0]), float(world[1]))
        self._mezz_drag_end = (sx, sy)
        self.redraw_mezzanine_preview()

    def on_mezz_canvas_up(self, event):
        if self._mezz_drag_start is None:
            self._mezz_draw_mode = False
            return
        world = self._mezz_canvas_to_world(event.x, event.y)
        if world is None:
            self._mezz_drag_start = None
            self._mezz_drag_end = None
            self._mezz_draw_mode = False
            return
        sx, sy = self._snap_mezz_world(float(world[0]), float(world[1]))
        self._mezz_drag_end = (sx, sy)

        xs, ys = self._mezz_drag_start
        xe, ye = self._mezz_drag_end
        self._mezz_drag_start = None
        self._mezz_drag_end = None
        self._mezz_draw_mode = False

        if abs(xe - xs) < 0.5 or abs(ye - ys) < 0.5:
            # Treat as a click — already handled by select on press; nothing more to do.
            self.redraw_mezzanine_preview()
            return

        # Add zone from the dragged rectangle
        self.add_mezz_zone_from_rect(xs, ys, xe, ye)

    def _on_mezz_dim_click(self, zone_id: str, axis: str):
        zone = None
        for z in self.mezz_zones:
            if str(z.get("id")) == str(zone_id):
                zone = z
                break
        if zone is None:
            return
        axis = str(axis or "").strip().upper()
        if axis in {"W", "L"}:
            current = (
                float(zone.get("x_end_ft", 0.0)) - float(zone.get("x_start_ft", 0.0))
                if axis == "W"
                else float(zone.get("y_end_ft", 0.0)) - float(zone.get("y_start_ft", 0.0))
            )
            prompt = "Enter mezzanine width (ft):" if axis == "W" else "Enter mezzanine length (ft):"
            value = simpledialog.askfloat(
                "Edit Mezzanine Dimension",
                prompt,
                parent=self.root,
                initialvalue=current,
                minvalue=2.0,
            )
            if value is None:
                return
            try:
                x0 = float(zone.get("x_start_ft", 0.0))
                y0 = float(zone.get("y_start_ft", 0.0))
                x1 = x0 + float(value) if axis == "W" else float(zone.get("x_end_ft", 0.0))
                y1 = y0 + float(value) if axis == "L" else float(zone.get("y_end_ft", 0.0))
                updated = self._build_mezz_zone_from_rect(
                    x0,
                    y0,
                    x1,
                    y1,
                    keep_id=str(zone.get("id")),
                )
            except InputValidationError as exc:
                messagebox.showerror("Invalid dimension", str(exc))
                return
            target_id = str(zone.get("id"))
            self.mezz_zones = [updated if str(item.get("id")) == target_id else item for item in self.mezz_zones]
            self.selected_mezz_zone_id = target_id
            self._invalidate_mezzanine_results()
            self.mezz_calc_status_var.set("Mezzanine dimensions updated. Run Calculate Mezzanine.")
            self._refresh_mezz_zone_tree()
            self.redraw_mezzanine_preview()
            return

        current = zone.get("internal_x_spacings_ft", []) if axis == "X" else zone.get("internal_y_spacings_ft", [])
        prompt = (
            "Enter comma-separated bay sizes in ft for internal X spacing:"
            if axis == "X"
            else "Enter comma-separated bay sizes in ft for internal Y spacing:"
        )
        initial = ", ".join(self._fmt_num(v, 2).rstrip("0").rstrip(".") for v in current)
        raw = simpledialog.askstring("Edit Mezzanine Spacing", prompt, initialvalue=initial, parent=self.root)
        if raw is None:
            return
        try:
            parsed = self._parse_spacing_csv(raw, f"Mezzanine internal {axis} spacing")
        except InputValidationError as exc:
            messagebox.showerror("Invalid spacing", str(exc))
            return
        width_ft = float(zone.get("x_end_ft", 0.0)) - float(zone.get("x_start_ft", 0.0))
        length_ft = float(zone.get("y_end_ft", 0.0)) - float(zone.get("y_start_ft", 0.0))
        cap = width_ft if axis == "X" else length_ft
        if parsed and sum(parsed) > (cap + 1e-6):
            messagebox.showerror(
                "Invalid spacing",
                f"Entered {axis}-spacing total ({sum(parsed):.2f} ft) exceeds mezzanine {axis}-length ({cap:.2f} ft).",
            )
            return
        if axis == "X":
            zone["internal_x_spacings_ft"] = parsed
        else:
            zone["internal_y_spacings_ft"] = parsed
        self._sanitize_mezz_zone_joist_overrides(zone)
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine inputs updated. Run Calculate Mezzanine.")
        self._refresh_mezz_zone_tree()
        self._refresh_mezz_internal_spacing_labels()
        self.redraw_mezzanine_preview()

    def _generate_mezz_name(self):
        used = {str(z.get("name", "")).strip().lower() for z in self.mezz_zones}
        n = 1
        while True:
            token = f"Mezzanine {n}"
            if token.lower() not in used:
                return token
            n += 1

    def _clear_mezz_draft_fields(self):
        self.selected_mezz_zone_id = None
        self._mezz_selected_panel_keys = set()
        self.mezz_name_var.set(self._generate_mezz_name())
        self.mezz_origin_x_var.set("0")
        self.mezz_origin_y_var.set("0")
        self.mezz_width_var.set("50")
        self.mezz_length_var.set("50")
        self.mezz_internal_x_var.set("")
        self.mezz_internal_y_var.set("")
        self.mezz_calc_status_var.set("Draft cleared. Click + Add Mezzanine, or drag on the plan.")
        self._refresh_mezz_internal_spacing_labels()
        self._refresh_mezz_panel_spacing_tree()
        self._update_mezz_inspector_visibility()
        self._update_mezz_props_state()
        self._refresh_mezz_zone_list(skip_reload=True)
        self.redraw_mezzanine_preview()

    def duplicate_selected_mezz_zone(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            messagebox.showerror("No zone selected", "Select a mezzanine zone first.")
            return
        self._mezz_zone_counter += 1
        clone = dict(zone)
        clone["id"] = f"MZ{self._mezz_zone_counter:03d}"
        base = str(zone.get("name", "Mezzanine")).strip() or "Mezzanine"
        used = {str(z.get("name", "")).strip().lower() for z in self.mezz_zones}
        suffix = 1
        candidate = f"{base} Copy"
        while candidate.lower() in used:
            suffix += 1
            candidate = f"{base} Copy {suffix}"
        clone["name"] = candidate
        clone["internal_x_spacings_ft"] = list(zone.get("internal_x_spacings_ft", []) or [])
        clone["internal_y_spacings_ft"] = list(zone.get("internal_y_spacings_ft", []) or [])
        clone["joist_spaces_overrides"] = dict(zone.get("joist_spaces_overrides", {}) or {})
        self.mezz_zones.append(clone)
        self.selected_mezz_zone_id = str(clone["id"])
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine zone duplicated. Run Calculate Mezzanine.")
        self._refresh_mezz_zone_tree()
        self.redraw_mezzanine_preview()

    def _parse_spacing_csv(self, text: str, label: str):
        token = str(text or "").strip()
        if not token:
            return []
        output = []
        for part in token.split(","):
            val = part.strip()
            if not val:
                continue
            try:
                num = float(val)
            except ValueError as exc:
                raise InputValidationError(f"{label} contains non-numeric value '{val}'.") from exc
            if num <= 0:
                raise InputValidationError(f"{label} values must be > 0.")
            output.append(round(num, 3))
        return output

    def _refresh_mezz_internal_spacing_labels(self):
        x_vals = self._parse_spacing_csv(self.mezz_internal_x_var.get(), "Internal X spacing")
        y_vals = self._parse_spacing_csv(self.mezz_internal_y_var.get(), "Internal Y spacing")
        if x_vals:
            self.mezz_internal_x_summary_var.set(
                "X bays: "
                + ", ".join(self._fmt_num(v, 2).rstrip("0").rstrip(".") for v in x_vals)
                + f" (total {self._fmt_num(sum(x_vals), 2)} ft)"
            )
        else:
            self.mezz_internal_x_summary_var.set("X bays: auto (single bay)")
        if y_vals:
            self.mezz_internal_y_summary_var.set(
                "Y bays: "
                + ", ".join(self._fmt_num(v, 2).rstrip("0").rstrip(".") for v in y_vals)
                + f" (total {self._fmt_num(sum(y_vals), 2)} ft)"
            )
        else:
            self.mezz_internal_y_summary_var.set("Y bays: auto (single bay)")

    def _set_mezz_internal_spacing_values(self, axis: str, values):
        axis = str(axis or "").strip().upper()
        text = ", ".join(self._fmt_num(v, 3).rstrip("0").rstrip(".") for v in values)
        if axis == "X":
            self.mezz_internal_x_var.set(text)
        else:
            self.mezz_internal_y_var.set(text)
        self._refresh_mezz_internal_spacing_labels()

    def _fit_mezz_zone_segments(self, total_ft: float, custom_segments):
        total = max(0.0, float(total_ft))
        if total <= 1e-6:
            return []
        segments = []
        running = 0.0
        tol = 1e-6
        for raw in custom_segments or []:
            try:
                seg = float(raw)
            except (TypeError, ValueError):
                continue
            if seg <= 0:
                continue
            if running + seg > total + tol:
                break
            segments.append(seg)
            running += seg
            if abs(running - total) <= tol:
                running = total
                break
        rem = total - running
        # Merge tiny numerical residuals so we never create near-zero panels.
        if rem > tol:
            if rem < 0.25 and segments:
                segments[-1] += rem
            else:
                segments.append(rem)
        out = [round(float(v), 3) for v in segments if float(v) > tol]
        if not out:
            return [round(total, 3)]
        return out

    def _parse_mezz_panel_key(self, key):
        text = str(key or "").strip().upper()
        if not text:
            return None
        if text.startswith("P"):
            text = text[1:]
        text = text.replace("-", ",").replace(":", ",").replace("/", ",")
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) != 2:
            return None
        try:
            ix = int(parts[0])
            iy = int(parts[1])
        except (TypeError, ValueError):
            return None
        if ix < 1 or iy < 1:
            return None
        return ix, iy

    def _iter_mezz_zone_panels(self, zone):
        if not zone:
            return []
        x0 = float(zone.get("x_start_ft", 0.0) or 0.0)
        x1 = float(zone.get("x_end_ft", 0.0) or 0.0)
        y0 = float(zone.get("y_start_ft", 0.0) or 0.0)
        y1 = float(zone.get("y_end_ft", 0.0) or 0.0)
        width = max(0.0, x1 - x0)
        length = max(0.0, y1 - y0)
        x_segments = self._fit_mezz_zone_segments(width, zone.get("internal_x_spacings_ft", []))
        y_segments = self._fit_mezz_zone_segments(length, zone.get("internal_y_spacings_ft", []))
        default_spaces = max(1, int(zone.get("joist_spaces_per_bay", 7) or 7))
        overrides = dict(zone.get("joist_spaces_overrides", {}) or {})
        out = []
        for ix, x_seg in enumerate(x_segments, start=1):
            for iy, y_seg in enumerate(y_segments, start=1):
                key = f"{ix},{iy}"
                try:
                    spaces = int(overrides.get(key, default_spaces))
                except (TypeError, ValueError):
                    spaces = default_spaces
                spaces = max(1, spaces)
                out.append(
                    {
                        "key": key,
                        "ix": ix,
                        "iy": iy,
                        "panel_label": f"P{ix:02d}-{iy:02d}",
                        "width_ft": float(x_seg),
                        "length_ft": float(y_seg),
                        "spaces": int(spaces),
                        "default_spaces": int(default_spaces),
                        "override": key in overrides,
                    }
                )
        return out

    def _sanitize_mezz_zone_joist_overrides(self, zone):
        if not zone:
            return
        valid_keys = {row["key"] for row in self._iter_mezz_zone_panels(zone)}
        clean = {}
        for raw_key, raw_val in dict(zone.get("joist_spaces_overrides", {}) or {}).items():
            parsed = self._parse_mezz_panel_key(raw_key)
            if not parsed:
                continue
            key = f"{parsed[0]},{parsed[1]}"
            if key not in valid_keys:
                continue
            try:
                sval = int(raw_val)
            except (TypeError, ValueError):
                continue
            if sval < 1:
                continue
            clean[key] = int(sval)
        zone["joist_spaces_overrides"] = clean

    def _serialize_mezz_zone_joist_overrides(self, zone):
        self._sanitize_mezz_zone_joist_overrides(zone)
        out = {}
        for key, value in dict(zone.get("joist_spaces_overrides", {}) or {}).items():
            try:
                ivalue = int(value)
            except (TypeError, ValueError):
                continue
            if ivalue < 1:
                continue
            if not self._parse_mezz_panel_key(key):
                continue
            out[str(key)] = int(ivalue)
        return out

    def _select_mezz_zone_panel_at(self, wx: float, wy: float):
        hit_zone = None
        for zone in reversed(self.mezz_zones):
            if not bool(zone.get("enabled", True)):
                continue
            x0 = float(zone.get("x_start_ft", 0.0) or 0.0)
            x1 = float(zone.get("x_end_ft", 0.0) or 0.0)
            y0 = float(zone.get("y_start_ft", 0.0) or 0.0)
            y1 = float(zone.get("y_end_ft", 0.0) or 0.0)
            if x0 <= float(wx) <= x1 and y0 <= float(wy) <= y1:
                hit_zone = zone
                break
        if hit_zone is None:
            self.selected_mezz_zone_id = None
            self._mezz_selected_panel_keys = set()
            self._refresh_mezz_panel_spacing_tree()
            self._update_mezz_inspector_visibility()
            self._update_mezz_props_state()
            self._refresh_mezz_zone_list(skip_reload=True)
            return

        hit_id = str(hit_zone.get("id", ""))
        # Reuse the canonical select helper (it already handles inspector + repaint)
        self._select_mezz_zone(hit_id)

        x0 = float(hit_zone.get("x_start_ft", 0.0) or 0.0)
        y0 = float(hit_zone.get("y_start_ft", 0.0) or 0.0)
        width = max(0.0, float(hit_zone.get("x_end_ft", 0.0) or 0.0) - x0)
        length = max(0.0, float(hit_zone.get("y_end_ft", 0.0) or 0.0) - y0)
        x_segments = self._fit_mezz_zone_segments(width, hit_zone.get("internal_x_spacings_ft", []))
        y_segments = self._fit_mezz_zone_segments(length, hit_zone.get("internal_y_spacings_ft", []))

        local_x = max(0.0, float(wx) - x0)
        local_y = max(0.0, float(wy) - y0)
        ix = 1
        run = 0.0
        for i, seg in enumerate(x_segments, start=1):
            run += float(seg)
            ix = i
            if local_x <= run + 1e-6:
                break
        iy = 1
        run = 0.0
        for i, seg in enumerate(y_segments, start=1):
            run += float(seg)
            iy = i
            if local_y <= run + 1e-6:
                break
        key = f"{ix},{iy}"
        if hasattr(self, "mezz_panel_tree") and self.mezz_panel_tree.exists(key):
            self.mezz_panel_tree.selection_set(key)
            self._on_mezz_panel_tree_selected()

    def _refresh_mezz_panel_spacing_tree(self):
        if not hasattr(self, "mezz_panel_tree"):
            return
        self.mezz_panel_tree.delete(*self.mezz_panel_tree.get_children())
        self._mezz_selected_panel_keys = set()
        zone = self._get_selected_mezz_zone()
        if not zone:
            self._update_mezz_props_state()
            return
        self._sanitize_mezz_zone_joist_overrides(zone)
        panel_rows = self._iter_mezz_zone_panels(zone)
        for row in panel_rows:
            key = str(row["key"])
            self.mezz_panel_tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    row["panel_label"],
                    f"{self._fmt_num(row['width_ft'], 2)} x {self._fmt_num(row['length_ft'], 2)}",
                    str(int(row["spaces"])),
                    "Override" if row["override"] else "Default",
                ),
            )
        self._update_mezz_props_state()

    def _on_mezz_panel_tree_selected(self, _event=None):
        if not hasattr(self, "mezz_panel_tree"):
            return
        selected_items = [str(item) for item in self.mezz_panel_tree.selection()]
        self._mezz_selected_panel_keys = set(selected_items)
        if selected_items:
            first = selected_items[0]
            try:
                spaces_text = str(self.mezz_panel_tree.set(first, "spaces"))
                self.mezz_panel_spacing_value_var.set(str(int(spaces_text)))
            except Exception:
                pass

    def set_selected_mezz_panel_spacing(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            messagebox.showerror("No zone selected", "Select a mezzanine zone first.")
            return
        if not hasattr(self, "mezz_panel_tree"):
            return
        selected = list(self.mezz_panel_tree.selection())
        if not selected:
            messagebox.showerror("Selection required", "Select one or more mezz panels in Per-Panel Joist Spaces.")
            return
        try:
            spaces = int(str(self.mezz_panel_spacing_value_var.get()).strip())
        except ValueError:
            messagebox.showerror("Invalid spacing", "Joist spaces must be an integer >= 1.")
            return
        if spaces < 1:
            messagebox.showerror("Invalid spacing", "Joist spaces must be >= 1.")
            return
        overrides = dict(zone.get("joist_spaces_overrides", {}) or {})
        for panel_key in selected:
            overrides[str(panel_key)] = int(spaces)
        zone["joist_spaces_overrides"] = overrides
        self._sanitize_mezz_zone_joist_overrides(zone)
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Updated mezz panel joist spacing overrides. Run Calculate Mezzanine.")
        self._refresh_mezz_panel_spacing_tree()
        self.redraw_mezzanine_preview()

    def clear_selected_mezz_panel_spacing(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            return
        if not hasattr(self, "mezz_panel_tree"):
            return
        selected = list(self.mezz_panel_tree.selection())
        if not selected:
            return
        overrides = dict(zone.get("joist_spaces_overrides", {}) or {})
        for panel_key in selected:
            overrides.pop(str(panel_key), None)
        zone["joist_spaces_overrides"] = overrides
        self._sanitize_mezz_zone_joist_overrides(zone)
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Cleared selected mezz panel spacing overrides.")
        self._refresh_mezz_panel_spacing_tree()
        self.redraw_mezzanine_preview()

    def clear_all_mezz_panel_spacing_overrides(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            return
        zone["joist_spaces_overrides"] = {}
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Cleared all mezz panel spacing overrides.")
        self._refresh_mezz_panel_spacing_tree()
        self.redraw_mezzanine_preview()

    def apply_bay_builder_to_mezz_dimensions(self):
        try:
            x_vals = self._parse_spacing_csv(self.mezz_internal_x_var.get(), "Internal X spacing")
            y_vals = self._parse_spacing_csv(self.mezz_internal_y_var.get(), "Internal Y spacing")
        except InputValidationError as exc:
            messagebox.showerror("Invalid bay list", str(exc))
            return
        if not x_vals or not y_vals:
            raise_text = "Add at least one X bay and one Y bay in the Bay Builder first."
            messagebox.showerror("Missing bay segments", raise_text)
            return
        total_x = sum(float(v) for v in x_vals)
        total_y = sum(float(v) for v in y_vals)
        self.mezz_width_var.set(self._fmt_num(total_x, 3).rstrip("0").rstrip("."))
        self.mezz_length_var.set(self._fmt_num(total_y, 3).rstrip("0").rstrip("."))
        self.mezz_calc_status_var.set(
            f"Bay builder applied: Width {self._fmt_num(total_x, 2)} ft, Length {self._fmt_num(total_y, 2)} ft."
        )

    def add_mezz_internal_x_bay(self):
        try:
            new_val = self._parse_positive_input("New X Bay", self.mezz_new_x_bay_var.get())
            items = self._parse_spacing_csv(self.mezz_internal_x_var.get(), "Internal X spacing")
            items.append(round(float(new_val), 3))
        except InputValidationError as exc:
            messagebox.showerror("Invalid X bay", str(exc))
            return
        self._set_mezz_internal_spacing_values("X", items)
        self.mezz_width_var.set(self._fmt_num(sum(items), 3).rstrip("0").rstrip("."))

    def remove_last_mezz_internal_x_bay(self):
        items = self._parse_spacing_csv(self.mezz_internal_x_var.get(), "Internal X spacing")
        if items:
            items.pop()
        self._set_mezz_internal_spacing_values("X", items)
        if items:
            self.mezz_width_var.set(self._fmt_num(sum(items), 3).rstrip("0").rstrip("."))

    def add_mezz_internal_y_bay(self):
        try:
            new_val = self._parse_positive_input("New Y Bay", self.mezz_new_y_bay_var.get())
            items = self._parse_spacing_csv(self.mezz_internal_y_var.get(), "Internal Y spacing")
            items.append(round(float(new_val), 3))
        except InputValidationError as exc:
            messagebox.showerror("Invalid Y bay", str(exc))
            return
        self._set_mezz_internal_spacing_values("Y", items)
        self.mezz_length_var.set(self._fmt_num(sum(items), 3).rstrip("0").rstrip("."))

    def remove_last_mezz_internal_y_bay(self):
        items = self._parse_spacing_csv(self.mezz_internal_y_var.get(), "Internal Y spacing")
        if items:
            items.pop()
        self._set_mezz_internal_spacing_values("Y", items)
        if items:
            self.mezz_length_var.set(self._fmt_num(sum(items), 3).rstrip("0").rstrip("."))

    def clear_mezz_internal_bays(self):
        self._set_mezz_internal_spacing_values("X", [])
        self._set_mezz_internal_spacing_values("Y", [])

    def reset_mezz_zoom(self):
        self.mezz_zoom_var.set(2.4)
        self.redraw_mezzanine_preview()

    def _refresh_mezz_line_options(self):
        if not hasattr(self, "mezz_x_start_combo"):
            return
        x_opts = [str(i + 1) for i in range(len(self.model.x_spans) + 1)]
        y_opts = [axis_letter(i) for i in range(len(self.model.y_spans) + 1)]
        if not x_opts:
            x_opts = ["1"]
        if not y_opts:
            y_opts = ["A"]

        self.mezz_x_start_combo["values"] = x_opts
        self.mezz_x_end_combo["values"] = x_opts
        self.mezz_y_start_combo["values"] = y_opts
        self.mezz_y_end_combo["values"] = y_opts

        if self.mezz_x_start_var.get() not in x_opts:
            self.mezz_x_start_var.set(x_opts[0])
        if self.mezz_x_end_var.get() not in x_opts:
            self.mezz_x_end_var.set(x_opts[min(1, len(x_opts) - 1)])
        if self.mezz_y_start_var.get() not in y_opts:
            self.mezz_y_start_var.set(y_opts[0])
        if self.mezz_y_end_var.get() not in y_opts:
            self.mezz_y_end_var.set(y_opts[min(1, len(y_opts) - 1)])

    def _parse_mezz_x_line_index(self, token: str):
        try:
            idx = int(str(token).strip()) - 1
        except ValueError as exc:
            raise InputValidationError("Mezzanine X line must be numeric.") from exc
        if idx < 0 or idx > len(self.model.x_spans):
            raise InputValidationError(
                f"Mezzanine X line must be within 1..{len(self.model.x_spans) + 1}."
            )
        return idx

    def _parse_mezz_y_line_index(self, token: str):
        try:
            idx = axis_index(str(token).strip())
        except ValueError as exc:
            raise InputValidationError("Mezzanine Y line must be a valid letter (A, B, C...).") from exc
        if idx < 0 or idx > len(self.model.y_spans):
            raise InputValidationError(
                f"Mezzanine Y line must be within A..{axis_letter(len(self.model.y_spans))}."
            )
        return idx

    def _get_selected_mezz_zone(self):
        target = str(self.selected_mezz_zone_id or "").strip()
        if not target:
            return None
        for zone in self.mezz_zones:
            if str(zone.get("id")) == target:
                return zone
        return None

    def _find_bay_index_for_world(self, x_ft: float, y_ft: float):
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        bx = None
        by = None
        for i in range(len(x_lines) - 1):
            if x_lines[i] <= x_ft < x_lines[i + 1]:
                bx = i
                break
        for i in range(len(y_lines) - 1):
            if y_lines[i] <= y_ft < y_lines[i + 1]:
                by = i
                break
        return bx, by

    def _main_column_nodes_world(self, active_bays=None, boundary_segments=None):
        if active_bays is None:
            active_bays = self.get_active_bays()
        if boundary_segments is None:
            boundary_segments = self._boundary_segments_for_active(active_bays)
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        nodes = []
        for xi in range(len(x_lines)):
            for yi in range(len(y_lines)):
                if self._column_has_steel_support(xi, yi, active_bays=active_bays, boundary_segments=boundary_segments):
                    nodes.append((float(x_lines[xi]), float(y_lines[yi]), xi, yi))
        return nodes

    def _load_bearing_wall_connections_for_rect(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        boundary_segments=None,
        tol_ft: float = 1.5,
    ):
        if boundary_segments is None:
            boundary_segments = self._current_boundary_segments()
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        touched = set()
        min_overlap = 0.5
        for edge in self.load_bearing_perimeter:
            if edge not in boundary_segments:
                continue
            orient, line_idx, seg_idx = edge
            if orient == "H":
                if not (0 <= line_idx < len(y_lines) and 0 <= seg_idx < len(self.model.x_spans)):
                    continue
                y_line = float(y_lines[line_idx])
                seg_x0 = float(x_lines[seg_idx])
                seg_x1 = float(x_lines[seg_idx + 1])
                overlap = max(0.0, min(x_max, seg_x1) - max(x_min, seg_x0))
                if overlap <= min_overlap:
                    continue
                if abs(y_line - y_min) <= tol_ft or abs(y_line - y_max) <= tol_ft:
                    touched.add(edge)
            elif orient == "V":
                if not (0 <= line_idx < len(x_lines) and 0 <= seg_idx < len(self.model.y_spans)):
                    continue
                x_line = float(x_lines[line_idx])
                seg_y0 = float(y_lines[seg_idx])
                seg_y1 = float(y_lines[seg_idx + 1])
                overlap = max(0.0, min(y_max, seg_y1) - max(y_min, seg_y0))
                if overlap <= min_overlap:
                    continue
                if abs(x_line - x_min) <= tol_ft or abs(x_line - x_max) <= tol_ft:
                    touched.add(edge)
        return touched

    def _validate_mezz_rect(self, x0: float, y0: float, x1: float, y1: float):
        x_min = min(float(x0), float(x1))
        x_max = max(float(x0), float(x1))
        y_min = min(float(y0), float(y1))
        y_max = max(float(y0), float(y1))
        if x_max - x_min < 2.0 or y_max - y_min < 2.0:
            raise InputValidationError("Mezzanine footprint is too small. Minimum size is 2 ft x 2 ft.")

        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        x_min = max(float(x_lines[0]), min(x_min, float(x_lines[-1])))
        x_max = max(float(x_lines[0]), min(x_max, float(x_lines[-1])))
        y_min = max(float(y_lines[0]), min(y_min, float(y_lines[-1])))
        y_max = max(float(y_lines[0]), min(y_max, float(y_lines[-1])))
        if x_max - x_min < 2.0 or y_max - y_min < 2.0:
            raise InputValidationError("Mezzanine footprint must be inside the active building extents.")

        active = self.get_active_bays()
        rect_area = (x_max - x_min) * (y_max - y_min)
        covered_area = 0.0
        tol = 1e-6
        first_inactive = None
        for bx in range(len(self.model.x_spans)):
            for by in range(len(self.model.y_spans)):
                bx0 = float(x_lines[bx])
                bx1 = float(x_lines[bx + 1])
                by0 = float(y_lines[by])
                by1 = float(y_lines[by + 1])
                ovx = max(0.0, min(x_max, bx1) - max(x_min, bx0))
                ovy = max(0.0, min(y_max, by1) - max(y_min, by0))
                ova = ovx * ovy
                if ova <= tol:
                    continue
                if (bx, by) in active:
                    covered_area += ova
                else:
                    if first_inactive is None:
                        first_inactive = (bx, by)
        if first_inactive is not None:
            raise InputValidationError(
                f"Mezzanine footprint overlaps void bay {axis_letter(first_inactive[1])}{first_inactive[0] + 1}."
            )
        if covered_area < rect_area - 1e-3:
            raise InputValidationError("Mezzanine footprint extends outside active building area.")

        boundary_segments = self._boundary_segments_for_active(active)
        main_nodes = self._main_column_nodes_world(active_bays=active, boundary_segments=boundary_segments)
        conn_tol = 1.5
        support_nodes = set()
        for nx, ny, nxi, nyi in main_nodes:
            if nx < (x_min - conn_tol) or nx > (x_max + conn_tol) or ny < (y_min - conn_tol) or ny > (y_max + conn_tol):
                continue
            on_vertical = (abs(nx - x_min) <= conn_tol or abs(nx - x_max) <= conn_tol) and (y_min - conn_tol) <= ny <= (y_max + conn_tol)
            on_horizontal = (abs(ny - y_min) <= conn_tol or abs(ny - y_max) <= conn_tol) and (x_min - conn_tol) <= nx <= (x_max + conn_tol)
            if on_vertical or on_horizontal:
                support_nodes.add((nxi, nyi))
        wall_supports = self._load_bearing_wall_connections_for_rect(
            x_min,
            y_min,
            x_max,
            y_max,
            boundary_segments=boundary_segments,
            tol_ft=conn_tol,
        )
        total_supports = len(support_nodes) + len(wall_supports)
        if total_supports < 2:
            raise InputValidationError(
                "Mezzanine must connect to at least 2 supports "
                "(main building columns and/or load-bearing walls) on its perimeter."
            )

        sxi, syi = self._find_bay_index_for_world(x_min + 1e-6, y_min + 1e-6)
        exi, eyi = self._find_bay_index_for_world(max(x_min + 1e-6, x_max - 1e-6), max(y_min + 1e-6, y_max - 1e-6))
        if sxi is None or syi is None or exi is None or eyi is None:
            raise InputValidationError("Mezzanine footprint could not be mapped to building bays.")

        return {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "support_count": int(total_supports),
            "main_support_count": int(len(support_nodes)),
            "lb_wall_support_count": int(len(wall_supports)),
            "x_start_line_index": int(sxi + 1),
            "x_end_line_index": int(exi + 2),
            "y_start_line_index": int(syi + 1),
            "y_end_line_index": int(eyi + 2),
            "x_start_label": str(sxi + 1),
            "x_end_label": str(exi + 2),
            "y_start_label": axis_letter(syi),
            "y_end_label": axis_letter(eyi + 1),
        }

    def _build_mezz_zone_common(self, x0: float, y0: float, x1: float, y1: float, keep_id: str = ""):
        if not self.model.x_spans or not self.model.y_spans:
            raise InputValidationError("Add grid bays before defining mezzanine zones.")

        name = str(self.mezz_name_var.get() or "").strip() or self._generate_mezz_name()
        elev_ft = self._parse_non_negative_load("Mezzanine elevation", self.mezz_elevation_var.get())
        dead_psf = self._parse_non_negative_load("Mezzanine dead load", self.mezz_dead_load_var.get())
        live_psf = self._parse_non_negative_load("Mezzanine live load", self.mezz_live_load_var.get())
        try:
            joist_spaces = int(str(self.mezz_joist_spaces_var.get()).strip())
        except ValueError as exc:
            raise InputValidationError("Mezzanine joist spaces per bay must be an integer >= 1.") from exc
        if joist_spaces < 1:
            raise InputValidationError("Mezzanine joist spaces per bay must be >= 1.")
        direction = "Horizontal" if str(self.mezz_joist_direction_var.get()).strip().lower().startswith("h") else "Vertical"
        internal_x = self._parse_spacing_csv(self.mezz_internal_x_var.get(), "Internal X spacing")
        internal_y = self._parse_spacing_csv(self.mezz_internal_y_var.get(), "Internal Y spacing")

        rect = self._validate_mezz_rect(x0, y0, x1, y1)
        width_ft = float(rect["x_max"] - rect["x_min"])
        length_ft = float(rect["y_max"] - rect["y_min"])
        if width_ft <= 0 or length_ft <= 0:
            raise InputValidationError("Selected mezzanine footprint must have positive width and length.")
        if internal_x and sum(internal_x) > (width_ft + 1e-6):
            raise InputValidationError(
                f"Internal X spacing total ({sum(internal_x):.2f}) exceeds mezzanine width ({width_ft:.2f} ft)."
            )
        if internal_y and sum(internal_y) > (length_ft + 1e-6):
            raise InputValidationError(
                f"Internal Y spacing total ({sum(internal_y):.2f}) exceeds mezzanine length ({length_ft:.2f} ft)."
            )

        zone_id = str(keep_id or "")
        if not zone_id:
            self._mezz_zone_counter += 1
            zone_id = f"MZ{self._mezz_zone_counter:03d}"
        existing_overrides = {}
        if keep_id:
            for existing in self.mezz_zones:
                if str(existing.get("id")) == str(keep_id):
                    existing_overrides = dict(existing.get("joist_spaces_overrides", {}) or {})
                    break
        zone_out = {
            "id": zone_id,
            "name": name,
            "enabled": True,
            "x_start_line_index": int(rect["x_start_line_index"]),
            "x_end_line_index": int(rect["x_end_line_index"]),
            "y_start_line_index": int(rect["y_start_line_index"]),
            "y_end_line_index": int(rect["y_end_line_index"]),
            "x_start_label": str(rect["x_start_label"]),
            "x_end_label": str(rect["x_end_label"]),
            "y_start_label": str(rect["y_start_label"]),
            "y_end_label": str(rect["y_end_label"]),
            "x_start_ft": float(rect["x_min"]),
            "x_end_ft": float(rect["x_max"]),
            "y_start_ft": float(rect["y_min"]),
            "y_end_ft": float(rect["y_max"]),
            "elevation_ft": float(elev_ft),
            "dead_load_psf": float(dead_psf),
            "live_load_psf": float(live_psf),
            "joist_spaces_per_bay": int(joist_spaces),
            "joist_spaces_overrides": existing_overrides,
            "joist_direction": direction,
            "internal_x_spacings_ft": list(internal_x),
            "internal_y_spacings_ft": list(internal_y),
            "support_connections": int(rect["support_count"]),
            "main_support_connections": int(rect.get("main_support_count", 0)),
            "lb_wall_support_connections": int(rect.get("lb_wall_support_count", 0)),
        }
        self._sanitize_mezz_zone_joist_overrides(zone_out)
        return zone_out

    def _build_mezz_zone_from_inputs(self, keep_id: str = ""):
        x0 = self._parse_non_negative_load("X Origin", self.mezz_origin_x_var.get())
        y0 = self._parse_non_negative_load("Y Origin", self.mezz_origin_y_var.get())
        w = self._parse_positive_input("Width", self.mezz_width_var.get())
        l = self._parse_positive_input("Length", self.mezz_length_var.get())
        return self._build_mezz_zone_common(
            float(x0),
            float(y0),
            float(x0) + float(w),
            float(y0) + float(l),
            keep_id=keep_id,
        )

    def _build_mezz_zone_from_rect(self, x0: float, y0: float, x1: float, y1: float, keep_id: str = ""):
        return self._build_mezz_zone_common(float(x0), float(y0), float(x1), float(y1), keep_id=keep_id)

    def _on_mezz_zone_selected(self, _event=None):
        # Selection lives in self.selected_mezz_zone_id; the rail list / canvas / project-load
        # paths all set it before calling this method.
        zone = self._get_selected_mezz_zone()
        if zone is None:
            self.selected_mezz_zone_id = None
            self._update_mezz_inspector_visibility()
            self._update_mezz_props_state()
            return
        self._sanitize_mezz_zone_joist_overrides(zone)
        self._mezz_loading_zone = True
        try:
            self.mezz_name_var.set(str(zone.get("name", "")))
            self.mezz_x_start_var.set(str(zone.get("x_start_label", "1")))
            self.mezz_x_end_var.set(str(zone.get("x_end_label", "2")))
            self.mezz_y_start_var.set(str(zone.get("y_start_label", "A")))
            self.mezz_y_end_var.set(str(zone.get("y_end_label", "B")))
            self.mezz_elevation_var.set(self._fmt_num(float(zone.get("elevation_ft", 0.0)), 2).rstrip("0").rstrip("."))
            self.mezz_dead_load_var.set(self._fmt_num(float(zone.get("dead_load_psf", 0.0)), 2).rstrip("0").rstrip("."))
            self.mezz_live_load_var.set(self._fmt_num(float(zone.get("live_load_psf", 0.0)), 2).rstrip("0").rstrip("."))
            self.mezz_joist_spaces_var.set(str(int(zone.get("joist_spaces_per_bay", 7) or 7)))
            self.mezz_panel_spacing_value_var.set(str(int(zone.get("joist_spaces_per_bay", 7) or 7)))
            self.mezz_joist_direction_var.set(str(zone.get("joist_direction", "Vertical")))
            self.mezz_internal_x_var.set(", ".join(self._fmt_num(v, 2).rstrip("0").rstrip(".") for v in zone.get("internal_x_spacings_ft", [])))
            self.mezz_internal_y_var.set(", ".join(self._fmt_num(v, 2).rstrip("0").rstrip(".") for v in zone.get("internal_y_spacings_ft", [])))
            x0 = float(zone.get("x_start_ft", 0.0))
            x1 = float(zone.get("x_end_ft", 0.0))
            y0 = float(zone.get("y_start_ft", 0.0))
            y1 = float(zone.get("y_end_ft", 0.0))
            self.mezz_origin_x_var.set(self._fmt_num(x0, 3).rstrip("0").rstrip("."))
            self.mezz_origin_y_var.set(self._fmt_num(y0, 3).rstrip("0").rstrip("."))
            self.mezz_width_var.set(self._fmt_num(max(0.0, x1 - x0), 3).rstrip("0").rstrip("."))
            self.mezz_length_var.set(self._fmt_num(max(0.0, y1 - y0), 3).rstrip("0").rstrip("."))
        finally:
            self._mezz_loading_zone = False
        self._refresh_mezz_internal_spacing_labels()
        self._refresh_mezz_panel_spacing_tree()
        self._update_mezz_inspector_visibility()
        self._update_mezz_props_state()

    def _update_mezz_props_state(self):
        zone_selected = self._get_selected_mezz_zone() is not None
        enabled = bool(self.mezzanine_enabled_var.get())
        zone_actions_enabled = enabled and zone_selected
        if hasattr(self, "mezz_update_btn"):
            self.mezz_update_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))
        if hasattr(self, "mezz_duplicate_btn"):
            self.mezz_duplicate_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))
        if hasattr(self, "mezz_delete_btn"):
            self.mezz_delete_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))
        if hasattr(self, "mezz_panel_set_btn"):
            self.mezz_panel_set_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))
        if hasattr(self, "mezz_panel_clear_btn"):
            self.mezz_panel_clear_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))
        if hasattr(self, "mezz_panel_reset_btn"):
            self.mezz_panel_reset_btn.configure(state=("normal" if zone_actions_enabled else "disabled"))

    def _set_widget_tree_state(self, widget, state):
        """Recursively set state on widgets that support it."""
        try:
            cls = widget.winfo_class()
            if cls in ("TEntry", "TCombobox", "TButton", "TCheckbutton", "TRadiobutton", "TSpinbox", "Spinbox"):
                widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._set_widget_tree_state(child, state)

    def _toggle_mezz_advanced(self):
        if not hasattr(self, "_mezz_advanced_frame"):
            return
        # Flip the visibility flag, then apply
        new_visible = not bool(self._mezz_advanced_visible.get())
        self._mezz_advanced_visible.set(new_visible)
        if new_visible:
            self._mezz_advanced_frame.grid()
            self._mezz_advanced_btn.configure(text="▼  Advanced (Internal Bays & Panel Overrides)")
        else:
            self._mezz_advanced_frame.grid_remove()
            self._mezz_advanced_btn.configure(text="▶  Advanced (Internal Bays & Panel Overrides)")

    def _on_mezz_property_changed(self, *_args):
        """Live-binding callback. Updates the selected zone whenever a property field changes."""
        if self._mezz_loading_zone:
            return
        zone = self._get_selected_mezz_zone()
        if zone is None:
            return
        try:
            ox = float(self.mezz_origin_x_var.get())
            oy = float(self.mezz_origin_y_var.get())
            w = float(self.mezz_width_var.get())
            ll = float(self.mezz_length_var.get())
        except (ValueError, tk.TclError):
            return
        if w <= 0 or ll <= 0:
            return
        try:
            updated = self._build_mezz_zone_from_rect(
                ox, oy, ox + w, oy + ll, keep_id=str(zone.get("id"))
            )
        except InputValidationError:
            return
        except (ValueError, TypeError):
            return
        target_id = str(zone.get("id"))
        self.mezz_zones = [updated if str(item.get("id")) == target_id else item for item in self.mezz_zones]
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine inputs updated. Run Calculate Mezzanine.")
        # Refresh the rail card and inspector title without re-loading fields (we're mid-edit).
        if hasattr(self, "mezz_inspector_title_var"):
            self.mezz_inspector_title_var.set(str(updated.get("name", "")) or "Mezzanine")
        self._refresh_mezz_zone_list_in_place()
        self.redraw_mezzanine_preview()

    def _refresh_mezz_zone_list_in_place(self):
        """Repaint the zone cards without changing selection or reloading fields.
        Safe during live-edits — `skip_reload=True` keeps user keystrokes intact.
        """
        self._refresh_mezz_zone_list(skip_reload=True)

    def _setup_mezz_property_traces(self):
        if self._mezz_property_traces_ready:
            return
        self._mezz_property_traces_ready = True
        for var in (
            self.mezz_name_var, self.mezz_elevation_var,
            self.mezz_dead_load_var, self.mezz_live_load_var,
            self.mezz_joist_direction_var, self.mezz_joist_spaces_var,
            self.mezz_origin_x_var, self.mezz_origin_y_var,
            self.mezz_width_var, self.mezz_length_var,
        ):
            var.trace_add("write", self._on_mezz_property_changed)

    # ------------------------------------------------------------------
    # Zone-list rendering & selection (replaces the old Treeview)
    # ------------------------------------------------------------------

    def _refresh_mezz_zone_list(self, *, preserve_draft: bool = False, skip_reload: bool = False):
        """Repopulate the left-rail zone cards.

        preserve_draft=True: do not auto-select any row (used when the caller has prepared
        draft fields for a *next* mezzanine and doesn't want them clobbered).
        skip_reload=True: do not call `_on_mezz_zone_selected` after rebuild — used during
        live in-place edits where reloading from the zone would stomp the user's keystrokes.
        """
        if not hasattr(self, "_mezz_zones_list"):
            return
        for child in self._mezz_zones_list.winfo_children():
            child.destroy()

        if not self.mezz_zones:
            empty = ttk_bs.Label(
                self._mezz_zones_list,
                text="No mezzanines yet.\nClick + Add Mezzanine\nor drag on the plan.",
                style="Muted.TLabel",
                justify="left",
                wraplength=200,
            )
            empty.grid(row=0, column=0, sticky="w", padx=8, pady=10)
            self.selected_mezz_zone_id = None
            self._update_mezz_inspector_visibility()
            self._refresh_mezz_panel_spacing_tree()
            self._update_mezz_props_state()
            return

        wheel_handler = getattr(self, "_mezz_zones_wheel_handler", None)
        for idx, zone in enumerate(self.mezz_zones):
            self._sanitize_mezz_zone_joist_overrides(zone)
            zid = str(zone.get("id", ""))
            is_selected = (zid == str(self.selected_mezz_zone_id or ""))
            card = ttk_bs.Frame(
                self._mezz_zones_list,
                padding=(8, 6),
                bootstyle=("primary" if is_selected else "secondary"),
            )
            card.grid(row=idx, column=0, sticky="ew", pady=(0, 6), padx=2)
            card.columnconfigure(0, weight=1)

            name_lbl = ttk_bs.Label(
                card,
                text=str(zone.get("name", "")) or "(unnamed)",
                font=("Segoe UI", 10, "bold"),
                bootstyle=("inverse-primary" if is_selected else "inverse-secondary"),
            )
            name_lbl.grid(row=0, column=0, sticky="w")

            del_btn = ttk_bs.Button(
                card,
                text="✕",
                bootstyle=("primary" if is_selected else "secondary"),
                command=lambda z=zid: self._delete_mezz_zone_by_id(z),
                width=2,
            )
            del_btn.grid(row=0, column=1, sticky="e", padx=(4, 0))

            try:
                w = float(zone.get("x_end_ft", 0.0)) - float(zone.get("x_start_ft", 0.0))
                ll = float(zone.get("y_end_ft", 0.0)) - float(zone.get("y_start_ft", 0.0))
                summary = (
                    f"{self._fmt_num(w, 1)}' × {self._fmt_num(ll, 1)}'  "
                    f"@ EL {self._fmt_num(float(zone.get('elevation_ft', 0.0)), 1)}'\n"
                    f"DL {int(float(zone.get('dead_load_psf', 0.0)))} / "
                    f"LL {int(float(zone.get('live_load_psf', 0.0)))} psf  ·  "
                    f"{int(zone.get('support_connections', 0) or 0)} sup"
                )
            except Exception:
                summary = ""
            ttk_bs.Label(
                card,
                text=summary,
                bootstyle=("inverse-primary" if is_selected else "inverse-secondary"),
                font=("Segoe UI", 9),
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

            # Bind clicks across the whole card to select it
            for w in (card, name_lbl):
                w.bind("<Button-1>", lambda _e, z=zid: self._select_mezz_zone(z))
            if wheel_handler:
                for w in (card, name_lbl):
                    w.bind("<MouseWheel>", wheel_handler, add="+")
                    w.bind("<Button-4>", wheel_handler, add="+")
                    w.bind("<Button-5>", wheel_handler, add="+")

        if preserve_draft:
            self.selected_mezz_zone_id = None
            self._update_mezz_inspector_visibility()
            self._refresh_mezz_panel_spacing_tree()
            self._update_mezz_props_state()
            return

        # Resolve selection: if current selection still exists keep it; else pick first.
        preserve = str(self.selected_mezz_zone_id or "")
        valid = {str(z.get("id", "")) for z in self.mezz_zones}
        if preserve and preserve in valid:
            self.selected_mezz_zone_id = preserve
            if not skip_reload:
                self._on_mezz_zone_selected()
        else:
            first_id = str(self.mezz_zones[0].get("id", ""))
            self.selected_mezz_zone_id = first_id
            if not skip_reload:
                self._on_mezz_zone_selected()

    # Backward-compat shim — older callers still use _refresh_mezz_zone_tree
    def _refresh_mezz_zone_tree(self, *, preserve_draft: bool = False):
        self._refresh_mezz_zone_list(preserve_draft=preserve_draft)

    def _select_mezz_zone(self, zone_id: str):
        """Select a zone by id (called from the rail list, the canvas, or other code paths)."""
        zid = str(zone_id or "")
        if not zid:
            return
        if not any(str(z.get("id", "")) == zid for z in self.mezz_zones):
            return
        if str(self.selected_mezz_zone_id or "") == zid:
            # Already selected — re-load anyway in case fields drifted
            self._on_mezz_zone_selected()
            return
        self.selected_mezz_zone_id = zid
        self._on_mezz_zone_selected()
        self._refresh_mezz_zone_list()  # repaint card highlight
        self.redraw_mezzanine_preview()

    def _delete_mezz_zone_by_id(self, zone_id: str):
        zid = str(zone_id or "")
        if not zid:
            return
        self.mezz_zones = [z for z in self.mezz_zones if str(z.get("id", "")) != zid]
        if str(self.selected_mezz_zone_id or "") == zid:
            self.selected_mezz_zone_id = None
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine deleted. Run Calculate Mezzanine.")
        self._refresh_mezz_zone_list()
        self.redraw_mezzanine_preview()

    def _update_mezz_inspector_visibility(self):
        """Show or hide the inspector body based on whether a zone is selected."""
        if not hasattr(self, "_mezz_inspector_body"):
            return
        zone = self._get_selected_mezz_zone()
        if zone is None:
            try:
                self._mezz_inspector_body.grid_remove()
            except Exception:
                pass
            if hasattr(self, "mezz_inspector_title_var"):
                self.mezz_inspector_title_var.set("No mezzanine selected")
        else:
            try:
                self._mezz_inspector_body.grid()
            except Exception:
                pass
            if hasattr(self, "mezz_inspector_title_var"):
                self.mezz_inspector_title_var.set(str(zone.get("name", "")) or "Mezzanine")

    def _invalidate_mezzanine_results(self):
        self.last_mezz_result = None
        self.last_mezz_footing_result = None
        self.mezz_joist_selection_by_group = {}
        self.mezz_girder_selection_by_group = {}
        self.mezz_column_selection_by_group = {}
        self._refresh_joist_selection_table()
        self._refresh_girder_selection_table()
        self._refresh_column_selection_table()
        self._refresh_mezz_panel_spacing_tree()

    def _find_free_mezz_slot(self):
        """Pick a (x0, y0, x1, y1) snapped to grid lines for a new mezzanine.

        Snapping the corners to grid lines guarantees the rectangle has at least
        4 main-column supports (the validator requires ≥2). Searches all
        contiguous bay rectangles up to a 2x2 bay block and returns the smallest
        free spot, falling back to a 1x1 bay if nothing larger fits.
        """
        if not self.model.x_spans or not self.model.y_spans:
            raise InputValidationError("Add grid bays before adding a mezzanine.")
        x_lines = [float(v) for v in self.model.x_lines]
        y_lines = [float(v) for v in self.model.y_lines]
        n_bx = len(self.model.x_spans)
        n_by = len(self.model.y_spans)

        def _overlaps(x0, y0, x1, y1):
            for z in self.mezz_zones:
                try:
                    zx0 = float(z.get("x_start_ft", 0.0))
                    zx1 = float(z.get("x_end_ft", 0.0))
                    zy0 = float(z.get("y_start_ft", 0.0))
                    zy1 = float(z.get("y_end_ft", 0.0))
                except (TypeError, ValueError):
                    continue
                if not (x1 <= zx0 + 1e-6 or x0 >= zx1 - 1e-6 or y1 <= zy0 + 1e-6 or y0 >= zy1 - 1e-6):
                    return True
            return False

        # Prefer 2x2 bay blocks; fall back to 1x1.
        for bay_w_ct, bay_h_ct in ((2, 2), (1, 2), (2, 1), (1, 1)):
            for by_start in range(0, max(1, n_by - bay_h_ct + 1)):
                for bx_start in range(0, max(1, n_bx - bay_w_ct + 1)):
                    x0 = x_lines[bx_start]
                    x1 = x_lines[min(n_bx, bx_start + bay_w_ct)]
                    y0 = y_lines[by_start]
                    y1 = y_lines[min(n_by, by_start + bay_h_ct)]
                    if not _overlaps(x0, y0, x1, y1):
                        return (x0, y0, x1, y1)

        # Nothing free at all — return first 1x1 bay (validator may complain about overlap)
        return (x_lines[0], y_lines[0], x_lines[1], y_lines[1])

    def add_mezz_zone(self):
        """Drop a new mezzanine into a free spot inside the grid and select it.

        This is the primary "+ Add Mezzanine" entry point. It does not require the
        user to fill in any form — last-used loads/joist params are inherited from
        the most recently added zone (or sane defaults).
        """
        if not self.mezzanine_enabled_var.get():
            self.mezzanine_enabled_var.set(True)
            self._on_mezz_enabled_changed()

        try:
            x0, y0, x1, y1 = self._find_free_mezz_slot()
        except InputValidationError as exc:
            messagebox.showerror("Cannot add mezzanine", str(exc))
            return

        # Stage all input-var writes inside the loading guard so the property traces
        # don't push partial values into the *currently-selected* zone (which is some
        # earlier mezzanine, not the one we're about to create).
        self._mezz_loading_zone = True
        try:
            if self.mezz_zones:
                template = self.mezz_zones[-1]
                self.mezz_elevation_var.set(
                    self._fmt_num(float(template.get("elevation_ft", 15.0)), 2).rstrip("0").rstrip(".")
                )
                self.mezz_dead_load_var.set(
                    self._fmt_num(float(template.get("dead_load_psf", 80.0)), 2).rstrip("0").rstrip(".")
                )
                self.mezz_live_load_var.set(
                    self._fmt_num(float(template.get("live_load_psf", 100.0)), 2).rstrip("0").rstrip(".")
                )
                self.mezz_joist_direction_var.set(str(template.get("joist_direction", "Vertical")))
                self.mezz_joist_spaces_var.set(str(int(template.get("joist_spaces_per_bay", 7) or 7)))
                self.mezz_internal_x_var.set("")
                self.mezz_internal_y_var.set("")
            self.mezz_name_var.set(self._generate_mezz_name())
            self.mezz_origin_x_var.set(self._fmt_num(x0, 3).rstrip("0").rstrip("."))
            self.mezz_origin_y_var.set(self._fmt_num(y0, 3).rstrip("0").rstrip("."))
            self.mezz_width_var.set(self._fmt_num(x1 - x0, 3).rstrip("0").rstrip("."))
            self.mezz_length_var.set(self._fmt_num(y1 - y0, 3).rstrip("0").rstrip("."))
        finally:
            self._mezz_loading_zone = False

        try:
            zone = self._build_mezz_zone_from_rect(x0, y0, x1, y1)
        except InputValidationError as exc:
            messagebox.showerror("Cannot add mezzanine", str(exc))
            return

        self.mezz_zones.append(zone)
        self.selected_mezz_zone_id = str(zone.get("id"))
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set(
            f"Added '{zone.get('name')}'. Drag on the plan or edit the inspector to fine-tune."
        )
        self._refresh_mezz_zone_list()
        self.redraw_mezzanine_preview()
        # Focus the name field so the user can rename immediately.
        try:
            if hasattr(self, "mezz_name_entry"):
                self.mezz_name_entry.focus_set()
                self.mezz_name_entry.select_range(0, "end")
        except Exception:
            pass

    def add_mezz_zone_from_rect(self, x0: float, y0: float, x1: float, y1: float):
        if not self.mezzanine_enabled_var.get():
            self.mezzanine_enabled_var.set(True)
            self._on_mezz_enabled_changed()
        try:
            zone = self._build_mezz_zone_from_rect(x0, y0, x1, y1)
        except InputValidationError as exc:
            messagebox.showerror("Invalid mezzanine zone", str(exc))
            self.mezz_calc_status_var.set(str(exc))
            return
        self.mezz_zones.append(zone)
        self.selected_mezz_zone_id = str(zone.get("id"))
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set(
            f"Added '{zone.get('name')}'. Run Calculate when ready."
        )
        self._refresh_mezz_zone_list()
        self.redraw_mezzanine_preview()
        try:
            if hasattr(self, "mezz_name_entry"):
                self.mezz_name_entry.focus_set()
                self.mezz_name_entry.select_range(0, "end")
        except Exception:
            pass

    def update_mezz_zone(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            messagebox.showerror("No zone selected", "Select a mezzanine zone first.")
            return
        try:
            updated = self._build_mezz_zone_from_inputs(keep_id=str(zone.get("id")))
        except InputValidationError as exc:
            messagebox.showerror("Invalid mezzanine zone", str(exc))
            return
        target_id = str(zone.get("id"))
        self.mezz_zones = [updated if str(item.get("id")) == target_id else item for item in self.mezz_zones]
        self.selected_mezz_zone_id = target_id
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine inputs updated. Run Calculate Mezzanine.")
        self._refresh_mezz_zone_tree()
        self.redraw_mezzanine_preview()

    def delete_mezz_zone(self):
        zone = self._get_selected_mezz_zone()
        if zone is None:
            return
        target_id = str(zone.get("id"))
        self.mezz_zones = [item for item in self.mezz_zones if str(item.get("id")) != target_id]
        self.selected_mezz_zone_id = None
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("Mezzanine inputs updated. Run Calculate Mezzanine.")
        self._refresh_mezz_zone_tree()
        self.redraw_mezzanine_preview()

    def clear_mezz_zones(self):
        self.mezz_zones = []
        self.selected_mezz_zone_id = None
        self._invalidate_mezzanine_results()
        self.mezz_calc_status_var.set("No mezzanine calculation run yet.")
        self._refresh_mezz_zone_tree()
        self._set_mezz_results_text("")
        self.redraw_mezzanine_preview()

    def prune_mezz_zones(self):
        cleaned = []
        for zone in self.mezz_zones:
            try:
                x0 = float(zone.get("x_start_ft", 0.0))
                x1 = float(zone.get("x_end_ft", 0.0))
                y0 = float(zone.get("y_start_ft", 0.0))
                y1 = float(zone.get("y_end_ft", 0.0))
                rect = self._validate_mezz_rect(x0, y0, x1, y1)
            except Exception:
                continue
            zone = dict(zone)
            zone["x_start_ft"] = float(rect["x_min"])
            zone["x_end_ft"] = float(rect["x_max"])
            zone["y_start_ft"] = float(rect["y_min"])
            zone["y_end_ft"] = float(rect["y_max"])
            zone["x_start_line_index"] = int(rect["x_start_line_index"])
            zone["x_end_line_index"] = int(rect["x_end_line_index"])
            zone["y_start_line_index"] = int(rect["y_start_line_index"])
            zone["y_end_line_index"] = int(rect["y_end_line_index"])
            zone["x_start_label"] = str(rect["x_start_label"])
            zone["x_end_label"] = str(rect["x_end_label"])
            zone["y_start_label"] = str(rect["y_start_label"])
            zone["y_end_label"] = str(rect["y_end_label"])
            zone["support_connections"] = int(rect["support_count"])
            zone["main_support_connections"] = int(rect.get("main_support_count", 0))
            zone["lb_wall_support_connections"] = int(rect.get("lb_wall_support_count", 0))
            self._sanitize_mezz_zone_joist_overrides(zone)
            cleaned.append(zone)
        self.mezz_zones = cleaned
        if self.selected_mezz_zone_id and not any(str(z.get("id")) == str(self.selected_mezz_zone_id) for z in self.mezz_zones):
            self.selected_mezz_zone_id = None
        self._refresh_mezz_zone_tree()

    def _set_mezz_results_text(self, content: str):
        if not hasattr(self, "mezz_results_text"):
            return
        self.mezz_results_text.configure(state="normal")
        self.mezz_results_text.delete("1.0", "end")
        self.mezz_results_text.insert("1.0", content)
        self.mezz_results_text.configure(state="disabled")

    def redraw_mezzanine_preview(self):
        if not hasattr(self, "mezz_canvas"):
            return
        c = self.mezz_canvas
        c.delete("all")
        self._mezz_canvas_transform = None
        if not self.model.x_spans or not self.model.y_spans:
            c.create_text(
                c.winfo_width() / 2,
                c.winfo_height() / 2,
                text="Add X/Y bays in Grid Layout to start mezzanine planning.",
                fill=self._cv["mezz_empty_text"],
                font=("Segoe UI", 11),
                justify="center",
            )
            return

        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        total_w = max(1e-6, x_lines[-1] - x_lines[0])
        total_h = max(1e-6, y_lines[-1] - y_lines[0])
        cw = max(220, c.winfo_width())
        ch = max(180, c.winfo_height())
        margin = 40
        fit_scale = min((cw - 2 * margin) / total_w, (ch - 2 * margin) / total_h)
        fit_scale = max(0.1, fit_scale)
        zoom = max(1.0, float(self.mezz_zoom_var.get() or 1.0))
        scale = fit_scale * zoom
        max_span_x = max(float(v) for v in self.model.x_spans) if self.model.x_spans else total_w
        max_span_y = max(float(v) for v in self.model.y_spans) if self.model.y_spans else total_h
        min_scale = max(40.0 / max(1e-6, max_span_x), 40.0 / max(1e-6, max_span_y))
        scale = max(scale, min_scale)
        full_w = (total_w * scale) + (2 * margin)
        full_h = (total_h * scale) + (2 * margin)
        ox = margin
        oy = margin
        c.configure(scrollregion=(0, 0, full_w, full_h))
        self._mezz_canvas_transform = {"scale": scale, "ox": ox, "oy": oy, "x0": x_lines[0], "y0": y_lines[0]}

        def to_px(wx, wy):
            return ox + (wx - x_lines[0]) * scale, oy + (wy - y_lines[0]) * scale

        active = self.get_active_bays()
        for x_idx in range(len(self.model.x_spans)):
            for y_idx in range(len(self.model.y_spans)):
                x0, y0 = x_lines[x_idx], y_lines[y_idx]
                x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
                sx0, sy0 = to_px(x0, y0)
                sx1, sy1 = to_px(x1, y1)
                if (x_idx, y_idx) in active:
                    c.create_rectangle(sx0, sy0, sx1, sy1, fill=self._cv["mezz_active_bay"], outline="")
                else:
                    c.create_rectangle(sx0, sy0, sx1, sy1, fill=self._cv["mezz_void_bay"], outline="")

        for x in x_lines:
            sx0, sy0 = to_px(x, y_lines[0])
            sx1, sy1 = to_px(x, y_lines[-1])
            c.create_line(sx0, sy0, sx1, sy1, fill=self._cv["mezz_grid_line"], width=2)
        for y in y_lines:
            sx0, sy0 = to_px(x_lines[0], y)
            sx1, sy1 = to_px(x_lines[-1], y)
            c.create_line(sx0, sy0, sx1, sy1, fill=self._cv["mezz_grid_line"], width=2)

        for i, x in enumerate(x_lines):
            sx, sy = to_px(x, y_lines[0])
            c.create_text(sx, sy - 16, text=str(i + 1), fill=self._cv["mezz_axis_label"], font=("Segoe UI", 9, "bold"))
        for i, y in enumerate(y_lines):
            sx, sy = to_px(x_lines[0], y)
            c.create_text(sx - 16, sy, text=axis_letter(i), fill=self._cv["mezz_axis_label"], font=("Segoe UI", 9, "bold"))

        zone_colors = ["#60a5fa", "#22c55e", "#f59e0b", "#e879f9", "#f97316", "#14b8a6"]
        enabled_zone_ids = [str(z.get("id", "")) for z in self.mezz_zones if bool(z.get("enabled", True))]
        selected_zone_id = str(self.selected_mezz_zone_id or "")
        show_dense_labels = len(enabled_zone_ids) <= 2
        for idx, zone in enumerate(self.mezz_zones):
            if not bool(zone.get("enabled", True)):
                continue
            x0 = float(zone.get("x_start_ft", 0.0))
            x1 = float(zone.get("x_end_ft", 0.0))
            y0 = float(zone.get("y_start_ft", 0.0))
            y1 = float(zone.get("y_end_ft", 0.0))
            if x1 <= x0 or y1 <= y0:
                continue
            color = zone_colors[idx % len(zone_colors)]
            is_selected = str(zone.get("id", "")) == selected_zone_id
            show_zone_detail = is_selected or show_dense_labels
            sx0, sy0 = to_px(x0, y0)
            sx1, sy1 = to_px(x1, y1)
            c.create_rectangle(
                sx0,
                sy0,
                sx1,
                sy1,
                fill=color,
                stipple="gray25",
                outline=color,
                width=(4 if is_selected else 2),
            )

            zx_span = x1 - x0
            zy_span = y1 - y0
            run_x = x0
            for seg in zone.get("internal_x_spacings_ft", []):
                run_x += float(seg)
                if run_x >= (x1 - 1e-6):
                    break
                lx0, ly0 = to_px(run_x, y0)
                lx1, ly1 = to_px(run_x, y1)
                c.create_line(lx0, ly0, lx1, ly1, fill=color, dash=(4, 3), width=1)
            run_y = y0
            for seg in zone.get("internal_y_spacings_ft", []):
                run_y += float(seg)
                if run_y >= (y1 - 1e-6):
                    break
                lx0, ly0 = to_px(x0, run_y)
                lx1, ly1 = to_px(x1, run_y)
                c.create_line(lx0, ly0, lx1, ly1, fill=color, dash=(4, 3), width=1)

            if show_zone_detail:
                label = (
                    f"{zone.get('name', 'Mezz')} | EL {self._fmt_num(zone.get('elevation_ft', 0.0), 1)} ft\n"
                    f"DL/LL {self._fmt_num(zone.get('dead_load_psf', 0.0), 0)}/{self._fmt_num(zone.get('live_load_psf', 0.0), 0)} psf | "
                    f"{zone.get('joist_direction', 'Vertical')[0]}-joists"
                )
                c.create_text(
                    (sx0 + sx1) / 2,
                    (sy0 + sy1) / 2,
                    text=label,
                    fill=self._cv["mezz_zone_text"],
                    font=("Segoe UI", 8, "bold"),
                )
            else:
                c.create_text(
                    sx0 + 8,
                    sy0 + 8,
                    text=str(zone.get("name", "Mezz")),
                    fill=self._cv["mezz_zone_text"],
                    font=("Segoe UI", 8, "bold"),
                    anchor="nw",
                )

            if is_selected:
                dim_x_txt = "Internal X: " + (
                    ", ".join(self._fmt_num(v, 1).rstrip("0").rstrip(".") for v in zone.get("internal_x_spacings_ft", []))
                    or f"{self._fmt_num(zx_span, 1)}"
                )
                dim_y_txt = "Internal Y: " + (
                    ", ".join(self._fmt_num(v, 1).rstrip("0").rstrip(".") for v in zone.get("internal_y_spacings_ft", []))
                    or f"{self._fmt_num(zy_span, 1)}"
                )
                dim_w_txt = f"W = {self._fmt_num(zx_span, 2)} ft (click to edit)"
                dim_l_txt = f"L = {self._fmt_num(zy_span, 2)} ft (click to edit)"
                tag_x = f"mezz_dim_x_{zone.get('id')}"
                tag_y = f"mezz_dim_y_{zone.get('id')}"
                tag_w = f"mezz_dim_w_{zone.get('id')}"
                tag_l = f"mezz_dim_l_{zone.get('id')}"
                c.create_text((sx0 + sx1) / 2, sy0 - 10, text=dim_x_txt, fill=self._cv["mezz_axis_label"], font=("Segoe UI", 8), tags=(tag_x,))
                c.create_text(sx0 - 10, (sy0 + sy1) / 2, text=dim_y_txt, fill=self._cv["mezz_axis_label"], font=("Segoe UI", 8), angle=90, tags=(tag_y,))
                c.create_text((sx0 + sx1) / 2, sy1 + 12, text=dim_w_txt, fill=self._cv["mezz_zone_text"], font=("Segoe UI", 8, "bold"), tags=(tag_w,))
                c.create_text(sx1 + 10, (sy0 + sy1) / 2, text=dim_l_txt, fill=self._cv["mezz_zone_text"], font=("Segoe UI", 8, "bold"), angle=90, tags=(tag_l,))
                c.tag_bind(tag_x, "<Button-1>", lambda _e, zid=str(zone.get("id")): self._on_mezz_dim_click(zid, "X"))
                c.tag_bind(tag_y, "<Button-1>", lambda _e, zid=str(zone.get("id")): self._on_mezz_dim_click(zid, "Y"))
                c.tag_bind(tag_w, "<Button-1>", lambda _e, zid=str(zone.get("id")): self._on_mezz_dim_click(zid, "W"))
                c.tag_bind(tag_l, "<Button-1>", lambda _e, zid=str(zone.get("id")): self._on_mezz_dim_click(zid, "L"))

            # Draw panel spacing labels and potential internal column points at panel nodes.
            x_segments = self._fit_mezz_zone_segments(zx_span, zone.get("internal_x_spacings_ft", []))
            y_segments = self._fit_mezz_zone_segments(zy_span, zone.get("internal_y_spacings_ft", []))
            x_nodes = [x0]
            run_x = x0
            for seg in x_segments:
                run_x += float(seg)
                x_nodes.append(run_x)
            y_nodes = [y0]
            run_y = y0
            for seg in y_segments:
                run_y += float(seg)
                y_nodes.append(run_y)
            default_spaces = max(1, int(zone.get("joist_spaces_per_bay", 7) or 7))
            overrides = dict(zone.get("joist_spaces_overrides", {}) or {})
            show_panel_spaces = is_selected or (show_dense_labels and len(x_segments) * len(y_segments) <= 36)
            selected_panels = set(self._mezz_selected_panel_keys) if is_selected else set()
            for ix in range(len(x_nodes) - 1):
                for iy in range(len(y_nodes) - 1):
                    pkey = f"{ix + 1},{iy + 1}"
                    p_spaces = int(overrides.get(pkey, default_spaces))
                    px0, py0 = to_px(x_nodes[ix], y_nodes[iy])
                    px1, py1 = to_px(x_nodes[ix + 1], y_nodes[iy + 1])
                    if is_selected and pkey in selected_panels:
                        c.create_rectangle(px0, py0, px1, py1, outline="#0ea5e9", width=2, dash=(3, 2))
                    if show_panel_spaces:
                        c.create_text(
                            (px0 + px1) / 2,
                            (py0 + py1) / 2,
                            text=f"J{int(max(1, p_spaces))}",
                            fill=self._cv["mezz_axis_label"],
                            font=("Segoe UI", 8, "bold"),
                        )
            for wx in x_nodes:
                for wy in y_nodes:
                    px, py = to_px(wx, wy)
                    c.create_rectangle(px - 2, py - 2, px + 2, py + 2, fill=self._cv["mezz_col_fill"], outline="")

            if zx_span <= 0 or zy_span <= 0:
                continue

        if self._mezz_draw_mode and self._mezz_drag_start and self._mezz_drag_end:
            xs, ys = self._mezz_drag_start
            xe, ye = self._mezz_drag_end
            sx0, sy0 = to_px(min(xs, xe), min(ys, ye))
            sx1, sy1 = to_px(max(xs, xe), max(ys, ye))
            c.create_rectangle(sx0, sy0, sx1, sy1, outline=self._cv["mezz_dim_color"], width=2, dash=(6, 4))
            w_ft = abs(float(xe) - float(xs))
            l_ft = abs(float(ye) - float(ys))
            c.create_line(sx0, sy1 + 18, sx1, sy1 + 18, fill=self._cv["mezz_dim_color"], width=1.5, arrow=tk.BOTH)
            c.create_line(sx1 + 18, sy0, sx1 + 18, sy1, fill=self._cv["mezz_dim_color"], width=1.5, arrow=tk.BOTH)
            c.create_text(
                (sx0 + sx1) / 2,
                sy1 + 32,
                text=f"W = {self._fmt_num(w_ft, 2)} ft",
                fill=self._cv["mezz_dim_color"],
                font=("Segoe UI", 9, "bold"),
            )
            c.create_text(
                sx1 + 34,
                (sy0 + sy1) / 2,
                text=f"L = {self._fmt_num(l_ft, 2)} ft",
                fill=self._cv["mezz_dim_color"],
                font=("Segoe UI", 9, "bold"),
                angle=90,
            )
            c.create_text(
                (sx0 + sx1) / 2,
                sy0 - 20,
                text=(
                    "Release to place mezzanine | "
                    f"X {self._fmt_num(min(xs, xe), 2)}-{self._fmt_num(max(xs, xe), 2)} ft | "
                    f"Y {self._fmt_num(min(ys, ye), 2)}-{self._fmt_num(max(ys, ye), 2)} ft"
                ),
                fill=self._cv["mezz_dim_color"],
                font=("Segoe UI", 9, "bold"),
            )

        if not self.mezzanine_enabled_var.get():
            c.create_text(
                cw - 12,
                14,
                text="Mezzanine mode disabled",
                fill=self._cv["mezz_conn_color"],
                font=("Segoe UI", 9, "italic"),
                anchor="ne",
            )
        elif self._mezz_draw_mode:
            c.create_text(
                cw - 12,
                14,
                text=(
                    "Drag a mezzanine footprint  "
                    "(must connect to ≥2 supports: columns and/or LB walls)"
                ),
                fill=self._cv["mezz_dim_color"],
                font=("Segoe UI", 9, "bold"),
                anchor="ne",
            )

    def calculate_mezzanines(self):
        try:
            payload = self.collect_joist_layout_data()
            result = calculate_mezzanine_takeoff(payload)
        except InputValidationError as exc:
            messagebox.showerror("Mezzanine input error", str(exc))
            self.mezz_calc_status_var.set(str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Calculation error", f"Unexpected error:\n{exc}")
            self.mezz_calc_status_var.set("Mezzanine calculation failed.")
            return

        self.last_mezz_result = result
        try:
            self.calculate_mezz_pad_footings()
        except InputValidationError:
            self.last_mezz_footing_result = None
        summary = result.get("summary", {})
        self.mezz_calc_status_var.set(
            "Mezzanine calculated | Zones: {z} | Panels: {p} | Joists: {j} | Girders: {g} | "
            "Mezz Columns: {c} | Reused Main Cols: {rc} | Area: {a} sf".format(
                z=summary.get("zone_count", 0),
                p=summary.get("panel_count", 0),
                j=summary.get("joist_count", 0),
                g=summary.get("girder_count", 0),
                c=summary.get("column_count", 0),
                rc=summary.get("reused_main_column_count", 0),
                a=self._fmt_num(summary.get("total_mezzanine_area_sf", 0.0), 2),
            )
        )

        lines = []
        lines.append("Zone | X Range | Y Range | Elev(ft) | DL | LL | TL | Dir | J Spaces | Width(ft) | Length(ft) | Area(sf) | Panels | Supports")
        lines.append(
            "Mezz Columns to size: {mc} | Main building columns reused (not re-sized in mezz): {rc}".format(
                mc=self._fmt_int(summary.get("column_count", 0)),
                rc=self._fmt_int(summary.get("reused_main_column_count", 0)),
            )
        )
        for zone in result.get("mezzanine_zones", []):
            lines.append(
                "{name} | {xs}-{xe} | {ys}-{ye} | {elev} | {dl} | {ll} | {tl} | {dir} | {js} | {w} | {l} | {a} | {p} | {conn}".format(
                    name=zone.get("name", "-"),
                    xs=zone.get("x_start_label", "-"),
                    xe=zone.get("x_end_label", "-"),
                    ys=zone.get("y_start_label", "-"),
                    ye=zone.get("y_end_label", "-"),
                    elev=self._fmt_num(zone.get("elevation_ft", 0.0), 2),
                    dl=self._fmt_num(zone.get("dead_load_psf", 0.0), 2),
                    ll=self._fmt_num(zone.get("live_load_psf", 0.0), 2),
                    tl=self._fmt_num(zone.get("total_load_psf", 0.0), 2),
                    dir=str(zone.get("joist_direction", "vertical"))[:1].upper(),
                    js=int(zone.get("joist_spaces_per_bay", 7)),
                    w=self._fmt_num(zone.get("width_ft", 0.0), 2),
                    l=self._fmt_num(zone.get("length_ft", 0.0), 2),
                    a=self._fmt_num(zone.get("area_sf", 0.0), 2),
                    p=int(zone.get("panel_count", 0)),
                    conn=int(zone.get("support_connections", zone.get("main_support_connections", 0))),
                )
            )
        lines.append("")
        lines.append("Mezz Joist Demand Groups")
        lines.append("Req(plf) | Span(ft) | Qty Joists | Zones")
        for grp in result.get("mezzanine_joist_demand_groups", []):
            lines.append(
                "{req} | {span} | {qty} | {zones}".format(
                    req=self._fmt_num(grp.get("required_capacity_plf", 0.0), 2),
                    span=self._fmt_num(grp.get("required_length_ft", 0.0), 2),
                    qty=int(grp.get("count", 0)),
                    zones=", ".join(grp.get("zones", [])),
                )
            )
        lines.append("")
        lines.append("Mezz Girder Demand Groups")
        lines.append("Req(lbs) | Span(ft) | N | Dmin(in) | Qty Girders | Zones")
        for grp in result.get("mezzanine_girder_demand_groups", []):
            lines.append(
                "{req} | {span} | {n} | {dmin} | {qty} | {zones}".format(
                    req=self._fmt_num(grp.get("required_capacity_lbs", 0.0), 2),
                    span=self._fmt_num(grp.get("required_length_ft", 0.0), 2),
                    n=self._fmt_int(grp.get("required_joist_n", 0)),
                    dmin=self._fmt_num(grp.get("min_depth_in", grp.get("max_depth_in", 30.0)), 2),
                    qty=int(grp.get("count", 0)),
                    zones=", ".join(grp.get("zones", [])),
                )
            )
        lines.append("")
        lines.append("Mezz Column Demand Groups")
        lines.append("Req(kips) | Height(ft) | Type | Qty | Zones")
        for grp in result.get("mezzanine_column_demand_groups", []):
            lines.append(
                "{k} | {h} | {t} | {q} | {zones}".format(
                    k=self._fmt_num(grp.get("required_capacity_kips", 0.0), 2),
                    h=self._fmt_num(grp.get("column_height_ft", 0.0), 2),
                    t=str(grp.get("main_or_mezz_column", "Mezz")),
                    q=int(grp.get("count", 0)),
                    zones=", ".join(grp.get("zones", [])),
                )
            )
        weight_summary = self._compute_mezz_assigned_weight_totals()
        lines.append("")
        lines.append("Assigned Mezzanine Steel Weights")
        lines.append(
            "Joists: {j} lbs ({ja}/{jt} groups) | Girders: {g} lbs ({ga}/{gt} groups) | "
            "Columns: {c} lbs ({ca}/{ct} groups) | Total: {t} lbs".format(
                j=self._fmt_num(weight_summary.get("joist_lbs", 0.0), 2),
                ja=self._fmt_int(weight_summary.get("joist_assigned_groups", 0)),
                jt=self._fmt_int(weight_summary.get("joist_total_groups", 0)),
                g=self._fmt_num(weight_summary.get("girder_lbs", 0.0), 2),
                ga=self._fmt_int(weight_summary.get("girder_assigned_groups", 0)),
                gt=self._fmt_int(weight_summary.get("girder_total_groups", 0)),
                c=self._fmt_num(weight_summary.get("column_lbs", 0.0), 2),
                ca=self._fmt_int(weight_summary.get("column_assigned_groups", 0)),
                ct=self._fmt_int(weight_summary.get("column_total_groups", 0)),
                t=self._fmt_num(weight_summary.get("total_steel_lbs", 0.0), 2),
            )
        )
        mezz_footing_summary = (self.last_mezz_footing_result or {}).get("summary", {})
        lines.append(
            "Mezz Footings: {n} pads | Total CY: {cy} | CY +10% waste: {cyw}".format(
                n=self._fmt_int(mezz_footing_summary.get("column_count", 0)),
                cy=self._fmt_num(mezz_footing_summary.get("total_cy", 0.0), 3),
                cyw=self._fmt_num(mezz_footing_summary.get("total_cy_with_waste", 0.0), 3),
            )
        )
        self._set_mezz_results_text("\n".join(lines))
        self._refresh_joist_selection_table()
        self._refresh_girder_selection_table()
        self._refresh_column_selection_table()
        self.redraw_mezzanine_preview()

    def clear_dock_line(self):
        # Backward-compatible alias.
        self.clear_speed_bay_rows()

    def clear_speed_bay_rows(self):
        self.speed_bay_rows = set()
        self._refresh_dock_line_options()

    def world_to_screen(self, x_ft: float, y_ft: float):
        return x_ft * self.zoom + self.offset_x, y_ft * self.zoom + self.offset_y

    def screen_to_world(self, x_px: float, y_px: float):
        return (x_px - self.offset_x) / self.zoom, (y_px - self.offset_y) / self.zoom

    def add_x_bay(self):
        try:
            val = float(self.x_spacing_var.get())
            if val <= MIN_SPACING_FT:
                raise ValueError
            old_boundaries = self._current_boundary_segments()
            self.model.x_spans.append(round(val, 3))
            self._sync_load_bearing_perimeter(old_boundaries)
            self._refresh_mezz_line_options()
            if self.auto_fit_on_bay_change.get():
                self.fit_to_view()
            else:
                self.redraw()
        except ValueError:
            messagebox.showerror("Invalid value", f"X bay spacing must be > {self._fmt_ft_arch(MIN_SPACING_FT)}.")

    def add_y_bay(self):
        try:
            val = float(self.y_spacing_var.get())
            if val <= MIN_SPACING_FT:
                raise ValueError
            old_boundaries = self._current_boundary_segments()
            self.model.y_spans.append(round(val, 3))
            self._sync_load_bearing_perimeter(old_boundaries)
            self._refresh_dock_line_options()
            self._refresh_mezz_line_options()
            if self.auto_fit_on_bay_change.get():
                self.fit_to_view()
            else:
                self.redraw()
        except ValueError:
            messagebox.showerror("Invalid value", f"Y bay spacing must be > {self._fmt_ft_arch(MIN_SPACING_FT)}.")

    def remove_x_bay(self):
        if self.model.x_spans:
            old_boundaries = self._current_boundary_segments()
            self.model.x_spans.pop()
            self._sync_load_bearing_perimeter(old_boundaries)
            self._refresh_mezz_line_options()
            if self.auto_fit_on_bay_change.get():
                self.fit_to_view()
            else:
                self.redraw()

    def remove_y_bay(self):
        if self.model.y_spans:
            old_boundaries = self._current_boundary_segments()
            self.model.y_spans.pop()
            self._sync_load_bearing_perimeter(old_boundaries)
            self._refresh_dock_line_options()
            self._refresh_mezz_line_options()
            if self.auto_fit_on_bay_change.get():
                self.fit_to_view()
            else:
                self.redraw()

    def clear_grid(self):
        self.model.x_spans = []
        self.model.y_spans = []
        self.collateral_bays = set()
        self.additional_load_layers = []
        self.selected_additional_load_layer_id = None
        self._additional_load_layer_counter = 0
        self.additional_load_name_var.set("Additional 1")
        self.custom_load_addition_var.set("0")
        self.additional_load_color_var.set("#f7d8a8")
        self.inactive_bays = set()
        self.load_bearing_perimeter = set()
        self.joists_per_bay = {}
        self.dock_line_var.set("")
        self.speed_bay_rows = set()
        self.mezz_zones = []
        self.selected_mezz_zone_id = None
        self._mezz_zone_counter = 0
        self.mezz_name_var.set("Mezzanine 1")
        self.mezz_joist_spaces_var.set("7")
        self.mezz_origin_x_var.set("0")
        self.mezz_origin_y_var.set("0")
        self.mezz_width_var.set("50")
        self.mezz_length_var.set("50")
        self.mezz_zoom_var.set(2.4)
        self.mezz_snap_enabled_var.set(True)
        self.mezz_snap_step_var.set("1.0")
        self.mezz_continuous_draw_var.set(True)
        self.mezz_internal_x_var.set("")
        self.mezz_internal_y_var.set("")
        self._refresh_mezz_internal_spacing_labels()
        self._mezz_draw_mode = False
        self._mezz_drag_start = None
        self._mezz_drag_end = None
        self.last_mezz_result = None
        self.last_mezz_footing_result = None
        self.mezz_joist_selection_by_group = {}
        self.mezz_girder_selection_by_group = {}
        self.mezz_column_selection_by_group = {}
        self.mezz_calc_status_var.set("No mezzanine calculation run yet.")
        self._on_mezz_enabled_changed()
        self.last_joist_result = None
        self.last_girder_result = None
        self.last_column_result = None
        self.last_tilt_result = None
        self.last_footing_result = None
        self.clear_selected_joists()
        self.clear_selected_girders()
        self.clear_selected_columns()
        self.joist_calc_status_var.set("No joist calculation run yet.")
        self.girder_calc_status_var.set("No girder calculation run yet.")
        self.column_calc_status_var.set("No column calculation run yet.")
        self.tilt_calc_status_var.set("No tilt wall calculation run yet.")
        self.footing_calc_status_var.set("No footing calculation run yet.")
        if hasattr(self, "mezz_calc_status_var"):
            self.mezz_calc_status_var.set("No mezzanine calculation run yet.")
        self.report_status_var.set("Ready to run all calculations and export company PDF.")
        self._set_joist_results_text("")
        self._set_girder_results_text("")
        self._set_column_results_text("")
        self._set_tilt_results_text("")
        self._set_footing_results_text("")
        self._clear_report_log()
        self._refresh_dock_line_options()
        self._refresh_mezz_line_options()
        self._refresh_additional_load_layer_tree()
        self._refresh_mezz_zone_tree()
        self._set_mezz_results_text("")
        self.redraw_roof_section()
        self.redraw_tilt_wall_preview()
        self.redraw_mezzanine_preview()
        self.fit_to_view()

    def clear_collateral_bays(self):
        self.collateral_bays = set()
        self.redraw()

    def clear_custom_load_bays(self):
        layer = self._get_selected_additional_load_layer()
        if layer is None:
            return
        layer["bays"] = set()
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def _normalize_hex_color(self, value: str, fallback: str = "#f7d8a8"):
        token = str(value or "").strip()
        if not token:
            return fallback
        if not token.startswith("#"):
            token = "#" + token
        if re.fullmatch(r"#[0-9a-fA-F]{6}", token):
            return token.lower()
        return fallback

    def _next_additional_load_default_color(self):
        idx = len(self.additional_load_layers) % max(1, len(self._additional_load_color_cycle))
        return self._additional_load_color_cycle[idx]

    def _generate_additional_load_name(self):
        used = {str(layer.get("name", "")).strip().lower() for layer in self.additional_load_layers}
        n = 1
        while True:
            name = f"Additional {n}"
            if name.lower() not in used:
                return name
            n += 1

    def _get_selected_additional_load_layer(self):
        target = str(self.selected_additional_load_layer_id or "").strip()
        if not target:
            return None
        for layer in self.additional_load_layers:
            if str(layer.get("id")) == target:
                return layer
        return None

    def _on_additional_load_layer_selected(self, _event=None):
        if not hasattr(self, "additional_load_tree"):
            return
        selection = self.additional_load_tree.selection()
        if not selection:
            self.selected_additional_load_layer_id = None
            return
        self.selected_additional_load_layer_id = str(selection[0])
        layer = self._get_selected_additional_load_layer()
        if layer is None:
            return
        self.additional_load_name_var.set(str(layer.get("name", "")))
        self.custom_load_addition_var.set(self._fmt_num(float(layer.get("psf", 0.0)), 3).rstrip("0").rstrip("."))
        self.additional_load_color_var.set(str(layer.get("color", "#f7d8a8")))
        self.additional_load_status_var.set(
            f"Selected '{layer.get('name', 'Layer')}' ({self._fmt_num(layer.get('psf', 0.0), 2)} psf). "
            f"Marked bays: {len(layer.get('bays', set()))}. Use mode 'Mark Additional Load Bays' to edit."
        )

    def _refresh_additional_load_layer_tree(self):
        if not hasattr(self, "additional_load_tree"):
            return
        preserve = str(self.selected_additional_load_layer_id or "")
        if not preserve:
            current = self.additional_load_tree.selection()
            preserve = str(current[0]) if current else ""
        self.additional_load_tree.delete(*self.additional_load_tree.get_children())
        for layer in self.additional_load_layers:
            layer_id = str(layer.get("id"))
            self.additional_load_tree.insert(
                "",
                "end",
                iid=layer_id,
                values=(
                    str(layer.get("name", "")),
                    self._fmt_num(float(layer.get("psf", 0.0)), 2),
                    str(layer.get("color", "")),
                    str(len(layer.get("bays", set()))),
                ),
            )
        if preserve and self.additional_load_tree.exists(preserve):
            self.additional_load_tree.selection_set(preserve)
            self.selected_additional_load_layer_id = preserve
            self._on_additional_load_layer_selected()
        elif self.additional_load_layers:
            first_id = str(self.additional_load_layers[0].get("id"))
            self.additional_load_tree.selection_set(first_id)
            self.selected_additional_load_layer_id = first_id
            self._on_additional_load_layer_selected()
        else:
            self.selected_additional_load_layer_id = None
            self.additional_load_status_var.set("No additional load layers defined.")

    def pick_additional_load_color(self):
        initial = self._normalize_hex_color(self.additional_load_color_var.get(), "#f7d8a8")
        rgb, hex_code = colorchooser.askcolor(color=initial, title="Choose Additional Load Layer Color")
        if rgb is None or not hex_code:
            return
        self.additional_load_color_var.set(self._normalize_hex_color(hex_code, initial))

    def add_additional_load_layer(self):
        try:
            psf = self._parse_non_negative_load("Additional Layer PSF", self.custom_load_addition_var.get())
        except InputValidationError as exc:
            messagebox.showerror("Invalid additional load", str(exc))
            return
        name = str(self.additional_load_name_var.get() or "").strip() or self._generate_additional_load_name()
        color = self._normalize_hex_color(self.additional_load_color_var.get(), self._next_additional_load_default_color())
        self._additional_load_layer_counter += 1
        layer_id = f"AL{self._additional_load_layer_counter:03d}"
        self.additional_load_layers.append(
            {"id": layer_id, "name": name, "psf": float(psf), "color": color, "bays": set()}
        )
        self.selected_additional_load_layer_id = layer_id
        self.additional_load_name_var.set(self._generate_additional_load_name())
        self.custom_load_addition_var.set("0")
        self.additional_load_color_var.set(self._next_additional_load_default_color())
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def update_selected_additional_load_layer(self):
        layer = self._get_selected_additional_load_layer()
        if layer is None:
            messagebox.showerror("No layer selected", "Select an additional load layer first.")
            return
        try:
            psf = self._parse_non_negative_load("Additional Layer PSF", self.custom_load_addition_var.get())
        except InputValidationError as exc:
            messagebox.showerror("Invalid additional load", str(exc))
            return
        name = str(self.additional_load_name_var.get() or "").strip() or str(layer.get("name", "Additional"))
        color = self._normalize_hex_color(self.additional_load_color_var.get(), str(layer.get("color", "#f7d8a8")))
        layer["name"] = name
        layer["psf"] = float(psf)
        layer["color"] = color
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def delete_selected_additional_load_layer(self):
        layer = self._get_selected_additional_load_layer()
        if layer is None:
            return
        target_id = str(layer.get("id"))
        self.additional_load_layers = [
            item for item in self.additional_load_layers if str(item.get("id")) != target_id
        ]
        self.selected_additional_load_layer_id = None
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def clear_all_additional_load_layers(self):
        self.additional_load_layers = []
        self.selected_additional_load_layer_id = None
        self.additional_load_name_var.set("Additional 1")
        self.custom_load_addition_var.set("0")
        self.additional_load_color_var.set("#f7d8a8")
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def clear_inactive_bays(self):
        old_boundaries = self._current_boundary_segments()
        self.inactive_bays = set()
        self._sync_load_bearing_perimeter(old_boundaries)
        self.redraw()

    def _boundary_segments_for_active(self, active_bays, x_count: int = None, y_count: int = None):
        if x_count is None:
            x_count = len(self.model.x_spans)
        if y_count is None:
            y_count = len(self.model.y_spans)
        if x_count <= 0 or y_count <= 0:
            return set()

        active = {
            (x_idx, y_idx)
            for (x_idx, y_idx) in active_bays
            if 0 <= x_idx < x_count and 0 <= y_idx < y_count
        }
        output = set()
        for x_idx, y_idx in active:
            if y_idx == 0 or (x_idx, y_idx - 1) not in active:
                output.add(("H", y_idx, x_idx))
            if y_idx == y_count - 1 or (x_idx, y_idx + 1) not in active:
                output.add(("H", y_idx + 1, x_idx))
            if x_idx == 0 or (x_idx - 1, y_idx) not in active:
                output.add(("V", x_idx, y_idx))
            if x_idx == x_count - 1 or (x_idx + 1, y_idx) not in active:
                output.add(("V", x_idx + 1, y_idx))
        return output

    def _active_bays_for_counts(self, x_count: int, y_count: int):
        return {
            (x_idx, y_idx)
            for x_idx in range(max(0, x_count))
            for y_idx in range(max(0, y_count))
            if (x_idx, y_idx) not in self.inactive_bays
        }

    def _current_boundary_segments(self):
        return self._boundary_segments_for_active(self.get_active_bays())

    def _sync_load_bearing_perimeter(self, old_boundary_segments=None):
        valid_now = self._current_boundary_segments()
        if old_boundary_segments is None:
            if not self.load_bearing_perimeter:
                self.load_bearing_perimeter = set(valid_now)
            else:
                self.load_bearing_perimeter = {seg for seg in self.load_bearing_perimeter if seg in valid_now}
            return

        old_set = set(old_boundary_segments)
        keep = {seg for seg in self.load_bearing_perimeter if seg in valid_now}
        new_segments = valid_now - old_set
        self.load_bearing_perimeter = keep | new_segments

    def prune_load_bearing_perimeter(self):
        valid_now = self._current_boundary_segments()
        self.load_bearing_perimeter = {seg for seg in self.load_bearing_perimeter if seg in valid_now}

    def set_all_load_bearing_perimeter(self):
        self.load_bearing_perimeter = set(self._current_boundary_segments())
        self.redraw()

    def clear_load_bearing_perimeter(self):
        self.load_bearing_perimeter = set()
        self.redraw()

    def _outer_edge_from_side(self, side: str, segment_idx: int):
        side = str(side or "").strip().upper()
        seg = int(segment_idx)
        if side == "N":
            return ("H", 0, seg)
        if side == "S":
            return ("H", len(self.model.y_spans), seg)
        if side == "W":
            return ("V", 0, seg)
        if side == "E":
            return ("V", len(self.model.x_spans), seg)
        return None

    def _is_load_bearing_perimeter_segment(self, side: str, segment_idx: int):
        edge = self._outer_edge_from_side(side, segment_idx)
        if edge is None:
            return False
        boundaries = self._current_boundary_segments()
        return edge in boundaries and edge in self.load_bearing_perimeter

    def _is_side_fully_load_bearing(self, side: str):
        side = str(side or "").strip().upper()
        if side not in {"N", "S", "E", "W"}:
            return False
        boundaries = self._current_boundary_segments()
        if side in {"N", "S"}:
            seg_count = len(self.model.x_spans)
        else:
            seg_count = len(self.model.y_spans)
        if seg_count <= 0:
            return False

        candidates = []
        for seg_idx in range(seg_count):
            edge = self._outer_edge_from_side(side, seg_idx)
            if edge is not None and edge in boundaries:
                candidates.append(edge)
        if not candidates:
            return False
        return all(edge in self.load_bearing_perimeter for edge in candidates)

    def clear_joist_assignments(self):
        self.joists_per_bay = {}
        self.last_joist_result = None
        self.last_girder_result = None
        self.last_column_result = None
        self.last_tilt_result = None
        self.last_footing_result = None
        self.last_mezz_result = None
        self.last_mezz_footing_result = None
        self.mezz_joist_selection_by_group = {}
        self.mezz_girder_selection_by_group = {}
        self.mezz_column_selection_by_group = {}
        self.clear_selected_joists()
        self.clear_selected_girders()
        self.clear_selected_columns()
        self.joist_calc_status_var.set("No joist calculation run yet.")
        self.girder_calc_status_var.set("No girder calculation run yet.")
        self.column_calc_status_var.set("No column calculation run yet.")
        self.tilt_calc_status_var.set("No tilt wall calculation run yet.")
        self.footing_calc_status_var.set("No footing calculation run yet.")
        if hasattr(self, "mezz_calc_status_var"):
            self.mezz_calc_status_var.set("No mezzanine calculation run yet.")
        self.report_status_var.set("Ready to run all calculations and export company PDF.")
        self._set_joist_results_text("")
        self._set_girder_results_text("")
        self._set_column_results_text("")
        self.redraw_roof_section()
        self._set_tilt_results_text("")
        self._set_footing_results_text("")
        self._clear_report_log()
        self.redraw_tilt_wall_preview()
        self.redraw_mezzanine_preview()
        self.redraw()

    def _parse_non_negative_load(self, label: str, value: str):
        try:
            parsed = float(value)
        except ValueError as exc:
            raise InputValidationError(f"{label} must be numeric.") from exc
        if parsed < 0:
            raise InputValidationError(f"{label} must be >= 0.")
        return round(parsed, 3)

    def _parse_positive_input(self, label: str, value: str):
        try:
            parsed = float(value)
        except ValueError as exc:
            raise InputValidationError(f"{label} must be numeric.") from exc
        if parsed <= 0:
            raise InputValidationError(f"{label} must be > 0.")
        return parsed

    def _normalize_snow_code(self, value: str) -> str:
        token = str(value or "").strip().upper().replace("–", "-")
        if token in {"ASCE 7-22", "7-22", "ASCE722", "ASCE 722"}:
            return "ASCE 7-22"
        return "ASCE 7-16"

    def get_default_joist_count(self):
        try:
            spaces = int(self.joist_count_var.get())
            if spaces < 1:
                raise ValueError
            return spaces
        except ValueError as exc:
            raise InputValidationError("Joist spaces per bay must be an integer >= 1.") from exc

    def get_active_bays(self):
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        return {
            (x_idx, y_idx)
            for x_idx in range(max_x)
            for y_idx in range(max_y)
            if (x_idx, y_idx) not in self.inactive_bays
        }

    def get_active_building_area_sf(self):
        active = self.get_active_bays()
        if not active:
            return 0.0
        total = 0.0
        for x_idx, y_idx in active:
            total += float(self.model.x_spans[x_idx]) * float(self.model.y_spans[y_idx])
        return total

    def apply_joists_to_all_bays(self):
        try:
            count = self.get_default_joist_count()
        except InputValidationError as exc:
            messagebox.showerror("Invalid joist spaces", str(exc))
            return

        self.joists_per_bay = {
            (x_idx, y_idx): count
            for (x_idx, y_idx) in self.get_active_bays()
        }
        self.redraw()

    def _collect_mezzanine_payload(self):
        self.prune_mezz_zones()
        output = []
        for zone in self.mezz_zones:
            output.append(
                {
                    "id": str(zone.get("id", "")),
                    "name": str(zone.get("name", "Mezzanine")).strip() or "Mezzanine",
                    "enabled": bool(zone.get("enabled", True)),
                    "x_start_line_index": int(zone.get("x_start_line_index", 1)),
                    "x_end_line_index": int(zone.get("x_end_line_index", 2)),
                    "y_start_line_index": int(zone.get("y_start_line_index", 1)),
                    "y_end_line_index": int(zone.get("y_end_line_index", 2)),
                    "x_start_line": int(zone.get("x_start_line_index", 1)),
                    "x_end_line": int(zone.get("x_end_line_index", 2)),
                    "y_start_line": int(zone.get("y_start_line_index", 1)),
                    "y_end_line": int(zone.get("y_end_line_index", 2)),
                    "x_start_ft": float(zone.get("x_start_ft", 0.0)),
                    "x_end_ft": float(zone.get("x_end_ft", 0.0)),
                    "y_start_ft": float(zone.get("y_start_ft", 0.0)),
                    "y_end_ft": float(zone.get("y_end_ft", 0.0)),
                    "joist_direction": str(zone.get("joist_direction", "Vertical")),
                    "joist_spaces_per_bay": int(zone.get("joist_spaces_per_bay", 7)),
                    "joist_spaces_overrides": self._serialize_mezz_zone_joist_overrides(zone),
                    "elevation_ft": float(zone.get("elevation_ft", 0.0)),
                    "dead_load_psf": float(zone.get("dead_load_psf", 0.0)),
                    "live_load_psf": float(zone.get("live_load_psf", 0.0)),
                    "internal_x_spacings_ft": [float(v) for v in zone.get("internal_x_spacings_ft", [])],
                    "internal_y_spacings_ft": [float(v) for v in zone.get("internal_y_spacings_ft", [])],
                    "support_connections": int(zone.get("support_connections", zone.get("main_support_connections", 0))),
                    "main_support_connections": int(zone.get("main_support_connections", 0)),
                    "lb_wall_support_connections": int(zone.get("lb_wall_support_connections", 0)),
                    "support_connection_tolerance_ft": 1.5,
                }
            )
        return output

    def collect_joist_layout_data(self):
        self.prune_inactive_bays()
        self.prune_collateral_bays()
        self.prune_custom_load_bays()
        self.prune_joist_assignments()
        self.prune_mezz_zones()
        self.prune_load_bearing_perimeter()
        active_bays = self.get_active_bays()
        if not active_bays:
            raise InputValidationError("No active bays found. Re-enable at least one bay in the building shape.")
        default_count = self.get_default_joist_count()

        joists_per_bay = []
        for x_idx, y_idx in sorted(active_bays, key=lambda item: (item[1], item[0])):
            count = self.joists_per_bay.get((x_idx, y_idx), default_count)
            joists_per_bay.append(
                {"x_bay": x_idx + 1, "y_bay": axis_letter(y_idx), "joist_count": count}
            )

        snow_code = self._normalize_snow_code(self.snow_code_var.get())
        if str(self.snow_code_var.get() or "").strip() != snow_code:
            self.snow_code_var.set(snow_code)
        load_inputs = {
            "dead_load_psf": self._parse_non_negative_load("Dead Load", self.dead_load_var.get()),
            "live_load_psf": self._parse_non_negative_load("Live Load", self.live_load_var.get()),
            "snow_load_psf": self._parse_non_negative_load("Snow Load", self.snow_load_var.get()),
            "collateral_addition_psf": self._parse_non_negative_load(
                "Collateral Load Addition", self.collateral_addition_var.get()
            ),
            # Legacy single custom-load key retained for backward compatibility.
            "custom_load_addition_psf": 0.0,
            "snow_code": snow_code,
            "reduced_snow_load_psf_manual": (
                self._parse_non_negative_load("Reduced Snow Load (manual)", self.reduced_snow_load_manual_var.get())
                if snow_code == "ASCE 7-22"
                else 0.0
            ),
            "location_city": str(self.location_city_var.get() or "").strip(),
            "location_state": str(self.location_state_var.get() or "").strip(),
        }

        additional_layers = []
        for layer in self.additional_load_layers:
            psf = self._parse_non_negative_load(
                f"Additional Load '{layer.get('name', 'Layer')}'", str(layer.get("psf", 0.0))
            )
            additional_layers.append(
                {
                    "id": str(layer.get("id", "")),
                    "name": str(layer.get("name", "Additional")).strip() or "Additional",
                    "psf": psf,
                    "color": self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8"),
                    "bays": [
                        {"x_bay": x_idx + 1, "y_bay": axis_letter(y_idx)}
                        for (x_idx, y_idx) in sorted(layer.get("bays", set()))
                    ],
                }
            )

        return {
            "x_spans_ft": list(self.model.x_spans),
            "y_spans_ft": list(self.model.y_spans),
            "speed_bay_rows": [
                {"y_row": axis_letter(row_idx), "row_index": row_idx + 1}
                for row_idx in sorted(self._get_selected_speed_bay_rows())
            ],
            "speed_transition_lines": [
                {"y_line": axis_letter(line_idx), "line_index": line_idx + 1}
                for line_idx in self._get_speed_bay_transition_line_indices()
            ],
            "active_bays": [
                {"x_bay": x_idx + 1, "y_bay": axis_letter(y_idx)}
                for (x_idx, y_idx) in sorted(active_bays, key=lambda item: (item[1], item[0]))
            ],
            "load_bearing_wall_segments": [
                {
                    "orientation": orient,
                    "line_index": line_idx + 1,
                    "segment_index": seg_idx + 1,
                }
                for orient, line_idx, seg_idx in sorted(self.load_bearing_perimeter)
            ],
            "collateral_bays": [
                {"x_bay": x_idx + 1, "y_bay": axis_letter(y_idx)}
                for (x_idx, y_idx) in sorted(self.collateral_bays)
            ],
            "custom_load_bays": [],
            "additional_load_layers": additional_layers,
            "mezzanine_enabled": bool(self.mezzanine_enabled_var.get()),
            "mezzanines": self._collect_mezzanine_payload(),
            "joists_per_bay": joists_per_bay,
            "load_inputs_psf": load_inputs,
        }

    def _set_joist_results_text(self, content: str):
        self.joist_results_text.configure(state="normal")
        self.joist_results_text.delete("1.0", "end")
        self.joist_results_text.insert("1.0", content)
        self.joist_results_text.configure(state="disabled")

    def _set_girder_results_text(self, content: str):
        self.girder_results_text.configure(state="normal")
        self.girder_results_text.delete("1.0", "end")
        self.girder_results_text.insert("1.0", content)
        self.girder_results_text.configure(state="disabled")

    def _set_column_results_text(self, content: str):
        self.column_results_text.configure(state="normal")
        self.column_results_text.delete("1.0", "end")
        self.column_results_text.insert("1.0", content)
        self.column_results_text.configure(state="disabled")

    def _set_tilt_results_text(self, content: str):
        self.tilt_results_text.configure(state="normal")
        self.tilt_results_text.delete("1.0", "end")
        self.tilt_results_text.insert("1.0", content)
        self.tilt_results_text.configure(state="disabled")

    def _set_footing_results_text(self, content: str):
        if not hasattr(self, "footing_results_text"):
            return
        self.footing_results_text.configure(state="normal")
        self.footing_results_text.delete("1.0", "end")
        self.footing_results_text.insert("1.0", content)
        self.footing_results_text.configure(state="disabled")

    def _get_mezz_result_for_tab_display(self):
        if not bool(self.mezzanine_enabled_var.get()) or not bool(self.mezz_zones):
            return None
        try:
            payload = self.collect_joist_layout_data()
            result = calculate_mezzanine_takeoff(payload)
            self.last_mezz_result = result
            try:
                self.calculate_mezz_pad_footings()
            except InputValidationError:
                self.last_mezz_footing_result = None
            return result
        except InputValidationError as exc:
            return {"_error": str(exc)}
        except Exception as exc:
            return {"_error": f"Unexpected mezzanine error: {exc}"}

    def _append_mezz_joist_section(self, lines, mezz_result):
        lines.append("")
        lines.append("=== MEZZANINE JOIST CALCULATIONS ===")
        if mezz_result is None:
            lines.append("Mezzanine is disabled or has no zones.")
            return
        if isinstance(mezz_result, dict) and "_error" in mezz_result:
            lines.append(f"Mezzanine calculation error: {mezz_result.get('_error')}")
            return
        summary = (mezz_result or {}).get("summary", {})
        lines.append(
            "Zones: {z} | Panels: {p} | Joist Items: {j} | Area: {a} sf".format(
                z=self._fmt_int(summary.get("zone_count", 0)),
                p=self._fmt_int(summary.get("panel_count", 0)),
                j=self._fmt_int(summary.get("joist_count", 0)),
                a=self._fmt_num(summary.get("total_mezzanine_area_sf", 0.0), 2),
            )
        )
        lines.append(
            "Zone | Panel | Dir | Spaces | Joists | Span(ft) | Spacing(ft) | Trib Area(sf) | TL(psf) | Req(plf)"
        )
        lines.append("-" * 138)
        for item in (mezz_result or {}).get("mezzanine_joist_calculations", []):
            lines.append(
                "{zone:>8} | {panel:>10} | {dir:>3} | {spaces:>6} | {count:>6} | {span:>8} | {spacing:>11} | {trib:>12.2f} | {tl:>7.2f} | {req:>8.2f}".format(
                    zone=str(item.get("zone_name", "-"))[:8],
                    panel=str(item.get("panel_id", "-"))[-10:],
                    dir=str(item.get("joist_direction", "vertical"))[:1].upper(),
                    spaces=self._fmt_int(item.get("joist_spaces_per_bay", 0)),
                    count=self._fmt_int(item.get("joist_count", 0)),
                    span=self._fmt_ft_arch(item.get("joist_span_ft", 0.0)),
                    spacing=self._fmt_ft_arch(item.get("joist_spacing_ft", 0.0)),
                    trib=float(item.get("tributary_area_sf", 0.0) or 0.0),
                    tl=float(item.get("total_load_psf", 0.0) or 0.0),
                    req=float(item.get("required_capacity_plf", 0.0) or 0.0),
                )
            )

    def _append_mezz_girder_section(self, lines, mezz_result):
        lines.append("")
        lines.append("=== MEZZANINE GIRDER CALCULATIONS ===")
        if mezz_result is None:
            lines.append("Mezzanine is disabled or has no zones.")
            return
        if isinstance(mezz_result, dict) and "_error" in mezz_result:
            lines.append(f"Mezzanine calculation error: {mezz_result.get('_error')}")
            return
        summary = (mezz_result or {}).get("summary", {})
        lines.append(
            "Zones: {z} | Girder Items: {g} | Area: {a} sf".format(
                z=self._fmt_int(summary.get("zone_count", 0)),
                g=self._fmt_int(summary.get("girder_count", 0)),
                a=self._fmt_num(summary.get("total_mezzanine_area_sf", 0.0), 2),
            )
        )
        lines.append(
            "Zone | Girder | Span(ft) | Trib(ft) | Avg JS(ft) | TL(psf) | Req Cap(lbs) | N | Dmin(in)"
        )
        lines.append("-" * 127)
        for item in (mezz_result or {}).get("mezzanine_girder_calculations", []):
            lines.append(
                "{zone:>8} | {gid:>12} | {span:>8} | {trib:>8} | {js:>10} | {tl:>7.2f} | {req:>12.2f} | {n:>2} | {dmin:>8.2f}".format(
                    zone=str(item.get("zone_name", "-"))[:8],
                    gid=str(item.get("girder_id", "-"))[-12:],
                    span=self._fmt_ft_arch(item.get("span_ft", 0.0)),
                    trib=self._fmt_ft_arch(item.get("tributary_length_ft", 0.0)),
                    js=self._fmt_ft_arch(item.get("average_joist_spacing_ft", 0.0)),
                    tl=float(item.get("total_load_psf", 0.0) or 0.0),
                    req=float(item.get("required_capacity_lbs", 0.0) or 0.0),
                    n=self._fmt_int(item.get("required_joist_n", 0)),
                    dmin=float(item.get("min_depth_in", item.get("max_depth_in", 30.0)) or 30.0),
                )
            )

    def _append_mezz_column_section(self, lines, mezz_result):
        lines.append("")
        lines.append("=== MEZZANINE COLUMN CALCULATIONS ===")
        if mezz_result is None:
            lines.append("Mezzanine is disabled or has no zones.")
            return
        if isinstance(mezz_result, dict) and "_error" in mezz_result:
            lines.append(f"Mezzanine calculation error: {mezz_result.get('_error')}")
            return
        summary = (mezz_result or {}).get("summary", {})
        lines.append(
            "Zones: {z} | Mezz Column Items: {c} | Reused Main Cols (not resized): {rc} | Area: {a} sf".format(
                z=self._fmt_int(summary.get("zone_count", 0)),
                c=self._fmt_int(summary.get("column_count", 0)),
                rc=self._fmt_int(summary.get("reused_main_column_count", 0)),
                a=self._fmt_num(summary.get("total_mezzanine_area_sf", 0.0), 2),
            )
        )
        lines.append(
            "Zone | Column | Grid | Type | TribX(ft) | TribY(ft) | At(sf) | TL(psf) | Height(ft) | Req(kips)"
        )
        lines.append("-" * 132)
        for item in (mezz_result or {}).get("mezzanine_column_calculations", []):
            lines.append(
                "{zone:>8} | {cid:>12} | {grid:>7} | {typ:>4} | {tx:>9} | {ty:>9} | {at:>7.2f} | {tl:>7.2f} | {h:>10} | {req:>9.2f}".format(
                    zone=str(item.get("zone_name", "-"))[:8],
                    cid=str(item.get("column_id", "-"))[-12:],
                    grid=f"{item.get('y_line_label', '-')}{item.get('x_line_label', '-')}",
                    typ=str(item.get("main_or_mezz_column", "Mezz"))[:4],
                    tx=self._fmt_ft_arch(item.get("tributary_width_ft", 0.0)),
                    ty=self._fmt_ft_arch(item.get("tributary_length_ft", 0.0)),
                    at=float(item.get("tributary_area_sf", 0.0) or 0.0),
                    tl=float(item.get("total_load_psf", 0.0) or 0.0),
                    h=self._fmt_ft_arch(item.get("column_height_ft", 0.0)),
                    req=float(item.get("required_capacity_kips", 0.0) or 0.0),
                )
            )

    def _append_report_log(self, content: str):
        if not hasattr(self, "report_log_text"):
            return
        self.report_log_text.configure(state="normal")
        if self.report_log_text.index("end-1c") != "1.0":
            self.report_log_text.insert("end", "\n")
        self.report_log_text.insert("end", content)
        self.report_log_text.see("end")
        self.report_log_text.configure(state="disabled")
        self.root.update_idletasks()

    def _clear_report_log(self):
        if not hasattr(self, "report_log_text"):
            return
        self.report_log_text.configure(state="normal")
        self.report_log_text.delete("1.0", "end")
        self.report_log_text.configure(state="disabled")

    def _parse_positive_float_or_default(self, text: str, default_val: float):
        try:
            val = float(text)
            if val <= 0:
                raise ValueError
            return val
        except ValueError:
            return default_val

    def _parse_non_negative_float_or_default(self, text: str, default_val: float):
        try:
            val = float(text)
            if val < 0:
                raise ValueError
            return val
        except ValueError:
            return default_val

    def _ceil_to_increment(self, value: float, increment: float):
        if increment <= 0:
            return round(float(value), 2)
        stepped = math.ceil((float(value) - 1e-12) / increment) * increment
        return round(stepped, 2)

    def _format_joist_group_id(self, required_capacity_plf: float, required_length_ft: float):
        return f"{round(float(required_capacity_plf), 2):.2f}|{round(float(required_length_ft), 2):.2f}"

    def _format_girder_group_id(
        self, required_capacity_lbs: float, required_length_ft: float, required_joist_n: int, max_depth_in: float
    ):
        return (
            f"{round(float(required_capacity_lbs), 2):.2f}|"
            f"{round(float(required_length_ft), 2):.2f}|"
            f"{int(required_joist_n)}|"
            f"{round(float(max_depth_in), 2):.2f}"
        )

    def _format_compact_number(self, value: float, decimals: int = 2):
        text = f"{float(value):.{decimals}f}"
        text = text.rstrip("0").rstrip(".")
        return text if text else "0"

    def _format_girder_designation(self, depth_in: float, joist_n: int, capacity_kips: float):
        depth_txt = self._format_compact_number(depth_in, 2)
        cap_txt = self._format_compact_number(capacity_kips, 2)
        if int(joist_n) > 0:
            return f"{depth_txt}G {int(joist_n)}N {cap_txt}K"
        return f"{depth_txt}G {cap_txt}K"

    def _axis_label_to_index(self, label: str):
        label = str(label or "").strip().upper()
        if not label:
            return None
        total = 0
        for ch in label:
            if not ("A" <= ch <= "Z"):
                return None
            total = (total * 26) + (ord(ch) - ord("A") + 1)
        return total - 1

    def _get_selected_dock_line_index(self):
        # Backward-compatible helper: return first speed transition line (if any).
        transitions = self._get_speed_bay_transition_line_indices()
        return transitions[0] if transitions else None

    def _get_assigned_joist_depth_for_row(self, y_row_idx: int):
        if y_row_idx < 0:
            return None
        if not self.last_joist_result:
            return None
        row_label = axis_letter(y_row_idx)
        depths = []
        for bay_calc in self.last_joist_result.get("joist_bay_calculations", []):
            if bay_calc.get("y_row_label") != row_label:
                continue
            group_id = self._format_joist_group_id(
                bay_calc["required_capacity_plf"],
                bay_calc["bay_length_ft"],
            )
            assigned = self.joist_selection_by_group.get(group_id)
            if assigned and float(assigned.get("depth_in", 0.0)) > 0:
                depths.append(float(assigned["depth_in"]))
        if not depths:
            return None
        # Conservative pick across bays in this row.
        return max(depths)

    def _interpolate_profile_height(self, station_ft: float, line_stations_ft, line_heights_ft):
        if not line_stations_ft or not line_heights_ft:
            return 0.0
        if len(line_stations_ft) == 1:
            return float(line_heights_ft[0])
        x = float(station_ft)
        if x <= line_stations_ft[0]:
            return float(line_heights_ft[0])
        if x >= line_stations_ft[-1]:
            return float(line_heights_ft[-1])
        for i in range(len(line_stations_ft) - 1):
            x0 = float(line_stations_ft[i])
            x1 = float(line_stations_ft[i + 1])
            if x0 <= x <= x1:
                h0 = float(line_heights_ft[i])
                h1 = float(line_heights_ft[i + 1])
                if abs(x1 - x0) <= 1e-9:
                    return h0
                t = (x - x0) / (x1 - x0)
                return h0 + (h1 - h0) * t
        return float(line_heights_ft[-1])

    def _classify_speed_row_side(self, row_idx: int, speed_rows: set, row_count: int, single_slope_direction: str):
        candidates = []
        if row_idx > 0 and (row_idx - 1) not in speed_rows:
            candidates.append("South")
        if row_idx < (row_count - 1) and (row_idx + 1) not in speed_rows:
            candidates.append("North")
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            # Interior isolated speed row (not typical); choose opposite rise side for stability.
            return "South" if str(single_slope_direction).strip().lower() == "north" else "North"
        # Fully surrounded by speed rows (or all rows are speed); choose by proximity to perimeter.
        return "North" if row_idx < (row_count / 2.0) else "South"

    def _compute_bay_slopes_ft_per_ft(
        self,
        y_spans,
        speed_rows: set,
        roof_type: str,
        break_clear_height: bool,
        single_slope_direction: str,
        ridge_line_idx: int,
    ):
        slope_main_ft_per_ft = 0.25 / 12.0
        slope_speed_ft_per_ft = 0.5 / 12.0
        row_count = len(y_spans)
        slopes = []
        rise_toward_north = str(single_slope_direction or "North").strip().lower() != "south"
        roof_is_double = str(roof_type).strip().lower() == "double slope"

        for row_idx in range(row_count):
            if roof_is_double:
                # North->South sign (+ means elevation increases going South).
                main_sign = 1.0 if row_idx < int(ridge_line_idx) else -1.0
            else:
                main_sign = -1.0 if rise_toward_north else 1.0

            if break_clear_height and row_idx in speed_rows:
                side = self._classify_speed_row_side(row_idx, speed_rows, row_count, single_slope_direction)
                sign = 1.0 if side == "North" else -1.0
                slopes.append(sign * slope_speed_ft_per_ft)
            else:
                slopes.append(main_sign * slope_main_ft_per_ft)

        return slopes

    def _roof_height_at_station(
        self,
        station_ft: float,
        total_len_ft: float,
        roof_type: str,
        break_clear_height: bool,
        start_station_ft: float,
        start_height_ft: float,
        ridge_station_ft: float = None,
        single_slope_direction: str = "North",
        speed_bay_side: str = "South",
    ):
        slope_main_ft_per_ft = 0.25 / 12.0   # 1/4 in per ft
        slope_speed_ft_per_ft = 0.5 / 12.0   # 1/2 in per ft (into speed bay when CH is broken)
        if total_len_ft <= 0:
            return start_height_ft
        if ridge_station_ft is None:
            ridge_station_ft = total_len_ft / 2.0
        rise_toward_north = str(single_slope_direction or "North").strip().lower() != "south"
        speed_side = str(speed_bay_side or "South").strip().lower()
        if speed_side not in {"north", "south"}:
            speed_side = "south"

        def single_slope_height(x_station_ft: float):
            if break_clear_height:
                if x_station_ft <= start_station_ft:
                    # North side of dock line.
                    dist = start_station_ft - x_station_ft
                    if speed_side == "north":
                        return start_height_ft - (dist * slope_speed_ft_per_ft)
                    sign = 1.0 if rise_toward_north else -1.0
                    return start_height_ft + sign * (dist * slope_main_ft_per_ft)

                # South side of dock line.
                dist = x_station_ft - start_station_ft
                if speed_side == "south":
                    return start_height_ft - (dist * slope_speed_ft_per_ft)
                sign = -1.0 if rise_toward_north else 1.0
                return start_height_ft + sign * (dist * slope_main_ft_per_ft)

            # No clear-height break:
            if rise_toward_north:
                return start_height_ft + (start_station_ft - x_station_ft) * slope_main_ft_per_ft
            return start_height_ft + (x_station_ft - start_station_ft) * slope_main_ft_per_ft

        single_height = single_slope_height(station_ft)
        if str(roof_type).strip().lower() != "double slope":
            return single_height

        ridge_height = single_slope_height(ridge_station_ft)
        start_offset = start_station_ft - ridge_station_ft
        station_offset = station_ft - ridge_station_ft

        # If station is across the ridge from the start line, mirror the single-slope profile.
        # This creates an up-to-midline then down-after-midline behavior.
        if start_offset == 0:
            return ridge_height - abs(station_offset) * slope_main_ft_per_ft
        if station_offset == 0:
            return ridge_height
        if start_offset * station_offset < 0:
            return (2.0 * ridge_height) - single_height
        return single_height

    def _build_roof_profile_data(self):
        y_spans = list(self.model.y_spans)
        if not y_spans:
            return None

        roof_type = self.roof_type_var.get()
        single_slope_direction = str(self.single_slope_direction_var.get() or "North").strip().title()
        if single_slope_direction not in {"North", "South"}:
            single_slope_direction = "North"
        break_clear_height = bool(self.break_clear_height_var.get())
        clear_height_ft = self._parse_positive_float_or_default(self.clear_height_var.get(), 36.0)
        joist_seat_depth_in = self._parse_non_negative_float_or_default(self.joist_seat_depth_var.get(), 2.5)

        y_lines = [0.0]
        running = 0.0
        for span in y_spans:
            running += span
            y_lines.append(running)
        total_len_ft = y_lines[-1]
        ridge_line_idx = len(y_lines) // 2
        ridge_station_ft = y_lines[ridge_line_idx]
        speed_rows = self._get_selected_speed_bay_rows()
        transition_lines = self._get_speed_bay_transition_line_indices()
        selected_dock_idx = transition_lines[0] if transition_lines else None

        if break_clear_height and transition_lines:
            if str(roof_type).strip().lower() == "single slope":
                # Anchor at transition opposite rise side.
                start_line_idx = max(transition_lines) if single_slope_direction == "North" else min(transition_lines)
            else:
                # For double slope with potential cross-dock, anchor nearest ridge.
                start_line_idx = min(transition_lines, key=lambda idx: abs(int(idx) - int(ridge_line_idx)))
            line_role_label = "Speed transition"
        else:
            start_line_idx = (len(y_lines) - 1) if single_slope_direction == "North" else 0
            line_role_label = "Start line"
        start_station_ft = y_lines[start_line_idx]

        speed_sides = []
        if 0 in speed_rows:
            speed_sides.append("North")
        if (len(y_spans) - 1) in speed_rows:
            speed_sides.append("South")
        speed_bay_side = "Both" if len(speed_sides) >= 2 else (speed_sides[0] if speed_sides else "None")

        if break_clear_height and transition_lines:
            north_row_idx = start_line_idx - 1
            south_row_idx = start_line_idx
            north_valid = 0 <= north_row_idx < len(y_spans)
            south_valid = 0 <= south_row_idx < len(y_spans)
            north_is_speed = north_valid and (north_row_idx in speed_rows)
            south_is_speed = south_valid and (south_row_idx in speed_rows)

            if north_valid and not north_is_speed and (not south_valid or south_is_speed):
                joist_depth_row_idx = north_row_idx
            elif south_valid and not south_is_speed and (not north_valid or north_is_speed):
                joist_depth_row_idx = south_row_idx
            else:
                # Fallback for ambiguous layouts: pick main side opposite rise.
                joist_depth_row_idx = south_row_idx if single_slope_direction == "North" else north_row_idx
        else:
            joist_depth_row_idx = start_line_idx - 1 if start_line_idx > 0 else 0

        joist_depth_row_idx = max(0, min(len(y_spans) - 1, int(joist_depth_row_idx)))
        joist_depth_in = self._get_assigned_joist_depth_for_row(joist_depth_row_idx)
        if joist_depth_in is None:
            joist_depth_in = 0.0
        start_height_ft = clear_height_ft + (joist_depth_in / 12.0)  # BMD == TOJ.

        bay_slopes_ft_per_ft = self._compute_bay_slopes_ft_per_ft(
            y_spans=y_spans,
            speed_rows=speed_rows,
            roof_type=roof_type,
            break_clear_height=break_clear_height,
            single_slope_direction=single_slope_direction,
            ridge_line_idx=ridge_line_idx,
        )
        line_toj_elevations_ft = [0.0 for _ in y_lines]
        line_toj_elevations_ft[start_line_idx] = float(start_height_ft)

        for row_idx in range(start_line_idx - 1, -1, -1):
            delta = float(bay_slopes_ft_per_ft[row_idx]) * float(y_spans[row_idx])
            line_toj_elevations_ft[row_idx] = float(line_toj_elevations_ft[row_idx + 1]) - delta
        for row_idx in range(start_line_idx, len(y_spans)):
            delta = float(bay_slopes_ft_per_ft[row_idx]) * float(y_spans[row_idx])
            line_toj_elevations_ft[row_idx + 1] = float(line_toj_elevations_ft[row_idx]) + delta

        return {
            "y_spans": y_spans,
            "y_lines": y_lines,
            "total_len_ft": total_len_ft,
            "roof_type": roof_type,
            "single_slope_direction": single_slope_direction,
            "break_clear_height": break_clear_height,
            "clear_height_ft": clear_height_ft,
            "joist_seat_depth_in": joist_seat_depth_in,
            "selected_dock_idx": selected_dock_idx,
            "speed_bay_rows": sorted(speed_rows),
            "speed_transition_line_indices": list(transition_lines),
            "speed_bay_sides": list(speed_sides),
            "start_line_idx": start_line_idx,
            "start_station_ft": start_station_ft,
            "line_role_label": line_role_label,
            "speed_bay_side": speed_bay_side,
            "ridge_line_idx": ridge_line_idx,
            "ridge_station_ft": ridge_station_ft,
            "bay_slopes_ft_per_ft": [float(v) for v in bay_slopes_ft_per_ft],
            "joist_depth_in": joist_depth_in,
            "start_height_ft": start_height_ft,
            "line_toj_elevations_ft": line_toj_elevations_ft,
            "line_roof_heights": line_toj_elevations_ft,  # Backward-compatible key.
            "joist_depth_thickness_in": joist_seat_depth_in,  # Backward-compatible key.
            "girder_seat_depth_in": joist_seat_depth_in,  # Backward-compatible key.
        }

    def _get_allowed_girder_depth_by_line_in(self):
        profile = self._build_roof_profile_data()
        if not profile:
            return {}
        clear_height_ft = profile["clear_height_ft"]
        allowed = {
            idx: round((toj_ft - clear_height_ft) * 12.0, 3)
            for idx, toj_ft in enumerate(profile.get("line_toj_elevations_ft", profile["line_roof_heights"]))
        }
        if profile.get("break_clear_height"):
            for line_idx in profile.get("speed_transition_line_indices", []):
                allowed[int(line_idx)] = 60.0
        return allowed

    def _get_jb_drop_in_by_line(self, profile=None):
        if profile is None:
            profile = self._build_roof_profile_data()
        if not profile:
            return {}
        toj_list = profile.get("line_toj_elevations_ft", profile.get("line_roof_heights", []))
        count = len(toj_list)
        if count <= 0:
            return {}

        joist_seat_depth_in = float(
            profile.get("joist_seat_depth_in", profile.get("joist_depth_thickness_in", 2.5))
        )
        return {idx: max(0.0, joist_seat_depth_in) for idx in range(count)}

    def _calculate_tilt_wall_takeoff(self):
        if not self.model.x_spans or not self.model.y_spans:
            raise InputValidationError("Add X and Y bays before calculating tilt walls.")

        profile = self._build_roof_profile_data()
        if not profile:
            raise InputValidationError("Roof profile unavailable for tilt wall calculation.")

        deck_in = self._parse_non_negative_load("Metal Deck Thickness", self.metal_deck_thickness_var.get())
        insulation_in = self._parse_non_negative_load("Insulation Depth", self.insulation_depth_var.get())
        deck_ft = deck_in / 12.0
        insulation_ft = insulation_in / 12.0

        x_spans = list(self.model.x_spans)
        y_spans = list(self.model.y_spans)
        total_x_ft = float(sum(x_spans))
        total_y_ft = float(sum(y_spans))

        toj_line_elevations_ft = [float(v) for v in profile.get("line_toj_elevations_ft", profile["line_roof_heights"])]
        tor_line_elevations_ft = [v + deck_ft + insulation_ft for v in toj_line_elevations_ft]

        north_tor_ft = tor_line_elevations_ft[0]
        south_tor_ft = tor_line_elevations_ft[-1]

        speed_rows = set(profile.get("speed_bay_rows", []))
        north_is_dock = len(y_spans) > 0 and (0 in speed_rows)
        south_is_dock = len(y_spans) > 0 and ((len(y_spans) - 1) in speed_rows)

        left_edge_len_ft = x_spans[0] / 2.0 if x_spans else 0.0
        right_edge_len_ft = x_spans[-1] / 2.0 if x_spans else 0.0
        center_len_ft = max(0.0, total_x_ft - left_edge_len_ft - right_edge_len_ft)

        def _build_ns_wall_payload(top_of_roof_ft: float, is_dock_side: bool):
            edge_h = top_of_roof_ft + 1.0
            if is_dock_side:
                center_h = top_of_roof_ft + 4.0
                area_sf = (
                    left_edge_len_ft * edge_h
                    + center_len_ft * center_h
                    + right_edge_len_ft * edge_h
                )
                wall_h = center_h
                center_base = -4.0
            else:
                center_h = edge_h
                area_sf = total_x_ft * edge_h
                wall_h = edge_h
                center_base = -1.0
            return {
                "length_ft": round(total_x_ft, 3),
                "top_of_roof_ft": round(top_of_roof_ft, 3),
                "is_dock_side": bool(is_dock_side),
                "base_elevation_ft": -1.0,
                "left_edge_length_ft": round(left_edge_len_ft if is_dock_side else 0.0, 3),
                "right_edge_length_ft": round(right_edge_len_ft if is_dock_side else 0.0, 3),
                "center_length_ft": round(center_len_ft if is_dock_side else total_x_ft, 3),
                "edge_base_elevation_ft": -1.0,
                "center_base_elevation_ft": center_base,
                "edge_height_ft": round(edge_h, 3),
                "center_height_ft": round(center_h, 3),
                "wall_height_ft": round(wall_h, 3),
                "area_sf": round(area_sf, 3),
            }

        north_wall = _build_ns_wall_payload(north_tor_ft, north_is_dock)
        south_wall = _build_ns_wall_payload(south_tor_ft, south_is_dock)
        north_area_sf = north_wall["area_sf"]
        south_area_sf = south_wall["area_sf"]

        # East/West walls: stepped using TOR variation along Y.
        step_segments = []
        east_area_sf = 0.0
        for idx, bay_len_ft in enumerate(y_spans):
            top_seg_ft = max(tor_line_elevations_ft[idx], tor_line_elevations_ft[idx + 1])
            seg_height_ft = top_seg_ft + 1.0  # base -1
            seg_area_sf = bay_len_ft * seg_height_ft
            east_area_sf += seg_area_sf
            step_segments.append(
                {
                    "segment_index": idx + 1,
                    "bay_length_ft": round(float(bay_len_ft), 3),
                    "top_of_roof_ft": round(top_seg_ft, 3),
                    "wall_height_ft": round(seg_height_ft, 3),
                    "area_sf": round(seg_area_sf, 3),
                }
            )
        west_area_sf = east_area_sf

        return {
            "inputs": {
                "metal_deck_thickness_in": round(deck_in, 3),
                "insulation_depth_in": round(insulation_in, 3),
                "metal_deck_thickness_ft": round(deck_ft, 4),
                "insulation_depth_ft": round(insulation_ft, 4),
            },
            "roof_elevations": {
                "top_of_joist_line_ft": [round(v, 3) for v in toj_line_elevations_ft],
                "top_of_roof_line_ft": [round(v, 3) for v in tor_line_elevations_ft],
            },
            "north_wall": north_wall,
            "south_wall": south_wall,
            "east_wall": {
                "length_ft": round(total_y_ft, 3),
                "base_elevation_ft": -1.0,
                "step_segments": step_segments,
                "area_sf": round(east_area_sf, 3),
            },
            "west_wall": {
                "length_ft": round(total_y_ft, 3),
                "base_elevation_ft": -1.0,
                "step_segments": step_segments,
                "area_sf": round(west_area_sf, 3),
            },
            "summary": {
                "north_area_sf": round(north_area_sf, 3),
                "south_area_sf": round(south_area_sf, 3),
                "east_area_sf": round(east_area_sf, 3),
                "west_area_sf": round(west_area_sf, 3),
                "north_is_dock_side": bool(north_is_dock),
                "south_is_dock_side": bool(south_is_dock),
                "total_area_sf": round(north_area_sf + south_area_sf + east_area_sf + west_area_sf, 3),
            },
        }

    def calculate_tilt_walls(self):
        try:
            result = self._calculate_tilt_wall_takeoff()
        except InputValidationError as exc:
            messagebox.showerror("Input error", str(exc))
            return

        self.last_tilt_result = result
        summary = result["summary"]
        self.tilt_calc_status_var.set(
            "Tilt wall areas calculated | North: {n:.2f} sf | South: {s:.2f} sf | "
            "East: {e:.2f} sf | West: {w:.2f} sf | Total: {t:.2f} sf".format(
                n=summary["north_area_sf"],
                s=summary["south_area_sf"],
                e=summary["east_area_sf"],
                w=summary["west_area_sf"],
                t=summary["total_area_sf"],
            )
        )

        n = result["north_wall"]
        s = result["south_wall"]
        e = result["east_wall"]

        def _format_ns_wall_line(name: str, wall: dict):
            if wall.get("is_dock_side"):
                return (
                    "{name} | Length: {l} | TOR: {tor} | Edge Base: {edge_base} ({le}+{re}) | "
                    "Center Base: {center_base} ({cl}) | Area: {a:.2f} sf"
                ).format(
                    name=name,
                    l=self._fmt_ft_arch(wall["length_ft"]),
                    tor=self._fmt_ft_arch(wall["top_of_roof_ft"]),
                    edge_base=self._fmt_ft_arch(-1.0),
                    le=self._fmt_ft_arch(wall["left_edge_length_ft"]),
                    re=self._fmt_ft_arch(wall["right_edge_length_ft"]),
                    center_base=self._fmt_ft_arch(-4.0),
                    cl=self._fmt_ft_arch(wall["center_length_ft"]),
                    a=wall["area_sf"],
                )
            return (
                "{name} | Length: {l} | TOR: {tor} | Base: {base} | "
                "Wall Ht: {h} | Area: {a:.2f} sf"
            ).format(
                name=name,
                l=self._fmt_ft_arch(wall["length_ft"]),
                tor=self._fmt_ft_arch(wall["top_of_roof_ft"]),
                base=self._fmt_ft_arch(-1.0),
                h=self._fmt_ft_arch(wall["wall_height_ft"]),
                a=wall["area_sf"],
            )

        lines = [
            "Tilt Wall Takeoff (sq ft)",
            "-" * 88,
            "Dock sides: {dock_sides}".format(
                dock_sides=(
                    ", ".join(
                        side
                        for side, is_dock in [("North", bool(n.get("is_dock_side"))), ("South", bool(s.get("is_dock_side")))]
                        if is_dock
                    )
                    or "None"
                )
            ),
            _format_ns_wall_line("North", n),
            _format_ns_wall_line("South", s),
            (
                "East  | Length: {l} | Stepped by bay | Base: {base} | Area: {a:.2f} sf"
            ).format(l=self._fmt_ft_arch(e["length_ft"]), base=self._fmt_ft_arch(-1.0), a=e["area_sf"]),
            (
                "West  | Length: {l} | Stepped by bay | Base: {base} | Area: {a:.2f} sf"
            ).format(
                l=self._fmt_ft_arch(result["west_wall"]["length_ft"]),
                base=self._fmt_ft_arch(-1.0),
                a=result["west_wall"]["area_sf"],
            ),
            "-" * 88,
            "East/West stepped segments:",
        ]
        for seg in e["step_segments"]:
            lines.append(
                "  Seg {idx:>2}: Len {l} | TOR {tor} | Ht {h} | Area {a:.2f} sf".format(
                    idx=seg["segment_index"],
                    l=self._fmt_ft_arch(seg["bay_length_ft"]),
                    tor=self._fmt_ft_arch(seg["top_of_roof_ft"]),
                    h=self._fmt_ft_arch(seg["wall_height_ft"]),
                    a=seg["area_sf"],
                )
            )
        lines.extend(
            [
                "-" * 88,
                "TOTAL TILT WALL AREA: {t:.2f} sf".format(t=summary["total_area_sf"]),
            ]
        )
        self._set_tilt_results_text("\n".join(lines))
        self.redraw_tilt_wall_preview()

    def redraw_tilt_wall_preview(self):
        if not hasattr(self, "tilt_canvas"):
            return
        canvas = self.tilt_canvas
        canvas.delete("all")
        cw = max(600, canvas.winfo_width())
        ch = max(280, canvas.winfo_height())

        try:
            data = self._calculate_tilt_wall_takeoff()
        except Exception:
            canvas.create_text(
                cw / 2,
                ch / 2,
                text="Tilt wall preview unavailable.\nAdd X/Y bays and roof inputs.",
                fill=self._cv["empty_text"],
                font=("Segoe UI", 12),
                justify="center",
            )
            return

        cv = self._cv
        north = data["north_wall"]
        south = data["south_wall"]
        east = data["east_wall"]
        west = data["west_wall"]
        total_x = max(1.0, float(north["length_ft"]))
        total_y = max(1.0, float(east["length_ft"]))

        # Shared vertical scale.
        max_h = max(
            north["center_height_ft"],
            south["center_height_ft"],
            max(seg["wall_height_ft"] for seg in east["step_segments"]) if east["step_segments"] else 0.0,
        )
        max_h = max(1.0, max_h)

        # Layout: 2x2 grid of elevation panels with a clear header strip on each panel
        # so the title and the TOR labels can never collide.
        outer_pad = 16
        gutter = 14
        title_h = 22         # vertical space for "North (#### sf)" title above the wall
        wall_top_pad = 18    # space between title and the highest TOR label / wall top
        wall_bottom_pad = 24 # space below wall for "Base -X" caption
        side_pad_l = 36
        side_pad_r = 14

        panel_w = (cw - 2 * outer_pad - gutter) / 2.0
        panel_h = (ch - 2 * outer_pad - gutter) / 2.0

        def draw_panel_frame(x0, y0, width, height, title):
            # Outer outlined frame
            canvas.create_rectangle(
                x0, y0, x0 + width, y0 + height,
                outline=cv["tilt_panel_outline"], width=1,
            )
            # Title strip (titles live above the wall, not on top of TOR labels)
            canvas.create_text(
                x0 + 10, y0 + title_h / 2,
                text=title, anchor="w",
                font=("Segoe UI", 10, "bold"),
                fill=cv["tilt_title"],
            )
            # Inner wall-drawing area
            wx = x0 + side_pad_l
            wy = y0 + title_h + wall_top_pad
            ww = width - side_pad_l - side_pad_r
            wh = height - title_h - wall_top_pad - wall_bottom_pad
            return wx, wy, max(40, ww), max(30, wh)

        def y_from_height(h_ft, py, ph):
            return py + ph - (h_ft / max_h) * ph

        def draw_ns_panel(x0, y0, wall_data, side_name):
            dock_tag = "/Dock" if wall_data.get("is_dock_side") else ""
            title_text = f"{side_name}{dock_tag} ({wall_data['area_sf']:.1f} sf)"
            px, py, pw, ph = draw_panel_frame(x0, y0, panel_w, panel_h, title_text)
            wx0 = px
            wx1 = px + pw
            base_edge_y = y_from_height(0.0, py, ph)
            top_y = y_from_height(wall_data["edge_height_ft"], py, ph)

            if side_name == "South":
                fill = cv["tilt_south_fill"]
                outline = cv["tilt_south_outline"]
                tor_text = cv["tilt_south_text"]
            else:
                fill = cv["tilt_north_fill"]
                outline = cv["tilt_north_outline"]
                tor_text = cv["tilt_north_text"]

            if wall_data.get("is_dock_side"):
                total_len = max(1.0, wall_data["length_ft"])
                lx = wx0 + pw * (wall_data["left_edge_length_ft"] / total_len)
                rx = wx1 - pw * (wall_data["right_edge_length_ft"] / total_len)
                base_center_y = y_from_height(3.0, py, ph)  # -4' center vs -1' edges.
                poly = [
                    wx0, top_y,
                    wx1, top_y,
                    wx1, base_edge_y,
                    rx, base_edge_y,
                    rx, base_center_y,
                    lx, base_center_y,
                    lx, base_edge_y,
                    wx0, base_edge_y,
                ]
                canvas.create_polygon(poly, fill=fill, outline=outline)
                canvas.create_text(wx0 + 4, base_edge_y + 4, text="Base -1' edges", anchor="nw", fill=cv["tilt_base_text"], font=("Segoe UI", 8))
                canvas.create_text(lx + 4, base_center_y + 4, text="Base -4' center", anchor="nw", fill=cv["tilt_base_text"], font=("Segoe UI", 8))
            else:
                canvas.create_rectangle(wx0, top_y, wx1, base_edge_y, fill=fill, outline=outline)
                canvas.create_text(wx0 + 4, base_edge_y + 4, text="Base -1'", anchor="nw", fill=cv["tilt_base_text"], font=("Segoe UI", 8))

            # TOR label sits in the wall_top_pad strip above the wall — never overlaps the title.
            canvas.create_text(
                wx0 + 4,
                top_y - 4,
                text=f"TOR {self._fmt_ft_arch(wall_data['top_of_roof_ft'])}",
                anchor="sw",
                fill=tor_text,
                font=("Segoe UI", 8, "bold"),
            )

        draw_ns_panel(outer_pad, outer_pad, north, "North")
        draw_ns_panel(outer_pad, outer_pad + gutter + panel_h, south, "South")

        # East/West stepped panels.
        def draw_step_panel(x_panel, y_panel, title, area_sf, wall_data, side_name):
            title_text = f"{title} ({area_sf:.1f} sf)"
            px, py, pw, ph = draw_panel_frame(x_panel, y_panel, panel_w, panel_h, title_text)
            ex = px
            base_y = y_from_height(0.0, py, ph)
            if side_name == "East":
                fill = cv["tilt_east_fill"]; outline = cv["tilt_east_outline"]; tor_text = cv["tilt_east_text"]
            else:
                fill = cv["tilt_west_fill"]; outline = cv["tilt_west_outline"]; tor_text = cv["tilt_west_text"]
            for seg in wall_data["step_segments"]:
                seg_w = pw * (seg["bay_length_ft"] / total_y)
                seg_top = y_from_height(seg["wall_height_ft"], py, ph)
                canvas.create_rectangle(ex, seg_top, ex + seg_w, base_y, fill=fill, outline=outline)
                seg_mid_x = ex + seg_w / 2.0
                canvas.create_text(
                    seg_mid_x,
                    seg_top - 4,
                    text=f"TOR {self._fmt_ft_arch(seg['top_of_roof_ft'])}",
                    anchor="s",
                    fill=tor_text,
                    font=("Segoe UI", 7, "bold"),
                )
                ex += seg_w
            canvas.create_text(px + 4, base_y + 4, text="Base -1'", anchor="nw", fill=cv["tilt_base_text"], font=("Segoe UI", 8))

        draw_step_panel(outer_pad + gutter + panel_w, outer_pad, "East (Stepped)", east["area_sf"], east, "East")
        draw_step_panel(outer_pad + gutter + panel_w, outer_pad + gutter + panel_h, "West (Stepped)", west["area_sf"], west, "West")

    def redraw_roof_section(self):
        if not hasattr(self, "roof_canvas"):
            return

        canvas = self.roof_canvas
        canvas.delete("all")
        cw = max(400, canvas.winfo_width())
        ch = max(280, canvas.winfo_height())

        cv = self._cv
        profile = self._build_roof_profile_data()
        if not profile:
            canvas.create_text(
                cw / 2,
                ch / 2,
                text="Roof section unavailable.\nAdd Y bays to generate X-X section.",
                fill=cv["empty_text"],
                font=("Segoe UI", 12),
                justify="center",
            )
            self.roof_section_status_var.set("Roof section waiting for Y-bay layout.")
            return

        y_spans = profile["y_spans"]
        y_lines = profile["y_lines"]
        total_len_ft = profile["total_len_ft"]
        roof_type = profile["roof_type"]
        break_clear_height = profile["break_clear_height"]
        clear_height_ft = profile["clear_height_ft"]
        joist_seat_depth_in = float(
            profile.get("joist_seat_depth_in", profile.get("joist_depth_thickness_in", 0.0))
        )
        start_line_idx = profile["start_line_idx"]
        start_station_ft = profile["start_station_ft"]
        line_role_label = profile["line_role_label"]
        ridge_line_idx = profile["ridge_line_idx"]
        ridge_station_ft = profile["ridge_station_ft"]
        single_slope_direction = profile.get("single_slope_direction", "North")
        speed_bay_side = profile.get("speed_bay_side", "None")
        speed_rows = profile.get("speed_bay_rows", [])
        transition_lines = profile.get("speed_transition_line_indices", [])
        joist_depth_in = profile["joist_depth_in"]
        start_height_ft = profile["start_height_ft"]
        line_toj_elevations_ft = profile.get("line_toj_elevations_ft", profile["line_roof_heights"])
        allowed_depths = self._get_allowed_girder_depth_by_line_in()
        north_lb = self._is_side_fully_load_bearing("N")
        south_lb = self._is_side_fully_load_bearing("S")

        max_roof_z = max(float(v) for v in line_toj_elevations_ft) if line_toj_elevations_ft else clear_height_ft

        margin_l = 78
        margin_r = 78
        margin_t = 84
        margin_b = 80
        ground_y = ch - margin_b
        usable_w = max(120, cw - margin_l - margin_r)
        usable_h = max(120, ground_y - margin_t)
        sx_scale = usable_w / max(total_len_ft, 1.0)
        sy_scale = usable_h / max(max_roof_z + 5.0, 1.0)

        def sx(x):
            return margin_l + x * sx_scale

        def sy(z):
            return ground_y - z * sy_scale

        def draw_badge(
            x_px,
            y_px,
            text,
            fill=None,
            outline=None,
            text_fill=None,
            font=("Segoe UI", 8, "bold"),
            pad_x=5,
            pad_y=2,
            anchor="center",
        ):
            fill = fill or cv["roof_legend_fill"]
            outline = outline or cv["roof_legend_outline"]
            text_fill = text_fill or cv["roof_legend_text"]
            text_id = canvas.create_text(x_px, y_px, text=text, fill=text_fill, font=font, anchor=anchor)
            x0, y0, x1, y1 = canvas.bbox(text_id)
            rect_id = canvas.create_rectangle(
                x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y,
                fill=fill,
                outline=outline,
                width=1,
            )
            canvas.tag_lower(rect_id, text_id)
            return rect_id, text_id

        canvas.create_text(
            margin_l,
            24,
            text="Section X-X",
            anchor="w",
            fill=cv["roof_section_title"],
            font=("Segoe UI", 12, "bold"),
        )
        canvas.create_line(margin_l - 30, ground_y, cw - margin_r + 20, ground_y, fill=cv["roof_ground_line"], width=2)

        clear_line_y = sy(clear_height_ft)
        canvas.create_line(
            margin_l - 20, clear_line_y, cw - margin_r + 10, clear_line_y, fill=cv["roof_clear_line"], width=1, dash=(5, 5)
        )
        draw_badge(
            margin_l + 60,
            clear_line_y - 10,
            f"Clear Height {self._fmt_ft_arch(clear_height_ft)}",
            fill=cv["roof_chl_fill"],
            outline=cv["roof_chl_outline"],
            text_fill=cv["roof_chl_text"],
            font=("Segoe UI", 9, "bold"),
        )

        poly_points = []
        sample_count = 100
        for i in range(sample_count + 1):
            x = total_len_ft * i / sample_count
            z = self._interpolate_profile_height(x, y_lines, line_toj_elevations_ft)
            poly_points.extend([sx(x), sy(z)])
        canvas.create_line(*poly_points, fill=cv["roof_profile_line"], width=3)

        for i, x in enumerate(y_lines):
            z = line_toj_elevations_ft[i]
            line_w = 4 if i in (0, len(y_lines) - 1) else 2
            color = cv["roof_grid_line"] if i in (0, len(y_lines) - 1) else cv["roof_grid_line_int"]
            canvas.create_line(sx(x), ground_y, sx(x), sy(z), fill=color, width=line_w)

            ly = ground_y + 28
            lr = 11
            canvas.create_oval(
                sx(x) - lr, ly - lr, sx(x) + lr, ly + lr,
                fill=cv["major_oval_fill"], outline=cv["major_oval_out"],
            )
            canvas.create_text(sx(x), ly, text=axis_letter(i), font=("Segoe UI", 9, "bold"), fill=cv["roof_axis_label"])

            allowed_girder_depth_in = float(allowed_depths.get(i, (z - clear_height_ft) * 12.0))
            depth_label_y = clear_line_y - (10 + (i % 2) * 12)
            tor_label_y = max(margin_t + 10, sy(z) - (26 + (i % 3) * 9))
            if tor_label_y > depth_label_y - 8:
                tor_label_y = depth_label_y - 12

            tor_x = sx(x) + (16 if i % 2 == 0 else -16)
            tor_anchor = "w" if i % 2 == 0 else "e"
            depth_x = sx(x) + (-14 if i % 2 == 0 else 14)
            depth_anchor = "e" if i % 2 == 0 else "w"

            canvas.create_line(sx(x), sy(z), tor_x, tor_label_y + 2, fill=cv["roof_toj_outline"], width=1)
            draw_badge(
                tor_x,
                tor_label_y,
                f"TOJ {self._fmt_ft_arch(z)}",
                fill=cv["roof_toj_fill"],
                outline=cv["roof_toj_outline"],
                text_fill=cv["roof_toj_text"],
                font=("Segoe UI", 7, "bold"),
                pad_x=4,
                pad_y=1,
                anchor=tor_anchor,
            )

            hide_depth_here = (i == 0 and north_lb) or (i == (len(y_lines) - 1) and south_lb)
            if not hide_depth_here:
                draw_badge(
                    depth_x,
                    depth_label_y,
                    f"{allowed_girder_depth_in:.1f} in",
                    fill=cv["roof_depth_fill"],
                    outline=cv["roof_depth_outline"],
                    text_fill=cv["roof_depth_text"],
                    font=("Segoe UI", 8, "bold"),
                    pad_x=4,
                    pad_y=1,
                    anchor=depth_anchor,
                )

            if i in transition_lines:
                canvas.create_line(sx(x), margin_t - 6, sx(x), ground_y + 8, fill=cv["roof_trans_outline"], dash=(4, 4), width=2)
                draw_badge(
                    sx(x) + 10,
                    margin_t - 18,
                    f"Transition {axis_letter(i)}",
                    fill=cv["roof_trans_fill"],
                    outline=cv["roof_trans_outline"],
                    text_fill=cv["roof_trans_text"],
                    font=("Segoe UI", 8, "bold"),
                )

        for i, span in enumerate(y_spans):
            x_mid = (y_lines[i] + y_lines[i + 1]) / 2.0
            canvas.create_text(
                sx(x_mid),
                ground_y + 52,
                text=self._fmt_ft_arch(span),
                fill=cv["roof_label_text"],
                font=("Segoe UI", 9),
            )

        transition_text = ", ".join(axis_letter(i) for i in transition_lines) if transition_lines else "None"
        speed_row_text = (
            ", ".join(f"{axis_letter(i)}-{axis_letter(i + 1)}" for i in speed_rows) if speed_rows else "None"
        )
        joist_note = (
            f"{joist_depth_in:.2f} in"
            if joist_depth_in > 0
            else "0.00 in (assign joist depths near transition/main rows)"
        )
        self.roof_section_status_var.set(
            "Type: {rtype} | Rise: {rise_dir} | Break CH: {break_ch} | Speed Rows: {speed_rows} | "
            "Transitions: {trans} | Start: {start_line} | Ridge: {ridge_line} | Speed Side: {speed_side} | "
            "Slope: {slope_note} | Start TOJ/BMD: {start}".format(
                rtype=roof_type,
                rise_dir=single_slope_direction if str(roof_type).strip().lower() == "single slope" else "N/A",
                break_ch="Yes" if break_clear_height else "No",
                speed_rows=speed_row_text,
                trans=transition_text,
                start_line=axis_letter(start_line_idx),
                ridge_line=axis_letter(ridge_line_idx),
                speed_side=speed_bay_side,
                slope_note=("1/4 in/ft (main) and 1/2 in/ft in speed bay" if break_clear_height else "1/4 in/ft"),
                start=self._fmt_ft_arch(start_height_ft),
            )
        )

        info_text = (
            f"CH {self._fmt_ft_arch(clear_height_ft)}\n"
            f"Joist {joist_note}\n"
            f"Seat {joist_seat_depth_in:.2f} in"
        )
        info_x = cw - margin_r - 78
        info_y = margin_t + 6
        draw_badge(
            info_x,
            info_y,
            info_text,
            fill=cv["roof_legend_fill"],
            outline=cv["roof_legend_outline"],
            text_fill=cv["roof_legend_text"],
            font=("Segoe UI", 8),
            pad_x=7,
            pad_y=5,
        )
        self.redraw_tilt_wall_preview()

    def _make_scoped_group_iid(self, scope: str, group_id: str):
        scope_token = "mezz" if str(scope or "").strip().lower().startswith("mezz") else "main"
        return f"{scope_token}::{str(group_id)}"

    def _parse_scoped_group_iid(self, iid: str):
        token = str(iid or "")
        if "::" not in token:
            return "main", token
        scope, group_id = token.split("::", 1)
        scope = "mezz" if str(scope).strip().lower().startswith("mezz") else "main"
        return scope, group_id

    def _refresh_joist_selection_table(self):
        if not hasattr(self, "joist_select_tree"):
            return

        main_groups = list((self.last_joist_result or {}).get("joist_demand_groups", []))
        mezz_groups = list((self.last_mezz_result or {}).get("mezzanine_joist_demand_groups", []))
        if not main_groups and not mezz_groups:
            self.joist_select_tree.delete(*self.joist_select_tree.get_children())
            self.total_joist_weight_var.set(
                "Total assigned joist weight: 0.00 lbs "
                "(main building only; includes shared-edge dedupe and perimeter LB wall rules)"
            )
            return

        main_valid_group_ids = {str(group.get("group_id", "")) for group in main_groups}
        self.joist_selection_by_group = {
            group_id: item
            for group_id, item in self.joist_selection_by_group.items()
            if str(group_id) in main_valid_group_ids
        }
        mezz_valid_group_ids = {str(group.get("group_id", "")) for group in mezz_groups}
        self.mezz_joist_selection_by_group = {
            group_id: item
            for group_id, item in self.mezz_joist_selection_by_group.items()
            if str(group_id) in mezz_valid_group_ids
        }

        self.joist_select_tree.delete(*self.joist_select_tree.get_children())

        main_assigned_weight_lbs = 0.0

        def insert_rows(scope_name, groups, selection_map):
            nonlocal main_assigned_weight_lbs
            for group in groups:
                group_id = str(group.get("group_id", ""))
                tree_iid = self._make_scoped_group_iid(scope_name, group_id)
                assigned = selection_map.get(group_id)
                adjusted_count = int(group.get("count", 0) or 0)
                requirement_text = str(group.get("requirement_text", "") or "")
                if requirement_text:
                    requirement_text = " ".join(requirement_text.split())
                else:
                    requirement_text = (
                        f"{adjusted_count} x {scope_name.title()} Joists require "
                        f"{float(group.get('required_capacity_plf', 0.0) or 0.0):.2f} plf."
                    )
                designation = ""
                depth = ""
                wt_plf = ""
                group_wt = ""
                if assigned:
                    designation = str(assigned.get("designation", "") or "")
                    depth = f"{float(assigned.get('depth_in', 0.0) or 0.0):.2f}"
                    wt_plf = f"{float(assigned.get('weight_plf', 0.0) or 0.0):.2f}"
                    adjusted_span_ft = max(0.0, float(group.get("total_span_ft", 0.0) or 0.0))
                    weight_lbs = float(assigned.get("weight_plf", 0.0) or 0.0) * adjusted_span_ft
                    group_wt = f"{weight_lbs:.2f}"
                    if scope_name == "main":
                        main_assigned_weight_lbs += weight_lbs

                self.joist_select_tree.insert(
                    "",
                    "end",
                    iid=tree_iid,
                    tags=(scope_name,),
                    values=(
                        "Main" if scope_name == "main" else "Mezz",
                        requirement_text,
                        adjusted_count,
                        f"{float(group.get('required_capacity_plf', 0.0) or 0.0):.2f}",
                        self._fmt_ft_arch(float(group.get("required_length_ft", 0.0) or 0.0)),
                        designation,
                        depth,
                        wt_plf,
                        group_wt,
                    ),
                )

        insert_rows("main", main_groups, self.joist_selection_by_group)
        insert_rows("mezz", mezz_groups, self.mezz_joist_selection_by_group)

        self.total_joist_weight_var.set(
            f"Total assigned joist weight: {main_assigned_weight_lbs:.2f} lbs "
            "(main building only; includes shared-edge dedupe and perimeter LB wall rules)"
        )

    def assign_selected_joist(self):
        has_main = bool((self.last_joist_result or {}).get("joist_demand_groups"))
        has_mezz = bool((self.last_mezz_result or {}).get("mezzanine_joist_demand_groups"))
        if not has_main and not has_mezz:
            messagebox.showerror("No calculations", "Run Calculate Joists first.")
            return
        selected = self.joist_select_tree.selection()
        if not selected:
            messagebox.showerror("Selection required", "Select a requirement row in the joist selection table.")
            return

        try:
            depth_in = float(self.selected_depth_var.get())
            weight_plf = float(self.selected_weight_plf_var.get())
            if depth_in <= 0 or weight_plf <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid joist selection", "Depth and weight must be positive numeric values.")
            return

        scope_name, group_id = self._parse_scoped_group_iid(selected[0])
        target_map = self.mezz_joist_selection_by_group if scope_name == "mezz" else self.joist_selection_by_group
        prev = target_map.get(group_id, {})
        target_map[group_id] = {
            "depth_in": depth_in,
            "weight_plf": weight_plf,
            "designation": str(prev.get("designation", "") or ""),
        }
        self._refresh_joist_selection_table()
        self.redraw_roof_section()

    def clear_selected_joists(self):
        self.joist_selection_by_group = {}
        self.mezz_joist_selection_by_group = {}
        self._refresh_joist_selection_table()
        self.redraw_roof_section()

    def _coerce_catalog_number(self, token: str):
        token = str(token or "").strip().replace(",", "")
        if not token:
            return None
        if token in {"'6", "’6", "`6"}:
            token = "9.6"
        token = token.replace("O", "0").replace("o", "0")
        if token.startswith("."):
            token = "0" + token
        if token.endswith("."):
            token = token[:-1]
        if not re.fullmatch(r"-?\d+(\.\d+)?", token):
            return None
        try:
            return float(token)
        except ValueError:
            return None

    def _catalog_search_dirs(self):
        dirs = []
        try:
            dirs.append(Path.cwd())
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            try:
                dirs.append(Path(sys.executable).resolve().parent)
            except Exception:
                pass
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                try:
                    dirs.append(Path(meipass))
                except Exception:
                    pass
        try:
            dirs.append(Path(__file__).resolve().parent)
        except Exception:
            pass
        unique_dirs = []
        seen = set()
        for item in dirs:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            unique_dirs.append(item)
        return unique_dirs

    def _find_girder_catalog_path(self):
        for base_dir in self._catalog_search_dirs():
            preferred = base_dir / "Expanded Vulcraft Joist Girder Catalog.xlsx"
            if preferred.exists():
                return preferred
        for base_dir in self._catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            # Prefer filenames with "girder" if available.
            girder_candidates = [p for p in candidates if "girder" in p.name.lower()]
            if girder_candidates:
                return girder_candidates[0]
            return candidates[0]
        return None

    def _parse_joist_space_descriptor(self, space_text: str):
        text = str(space_text or "").replace("\n", " ").strip()
        n_match = re.search(r"(\d+)\s*[Nn]", text)
        s_match = re.search(r"@\s*([0-9]+(?:\.[0-9]+)?)", text)
        joist_n = int(n_match.group(1)) if n_match else None
        spacing_ft = float(s_match.group(1)) if s_match else None
        return joist_n, spacing_ft

    def _parse_girder_catalog_excel(self, excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        load_header_row = None
        load_col_start = None
        load_values = []
        scan_max_row = min(40, ws.max_row)
        for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=scan_max_row, values_only=True), start=1):
            row = list(row)
            for c_idx, value in enumerate(row, start=1):
                num = self._coerce_catalog_number(value)
                if num is None:
                    continue
                if c_idx >= 5 and 1 <= num <= 100:
                    trial = []
                    j = c_idx
                    while j <= len(row):
                        v = self._coerce_catalog_number(row[j - 1])
                        if v is None:
                            break
                        if not (1 <= v <= 100):
                            break
                        trial.append(float(v))
                        j += 1
                    if len(trial) >= 4:
                        load_header_row = r_idx
                        load_col_start = c_idx
                        load_values = trial
                        break
            if load_header_row is not None:
                break

        if load_header_row is None:
            raise InputValidationError("Could not locate girder load header row in catalog Excel.")

        rows = []
        current_span = None
        current_space = None
        for row in ws.iter_rows(min_row=load_header_row + 1, max_row=ws.max_row, values_only=True):
            row = list(row)
            span_num = self._coerce_catalog_number(row[1] if len(row) >= 2 else None)
            if span_num is not None and 10 <= span_num <= 400:
                current_span = round(float(span_num), 3)

            space_txt = row[2] if len(row) >= 3 else None
            if isinstance(space_txt, str) and space_txt.strip():
                current_space = space_txt.strip()

            depth_num = self._coerce_catalog_number(row[3] if len(row) >= 4 else None)
            if current_span is None or depth_num is None:
                continue
            depth_in = round(float(depth_num), 3)
            if depth_in <= 0:
                continue
            joist_n, joist_spacing_ft = self._parse_joist_space_descriptor(current_space or "")
            if joist_n is None:
                continue

            for offset, load_kips in enumerate(load_values):
                col_idx = load_col_start + offset
                if col_idx - 1 >= len(row):
                    continue
                wt_num = self._coerce_catalog_number(row[col_idx - 1])
                if wt_num is None or wt_num <= 0:
                    continue
                rows.append(
                    {
                        "span_ft": current_span,
                        "depth_in": depth_in,
                        "panel_load_kips": round(float(load_kips), 3),
                        "weight_plf": round(float(wt_num), 3),
                        "joist_spaces": current_space or "",
                        "joist_n": joist_n,
                        "joist_spacing_ft": joist_spacing_ft,
                    }
                )

        if not rows:
            raise InputValidationError(f"No usable catalog rows found in {excel_path.name}.")
        return rows

    def _build_girder_catalog_index(self, rows):
        # Index by exact span (2 decimals) and joist N.
        # Each bucket stores depth->sorted(load_kips, min_weight_plf) curve.
        index = {}
        buckets = {}
        for row in rows:
            span_key = round(float(row["span_ft"]), 2)
            joist_n = int(row.get("joist_n") or 0)
            if joist_n <= 0:
                continue
            depth = round(float(row["depth_in"]), 3)
            load_kips = round(float(row["panel_load_kips"]), 3)
            weight_plf = float(row["weight_plf"])
            key = (span_key, joist_n, depth)
            load_map = buckets.setdefault(key, {})
            prev = load_map.get(load_kips)
            if prev is None or weight_plf < prev:
                load_map[load_kips] = weight_plf

        for (span_key, joist_n, depth), load_map in buckets.items():
            curve = sorted(load_map.items(), key=lambda x: x[0])
            index.setdefault((span_key, joist_n), {})[depth] = curve
        return index

    def _load_girder_catalog_rows(self):
        if self.girder_catalog_rows is not None:
            if self.girder_catalog_index is None:
                self.girder_catalog_index = self._build_girder_catalog_index(self.girder_catalog_rows)
            return self.girder_catalog_rows

        excel_path = self._find_girder_catalog_path()
        if excel_path is None or not excel_path.exists():
            raise InputValidationError("No girder catalog Excel file found in the current folder.")

        rows = self._parse_girder_catalog_excel(excel_path)
        dedup = {}
        for row in rows:
            key = (
                round(float(row["span_ft"]), 3),
                int(row["joist_n"]) if row.get("joist_n") is not None else None,
                round(float(row["depth_in"]), 3),
                round(float(row["panel_load_kips"]), 3),
            )
            current = dedup.get(key)
            if current is None or float(row["weight_plf"]) < float(current["weight_plf"]):
                dedup[key] = row
        rows = list(dedup.values())
        self.girder_catalog_rows = rows
        self.girder_catalog_index = self._build_girder_catalog_index(rows)
        self.girder_catalog_source = str(excel_path)
        return self.girder_catalog_rows

    def _parse_hss_depth_from_designation(self, designation: str):
        text = str(designation or "").strip().lower()
        if text.startswith("hss"):
            text = text[3:]
        match = re.match(r"^(\d+(?:\.\d+)?)x", text)
        if not match:
            return None
        try:
            depth_in = float(match.group(1))
        except ValueError:
            return None
        if depth_in <= 0:
            return None
        return round(depth_in, 3)

    def _find_column_catalog_path(self):
        for base_dir in self._catalog_search_dirs():
            preferred = base_dir / "Column Table.xlsx"
            if preferred.exists():
                return preferred
        for base_dir in self._catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            column_candidates = [p for p in candidates if "column" in p.name.lower()]
            if column_candidates:
                return column_candidates[0]
            return candidates[0]
        return None

    def _parse_column_catalog_excel(self, excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        # Expected layout:
        # - Row 2: designation in odd columns (3,5,...)
        # - Row 3: weight at same designation column
        # - Row 15: ASD/LRFD headers in paired columns
        # - Row 16+: KL table with KL in col 1 and ASD capacities in ASD columns
        row2 = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
        row3 = list(ws.iter_rows(min_row=3, max_row=3, values_only=True))[0]
        row15 = list(ws.iter_rows(min_row=15, max_row=15, values_only=True))[0]

        section_cols = []
        for col_idx, raw_name in enumerate(row2, start=1):
            name = str(raw_name or "").strip()
            if not name:
                continue
            if not re.search(r"^\d+(?:\.\d+)?x\d+(?:\.\d+)?x\d+/\d+$", name):
                continue
            asd_col = col_idx - 1
            if asd_col < 2:
                continue
            asd_header = str(row15[asd_col - 1] if asd_col - 1 < len(row15) else "").strip().upper()
            if asd_header != "ASD":
                continue
            weight = self._coerce_catalog_number(row3[col_idx - 1] if col_idx - 1 < len(row3) else None)
            if weight is None or weight <= 0:
                continue
            normalized_name = name if name.upper().startswith("HSS") else f"HSS{name}"
            section_cols.append(
                {
                    "designation": normalized_name,
                    "asd_col_idx": asd_col,
                    "depth_in": self._parse_hss_depth_from_designation(name),
                    "weight_plf": round(float(weight), 3),
                }
            )

        if not section_cols:
            raise InputValidationError(f"Could not parse section columns from {excel_path.name}.")

        rows = []
        for row in ws.iter_rows(min_row=17, max_row=ws.max_row, values_only=True):
            kl_val = self._coerce_catalog_number(row[0] if len(row) >= 1 else None)
            if kl_val is None:
                continue
            kl_ft = int(round(float(kl_val)))
            if kl_ft < 1:
                continue
            for section in section_cols:
                asd_col_idx = section["asd_col_idx"]
                if asd_col_idx - 1 >= len(row):
                    continue
                asd_kips = self._coerce_catalog_number(row[asd_col_idx - 1])
                if asd_kips is None or asd_kips <= 0:
                    continue
                rows.append(
                    {
                        "kl_ft": kl_ft,
                        "designation": section["designation"],
                        "depth_in": section["depth_in"] if section["depth_in"] is not None else 0.0,
                        "weight_plf": section["weight_plf"],
                        "asd_capacity_kips": round(float(asd_kips), 3),
                    }
                )

        if not rows:
            raise InputValidationError(f"No usable ASD column rows found in {excel_path.name}.")

        # Deduplicate by (KL, designation) and keep the lighter weight entry.
        dedup = {}
        for item in rows:
            key = (item["kl_ft"], item["designation"])
            current = dedup.get(key)
            if current is None or float(item["weight_plf"]) < float(current["weight_plf"]):
                dedup[key] = item
        return list(dedup.values())

    def _load_column_catalog_rows(self):
        if self.column_catalog_rows is not None:
            return self.column_catalog_rows

        excel_path = self._find_column_catalog_path()
        if excel_path is None or not excel_path.exists():
            raise InputValidationError("No column catalog Excel file found in the current folder.")

        self.column_catalog_rows = self._parse_column_catalog_excel(excel_path)
        self.column_catalog_source = str(excel_path)
        return self.column_catalog_rows

    def _find_joist_catalog_excel_path(self):
        preferred_names = [
            "Joist Table 2.xlsx",
            "Joist Table2.xlsx",
            "Joist Table.xlsx",
        ]
        for base_dir in self._catalog_search_dirs():
            for name in preferred_names:
                candidate = base_dir / name
                if candidate.exists():
                    return candidate
        for base_dir in self._catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            joist_candidates = [
                p
                for p in candidates
                if "joist" in p.name.lower() and "girder" not in p.name.lower()
            ]
            if joist_candidates:
                joist_candidates.sort(key=lambda p: ("table 2" not in p.name.lower(), p.name.lower()))
                return joist_candidates[0]
        return None

    def _find_mezz_joist_catalog_excel_path(self):
        preferred_names = [
            "LH Joist Table.xlsx",
            "LH Joist Table 2.xlsx",
            "LH Joist Table2.xlsx",
            "LHJoistTable.xlsx",
            "LH Table.xlsx",
        ]
        for base_dir in self._catalog_search_dirs():
            for name in preferred_names:
                candidate = base_dir / name
                if candidate.exists():
                    return candidate
        for base_dir in self._catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            lh_candidates = [
                p
                for p in candidates
                if ("joist" in p.name.lower() and "lh" in p.name.lower() and "girder" not in p.name.lower())
            ]
            if lh_candidates:
                lh_candidates.sort(key=lambda p: p.name.lower())
                return lh_candidates[0]
        return None

    def _parse_joist_catalog_excel(self, excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        span_header_row_idx = None
        designation_cols = []
        desig_pattern = re.compile(r"^\d{2,3}(?:K|LH)\d{1,2}$", flags=re.IGNORECASE)
        for r_idx in range(1, min(100, ws.max_row) + 1):
            row = list(ws.iter_rows(min_row=r_idx, max_row=r_idx, values_only=True))[0]
            first = str(row[0] or "").strip().lower()
            if "span" not in first:
                continue
            for c_idx, val in enumerate(row, start=1):
                txt = str(val or "").strip()
                if desig_pattern.fullmatch(txt):
                    designation_cols.append((c_idx, txt))
            if designation_cols:
                span_header_row_idx = r_idx
                break

        if span_header_row_idx is None:
            raise InputValidationError(f"Could not locate joist designation header row in {excel_path.name}.")

        depth_row = list(ws.iter_rows(min_row=span_header_row_idx + 1, max_row=span_header_row_idx + 1, values_only=True))[0]
        wt_row = list(ws.iter_rows(min_row=span_header_row_idx + 2, max_row=span_header_row_idx + 2, values_only=True))[0]

        cols = []
        for c_idx, designation in designation_cols:
            depth_val = self._coerce_catalog_number(depth_row[c_idx - 1] if c_idx - 1 < len(depth_row) else None)
            wt_val = self._coerce_catalog_number(wt_row[c_idx - 1] if c_idx - 1 < len(wt_row) else None)
            if depth_val is None or wt_val is None:
                continue
            if depth_val <= 0 or wt_val <= 0:
                continue
            cols.append(
                {
                    "col_idx": c_idx,
                    "designation": designation,
                    "depth_in": round(float(depth_val), 3),
                    "weight_plf": round(float(wt_val), 3),
                }
            )

        if not cols:
            raise InputValidationError(f"No usable joist designation columns found in {excel_path.name}.")

        rows = []
        for r_idx in range(span_header_row_idx + 3, ws.max_row + 1):
            row = list(ws.iter_rows(min_row=r_idx, max_row=r_idx, values_only=True))[0]
            span_val = self._coerce_catalog_number(row[0] if len(row) >= 1 else None)
            if span_val is None:
                continue
            span_ft = round(float(span_val), 3)
            if span_ft < 10 or span_ft > 150:
                continue

            for col in cols:
                c_idx = col["col_idx"]
                cap_val = self._coerce_catalog_number(row[c_idx - 1] if c_idx - 1 < len(row) else None)
                if cap_val is None or cap_val <= 0:
                    continue
                rows.append(
                    {
                        "designation": col["designation"],
                        "depth_in": col["depth_in"],
                        "weight_plf": col["weight_plf"],
                        "span_ft": span_ft,
                        "capacity_plf": round(float(cap_val), 3),
                    }
                )

        if not rows:
            raise InputValidationError(f"No joist capacity rows found in {excel_path.name}.")
        return rows

    def _extract_joist_catalog_page_table(self, lines):
        desig_pattern = re.compile(r"^\d{2,3}(?:K|LH)\d{1,2}$", flags=re.IGNORECASE)
        designations = []
        first_desig_idx = None
        for i, txt in enumerate(lines):
            if desig_pattern.fullmatch(txt):
                first_desig_idx = i
                break
        if first_desig_idx is None:
            return {"designations": [], "depths": [], "weights": [], "span_rows": {}}

        i = first_desig_idx
        while i < len(lines):
            txt = lines[i]
            if "Designation" in txt or "Depth" in txt:
                break
            if desig_pattern.fullmatch(txt):
                designations.append(txt)
            i += 1
        if not designations:
            return {"designations": [], "depths": [], "weights": [], "span_rows": {}}
        n_cols = len(designations)

        depth_idx = next((idx for idx, txt in enumerate(lines) if "Depth" in txt), -1)
        depths = []
        if depth_idx >= 0:
            for txt in lines[depth_idx + 1 :]:
                num = self._coerce_catalog_number(txt)
                if num is None:
                    continue
                if 8 <= num <= 60:
                    depths.append(float(round(num, 2)))
                    if len(depths) >= n_cols:
                        break

        wt_idx = next((idx for idx, txt in enumerate(lines) if "Approx.Wt" in txt), -1)
        weights = []
        if wt_idx >= 0:
            for txt in lines[wt_idx + 1 :]:
                num = self._coerce_catalog_number(txt)
                if num is None:
                    continue
                if 1 <= num <= 40:
                    weights.append(float(round(num, 3)))
                    if len(weights) >= n_cols:
                        break

        span_idx = next((idx for idx, txt in enumerate(lines) if "Span" in txt and "ft" in txt), -1)
        span_rows = {}
        if span_idx >= 0:
            i = span_idx + 1
            while i < len(lines):
                span_num = self._coerce_catalog_number(lines[i])
                if span_num is None or abs(span_num - round(span_num)) > 1e-9:
                    i += 1
                    continue
                span_ft = int(round(span_num))
                if span_ft < 10 or span_ft > 120:
                    i += 1
                    continue

                vals = []
                j = i + 1
                while j < len(lines) and len(vals) < n_cols:
                    nxt = self._coerce_catalog_number(lines[j])
                    if nxt is not None and 0 < nxt <= 1000:
                        # Skip likely row-span markers while collecting capacities.
                        if (
                            abs(nxt - round(nxt)) <= 1e-9
                            and 10 <= int(round(nxt)) <= 120
                            and 0 < len(vals) < n_cols
                            and nxt < 130
                        ):
                            j += 1
                            continue
                        vals.append(float(nxt))
                    j += 1

                if len(vals) == n_cols:
                    span_rows[span_ft] = [float(round(v, 3)) for v in vals]
                i += 1

        return {
            "designations": designations,
            "depths": depths,
            "weights": weights,
            "span_rows": span_rows,
        }

    def _parse_joist_catalog_pdf(self, pdf_path: Path):
        try:
            import numpy as np
            import pypdfium2 as pdfium
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:
            raise InputValidationError(
                "Catalog OCR dependencies are missing. Install `pypdfium2` and `rapidocr-onnxruntime`."
            ) from exc

        doc = pdfium.PdfDocument(str(pdf_path))
        ocr = RapidOCR()
        scales = [3.0]
        page_tables = []
        for page_idx in range(len(doc)):
            best = None
            best_score = -1
            for scale in scales:
                page = doc[page_idx]
                img = np.array(page.render(scale=scale).to_pil())
                result, _ = ocr(img)
                lines = [r[1].strip() for r in (result or []) if r[1].strip()]
                table = self._extract_joist_catalog_page_table(lines)
                score = len(table["designations"]) * max(1, len(table["span_rows"]))
                if score > best_score:
                    best_score = score
                    best = table
            if best:
                page_tables.append(best)

        rows = []
        for table in page_tables:
            designations = table["designations"]
            depths = table["depths"]
            weights = table["weights"]
            span_rows = table["span_rows"]
            n_cols = min(len(designations), len(depths), len(weights))
            if n_cols <= 0 or not span_rows:
                continue
            for span_ft, caps in span_rows.items():
                for col_idx in range(min(n_cols, len(caps))):
                    capacity_plf = float(caps[col_idx])
                    if capacity_plf <= 0:
                        continue
                    rows.append(
                        {
                            "designation": designations[col_idx],
                            "depth_in": float(depths[col_idx]),
                            "weight_plf": float(weights[col_idx]),
                            "span_ft": float(span_ft),
                            "capacity_plf": capacity_plf,
                        }
                    )

        # Deduplicate possible OCR duplicates across pages/scales.
        dedup = {}
        for item in rows:
            key = (
                item["designation"],
                round(item["depth_in"], 3),
                round(item["weight_plf"], 3),
                round(item["span_ft"], 3),
            )
            current = dedup.get(key)
            if current is None or item["capacity_plf"] > current["capacity_plf"]:
                dedup[key] = item
        return list(dedup.values())

    def _load_joist_catalog_rows(self):
        if self.joist_catalog_rows is not None:
            return self.joist_catalog_rows

        excel_path = self._find_joist_catalog_excel_path()
        if excel_path is not None and excel_path.exists():
            rows = self._parse_joist_catalog_excel(excel_path)
            self.joist_catalog_rows = rows
            self.joist_catalog_source = str(excel_path)
            return self.joist_catalog_rows

        # Fallback to OCR-based PDF parsing if Excel table is unavailable.
        pdf_path = None
        for base_dir in self._catalog_search_dirs():
            candidate = base_dir / "Joist Catalog.pdf"
            if candidate.exists():
                pdf_path = candidate
                break
        if pdf_path is None:
            raise InputValidationError(
                "No Joist Excel table or Joist Catalog.pdf found in working/app folder."
            )
        rows = self._parse_joist_catalog_pdf(pdf_path)
        if not rows:
            raise InputValidationError("No joist rows were parsed from Joist Catalog.pdf.")
        self.joist_catalog_rows = rows
        self.joist_catalog_source = str(pdf_path)
        return self.joist_catalog_rows

    def _load_mezz_joist_catalog_rows(self):
        if self.mezz_joist_catalog_rows is not None:
            return self.mezz_joist_catalog_rows

        excel_path = self._find_mezz_joist_catalog_excel_path()
        if excel_path is None or not excel_path.exists():
            raise InputValidationError(
                "No LH Joist Table Excel found for mezzanine joist auto-assignment. "
                "Expected a file like 'LH Joist Table.xlsx' in the working/app folder."
            )

        rows = self._parse_joist_catalog_excel(excel_path)
        self.mezz_joist_catalog_rows = rows
        self.mezz_joist_catalog_source = str(excel_path)
        return self.mezz_joist_catalog_rows

    def _estimate_value_by_span_points(self, span_points, req_span_ft: float, tol: float = 0.01):
        """
        Estimate a value at a requested span using tiered logic:
        exact -> interpolate -> extrapolate -> single-point fallback.
        span_points: iterable[(span_ft, value)] sorted or unsorted.
        Returns: (estimated_value_or_none, tier_name_or_none)
        """
        points = sorted((float(s), float(v)) for s, v in (span_points or []))
        if not points:
            return None, None

        for span_ft, value in points:
            if abs(span_ft - req_span_ft) <= tol:
                return float(value), "exact"

        if len(points) == 1:
            return float(points[0][1]), "single"

        def lin(x, x0, y0, x1, y1):
            if abs(x1 - x0) <= 1e-12:
                return float(max(y0, y1))
            return float(y0 + ((x - x0) / (x1 - x0)) * (y1 - y0))

        if req_span_ft < points[0][0]:
            x0, y0 = points[0]
            x1, y1 = points[1]
            return float(lin(req_span_ft, x0, y0, x1, y1)), "extrapolate"

        if req_span_ft > points[-1][0]:
            x0, y0 = points[-2]
            x1, y1 = points[-1]
            return float(lin(req_span_ft, x0, y0, x1, y1)), "extrapolate"

        for i in range(1, len(points)):
            x1, y1 = points[i]
            if req_span_ft <= x1 + tol:
                x0, y0 = points[i - 1]
                return float(lin(req_span_ft, x0, y0, x1, y1)), "interpolate"

        return None, None

    def _build_joist_designation_index(self, catalog_rows):
        index = {}
        for row in catalog_rows or []:
            designation = str(row.get("designation", "")).strip()
            if not designation:
                continue
            span_ft = float(row.get("span_ft", 0.0))
            capacity_plf = float(row.get("capacity_plf", 0.0))
            depth_in = float(row.get("depth_in", 0.0))
            weight_plf = float(row.get("weight_plf", 0.0))
            if span_ft <= 0 or capacity_plf <= 0 or depth_in <= 0 or weight_plf <= 0:
                continue

            entry = index.setdefault(
                designation,
                {"designation": designation, "depth_in": depth_in, "weight_plf": weight_plf, "span_caps": {}},
            )
            # Keep the lightest/deepest metadata stable for this designation.
            if weight_plf < float(entry["weight_plf"]) - 1e-9:
                entry["weight_plf"] = weight_plf
                entry["depth_in"] = depth_in
            span_key = round(span_ft, 3)
            prev_cap = entry["span_caps"].get(span_key)
            if prev_cap is None or capacity_plf > prev_cap:
                entry["span_caps"][span_key] = capacity_plf
        return index

    def _compute_joist_auto_assignments(self, groups, catalog_rows, prefer_lightest_over_tier: bool = False):
        assignments = {}
        missing = []
        by_designation = self._build_joist_designation_index(catalog_rows)
        tier_rank = {"exact": 0, "interpolate": 1, "extrapolate": 2, "single": 3}

        for group in groups:
            req_capacity = float(group["required_capacity_plf"])
            req_length = round(float(group.get("required_length_ft", 0.0)), 2)
            candidates_by_tier = {name: [] for name in tier_rank}
            for designation, item in by_designation.items():
                span_caps = item.get("span_caps", {})
                if not span_caps:
                    continue
                est_capacity, tier = self._estimate_value_by_span_points(
                    list(span_caps.items()), req_length, tol=0.01
                )
                if est_capacity is None or tier not in tier_rank:
                    continue
                est_capacity = max(0.0, float(est_capacity))
                if est_capacity + 1e-9 < req_capacity:
                    continue
                candidates_by_tier[tier].append(
                    {
                        "designation": designation,
                        "depth_in": float(item["depth_in"]),
                        "weight_plf": float(item["weight_plf"]),
                        "estimated_capacity_plf": est_capacity,
                        "tier": tier,
                    }
                )

            tier_candidates = []
            if prefer_lightest_over_tier:
                for tier_name in ("exact", "interpolate", "extrapolate", "single"):
                    tier_candidates.extend(candidates_by_tier[tier_name])
            else:
                for tier_name in ("exact", "interpolate", "extrapolate", "single"):
                    if candidates_by_tier[tier_name]:
                        tier_candidates = candidates_by_tier[tier_name]
                        break

            if not tier_candidates:
                missing.append(f"{req_capacity:.2f} plf @ {self._fmt_ft_arch(req_length)}")
                continue

            best = min(
                tier_candidates,
                key=lambda r: (
                    float(r["weight_plf"]),
                    float(r["depth_in"]),
                    str(r["designation"]),
                    tier_rank.get(str(r.get("tier", "")), 99),
                ),
            )
            assignments[group["group_id"]] = {
                "depth_in": float(best["depth_in"]),
                "weight_plf": float(best["weight_plf"]),
                "designation": str(best["designation"]),
            }
        return assignments, missing

    def _compute_main_joist_assignments_with_lh_fallback(self, main_groups, main_catalog_rows):
        main_assignments, _main_missing = self._compute_joist_auto_assignments(main_groups, main_catalog_rows)
        unresolved = [
            group for group in (main_groups or [])
            if str(group.get("group_id", "")) not in main_assignments
        ]
        fallback_assigned_count = 0
        fallback_source = ""
        fallback_error = ""
        if unresolved:
            try:
                lh_rows = self._load_mezz_joist_catalog_rows()
                fallback_source = str(self.mezz_joist_catalog_source or "")
                lh_assignments, _lh_missing = self._compute_joist_auto_assignments(
                    unresolved, lh_rows, prefer_lightest_over_tier=True
                )
                for gid, item in lh_assignments.items():
                    merged = dict(item or {})
                    merged["catalog_source"] = "LH fallback"
                    main_assignments[gid] = merged
                fallback_assigned_count = len(lh_assignments)
            except InputValidationError as exc:
                fallback_error = str(exc)

        still_unresolved = [
            group for group in (main_groups or [])
            if str(group.get("group_id", "")) not in main_assignments
        ]
        missing = [
            f"{float(group.get('required_capacity_plf', 0.0) or 0.0):.2f} plf @ "
            f"{self._fmt_ft_arch(float(group.get('required_length_ft', 0.0) or 0.0))}"
            for group in still_unresolved
        ]
        return main_assignments, missing, int(fallback_assigned_count), str(fallback_source), str(fallback_error)

    def auto_assign_joists_from_catalog(self):
        if not self.last_joist_result:
            self.calculate_joists()
            if not self.last_joist_result:
                return

        try:
            catalog_rows = self._load_joist_catalog_rows()
        except InputValidationError as exc:
            messagebox.showerror("Catalog error", str(exc))
            return

        main_groups = list((self.last_joist_result or {}).get("joist_demand_groups", []))
        (
            main_assignments,
            main_missing,
            main_fallback_assigned,
            main_fallback_source,
            main_fallback_error,
        ) = self._compute_main_joist_assignments_with_lh_fallback(main_groups, catalog_rows)
        self.joist_selection_by_group.update(main_assignments)

        mezz_groups = []
        mezz_assignments = {}
        mezz_missing = []
        mezz_catalog_source = ""
        if bool(self.mezzanine_enabled_var.get()) and bool(self.mezz_zones):
            mezz_result = self._get_mezz_result_for_tab_display()
            if isinstance(mezz_result, dict) and "_error" in mezz_result:
                messagebox.showwarning(
                    "Mezzanine warning",
                    f"Main joists were auto-assigned, but mezzanine could not be calculated:\n{mezz_result.get('_error')}",
                )
            else:
                mezz_groups = list((self.last_mezz_result or {}).get("mezzanine_joist_demand_groups", []))
                if mezz_groups:
                    try:
                        mezz_catalog_rows = self._load_mezz_joist_catalog_rows()
                        mezz_catalog_source = str(self.mezz_joist_catalog_source or "")
                        mezz_assignments, mezz_missing = self._compute_joist_auto_assignments(
                            mezz_groups, mezz_catalog_rows, prefer_lightest_over_tier=True
                        )
                        self.mezz_joist_selection_by_group.update(mezz_assignments)
                    except InputValidationError as exc:
                        mezz_missing = [str(exc)]

        assigned_count = len(main_assignments)
        mezz_assigned_count = len(mezz_assignments)

        self._refresh_joist_selection_table()
        self.redraw_roof_section()
        if main_missing or mezz_missing or main_fallback_error:
            merged_missing = []
            merged_missing.extend([f"Main: {item}" for item in main_missing])
            merged_missing.extend([f"Mezz: {item}" for item in mezz_missing])
            if main_fallback_error:
                merged_missing.append(f"Main LH fallback unavailable: {main_fallback_error}")
            messagebox.showwarning(
                "Partial auto-assignment",
                (
                    f"Main: {assigned_count}/{len(main_groups)} groups assigned.\n"
                    + (
                        f"Main LH fallback assignments: {main_fallback_assigned}"
                        + (f" via {main_fallback_source}" if main_fallback_source else "")
                        + "\n"
                        if main_fallback_assigned > 0 or main_fallback_error
                        else ""
                    )
                    +
                    f"Mezz: {mezz_assigned_count}/{len(mezz_groups)} groups assigned.\n"
                    "No candidate found after exact/interpolation/extrapolation tiers for:\n- "
                    + "\n- ".join(merged_missing[:12]) +
                    ("\n..." if len(merged_missing) > 12 else "")
                ),
            )
        else:
            messagebox.showinfo(
                "Auto-assignment complete",
                (
                    f"Assigned joists from {self.joist_catalog_source} (Main).\n"
                    + (
                        f"Main LH fallback assignments: {main_fallback_assigned}"
                        + (f" via {main_fallback_source}" if main_fallback_source else "")
                        + "\n"
                        if main_fallback_assigned > 0
                        else ""
                    )
                    +
                    f"Main: {assigned_count}/{len(main_groups)} groups\n"
                    f"Mezz: {mezz_assigned_count}/{len(mezz_groups)} groups"
                    + (f" via {mezz_catalog_source}" if mezz_catalog_source else "")
                ),
            )

    def _build_girder_demand_groups(self, girder_calcs):
        allowed_depth_by_line = self._get_allowed_girder_depth_by_line_in()
        groups = {}
        for item in girder_calcs:
            line_idx = self._axis_label_to_index(item["line_label"])
            max_depth_in = allowed_depth_by_line.get(line_idx)
            if max_depth_in is None:
                max_depth_in = 0.0
            required_capacity_lbs = round(float(item["required_capacity_lbs"]), 2)
            required_length_ft = round(float(item["bay_width_ft"]), 2)
            required_joist_n = int(item.get("required_joist_count_n", 0) or 0)
            key = (required_capacity_lbs, required_length_ft, required_joist_n, round(float(max_depth_in), 2))
            group_id = self._format_girder_group_id(key[0], key[1], key[2], key[3])
            if group_id not in groups:
                groups[group_id] = {
                    "group_id": group_id,
                    "required_capacity_lbs": key[0],
                    "required_length_ft": key[1],
                    "required_joist_n": key[2],
                    "max_depth_in": key[3],
                    "count": 0,
                    "total_span_ft": 0.0,
                }
            groups[group_id]["count"] += 1
            groups[group_id]["total_span_ft"] += float(item["bay_width_ft"])

        output = []
        for grp in groups.values():
            output.append(
                {
                    "group_id": grp["group_id"],
                    "required_capacity_lbs": grp["required_capacity_lbs"],
                    "required_length_ft": grp["required_length_ft"],
                    "required_joist_n": grp["required_joist_n"],
                    "max_depth_in": grp["max_depth_in"],
                    "count": grp["count"],
                    "total_span_ft": round(grp["total_span_ft"], 3),
                    "requirement_text": (
                        f"{grp['count']} x Girders require {grp['required_capacity_lbs']:.2f} lbs "
                        f"at {self._fmt_ft_arch(grp['required_length_ft'])}, {int(grp['required_joist_n'])}N, "
                        f"max depth {grp['max_depth_in']:.2f} in. Choose girder:"
                    ),
                }
            )
        output.sort(
            key=lambda x: (x["required_capacity_lbs"], x["required_length_ft"], x["required_joist_n"], x["max_depth_in"])
        )
        return output

    def _refresh_girder_selection_table(self):
        if not hasattr(self, "girder_select_tree"):
            return
        main_groups = list((self.last_girder_result or {}).get("girder_demand_groups", []))
        mezz_groups = list((self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", []))
        if not main_groups and not mezz_groups:
            self.girder_select_tree.delete(*self.girder_select_tree.get_children())
            self.total_girder_weight_var.set("Total assigned girder weight: 0.00 lbs (main building only)")
            return

        valid_group_ids = {str(group.get("group_id", "")) for group in main_groups}
        self.girder_selection_by_group = {
            group_id: item
            for group_id, item in self.girder_selection_by_group.items()
            if str(group_id) in valid_group_ids
        }
        mezz_valid_group_ids = {str(group.get("group_id", "")) for group in mezz_groups}
        self.mezz_girder_selection_by_group = {
            group_id: item
            for group_id, item in self.mezz_girder_selection_by_group.items()
            if str(group_id) in mezz_valid_group_ids
        }

        self.girder_select_tree.delete(*self.girder_select_tree.get_children())
        main_assigned_weight_lbs = 0.0

        def insert_rows(scope_name, groups, selection_map):
            nonlocal main_assigned_weight_lbs
            for group in groups:
                group_id = str(group.get("group_id", ""))
                tree_iid = self._make_scoped_group_iid(scope_name, group_id)
                assigned = selection_map.get(group_id)
                designation = ""
                depth = ""
                wt_plf = ""
                group_wt = ""
                if assigned:
                    designation = str(assigned.get("designation", "") or "")
                    depth = f"{float(assigned.get('depth_in', 0.0) or 0.0):.2f}"
                    wt_plf = f"{float(assigned.get('weight_plf', 0.0) or 0.0):.2f}"
                    weight_lbs = float(assigned.get("weight_plf", 0.0) or 0.0) * float(group.get("total_span_ft", 0.0) or 0.0)
                    group_wt = f"{weight_lbs:.2f}"
                    if scope_name == "main":
                        main_assigned_weight_lbs += weight_lbs

                self.girder_select_tree.insert(
                    "",
                    "end",
                    iid=tree_iid,
                    tags=(scope_name,),
                    values=(
                        "Main" if scope_name == "main" else "Mezz",
                        str(group.get("requirement_text", "") or ""),
                        int(group.get("count", 0) or 0),
                        f"{float(group.get('required_capacity_lbs', 0.0) or 0.0):.2f}",
                        self._fmt_ft_arch(float(group.get("required_length_ft", 0.0) or 0.0)),
                        f"{int(group.get('required_joist_n', 0) or 0)}",
                        f"{float(group.get('max_depth_in', 0.0) or 0.0):.2f}",
                        designation,
                        depth,
                        wt_plf,
                        group_wt,
                    ),
                )

        insert_rows("main", main_groups, self.girder_selection_by_group)
        insert_rows("mezz", mezz_groups, self.mezz_girder_selection_by_group)

        self.total_girder_weight_var.set(
            f"Total assigned girder weight: {main_assigned_weight_lbs:.2f} lbs (main building only)"
        )

    def assign_selected_girder(self):
        has_main = bool((self.last_girder_result or {}).get("girder_demand_groups"))
        has_mezz = bool((self.last_mezz_result or {}).get("mezzanine_girder_demand_groups"))
        if not has_main and not has_mezz:
            messagebox.showerror("No calculations", "Run Calculate Girders first.")
            return
        selected = self.girder_select_tree.selection()
        if not selected:
            messagebox.showerror("Selection required", "Select a requirement row in the girder selection table.")
            return

        try:
            depth_in = float(self.selected_girder_depth_var.get())
            weight_plf = float(self.selected_girder_weight_plf_var.get())
            if depth_in <= 0 or weight_plf <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid girder selection", "Depth and weight must be positive numeric values.")
            return

        scope_name, group_id = self._parse_scoped_group_iid(selected[0])
        if scope_name == "mezz":
            group_map = {
                str(group.get("group_id", "")): group
                for group in (self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", [])
            }
            target_map = self.mezz_girder_selection_by_group
        else:
            group_map = {
                str(group.get("group_id", "")): group
                for group in (self.last_girder_result or {}).get("girder_demand_groups", [])
            }
            target_map = self.girder_selection_by_group
        if group_id not in group_map:
            return

        group = group_map[group_id]
        designation = self._format_girder_designation(
            depth_in,
            int(group.get("required_joist_n", 0) or 0),
            float(group.get("required_capacity_lbs", 0.0)) / 1000.0,
        )
        target_map[group_id] = {
            "depth_in": depth_in,
            "weight_plf": weight_plf,
            "designation": designation,
        }
        self._refresh_girder_selection_table()

    def clear_selected_girders(self):
        self.girder_selection_by_group = {}
        self.mezz_girder_selection_by_group = {}
        self._refresh_girder_selection_table()

    def _interpolate_weight_from_curve(self, curve, req_load_kips: float):
        if not curve:
            return None
        if req_load_kips <= curve[0][0] + 1e-9:
            return float(curve[0][1])
        for i in range(1, len(curve)):
            l0, w0 = curve[i - 1]
            l1, w1 = curve[i]
            if req_load_kips <= l1 + 1e-9:
                if abs(l1 - l0) < 1e-9:
                    return float(max(w0, w1))
                ratio = (req_load_kips - l0) / (l1 - l0)
                return float(w0 + ratio * (w1 - w0))
        return None

    def _estimate_girder_weight_by_span(
        self,
        catalog_index,
        req_span_ft: float,
        req_joist_n: int,
        depth_in: float,
        req_load_kips: float,
    ):
        span_weight_points = []
        for (span_key, joist_n), depth_map in (catalog_index or {}).items():
            if int(joist_n) != int(req_joist_n):
                continue
            curve = depth_map.get(depth_in)
            if not curve:
                continue
            weight_plf = self._interpolate_weight_from_curve(curve, req_load_kips)
            if weight_plf is None:
                continue
            span_weight_points.append((float(span_key), float(weight_plf)))
        return self._estimate_value_by_span_points(span_weight_points, req_span_ft, tol=0.01)

    def _compute_girder_auto_assignments(self, groups, catalog_index):
        assignments = {}
        missing = []
        tier_order = ("exact", "interpolate", "extrapolate", "single")
        for group in groups:
            req_capacity_lbs = float(group["required_capacity_lbs"])
            req_load_kips = req_capacity_lbs / 1000.0
            req_span_ft = round(float(group.get("required_length_ft", 0.0)), 2)
            req_joist_n = int(group.get("required_joist_n", 0) or 0)
            max_depth_in = float(group.get("max_depth_in", 0.0))
            min_depth_in = float(group.get("min_depth_in", 0.0) or 0.0)
            has_min_depth_rule = min_depth_in > 0.0

            depth_values = set()
            for (span_key, joist_n), depth_map in (catalog_index or {}).items():
                if int(joist_n) != req_joist_n:
                    continue
                if depth_map:
                    depth_values.update(float(d) for d in depth_map.keys())

            req_text = (
                f"{req_capacity_lbs:.2f} lbs @ {self._fmt_ft_arch(req_span_ft)}, {req_joist_n}N, "
                + (
                    f"min {min_depth_in:.2f} in"
                    if has_min_depth_rule
                    else f"max {max_depth_in:.2f} in"
                )
            )
            if not depth_values:
                missing.append(req_text)
                continue

            candidates_by_tier = {name: [] for name in tier_order}
            exact_min_depth_candidates_by_tier = {name: [] for name in tier_order}
            for depth in sorted(depth_values):
                if has_min_depth_rule:
                    if depth + 1e-9 < min_depth_in:
                        continue
                elif depth > max_depth_in + 1e-9:
                    continue
                est_weight, tier = self._estimate_girder_weight_by_span(
                    catalog_index,
                    req_span_ft=req_span_ft,
                    req_joist_n=req_joist_n,
                    depth_in=float(depth),
                    req_load_kips=req_load_kips,
                )
                if est_weight is None or tier not in candidates_by_tier:
                    continue
                candidates_by_tier[tier].append(
                    {
                        "depth_in": float(depth),
                        "weight_plf": float(est_weight),
                        "tier": tier,
                    }
                )
                if has_min_depth_rule and abs(float(depth) - float(min_depth_in)) <= 0.20:
                    exact_min_depth_candidates_by_tier[tier].append(
                        {
                            "depth_in": float(depth),
                            "weight_plf": float(est_weight),
                            "tier": tier,
                        }
                    )

            tier_candidates = []
            if has_min_depth_rule:
                for tier_name in tier_order:
                    if exact_min_depth_candidates_by_tier[tier_name]:
                        tier_candidates = exact_min_depth_candidates_by_tier[tier_name]
                        break
                if not tier_candidates:
                    for tier_name in tier_order:
                        if candidates_by_tier[tier_name]:
                            tier_candidates = candidates_by_tier[tier_name]
                            break
            else:
                for tier_name in tier_order:
                    if candidates_by_tier[tier_name]:
                        tier_candidates = candidates_by_tier[tier_name]
                        break

            if not tier_candidates:
                missing.append(req_text)
                continue

            if has_min_depth_rule:
                exact_min_pool = [c for c in tier_candidates if abs(float(c.get("depth_in", 0.0)) - min_depth_in) <= 0.20]
                if exact_min_pool:
                    best = min(
                        exact_min_pool,
                        key=lambda item: (
                            float(item["weight_plf"]),
                            float(item["depth_in"]),
                        ),
                    )
                else:
                    best = min(
                        tier_candidates,
                        key=lambda item: (
                            float(item["depth_in"]),  # smallest depth >= minimum
                            float(item["weight_plf"]),
                        ),
                    )
            else:
                best = min(
                    tier_candidates,
                    key=lambda item: (
                        -float(item["depth_in"]),  # closest to max allowable depth (largest <= max)
                        float(item["weight_plf"]),
                    ),
                )

            assignments[group["group_id"]] = {
                "depth_in": float(best["depth_in"]),
                "weight_plf": float(round(float(best["weight_plf"]), 3)),
                "panel_load_kips": float(round(req_load_kips, 3)),
                "designation": self._format_girder_designation(float(best["depth_in"]), req_joist_n, req_load_kips),
            }
        return assignments, missing

    def _finish_auto_assign_girders(
        self,
        assignments,
        missing,
        group_count,
        source,
        error,
        mezz_assignments=None,
        mezz_missing=None,
        mezz_group_count=0,
    ):
        self._girder_auto_assign_running = False
        if hasattr(self, "auto_assign_girder_btn"):
            self.auto_assign_girder_btn.configure(state="normal")

        if error:
            self.girder_calc_status_var.set("Girder auto-assignment failed.")
            messagebox.showerror("Catalog error", error)
            return

        mezz_assignments = dict(mezz_assignments or {})
        mezz_missing = list(mezz_missing or [])

        valid_group_ids = {
            str(group.get("group_id", "")) for group in (self.last_girder_result or {}).get("girder_demand_groups", [])
        }
        for group_id, selection in assignments.items():
            if str(group_id) in valid_group_ids:
                self.girder_selection_by_group[group_id] = selection
        valid_mezz_group_ids = {
            str(group.get("group_id", ""))
            for group in (self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", [])
        }
        for group_id, selection in mezz_assignments.items():
            if str(group_id) in valid_mezz_group_ids:
                self.mezz_girder_selection_by_group[group_id] = selection

        assigned_count = len(assignments)
        mezz_assigned_count = len(mezz_assignments)
        self._refresh_girder_selection_table()
        self.girder_calc_status_var.set(
            "Girder auto-assignment complete: "
            f"Main {assigned_count}/{group_count}, Mezz {mezz_assigned_count}/{int(mezz_group_count)} groups."
        )
        if missing or mezz_missing:
            merged_missing = []
            merged_missing.extend([f"Main: {item}" for item in missing])
            merged_missing.extend([f"Mezz: {item}" for item in mezz_missing])
            messagebox.showwarning(
                "Partial auto-assignment",
                (
                    f"Main: {assigned_count}/{group_count} girder groups assigned.\n"
                    f"Mezz: {mezz_assigned_count}/{int(mezz_group_count)} girder groups assigned.\n"
                    "No matching candidate after exact/interpolation/extrapolation tiers for:\n- "
                    + "\n- ".join(merged_missing[:12]) +
                    ("\n..." if len(merged_missing) > 12 else "")
                ),
            )
        else:
            messagebox.showinfo(
                "Auto-assignment complete",
                (
                    f"Assigned girder groups from {source}.\n"
                    f"Main: {assigned_count}/{group_count}\n"
                    f"Mezz: {mezz_assigned_count}/{int(mezz_group_count)}"
                ),
            )

    def _auto_assign_girders_worker(self, groups, mezz_groups):
        assignments = {}
        missing = []
        mezz_assignments = {}
        mezz_missing = []
        source = self.girder_catalog_source or "catalog"
        error = None
        try:
            self._load_girder_catalog_rows()
            source = self.girder_catalog_source or source
            catalog_index = self.girder_catalog_index or {}
            assignments, missing = self._compute_girder_auto_assignments(groups, catalog_index)
            if mezz_groups:
                mezz_assignments, mezz_missing = self._compute_girder_auto_assignments(mezz_groups, catalog_index)
        except InputValidationError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"Unexpected error during girder auto-assignment: {exc}"

        self._girder_auto_assign_result = {
            "assignments": assignments,
            "missing": missing,
            "group_count": len(groups),
            "mezz_assignments": mezz_assignments,
            "mezz_missing": mezz_missing,
            "mezz_group_count": len(mezz_groups),
            "source": source,
            "error": error,
        }

    def _poll_auto_assign_girders(self):
        thread = self._girder_auto_assign_thread
        if thread is not None and thread.is_alive():
            self.root.after(80, self._poll_auto_assign_girders)
            return

        result = self._girder_auto_assign_result or {}
        self._girder_auto_assign_thread = None
        self._girder_auto_assign_result = None
        self._finish_auto_assign_girders(
            result.get("assignments", {}),
            result.get("missing", []),
            int(result.get("group_count", 0)),
            str(result.get("source", self.girder_catalog_source or "catalog")),
            result.get("error"),
            result.get("mezz_assignments", {}),
            result.get("mezz_missing", []),
            int(result.get("mezz_group_count", 0)),
        )

    def auto_assign_girders_from_excel(self):
        if self._girder_auto_assign_running:
            return
        if not self.last_girder_result:
            self.calculate_girders()
            if not self.last_girder_result:
                return

        groups = list(self.last_girder_result.get("girder_demand_groups", []))

        mezz_groups = []
        if bool(self.mezzanine_enabled_var.get()) and bool(self.mezz_zones):
            mezz_result = self._get_mezz_result_for_tab_display()
            if isinstance(mezz_result, dict) and "_error" in mezz_result:
                messagebox.showwarning(
                    "Mezzanine warning",
                    f"Main girders will be auto-assigned, but mezzanine could not be calculated:\n{mezz_result.get('_error')}",
                )
            else:
                mezz_groups = self._build_mezz_girder_groups_for_assignment()

        if not groups and not mezz_groups:
            messagebox.showerror("No calculations", "Run Calculate Girders first.")
            return

        self._girder_auto_assign_running = True
        if hasattr(self, "auto_assign_girder_btn"):
            self.auto_assign_girder_btn.configure(state="disabled")
        self.girder_calc_status_var.set("Auto-assigning main + mezz girders from Excel... UI remains responsive.")
        self._girder_auto_assign_result = None
        self._girder_auto_assign_thread = threading.Thread(
            target=self._auto_assign_girders_worker, args=(groups, mezz_groups), daemon=True
        )
        self._girder_auto_assign_thread.start()
        self.root.after(80, self._poll_auto_assign_girders)

    def _get_column_height_by_line_ft(self):
        profile = self._build_roof_profile_data()
        if not profile:
            clear_height_ft = self._parse_positive_float_or_default(self.clear_height_var.get(), 36.0)
            return {}, clear_height_ft
        joist_seat_depth_in = float(
            profile.get("joist_seat_depth_in", profile.get("joist_depth_thickness_in", 0.0))
        )
        seat_depth_ft = joist_seat_depth_in / 12.0
        toj_by_line = profile.get("line_toj_elevations_ft", profile.get("line_roof_heights", []))
        line_height_map = {
            idx: max(0.0, float(height_ft) - seat_depth_ft)
            for idx, height_ft in enumerate(toj_by_line)
        }
        return line_height_map, float(profile["clear_height_ft"])

    def _build_column_demand_groups(self, column_calcs):
        line_height_map, clear_height_ft = self._get_column_height_by_line_ft()
        groups = {}
        for item in column_calcs:
            y_line_idx = int(item.get("y_line_index", -1))
            column_height_ft = float(line_height_map.get(y_line_idx, clear_height_ft))
            required_capacity_kips = round(float(item["required_capacity_kips"]), 2)
            group_id = f"{required_capacity_kips:.2f}"
            if group_id not in groups:
                groups[group_id] = {
                    "group_id": group_id,
                    "required_capacity_kips": required_capacity_kips,
                    "avg_height_ft": round(column_height_ft, 2),
                    "count": 0,
                    "total_height_ft": 0.0,
                }
            groups[group_id]["count"] += 1
            groups[group_id]["total_height_ft"] += column_height_ft

        output = []
        for grp in groups.values():
            avg_height_ft = grp["total_height_ft"] / max(1, grp["count"])
            output.append(
                {
                    "group_id": grp["group_id"],
                    "required_capacity_kips": grp["required_capacity_kips"],
                    "avg_height_ft": round(avg_height_ft, 2),
                    "count": grp["count"],
                    "total_height_ft": round(grp["total_height_ft"], 3),
                    "requirement_text": (
                        f"{grp['count']} x Columns require {grp['required_capacity_kips']:.2f} kips "
                        f"at avg TOC/JB {self._fmt_ft_arch(avg_height_ft)}. Choose column:"
                    ),
                }
            )
        output.sort(key=lambda x: x["required_capacity_kips"])
        return output

    def _refresh_column_selection_table(self):
        if not hasattr(self, "column_select_tree"):
            return
        main_groups = list((self.last_column_result or {}).get("column_demand_groups", []))
        mezz_groups = list((self.last_mezz_result or {}).get("mezzanine_column_demand_groups", []))
        if not main_groups and not mezz_groups:
            self.column_select_tree.delete(*self.column_select_tree.get_children())
            self.total_column_weight_var.set("Total assigned column weight: 0.00 lbs (main building only)")
            return

        valid_group_ids = {str(group.get("group_id", "")) for group in main_groups}
        self.column_selection_by_group = {
            group_id: item
            for group_id, item in self.column_selection_by_group.items()
            if str(group_id) in valid_group_ids
        }
        mezz_valid_group_ids = {str(group.get("group_id", "")) for group in mezz_groups}
        self.mezz_column_selection_by_group = {
            group_id: item
            for group_id, item in self.mezz_column_selection_by_group.items()
            if str(group_id) in mezz_valid_group_ids
        }

        self.column_select_tree.delete(*self.column_select_tree.get_children())
        main_assigned_weight_lbs = 0.0

        def insert_rows(scope_name, groups, selection_map):
            nonlocal main_assigned_weight_lbs
            for group in groups:
                group_id = str(group.get("group_id", ""))
                tree_iid = self._make_scoped_group_iid(scope_name, group_id)
                assigned = selection_map.get(group_id)
                designation = ""
                depth = ""
                wt_plf = ""
                group_wt = ""
                if assigned:
                    designation = str(assigned.get("designation", "") or "")
                    depth = f"{float(assigned.get('depth_in', 0.0) or 0.0):.2f}"
                    wt_plf = f"{float(assigned.get('weight_plf', 0.0) or 0.0):.2f}"
                    total_height_ft = float(group.get("total_height_ft", 0.0) or 0.0)
                    if total_height_ft <= 0.0:
                        height_ft = float(group.get("column_height_ft", group.get("avg_height_ft", 0.0)) or 0.0)
                        total_height_ft = max(0.0, height_ft) * float(group.get("count", 0) or 0)
                    weight_lbs = float(assigned.get("weight_plf", 0.0) or 0.0) * total_height_ft
                    group_wt = f"{weight_lbs:.2f}"
                    if scope_name == "main":
                        main_assigned_weight_lbs += weight_lbs

                avg_height_ft = float(group.get("avg_height_ft", group.get("column_height_ft", 0.0)) or 0.0)
                self.column_select_tree.insert(
                    "",
                    "end",
                    iid=tree_iid,
                    tags=(scope_name,),
                    values=(
                        "Main" if scope_name == "main" else "Mezz",
                        str(group.get("requirement_text", "") or ""),
                        int(group.get("count", 0) or 0),
                        f"{float(group.get('required_capacity_kips', 0.0) or 0.0):.2f}",
                        self._fmt_ft_arch(avg_height_ft),
                        designation,
                        depth,
                        wt_plf,
                        group_wt,
                    ),
                )

        insert_rows("main", main_groups, self.column_selection_by_group)
        insert_rows("mezz", mezz_groups, self.mezz_column_selection_by_group)

        self.total_column_weight_var.set(
            f"Total assigned column weight: {main_assigned_weight_lbs:.2f} lbs (main building only)"
        )

    def assign_selected_column(self):
        has_main = bool((self.last_column_result or {}).get("column_demand_groups"))
        has_mezz = bool((self.last_mezz_result or {}).get("mezzanine_column_demand_groups"))
        if not has_main and not has_mezz:
            messagebox.showerror("No calculations", "Run Calculate Columns first.")
            return
        selected = self.column_select_tree.selection()
        if not selected:
            messagebox.showerror("Selection required", "Select a requirement row in the column selection table.")
            return

        try:
            depth_in = float(self.selected_column_depth_var.get())
            weight_plf = float(self.selected_column_weight_plf_var.get())
            if depth_in <= 0 or weight_plf <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid column selection", "Depth and weight must be positive numeric values.")
            return

        scope_name, group_id = self._parse_scoped_group_iid(selected[0])
        if scope_name == "mezz":
            group_map = {
                str(group.get("group_id", "")): group
                for group in (self.last_mezz_result or {}).get("mezzanine_column_demand_groups", [])
            }
            target_map = self.mezz_column_selection_by_group
        else:
            group_map = {
                str(group.get("group_id", "")): group
                for group in (self.last_column_result or {}).get("column_demand_groups", [])
            }
            target_map = self.column_selection_by_group
        if group_id not in group_map:
            return

        prev = target_map.get(group_id, {})
        target_map[group_id] = {
            "depth_in": depth_in,
            "weight_plf": weight_plf,
            "designation": str(prev.get("designation", "") or ""),
        }
        self._refresh_column_selection_table()

    def clear_selected_columns(self):
        self.column_selection_by_group = {}
        self.mezz_column_selection_by_group = {}
        self._refresh_column_selection_table()

    def _compute_column_auto_assignments(self, groups, catalog_rows, clear_height_ft: float):
        target_kl_ft = int(math.ceil(clear_height_ft - 1e-9))
        available_kl = sorted({int(row["kl_ft"]) for row in catalog_rows})
        if not available_kl:
            raise InputValidationError("No KL rows available in column catalog.")
        if target_kl_ft < available_kl[0] or target_kl_ft > available_kl[-1]:
            raise InputValidationError(
                (
                    f"KL={self._fmt_ft_arch(target_kl_ft)} (from clear height {self._fmt_ft_arch(clear_height_ft)}) is out of catalog range "
                    f"{self._fmt_ft_arch(available_kl[0])}-{self._fmt_ft_arch(available_kl[-1])}."
                )
            )

        kl_rows = [row for row in catalog_rows if int(row["kl_ft"]) == target_kl_ft]
        if not kl_rows:
            raise InputValidationError(f"No entries found at KL={self._fmt_ft_arch(target_kl_ft)} in column catalog.")

        assignments = {}
        missing = []
        for group in groups:
            req_kips = float(group["required_capacity_kips"])
            candidates = [row for row in kl_rows if float(row["asd_capacity_kips"]) + 1e-9 >= req_kips]
            if not candidates:
                missing.append(f"{req_kips:.2f} kips")
                continue
            best = min(
                candidates,
                key=lambda row: (
                    float(row["weight_plf"]),
                    float(row["depth_in"]),
                    float(row["asd_capacity_kips"]),
                    str(row["designation"]),
                ),
            )
            assignments[group["group_id"]] = {
                "depth_in": float(best["depth_in"]),
                "weight_plf": float(best["weight_plf"]),
                "designation": str(best["designation"]),
                "asd_capacity_kips": float(best["asd_capacity_kips"]),
                "kl_ft": target_kl_ft,
            }
        return assignments, missing, target_kl_ft

    def auto_assign_columns_from_excel(self):
        if not self.last_column_result:
            self.calculate_columns()
            if not self.last_column_result:
                return

        try:
            catalog_rows = self._load_column_catalog_rows()
            clear_height_ft = self._parse_positive_input("Clear Height", self.clear_height_var.get())
        except InputValidationError as exc:
            messagebox.showerror("Catalog/Input error", str(exc))
            return

        groups = list((self.last_column_result or {}).get("column_demand_groups", []))
        try:
            assignments, missing, target_kl_ft = self._compute_column_auto_assignments(
                groups, catalog_rows, clear_height_ft
            )
        except InputValidationError as exc:
            messagebox.showerror("Catalog error", str(exc))
            return

        mezz_groups = []
        mezz_assignments = {}
        mezz_missing = []
        used_mezz_kl = []
        if bool(self.mezzanine_enabled_var.get()) and bool(self.mezz_zones):
            mezz_result = self._get_mezz_result_for_tab_display()
            if isinstance(mezz_result, dict) and "_error" in mezz_result:
                messagebox.showwarning(
                    "Mezzanine warning",
                    f"Main columns were auto-assigned, but mezzanine could not be calculated:\n{mezz_result.get('_error')}",
                )
            else:
                mezz_groups = list((self.last_mezz_result or {}).get("mezzanine_column_demand_groups", []))
                if mezz_groups:
                    try:
                        mezz_assignments, mezz_missing, used_mezz_kl = self._compute_mezz_column_auto_assignments(
                            mezz_groups, catalog_rows
                        )
                    except InputValidationError as exc:
                        mezz_missing = [str(exc)]

        self.column_selection_by_group.update(assignments)
        self.mezz_column_selection_by_group.update(mezz_assignments)
        assigned_count = len(assignments)
        mezz_assigned_count = len(mezz_assignments)

        self._refresh_column_selection_table()
        if missing or mezz_missing:
            merged_missing = []
            merged_missing.extend([f"Main: {item}" for item in missing])
            merged_missing.extend([f"Mezz: {item}" for item in mezz_missing])
            if mezz_groups and used_mezz_kl:
                mezz_kl_text = (
                    " (KL used: "
                    + ", ".join(self._fmt_ft_arch(v) for v in used_mezz_kl[:6])
                    + ("..." if len(used_mezz_kl) > 6 else "")
                    + ").\n"
                )
            elif mezz_groups:
                mezz_kl_text = ".\n"
            else:
                mezz_kl_text = ".\n"
            messagebox.showwarning(
                "Partial auto-assignment",
                (
                    f"Main: {assigned_count}/{len(groups)} column groups assigned "
                    f"(KL={self._fmt_ft_arch(target_kl_ft)}, ASD).\n"
                    f"Mezz: {mezz_assigned_count}/{len(mezz_groups)} column groups assigned"
                    + mezz_kl_text
                    + "No candidate found for:\n- "
                    + "\n- ".join(merged_missing[:12]) +
                    ("\n..." if len(merged_missing) > 12 else "")
                ),
            )
        else:
            messagebox.showinfo(
                "Auto-assignment complete",
                (
                    f"Assigned column groups from {self.column_catalog_source}\n"
                    f"Main: {assigned_count}/{len(groups)} groups at KL={self._fmt_ft_arch(target_kl_ft)} (ASD)\n"
                    f"Mezz: {mezz_assigned_count}/{len(mezz_groups)} groups (ASD)"
                ),
            )

    def _build_mezz_girder_groups_for_assignment(self):
        groups = []
        for group in (self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", []):
            groups.append(
                {
                    "group_id": str(group.get("group_id", "")),
                    "required_capacity_lbs": float(group.get("required_capacity_lbs", 0.0) or 0.0),
                    "required_length_ft": float(group.get("required_length_ft", 0.0) or 0.0),
                    "required_joist_n": int(group.get("required_joist_n", 0) or 0),
                    "min_depth_in": float(group.get("min_depth_in", 30.0) or 30.0),
                    "max_depth_in": float(group.get("max_depth_in", 30.0) or 30.0),
                    "count": int(group.get("count", 0) or 0),
                    "total_span_ft": float(group.get("total_span_ft", 0.0) or 0.0),
                }
            )
        return groups

    def _compute_mezz_column_auto_assignments(self, groups, catalog_rows):
        available_kl = sorted({int(row["kl_ft"]) for row in catalog_rows})
        if not available_kl:
            raise InputValidationError("No KL rows available in column catalog.")

        assignments = {}
        missing = []
        used_kl = set()
        for group in groups:
            group_id = str(group.get("group_id", ""))
            req_kips = float(group.get("required_capacity_kips", 0.0) or 0.0)
            target_height_ft = float(group.get("column_height_ft", group.get("avg_height_ft", 0.0)) or 0.0)
            target_kl_ft = int(math.ceil(target_height_ft - 1e-9))
            if target_kl_ft < available_kl[0] or target_kl_ft > available_kl[-1]:
                missing.append(
                    (
                        f"{group_id}: {req_kips:.2f} kips @ KL={self._fmt_ft_arch(target_kl_ft)} "
                        f"(catalog {self._fmt_ft_arch(available_kl[0])}-{self._fmt_ft_arch(available_kl[-1])})"
                    )
                )
                continue

            kl_rows = [row for row in catalog_rows if int(row["kl_ft"]) == target_kl_ft]
            if not kl_rows:
                missing.append(f"{group_id}: no KL row at {self._fmt_ft_arch(target_kl_ft)}")
                continue
            candidates = [row for row in kl_rows if float(row["asd_capacity_kips"]) + 1e-9 >= req_kips]
            if not candidates:
                missing.append(f"{group_id}: {req_kips:.2f} kips @ KL={self._fmt_ft_arch(target_kl_ft)}")
                continue
            best = min(
                candidates,
                key=lambda row: (
                    float(row["weight_plf"]),
                    float(row["depth_in"]),
                    float(row["asd_capacity_kips"]),
                    str(row["designation"]),
                ),
            )
            assignments[group_id] = {
                "depth_in": float(best["depth_in"]),
                "weight_plf": float(best["weight_plf"]),
                "designation": str(best["designation"]),
                "asd_capacity_kips": float(best["asd_capacity_kips"]),
                "kl_ft": target_kl_ft,
            }
            used_kl.add(target_kl_ft)
        return assignments, missing, sorted(used_kl)

    def _compute_mezz_assigned_weight_totals(self):
        out = {
            "joist_lbs": 0.0,
            "girder_lbs": 0.0,
            "column_lbs": 0.0,
            "total_steel_lbs": 0.0,
            "joist_assigned_groups": 0,
            "joist_total_groups": 0,
            "girder_assigned_groups": 0,
            "girder_total_groups": 0,
            "column_assigned_groups": 0,
            "column_total_groups": 0,
        }
        if not self.last_mezz_result:
            return out

        joist_groups = (self.last_mezz_result or {}).get("mezzanine_joist_demand_groups", [])
        out["joist_total_groups"] = len(joist_groups)
        for group in joist_groups:
            group_id = str(group.get("group_id", ""))
            selected = self.mezz_joist_selection_by_group.get(group_id)
            if not selected:
                continue
            out["joist_assigned_groups"] += 1
            out["joist_lbs"] += float(selected.get("weight_plf", 0.0) or 0.0) * float(group.get("total_span_ft", 0.0) or 0.0)

        girder_groups = (self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", [])
        out["girder_total_groups"] = len(girder_groups)
        for group in girder_groups:
            group_id = str(group.get("group_id", ""))
            selected = self.mezz_girder_selection_by_group.get(group_id)
            if not selected:
                continue
            out["girder_assigned_groups"] += 1
            out["girder_lbs"] += float(selected.get("weight_plf", 0.0) or 0.0) * float(group.get("total_span_ft", 0.0) or 0.0)

        column_groups = (self.last_mezz_result or {}).get("mezzanine_column_demand_groups", [])
        out["column_total_groups"] = len(column_groups)
        for group in column_groups:
            group_id = str(group.get("group_id", ""))
            selected = self.mezz_column_selection_by_group.get(group_id)
            if not selected:
                continue
            out["column_assigned_groups"] += 1
            total_height_ft = float(group.get("total_height_ft", 0.0) or 0.0)
            if total_height_ft <= 0.0:
                height_ft = float(group.get("column_height_ft", group.get("avg_height_ft", 0.0)) or 0.0)
                total_height_ft = max(0.0, height_ft) * float(group.get("count", 0) or 0)
            out["column_lbs"] += float(selected.get("weight_plf", 0.0) or 0.0) * total_height_ft

        out["total_steel_lbs"] = out["joist_lbs"] + out["girder_lbs"] + out["column_lbs"]
        return out

    def _auto_assign_mezz_members(self, show_messages: bool = True):
        if not self.last_mezz_result:
            if show_messages:
                messagebox.showerror("No mezzanine calculation", "Run Calculate Mezzanine first.")
            return None

        joist_groups = list((self.last_mezz_result or {}).get("mezzanine_joist_demand_groups", []))
        girder_groups = self._build_mezz_girder_groups_for_assignment()
        column_groups = list((self.last_mezz_result or {}).get("mezzanine_column_demand_groups", []))

        joist_rows = self._load_mezz_joist_catalog_rows()
        girder_rows = self._load_girder_catalog_rows()
        column_rows = self._load_column_catalog_rows()
        _ = girder_rows  # loaded for index side-effect

        joist_assignments, joist_missing = self._compute_joist_auto_assignments(
            joist_groups, joist_rows, prefer_lightest_over_tier=True
        )
        girder_assignments, girder_missing = self._compute_girder_auto_assignments(
            girder_groups, self.girder_catalog_index or {}
        )
        column_assignments, column_missing, used_kl = self._compute_mezz_column_auto_assignments(
            column_groups, column_rows
        )

        self.mezz_joist_selection_by_group.update(joist_assignments)
        self.mezz_girder_selection_by_group.update(girder_assignments)
        self.mezz_column_selection_by_group.update(column_assignments)
        self._refresh_joist_selection_table()
        self._refresh_girder_selection_table()
        self._refresh_column_selection_table()

        weight_summary = self._compute_mezz_assigned_weight_totals()
        summary = {
            "joist_total_groups": len(joist_groups),
            "joist_assigned_groups": len(joist_assignments),
            "joist_missing": joist_missing,
            "girder_total_groups": len(girder_groups),
            "girder_assigned_groups": len(girder_assignments),
            "girder_missing": girder_missing,
            "column_total_groups": len(column_groups),
            "column_assigned_groups": len(column_assignments),
            "column_missing": column_missing,
            "used_kl": used_kl,
            "weight_summary": weight_summary,
            "joist_catalog_source": str(self.mezz_joist_catalog_source or ""),
        }

        if show_messages:
            if joist_missing or girder_missing or column_missing:
                messagebox.showwarning(
                    "Mezzanine auto-assign (partial)",
                    (
                        f"LH Joist Source: {self.mezz_joist_catalog_source or 'N/A'}\n"
                        f"Joists: {len(joist_assignments)}/{len(joist_groups)}\n"
                        f"Girders: {len(girder_assignments)}/{len(girder_groups)}\n"
                        f"Columns: {len(column_assignments)}/{len(column_groups)}\n"
                        f"Mezz steel assigned: {self._fmt_num(weight_summary['total_steel_lbs'], 2)} lbs"
                    ),
                )
            else:
                messagebox.showinfo(
                    "Mezzanine auto-assign complete",
                    (
                        f"LH Joist Source: {self.mezz_joist_catalog_source or 'N/A'}\n"
                        f"Joists/Girders/Columns fully assigned.\n"
                        f"Mezz steel assigned: {self._fmt_num(weight_summary['total_steel_lbs'], 2)} lbs"
                    ),
                )
        return summary

    def calculate_mezz_pad_footings(self):
        if not self.last_mezz_result:
            self.last_mezz_footing_result = {
                "footing_depth_ft": 0.0,
                "bearing_pressure_psi": 0.0,
                "column_footings": [],
                "summary": {"column_count": 0, "total_cy": 0.0, "total_cy_with_waste": 0.0},
            }
            return self.last_mezz_footing_result

        footing_depth_ft = self._parse_positive_input("Footing Depth", self.footing_depth_var.get())
        bearing_pressure_psi = self._parse_positive_input("Bearing Pressure", self.bearing_pressure_var.get())

        denom = math.sqrt(bearing_pressure_psi / 1000.0)
        if denom <= 0:
            raise InputValidationError("Bearing Pressure must be > 0.")

        columns = [
            row
            for row in list((self.last_mezz_result or {}).get("mezzanine_column_calculations", []))
            if str(row.get("main_or_mezz_column", "Mezz")).strip().lower() != "main"
        ]
        if not columns:
            self.last_mezz_footing_result = {
                "footing_depth_ft": round(float(footing_depth_ft), 3),
                "bearing_pressure_psi": round(float(bearing_pressure_psi), 3),
                "column_footings": [],
                "summary": {"column_count": 0, "total_cy": 0.0, "total_cy_with_waste": 0.0},
            }
            return self.last_mezz_footing_result

        total_cy = 0.0
        column_footings = []
        for row in columns:
            required_capacity_kips = float(row.get("required_capacity_kips", 0.0) or 0.0)
            footing_size_raw_ft = math.sqrt(max(0.0, required_capacity_kips)) / denom
            footing_size_ft = self._ceil_to_increment(footing_size_raw_ft, 0.25)
            footing_volume_cy = (footing_size_ft * footing_size_ft * footing_depth_ft) / 27.0
            total_cy += footing_volume_cy
            grid = f"{row.get('y_line_label', '-')}{row.get('x_line_label', '-')}"
            column_footings.append(
                {
                    "column_id": str(row.get("column_id", "-")),
                    "grid": grid,
                    "zone_name": str(row.get("zone_name", "-")),
                    "required_capacity_kips": round(required_capacity_kips, 3),
                    "footing_size_raw_ft": round(footing_size_raw_ft, 4),
                    "footing_size_ft": round(footing_size_ft, 2),
                    "footing_depth_ft": round(float(footing_depth_ft), 3),
                    "footing_volume_cy": round(footing_volume_cy, 4),
                    "column_type": str(row.get("main_or_mezz_column", "Mezz")),
                }
            )

        total_cy_waste = total_cy * 1.10
        self.last_mezz_footing_result = {
            "footing_depth_ft": round(float(footing_depth_ft), 3),
            "bearing_pressure_psi": round(float(bearing_pressure_psi), 3),
            "column_footings": column_footings,
            "summary": {
                "column_count": len(column_footings),
                "total_cy": round(total_cy, 4),
                "total_cy_with_waste": round(total_cy_waste, 4),
            },
        }
        return self.last_mezz_footing_result

    def _parse_lbs_value(self, text: str):
        match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*lbs", str(text or ""), flags=re.IGNORECASE)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0

    def _parse_float_from_text(self, text: str):
        text = str(text or "").replace(",", "")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None

    def _fmt_num(self, value, decimals=2):
        try:
            return format(float(value), f",.{int(decimals)}f")
        except Exception:
            return str(value)

    def _fmt_int(self, value):
        try:
            return f"{int(round(float(value))):,d}"
        except Exception:
            return str(value)

    def _fmt_ft_arch(self, value, inch_resolution: float = 0.5):
        try:
            feet_value = float(value)
        except Exception:
            return str(value)
        if math.isnan(feet_value) or math.isinf(feet_value):
            return str(value)

        res = max(1e-6, float(inch_resolution))
        sign = "-" if feet_value < 0 else ""
        total_inches = abs(feet_value) * 12.0
        total_inches = round(total_inches / res) * res

        feet_int = int(total_inches // 12.0)
        rem_inches = total_inches - (feet_int * 12.0)
        if rem_inches >= (12.0 - 1e-8):
            feet_int += 1
            rem_inches = 0.0

        inch_whole = int(rem_inches // 1.0)
        inch_frac = rem_inches - inch_whole
        if inch_frac >= (1.0 - 1e-8):
            inch_whole += 1
            inch_frac = 0.0
        if inch_whole >= 12:
            feet_int += 1
            inch_whole -= 12

        if inch_frac <= 1e-8:
            inch_text = f"{inch_whole}\""
        else:
            frac = Fraction(inch_frac).limit_denominator(64)
            if inch_whole > 0:
                inch_text = f"{inch_whole} {frac.numerator}/{frac.denominator}\""
            else:
                inch_text = f"{frac.numerator}/{frac.denominator}\""

        return f"{sign}{feet_int}'-{inch_text}"

    def _collect_tree_table_rows(self, tree_widget):
        rows = []
        for iid in tree_widget.get_children():
            vals = tree_widget.item(iid, "values")
            rows.append([str(v) if v is not None else "" for v in vals])
        return rows

    def _collect_weight_summary(self):
        main_joist_lbs = self._parse_lbs_value(self.total_joist_weight_var.get())
        main_girder_lbs = self._parse_lbs_value(self.total_girder_weight_var.get())
        main_column_lbs = self._parse_lbs_value(self.total_column_weight_var.get())
        mezz_weights = self._compute_mezz_assigned_weight_totals()
        mezz_joist_lbs = float(mezz_weights.get("joist_lbs", 0.0) or 0.0)
        mezz_girder_lbs = float(mezz_weights.get("girder_lbs", 0.0) or 0.0)
        mezz_column_lbs = float(mezz_weights.get("column_lbs", 0.0) or 0.0)
        building_area_sf = float(self.get_active_building_area_sf())
        joist_girder_psf = ((main_joist_lbs + main_girder_lbs) / building_area_sf) if building_area_sf > 0 else 0.0
        target_psf = 2.13
        deviation_psf = joist_girder_psf - target_psf
        combined_joist_lbs = main_joist_lbs + mezz_joist_lbs
        combined_girder_lbs = main_girder_lbs + mezz_girder_lbs
        combined_column_lbs = main_column_lbs + mezz_column_lbs
        combined_total_steel_lbs = combined_joist_lbs + combined_girder_lbs + combined_column_lbs
        return {
            "joist_lbs": main_joist_lbs,
            "girder_lbs": main_girder_lbs,
            "column_lbs": main_column_lbs,
            "total_steel_main_lbs": main_joist_lbs + main_girder_lbs + main_column_lbs,
            "mezz_joist_lbs": mezz_joist_lbs,
            "mezz_girder_lbs": mezz_girder_lbs,
            "mezz_column_lbs": mezz_column_lbs,
            "total_steel_mezz_lbs": mezz_joist_lbs + mezz_girder_lbs + mezz_column_lbs,
            "combined_joist_lbs": combined_joist_lbs,
            "combined_girder_lbs": combined_girder_lbs,
            "combined_column_lbs": combined_column_lbs,
            "total_steel_lbs": combined_total_steel_lbs,
            "building_area_sf": building_area_sf,
            "joist_girder_psf": joist_girder_psf,
            "target_psf": target_psf,
            "deviation_psf": deviation_psf,
            "mezz_weight_summary": mezz_weights,
        }

    def _report_palette(self):
        return {
            "bg": "#f5f8fc",
            "header": "#17375e",
            "header_text": "#ffffff",
            "subtle": "#e6eef7",
            "text": "#203142",
            "muted": "#526980",
            "alt": "#f8fbff",
            "border": "#d5e1ef",
        }

    def _normalize_widths(self, widths, count: int):
        if not widths or len(widths) != count:
            return [1.0 / max(1, count)] * count
        total = sum(max(0.0001, float(w)) for w in widths)
        if total <= 0:
            return [1.0 / max(1, count)] * count
        return [float(w) / total for w in widths]

    def _clean_table_rows(self, rows):
        cleaned = []
        for row in rows:
            cleaned_row = []
            for _col_idx, value in enumerate(row):
                text = str(value)
                cleaned_row.append(text)
            cleaned.append(cleaned_row)
        return cleaned

    def _add_table_pages(
        self,
        pdf,
        title,
        headers,
        rows,
        subtitle="",
        max_rows=22,
        col_widths=None,
        right_align_cols=None,
    ):
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        palette = self._report_palette()
        widths = self._normalize_widths(col_widths, len(headers))
        rows = self._clean_table_rows(rows)
        right_align_cols = set(right_align_cols or [])

        if not rows:
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            ax.axis("off")
            fig.patch.set_facecolor(palette["bg"])
            fig.text(0.04, 0.95, title, fontsize=18, fontweight="bold", color=palette["header"], va="top")
            if subtitle:
                fig.text(0.04, 0.91, subtitle, fontsize=10, color=palette["muted"], va="top")
            ax.text(0.5, 0.5, "No data available.", ha="center", va="center", fontsize=13, color="#666666")
            pdf.savefig(fig)
            plt.close(fig)
            return

        page = 1
        for idx in range(0, len(rows), max_rows):
            chunk = rows[idx : idx + max_rows]
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            ax.axis("off")
            fig.patch.set_facecolor(palette["bg"])
            # Header bar
            fig.patches.append(
                mpatches.Rectangle(
                    (0.0, 0.935), 1.0, 0.065, transform=fig.transFigure, facecolor=palette["header"], edgecolor="none"
                )
            )
            fig.text(0.03, 0.966, title, fontsize=16, fontweight="bold", color=palette["header_text"], va="center")
            meta = subtitle
            if len(rows) > max_rows:
                meta = (meta + " | " if meta else "") + f"Page {page} of {math.ceil(len(rows) / max_rows)}"
            if meta:
                fig.text(0.03, 0.915, meta, fontsize=9.5, color=palette["muted"], va="top")

            table = ax.table(
                cellText=chunk,
                colLabels=headers,
                loc="upper left",
                cellLoc="left",
                colLoc="left",
                colWidths=widths,
                bbox=[0.03, 0.08, 0.94, 0.80],
            )
            table.auto_set_font_size(False)
            table_font = 8.4 if len(headers) <= 8 else 7.8
            table.set_fontsize(table_font)
            table.scale(1.0, 1.24)

            for (r, c), cell in table.get_celld().items():
                if r == 0:
                    cell.set_facecolor(palette["header"])
                    cell.set_text_props(color=palette["header_text"], fontweight="bold")
                else:
                    cell.set_facecolor(palette["alt"] if r % 2 == 0 else "#ffffff")
                    if c == 0:
                        cell.set_text_props(color=palette["text"], fontweight="bold")
                    else:
                        cell.set_text_props(color=palette["text"])
                    if c in right_align_cols:
                        cell.set_text_props(ha="right")
                cell.set_edgecolor(palette["border"])
                cell.set_linewidth(0.55)

            fig.text(0.03, 0.03, f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}", fontsize=8, color=palette["muted"])
            pdf.savefig(fig)
            plt.close(fig)
            page += 1

    def _build_grid_plan_report_figure(self):
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        self.prune_load_bearing_perimeter()
        self.prune_custom_load_bays()
        palette = self._report_palette()
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        fig.patch.set_facecolor(palette["bg"])
        ax.set_facecolor("#ffffff")
        fig.suptitle("Grid Layout Plan", fontsize=19, fontweight="bold", color=palette["header"], y=0.97)

        if not self.model.x_spans or not self.model.y_spans:
            ax.axis("off")
            ax.text(0.5, 0.5, "Grid unavailable.", ha="center", va="center", fontsize=14, color="#666666")
            return fig

        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        total_x = x_lines[-1]
        total_y = y_lines[-1]
        active_bays = self.get_active_bays()

        speed_rows = self._get_selected_speed_bay_rows()
        for y_idx in speed_rows:
            if y_idx >= len(self.model.y_spans):
                continue
            for x_idx in range(len(self.model.x_spans)):
                if (x_idx, y_idx) not in active_bays:
                    continue
                x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
                y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
                ax.add_patch(
                    mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#f6d8a8", edgecolor="none", alpha=0.55)
                )

        for x_idx, y_idx in self.collateral_bays:
            if (x_idx, y_idx) in self.inactive_bays:
                continue
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            ax.add_patch(
                mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#b7e4c7", edgecolor="none", alpha=0.85)
            )
        addl_bay_colors = {}
        for layer in self.additional_load_layers:
            color = self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8")
            for bay in layer.get("bays", set()):
                addl_bay_colors.setdefault(bay, []).append(color)
        for (x_idx, y_idx), colors in addl_bay_colors.items():
            if (x_idx, y_idx) in self.inactive_bays:
                continue
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans) or not colors:
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            if len(colors) == 1:
                ax.add_patch(
                    mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=colors[0], edgecolor="none", alpha=0.58)
                )
                continue
            n = len(colors)
            for i, color in enumerate(colors):
                seg_x0 = x0 + ((x1 - x0) * i / n)
                seg_x1 = x0 + ((x1 - x0) * (i + 1) / n)
                ax.add_patch(
                    mpatches.Rectangle((seg_x0, y0), seg_x1 - seg_x0, y1 - y0, facecolor=color, edgecolor="none", alpha=0.58)
                )

        for x_idx, y_idx in self.inactive_bays:
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            ax.add_patch(
                mpatches.Rectangle(
                    (x0, y0),
                    x1 - x0,
                    y1 - y0,
                    facecolor="#a0aab8",
                    edgecolor="#6a7483",
                    linewidth=0.8,
                    hatch="///",
                    alpha=0.95,
                )
            )

        for x in x_lines:
            ax.plot([x, x], [0, total_y], color="#25364a", linewidth=1.2)
        transition_lines = set(self._get_speed_bay_transition_line_indices())
        for line_idx, y in enumerate(y_lines):
            color = "#2b9348" if line_idx in transition_lines else "#2d2d2d"
            lw = 1.8 if line_idx in transition_lines else 1.2
            ax.plot([0, total_x], [y, y], color=color, linewidth=lw)

        # Load-bearing wall segments on active boundaries.
        for edge in sorted(self.load_bearing_perimeter):
            seg = self._edge_to_world_segment(edge)
            if not seg:
                continue
            x1, y1, x2, y2 = seg
            ax.plot([x1, x2], [y1, y2], color="#b23a48", linewidth=3.0)

        boundary_segments = self._boundary_segments_for_active(active_bays)
        try:
            default_spaces = self.get_default_joist_count()
        except InputValidationError:
            default_spaces = 7
        for x_idx in range(len(self.model.x_spans)):
            for y_idx in range(len(self.model.y_spans)):
                if (x_idx, y_idx) not in active_bays:
                    continue
                spaces = int(self.joists_per_bay.get((x_idx, y_idx), default_spaces))
                if spaces <= 0:
                    continue
                x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
                y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
                spacing_ft = (x1 - x0) / spaces
                member_count = spaces + 1
                for i in range(member_count):
                    xpos = x0 + spacing_ft * i
                    if i == 0:
                        west_edge = ("V", x_idx, y_idx)
                        if (x_idx - 1, y_idx) in active_bays:
                            continue
                        if west_edge in boundary_segments and west_edge in self.load_bearing_perimeter:
                            continue
                    if i == (member_count - 1):
                        east_edge = ("V", x_idx + 1, y_idx)
                        if east_edge in boundary_segments and east_edge in self.load_bearing_perimeter:
                            continue
                    ax.plot([xpos, xpos], [y0, y1], color="#006d77", linewidth=0.65, alpha=0.8)

        for x_idx in range(0, len(x_lines)):
            for y_idx in range(0, len(y_lines)):
                if not self._column_has_steel_support(x_idx, y_idx, active_bays, boundary_segments):
                    continue
                x = x_lines[x_idx]
                y = y_lines[y_idx]
                ax.add_patch(mpatches.Rectangle((x - 0.8, y - 0.8), 1.6, 1.6, facecolor="#222222", edgecolor="none"))

        for i, x in enumerate(x_lines):
            ax.text(x, -4.2, str(i + 1), ha="center", va="bottom", fontsize=9, fontweight="bold", color=palette["text"])
        for i, y in enumerate(y_lines):
            ax.text(-4.2, y, axis_letter(i), ha="right", va="center", fontsize=9, fontweight="bold", color=palette["text"])

        for i, span in enumerate(self.model.x_spans):
            xm = (x_lines[i] + x_lines[i + 1]) / 2.0
            ax.text(xm, -8.0, self._fmt_ft_arch(span), ha="center", va="bottom", fontsize=8, color="#4d4d4d")
        for i, span in enumerate(self.model.y_spans):
            ym = (y_lines[i] + y_lines[i + 1]) / 2.0
            ax.text(-8.5, ym, self._fmt_ft_arch(span), ha="right", va="center", fontsize=8, color="#4d4d4d")

        legend_items = [
            mpatches.Patch(facecolor="#f6d8a8", edgecolor="none", label="Speed Bay Row"),
            mpatches.Patch(facecolor="#b7e4c7", edgecolor="none", label="Collateral Bay"),
            mpatches.Patch(facecolor="#f7d8a8", edgecolor="none", label="Additional Load Bay"),
            mpatches.Patch(facecolor="#a0aab8", edgecolor="#6a7483", hatch="///", label="Void Bay"),
            mpatches.Patch(facecolor="#b23a48", edgecolor="none", label="Load-Bearing Wall"),
            mpatches.Patch(facecolor="#006d77", edgecolor="none", label="Joists"),
            mpatches.Patch(facecolor="#222222", edgecolor="none", label="Columns"),
        ]
        for layer in self.additional_load_layers[:4]:
            legend_items.append(
                mpatches.Patch(
                    facecolor=self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8"),
                    edgecolor="none",
                    label=f"Addl: {str(layer.get('name', 'Layer'))[:18]}",
                )
            )
        if transition_lines:
            legend_items.append(mpatches.Patch(facecolor="#2b9348", edgecolor="none", label="Speed Transition"))
        ax.legend(handles=legend_items, loc="upper right", frameon=True, facecolor="#ffffff", edgecolor=palette["border"], fontsize=8.5)

        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-14, total_x + 4)
        ax.set_ylim(total_y + 4, -14)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(f"{len(self.model.x_spans)} bays in X  |  {len(self.model.y_spans)} bays in Y", fontsize=10, color=palette["muted"], pad=10)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        return fig

    def _build_member_designation_maps(self):
        joist_by_bay = {}
        girder_by_segment = {}
        column_by_node = {}

        if self.last_joist_result:
            for bay in self.last_joist_result.get("joist_bay_calculations", []):
                x_idx = int(bay.get("x_bay_index", 0) or 0) - 1
                y_idx = self._axis_label_to_index(bay.get("y_row_label"))
                if x_idx < 0 or y_idx is None or y_idx < 0:
                    continue
                group_id = self._format_joist_group_id(
                    float(bay.get("required_capacity_plf", 0.0) or 0.0),
                    float(bay.get("bay_length_ft", 0.0) or 0.0),
                )
                designation = str(self.joist_selection_by_group.get(group_id, {}).get("designation", "") or "").strip()
                if designation:
                    joist_by_bay[(x_idx, y_idx)] = designation

        if self.last_girder_result:
            allowed_depth_by_line = self._get_allowed_girder_depth_by_line_in()
            for girder in self.last_girder_result.get("girder_calculations", []):
                y_line_idx = self._axis_label_to_index(girder.get("line_label"))
                x_idx = int(girder.get("x_bay_index", 0) or 0) - 1
                if y_line_idx is None or y_line_idx < 0 or x_idx < 0:
                    continue
                group_id = self._format_girder_group_id(
                    float(girder.get("required_capacity_lbs", 0.0) or 0.0),
                    float(girder.get("bay_width_ft", 0.0) or 0.0),
                    int(girder.get("required_joist_count_n", 0) or 0),
                    float(allowed_depth_by_line.get(y_line_idx, 0.0)),
                )
                designation = str(self.girder_selection_by_group.get(group_id, {}).get("designation", "") or "").strip()
                if not designation:
                    designation = str(girder.get("girder_id", "") or "").strip()
                if designation:
                    girder_by_segment[(y_line_idx, x_idx)] = designation

        if self.last_column_result:
            for col in self.last_column_result.get("column_calculations", []):
                x_line_idx = int(col.get("x_line_index", -1) or -1)
                y_line_idx = int(col.get("y_line_index", -1) or -1)
                if x_line_idx < 0 or y_line_idx < 0:
                    continue
                group_id = f"{round(float(col.get('required_capacity_kips', 0.0) or 0.0), 2):.2f}"
                designation = str(self.column_selection_by_group.get(group_id, {}).get("designation", "") or "").strip()
                if not designation:
                    designation = str(col.get("column_id", "") or "").strip()
                if designation:
                    column_by_node[(x_line_idx, y_line_idx)] = designation

        return joist_by_bay, girder_by_segment, column_by_node

    def _build_member_labeled_plan_report_figure(self):
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        self.prune_load_bearing_perimeter()
        self.prune_custom_load_bays()
        palette = self._report_palette()
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        fig.patch.set_facecolor(palette["bg"])
        ax.set_facecolor("#ffffff")
        fig.suptitle("Labeled Steel Framing Plan", fontsize=18.5, fontweight="bold", color=palette["header"], y=0.968)

        if not self.model.x_spans or not self.model.y_spans:
            ax.axis("off")
            ax.text(0.5, 0.5, "Grid unavailable.", ha="center", va="center", fontsize=13, color="#666666")
            return fig

        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        total_x = x_lines[-1]
        total_y = y_lines[-1]
        active_bays = self.get_active_bays()
        boundary_segments = self._boundary_segments_for_active(active_bays)
        joist_map, girder_map, column_map = self._build_member_designation_maps()

        density = max(1, len(self.model.x_spans) + len(self.model.y_spans))
        axis_font = max(5.8, min(8.8, 9.6 - 0.18 * density))
        member_font = max(5.0, min(7.2, 8.0 - 0.13 * density))
        detail_font = max(4.6, min(6.2, 7.0 - 0.12 * density))
        column_font = max(4.5, detail_font - 0.25)

        margin = max(6.0, 0.03 * max(total_x, total_y))
        x_min = -margin * 1.8
        x_max = total_x + margin * 0.8
        y_top = -margin * 1.8
        y_bottom = total_y + margin * 0.8
        x_range = max(1.0, x_max - x_min)
        y_range = max(1.0, y_bottom - y_top)
        fig_w_in, fig_h_in = fig.get_size_inches()
        ax_pos = ax.get_position()
        ax_w_in = max(1e-6, fig_w_in * ax_pos.width)
        ax_h_in = max(1e-6, fig_h_in * ax_pos.height)
        occupied_boxes = []

        def _label_box(x, y, text, font_size, ha="center", va="center"):
            lines = str(text or "").splitlines() or [""]
            max_chars = max(1, max(len(line) for line in lines))
            n_lines = max(1, len(lines))
            char_w_data = (font_size * 0.56 / 72.0) * (x_range / ax_w_in)
            line_h_data = (font_size * 1.25 / 72.0) * (y_range / ax_h_in)
            box_w = (max_chars * char_w_data) + (0.70 * line_h_data)
            box_h = (n_lines * line_h_data) + (0.55 * line_h_data)

            if ha == "left":
                x0, x1 = x, x + box_w
            elif ha == "right":
                x0, x1 = x - box_w, x
            else:
                x0, x1 = x - (box_w / 2.0), x + (box_w / 2.0)

            if va == "top":
                y0, y1 = y - box_h, y
            elif va == "bottom":
                y0, y1 = y, y + box_h
            else:
                y0, y1 = y - (box_h / 2.0), y + (box_h / 2.0)
            return (x0, x1, y0, y1)

        def _intersects(box_a, box_b, pad=0.16):
            ax0, ax1, ay0, ay1 = box_a
            bx0, bx1, by0, by1 = box_b
            return not (
                (ax1 + pad) < bx0
                or (ax0 - pad) > bx1
                or (ay1 + pad) < by0
                or (ay0 - pad) > by1
            )

        def _place_label(
            x,
            y,
            text,
            font_size,
            color,
            zorder,
            ha="center",
            va="center",
            try_offsets=None,
            bbox_alpha=0.70,
            bbox_pad=0.12,
        ):
            if not text:
                return False
            offsets = try_offsets if try_offsets else [(0.0, 0.0)]
            for dx, dy in offsets:
                cx = float(x) + float(dx)
                cy = float(y) + float(dy)
                box = _label_box(cx, cy, text, font_size, ha=ha, va=va)
                if box[0] < x_min or box[1] > x_max or box[2] < y_top or box[3] > y_bottom:
                    continue
                if any(_intersects(box, other) for other in occupied_boxes):
                    continue
                ax.text(
                    cx,
                    cy,
                    text,
                    ha=ha,
                    va=va,
                    fontsize=font_size,
                    color=color,
                    bbox={"facecolor": "#ffffff", "edgecolor": "none", "alpha": bbox_alpha, "pad": bbox_pad},
                    zorder=zorder,
                )
                occupied_boxes.append(box)
                return True
            return False

        def _draw_fixed_label(
            x,
            y,
            text,
            font_size,
            color,
            zorder,
            ha="center",
            va="center",
            bbox_alpha=0.76,
            bbox_pad=0.10,
        ):
            if not text:
                return None
            box = _label_box(x, y, text, font_size, ha=ha, va=va)
            ax.text(
                x,
                y,
                text,
                ha=ha,
                va=va,
                fontsize=font_size,
                color=color,
                bbox={"facecolor": "#ffffff", "edgecolor": "none", "alpha": bbox_alpha, "pad": bbox_pad},
                zorder=zorder,
            )
            occupied_boxes.append(box)
            return box

        # Background zones.
        for x_idx, y_idx in self.collateral_bays:
            if (x_idx, y_idx) not in active_bays:
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            ax.add_patch(
                mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#c7f0d6", edgecolor="none", alpha=0.58, zorder=1)
            )
        addl_bay_colors = {}
        for layer in self.additional_load_layers:
            color = self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8")
            for bay in layer.get("bays", set()):
                addl_bay_colors.setdefault(bay, []).append(color)
        for (x_idx, y_idx), colors in addl_bay_colors.items():
            if (x_idx, y_idx) not in active_bays or not colors:
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            if len(colors) == 1:
                ax.add_patch(
                    mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=colors[0], edgecolor="none", alpha=0.50, zorder=1)
                )
                continue
            n = len(colors)
            for i, color in enumerate(colors):
                seg_x0 = x0 + ((x1 - x0) * i / n)
                seg_x1 = x0 + ((x1 - x0) * (i + 1) / n)
                ax.add_patch(
                    mpatches.Rectangle((seg_x0, y0), seg_x1 - seg_x0, y1 - y0, facecolor=color, edgecolor="none", alpha=0.50, zorder=1)
                )
        for x_idx, y_idx in self.inactive_bays:
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
            y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
            ax.add_patch(
                mpatches.Rectangle(
                    (x0, y0),
                    x1 - x0,
                    y1 - y0,
                    facecolor="#96a3b3",
                    edgecolor="#6a7483",
                    linewidth=0.75,
                    hatch="///",
                    alpha=0.92,
                    zorder=1,
                )
            )

        # Base grid.
        for x in x_lines:
            ax.plot([x, x], [0, total_y], color="#6d7d8f", linewidth=0.6, linestyle=(0, (3, 4)), zorder=2)
        for y in y_lines:
            ax.plot([0, total_x], [y, y], color="#6d7d8f", linewidth=0.6, linestyle=(0, (3, 4)), zorder=2)

        # Steel girders (geometry).
        for y_line_idx in range(0, len(self.model.y_spans) + 1):
            y = y_lines[y_line_idx]
            for x_idx in range(len(self.model.x_spans)):
                if not self._horizontal_segment_has_steel_girder(
                    y_line_idx, x_idx, active_bays=active_bays, boundary_segments=boundary_segments
                ):
                    continue
                x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
                ax.plot([x0, x1], [y, y], color="#111827", linewidth=1.35, zorder=5)

        # Load-bearing wall boundaries.
        for edge in sorted(self.load_bearing_perimeter):
            seg = self._edge_to_world_segment(edge)
            if not seg:
                continue
            x1, y1, x2, y2 = seg
            ax.plot([x1, x2], [y1, y2], color="#b23a48", linewidth=2.6, zorder=7)

        # Joists and joist labels by bay.
        try:
            default_spaces = self.get_default_joist_count()
        except InputValidationError:
            default_spaces = 7

        for x_idx in range(len(self.model.x_spans)):
            for y_idx in range(len(self.model.y_spans)):
                if (x_idx, y_idx) not in active_bays:
                    continue
                spaces = int(self.joists_per_bay.get((x_idx, y_idx), default_spaces))
                if spaces <= 0:
                    continue

                x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
                y0, y1 = y_lines[y_idx], y_lines[y_idx + 1]
                spacing_ft = (x1 - x0) / spaces
                member_count = spaces + 1

                for i in range(member_count):
                    xpos = x0 + spacing_ft * i
                    if i == 0:
                        west_edge = ("V", x_idx, y_idx)
                        if (x_idx - 1, y_idx) in active_bays:
                            continue
                        if west_edge in boundary_segments and west_edge in self.load_bearing_perimeter:
                            continue
                    if i == (member_count - 1):
                        east_edge = ("V", x_idx + 1, y_idx)
                        if east_edge in boundary_segments and east_edge in self.load_bearing_perimeter:
                            continue
                    ax.plot([xpos, xpos], [y0, y1], color="#334155", linewidth=0.52, alpha=0.90, zorder=4)

        # Girder designation labels: label every steel girder segment.
        girder_font = max(4.2, detail_font - 0.35)
        for y_line_idx in range(0, len(self.model.y_spans) + 1):
            y = y_lines[y_line_idx]
            for x_idx in range(len(self.model.x_spans)):
                if not self._horizontal_segment_has_steel_girder(
                    y_line_idx, x_idx, active_bays=active_bays, boundary_segments=boundary_segments
                ):
                    continue
                des = str(girder_map.get((y_line_idx, x_idx), "") or "").strip()
                if not des:
                    continue
                x0 = x_lines[x_idx]
                x1 = x_lines[x_idx + 1]
                xm = (x0 + x1) / 2.0
                offset_cycle = (-1.0, 1.0, -1.8, 1.8)
                yoff = offset_cycle[(x_idx + y_line_idx) % len(offset_cycle)]
                label_y = max(y_top + 0.8, min(y_bottom - 0.8, y + yoff))
                _draw_fixed_label(
                    xm,
                    label_y,
                    des,
                    girder_font,
                    color="#0f172a",
                    zorder=8,
                    ha="center",
                    va="center",
                    bbox_alpha=0.76,
                    bbox_pad=0.10,
                )

        # Joist designation labels (run-based per row to prevent clutter).
        show_spacing_detail = density <= 11
        for y_idx in range(len(self.model.y_spans)):
            run_start = None
            run_key = None
            for x_idx in range(len(self.model.x_spans) + 1):
                if x_idx < len(self.model.x_spans) and (x_idx, y_idx) in active_bays:
                    spaces = int(self.joists_per_bay.get((x_idx, y_idx), default_spaces))
                    x0, x1 = x_lines[x_idx], x_lines[x_idx + 1]
                    spacing_ft = (x1 - x0) / max(1, spaces)
                    joist_des = str(joist_map.get((x_idx, y_idx), "") or "").strip()
                    key = (joist_des, spaces, round(spacing_ft, 2)) if joist_des else None
                else:
                    key = None

                if key and run_start is None:
                    run_start = x_idx
                    run_key = key
                elif run_start is not None and key != run_key:
                    x0 = x_lines[run_start]
                    x1 = x_lines[x_idx]
                    y0 = y_lines[y_idx]
                    y1 = y_lines[y_idx + 1]
                    run_w = x1 - x0
                    bay_h = y1 - y0
                    des, spaces, spacing_ft = run_key
                    if run_w >= 12.0 and bay_h >= 11.0:
                        xm = (x0 + x1) / 2.0
                        ym = (y0 + y1) / 2.0
                        label_text = des
                        if show_spacing_detail and run_w >= 22.0 and bay_h >= 14.0:
                            label_text = f"{des}\n{spaces} SP @ {self._fmt_ft_arch(spacing_ft)}"
                        _place_label(
                            xm,
                            ym,
                            label_text,
                            member_font,
                            color="#0b2942",
                            zorder=9,
                            ha="center",
                            va="center",
                            try_offsets=[(0.0, -0.2), (0.0, 0.8), (0.0, -1.0)],
                            bbox_alpha=0.72,
                            bbox_pad=0.14,
                        )
                    run_start = x_idx if key else None
                    run_key = key if key else None

        # Columns + labels.
        for x_idx in range(0, len(x_lines)):
            for y_idx in range(0, len(y_lines)):
                if not self._column_has_steel_support(x_idx, y_idx, active_bays, boundary_segments):
                    continue
                x = x_lines[x_idx]
                y = y_lines[y_idx]
                ax.add_patch(
                    mpatches.Rectangle((x - 0.65, y - 0.65), 1.3, 1.3, facecolor="#111111", edgecolor="#111111", zorder=10)
                )

        # Column designation labels: label every steel-supported column with offset and leader.
        for x_idx in range(0, len(x_lines)):
            for y_idx in range(0, len(y_lines)):
                if not self._column_has_steel_support(x_idx, y_idx, active_bays, boundary_segments):
                    continue
                designation = str(column_map.get((x_idx, y_idx), "") or "").strip()
                if not designation:
                    continue

                x = x_lines[x_idx]
                y = y_lines[y_idx]
                placed = False
                candidate_offsets = [
                    (1.8, 3.0, "left"),
                    (-1.8, 3.0, "right"),
                    (1.8, -3.0, "left"),
                    (-1.8, -3.0, "right"),
                    (2.6, 3.7, "left"),
                    (-2.6, 3.7, "right"),
                    (2.6, -3.7, "left"),
                    (-2.6, -3.7, "right"),
                ]
                for dx, dy, ha in candidate_offsets:
                    lx = x + dx
                    ly = y + dy
                    box = _label_box(lx, ly, designation, column_font, ha=ha, va="center")
                    if box[0] < x_min or box[1] > x_max or box[2] < y_top or box[3] > y_bottom:
                        continue
                    if any(_intersects(box, other, pad=0.10) for other in occupied_boxes):
                        continue
                    ax.plot([x, lx], [y, ly], color="#6b7280", linewidth=0.35, alpha=0.9, zorder=10)
                    ax.text(
                        lx,
                        ly,
                        designation,
                        ha=ha,
                        va="center",
                        fontsize=column_font,
                        color="#111827",
                        bbox={"facecolor": "#ffffff", "edgecolor": "none", "alpha": 0.76, "pad": 0.08},
                        zorder=11,
                    )
                    occupied_boxes.append(box)
                    placed = True
                    break

                if not placed:
                    # Guaranteed label fallback with stronger offset.
                    dx = 3.4 if (x_idx % 2 == 0) else -3.4
                    dy = 4.2 if ((x_idx + y_idx) % 2 == 0) else -4.2
                    lx = x + dx
                    ly = y + dy
                    ha = "left" if dx > 0 else "right"
                    ax.plot([x, lx], [y, ly], color="#6b7280", linewidth=0.35, alpha=0.9, zorder=10)
                    _draw_fixed_label(
                        lx,
                        ly,
                        designation,
                        column_font,
                        color="#111827",
                        zorder=11,
                        ha=ha,
                        va="center",
                        bbox_alpha=0.76,
                        bbox_pad=0.08,
                    )

        # Grid labels.
        for i, x in enumerate(x_lines):
            ax.text(x, -3.9, str(i + 1), ha="center", va="bottom", fontsize=axis_font, fontweight="bold", color=palette["text"])
        for i, y in enumerate(y_lines):
            ax.text(-4.2, y, axis_letter(i), ha="right", va="center", fontsize=axis_font, fontweight="bold", color=palette["text"])

        # Notes + legend.
        ax.text(
            0.01,
            0.985,
            "Labels are sourced from assigned schedules. Every girder/column is labeled; joist labels are density-aware.",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=max(5.0, detail_font),
            color=palette["muted"],
        )
        legend_items = [
            mpatches.Patch(facecolor="#334155", edgecolor="none", label="Joists"),
            mpatches.Patch(facecolor="#111827", edgecolor="none", label="Girders"),
            mpatches.Patch(facecolor="#111111", edgecolor="none", label="Columns"),
            mpatches.Patch(facecolor="#b23a48", edgecolor="none", label="Load-Bearing Wall"),
            mpatches.Patch(facecolor="#c7f0d6", edgecolor="none", label="Collateral Bay"),
            mpatches.Patch(facecolor="#f8ddb0", edgecolor="none", label="Additional Load Bay"),
            mpatches.Patch(facecolor="#96a3b3", edgecolor="#6a7483", hatch="///", label="Void Bay"),
        ]
        for layer in self.additional_load_layers[:4]:
            legend_items.append(
                mpatches.Patch(
                    facecolor=self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8"),
                    edgecolor="none",
                    label=f"Addl: {str(layer.get('name', 'Layer'))[:16]}",
                )
            )
        ax.legend(
            handles=legend_items,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.045),
            ncol=3,
            frameon=True,
            facecolor="#ffffff",
            edgecolor=palette["border"],
            fontsize=max(5.8, detail_font + 0.2),
        )

        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_bottom, y_top)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(
            f"Adaptive label scale for readability | {len(self.model.x_spans)} X-bays x {len(self.model.y_spans)} Y-bays",
            fontsize=max(6.2, detail_font + 0.5),
            color=palette["muted"],
            pad=8,
        )
        fig.tight_layout(rect=(0, 0.055, 1, 0.95))
        return fig

    def _build_roof_report_figure(self):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        fig.patch.set_facecolor("#f2f4f7")
        ax.set_facecolor("#f7f9fb")

        profile = self._build_roof_profile_data()
        if not profile:
            ax.axis("off")
            ax.text(0.5, 0.5, "Roof profile unavailable.", ha="center", va="center", fontsize=14, color="#666666")
            return fig

        y_spans = profile["y_spans"]
        y_lines = profile["y_lines"]
        total_len_ft = profile["total_len_ft"]
        roof_type = profile["roof_type"]
        single_slope_direction = profile.get("single_slope_direction", "North")
        break_clear_height = profile["break_clear_height"]
        clear_height_ft = profile["clear_height_ft"]
        start_station_ft = profile["start_station_ft"]
        start_height_ft = profile["start_height_ft"]
        ridge_station_ft = profile["ridge_station_ft"]
        speed_bay_side = profile.get("speed_bay_side", "None")
        speed_rows = profile.get("speed_bay_rows", [])
        transition_lines = profile.get("speed_transition_line_indices", [])
        line_toj_elevations_ft = profile.get("line_toj_elevations_ft", profile["line_roof_heights"])
        allowed_depths = self._get_allowed_girder_depth_by_line_in()
        north_lb = self._is_side_fully_load_bearing("N")
        south_lb = self._is_side_fully_load_bearing("S")

        jb_drop_in_by_line = self._get_jb_drop_in_by_line(profile)
        line_jb_elevations_ft = [
            max(0.0, float(toj) - (float(jb_drop_in_by_line.get(idx, 0.0)) / 12.0))
            for idx, toj in enumerate(line_toj_elevations_ft)
        ]

        xs = [total_len_ft * i / 220.0 for i in range(221)]
        zs = [self._interpolate_profile_height(x, y_lines, line_toj_elevations_ft) for x in xs]
        max_toj = max(zs) if zs else clear_height_ft

        x_pad_left = max(5.0, total_len_ft * 0.06)
        x_pad_right = max(8.0, total_len_ft * 0.10)
        y_bottom = -2.6
        y_top = max_toj + 5.0

        # Section title block (same intent as app view, simplified for PDF).
        fig.suptitle("Roof Section X-X", fontsize=22, fontweight="bold", color="#262626", y=0.97)
        fig.text(
            0.03,
            0.932,
            "Type: {rtype} | Rise: {rise} | Break CH: {break_ch} | Speed Rows: {speed_rows} | "
            "Transitions: {trans} | Speed Side: {speed_side} | Slope: {slope_note} | J/B = TOJ - Seat".format(
                rtype=roof_type,
                rise=single_slope_direction if str(roof_type).strip().lower() == "single slope" else "N/A",
                break_ch="Yes" if break_clear_height else "No",
                speed_rows=(
                    ", ".join(f"{axis_letter(i)}-{axis_letter(i + 1)}" for i in speed_rows) if speed_rows else "None"
                ),
                trans=(", ".join(axis_letter(i) for i in transition_lines) if transition_lines else "None"),
                speed_side=speed_bay_side,
                slope_note=("1/4 in/ft main, 1/2 in/ft in speed bay" if break_clear_height else "1/4 in/ft"),
            ),
            ha="left",
            va="top",
            fontsize=10.0,
            color="#465c76",
        )
        ax.set_title("BMD, J/B, and Girder Depth (G) shown at each line", fontsize=12, color="#4b5f78", pad=6)

        # Floor and clear-height references.
        ax.plot([-x_pad_left * 0.12, total_len_ft + x_pad_right], [0.0, 0.0], color="#555555", linewidth=2.0, zorder=1)
        ax.plot(
            [-x_pad_left * 0.12, total_len_ft + x_pad_right],
            [clear_height_ft, clear_height_ft],
            color="#7a7a7a",
            linewidth=1.0,
            linestyle=(0, (10, 6)),
            zorder=1,
        )
        ax.text(
            total_len_ft + (x_pad_right * 0.18),
            clear_height_ft + 0.05,
            f"CLEAR HEIGHT  {self._fmt_ft_arch(clear_height_ft)}",
            fontsize=10,
            color="#4c4c4c",
            ha="left",
            va="bottom",
        )
        ax.text(
            total_len_ft + (x_pad_right * 0.18),
            0.0,
            "T/SLAB  0'-0\"",
            fontsize=9.5,
            color="#444444",
            ha="left",
            va="center",
        )

        # Roof line (BMD/TOJ).
        ax.plot(xs, zs, color="#8d2e2e", linewidth=3.0, zorder=5)

        density = len(y_lines)
        callout_fs = 9.0 if density <= 6 else 8.0 if density <= 10 else 7.0
        g_fs = max(6.7, callout_fs - 0.6)
        badge_shift_x = max(1.6, min(4.8, total_len_ft * 0.025))

        # Vertical lines, line bubbles, dock indicator, and line annotations.
        for idx, x in enumerate(y_lines):
            toj = float(line_toj_elevations_ft[idx])
            jb = float(line_jb_elevations_ft[idx])
            is_edge = idx in (0, len(y_lines) - 1)
            line_w = 3.2 if is_edge else 1.7
            line_color = "#3e3e3e" if is_edge else "#595959"
            ax.plot([x, x], [0.0, toj], color=line_color, linewidth=line_w, zorder=2)

            # Line bubble at base.
            bubble_y = -1.25
            ax.scatter([x], [bubble_y], s=330, facecolors="#ffffff", edgecolors="#2d2d2d", linewidths=1.0, zorder=8)
            ax.text(x, bubble_y, axis_letter(idx), ha="center", va="center", fontsize=10, fontweight="bold", color="#222222", zorder=9)

            # Speed transition marker(s).
            if idx in transition_lines:
                ax.plot([x, x], [y_bottom + 0.2, y_top - 0.2], color="#2b9348", linewidth=1.2, linestyle=(0, (2, 2)), zorder=1)
                ax.text(
                    x + 0.35,
                    y_top - 0.45,
                    f"Transition {axis_letter(idx)}",
                    ha="left",
                    va="top",
                    fontsize=10,
                    color="#2b9348",
                    bbox=dict(facecolor="#e9f8ee", edgecolor="#86c49a", pad=2.2),
                    zorder=10,
                )

            # BMD + J/B callout near roof node.
            side = 1.0 if (idx % 2 == 0) else -1.0
            if idx == 0:
                side = 1.0
            elif idx == (len(y_lines) - 1):
                side = -1.0
            tx = x + (badge_shift_x * side)
            ty = toj + 0.9 + ((idx % 3) * 0.38)
            ax.plot([x, tx], [toj, ty - 0.08], color="#ba8f8f", linewidth=0.9, zorder=6)
            ax.text(
                tx,
                ty,
                f"BMD {self._fmt_ft_arch(toj)}\nJ/B {self._fmt_ft_arch(jb)}",
                ha="left" if side > 0 else "right",
                va="bottom",
                fontsize=callout_fs,
                color="#2f2f2f",
                linespacing=1.07,
                bbox=dict(facecolor="#f9f9fb", edgecolor="#d5dbe3", pad=1.7, alpha=0.96),
                zorder=7,
            )

            # Girder depth label centered above clear-height line on each line.
            hide_depth_here = (idx == 0 and north_lb) or (idx == (len(y_lines) - 1) and south_lb)
            if not hide_depth_here:
                g_in = float(allowed_depths.get(idx, (toj - clear_height_ft) * 12.0))
                gy = clear_height_ft + max(0.35, (toj - clear_height_ft) * 0.55)
                ax.text(
                    x,
                    gy,
                    f"G {g_in:.1f} in",
                    ha="center",
                    va="center",
                    fontsize=g_fs,
                    color="#1f5a8c",
                    fontweight="bold",
                    bbox=dict(facecolor="#f2f8ff", edgecolor="#a6c0de", pad=1.2, alpha=0.95),
                    zorder=7,
                )

        # Span labels.
        for i, span in enumerate(y_spans):
            xm = (y_lines[i] + y_lines[i + 1]) / 2.0
            ax.text(xm, -2.0, self._fmt_ft_arch(span), ha="center", va="top", fontsize=10, color="#5a4230")

        ax.set_xlim(-x_pad_left, total_len_ft + x_pad_right)
        ax.set_ylim(y_bottom, y_top)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        fig.tight_layout(rect=(0, 0, 1, 0.91))
        return fig

    def _build_tilt_wall_report_figure(self):
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        palette = self._report_palette()
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))
        fig.patch.set_facecolor(palette["bg"])
        fig.suptitle("Tilt Wall Elevations", fontsize=19, fontweight="bold", color=palette["header"], y=0.97)

        try:
            data = self._calculate_tilt_wall_takeoff()
        except Exception:
            for ax in axes.ravel():
                ax.axis("off")
            fig.text(0.5, 0.5, "Tilt wall data unavailable.", ha="center", va="center", fontsize=14, color="#666666")
            return fig

        north = data["north_wall"]
        south = data["south_wall"]
        east = data["east_wall"]
        west = data["west_wall"]

        max_h = max(
            north["center_height_ft"],
            south["center_height_ft"],
            max(seg["wall_height_ft"] for seg in east["step_segments"]) if east["step_segments"] else 0.0,
            1.0,
        )

        def _draw_ns_wall_axis(ax, wall, side_name: str):
            dock_tag = "/Dock" if wall.get("is_dock_side") else ""
            ax.set_title(f"{side_name}{dock_tag} ({wall['area_sf']:.1f} sf)", fontsize=10, fontweight="bold")
            if wall.get("is_dock_side"):
                x0 = 0.0
                for seg_len, seg_h, color in [
                    (wall["left_edge_length_ft"], wall["edge_height_ft"], "#f7e1d8" if side_name == "South" else "#dbe9f8"),
                    (wall["center_length_ft"], wall["center_height_ft"], "#f5d3c6" if side_name == "South" else "#c9dcf4"),
                    (wall["right_edge_length_ft"], wall["edge_height_ft"], "#f7e1d8" if side_name == "South" else "#dbe9f8"),
                ]:
                    ax.add_patch(
                        mpatches.Rectangle(
                            (x0, 0),
                            seg_len,
                            seg_h,
                            facecolor=color,
                            edgecolor="#9b4f2f" if side_name == "South" else "#3f6a9e",
                        )
                    )
                    x0 += seg_len
            else:
                ax.add_patch(
                    mpatches.Rectangle(
                        (0, 0),
                        wall["length_ft"],
                        wall["wall_height_ft"],
                        facecolor="#f7e1d8" if side_name == "South" else "#d9e6f5",
                        edgecolor="#9b4f2f" if side_name == "South" else "#3f6a9e",
                    )
                )
            ax.text(
                0.02,
                0.96,
                f"TOR {self._fmt_ft_arch(wall['top_of_roof_ft'])}",
                transform=ax.transAxes,
                va="top",
                fontsize=8,
            )

        _draw_ns_wall_axis(axes[0, 0], north, "North")
        _draw_ns_wall_axis(axes[1, 0], south, "South")

        for ax, wall, title in [(axes[0, 1], east, f"East ({east['area_sf']:.1f} sf)"), (axes[1, 1], west, f"West ({west['area_sf']:.1f} sf)")]:
            ax.set_title(title, fontsize=10, fontweight="bold")
            x = 0.0
            for seg in wall["step_segments"]:
                seg_len = seg["bay_length_ft"]
                seg_h = seg["wall_height_ft"]
                ax.add_patch(mpatches.Rectangle((x, 0), seg_len, seg_h, facecolor="#dff1df", edgecolor="#3f8a3f"))
                ax.text(
                    x + seg_len / 2.0,
                    seg_h + 0.25,
                    f"TOR {self._fmt_ft_arch(seg['top_of_roof_ft'])}",
                    ha="center",
                    va="bottom",
                    fontsize=6.8,
                    color="#2f6f2f",
                )
                x += seg_len

        axis_meta = [
            (axes[0, 0], north["length_ft"]),
            (axes[1, 0], south["length_ft"]),
            (axes[0, 1], east["length_ft"]),
            (axes[1, 1], west["length_ft"]),
        ]
        for ax, x_len in axis_meta:
            ax.set_ylim(0, max_h * 1.1)
            ax.set_xlim(0, max(1.0, x_len))
            ax.set_xlabel("Length (ft)", fontsize=8, color=palette["muted"])
            ax.set_ylabel("Height (ft)", fontsize=8, color=palette["muted"])
            ax.grid(alpha=0.16, color="#c2d0de")
            for spine in ax.spines.values():
                spine.set_color(palette["border"])
                spine.set_linewidth(0.9)

        fig.tight_layout(rect=(0, 0, 1, 0.95))
        return fig

    def _build_pdf_joist_rows(self):
        rows = []
        groups = (self.last_joist_result or {}).get("joist_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = group["group_id"]
            assigned = self.joist_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            display_count = int(group.get("count", 0) or 0)
            group_wt = None
            if wt_plf is not None:
                group_wt = float(wt_plf) * float(group.get("total_span_ft", 0.0) or 0.0)

            rows.append(
                [
                    f"J{idx:03d}",
                    self._fmt_int(display_count),
                    self._fmt_num(group.get("required_capacity_plf", 0.0), 2),
                    self._fmt_ft_arch(group.get("required_length_ft", 0.0)),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_girder_rows(self):
        rows = []
        groups = (self.last_girder_result or {}).get("girder_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = group["group_id"]
            assigned = self.girder_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            group_wt = None
            if wt_plf is not None:
                group_wt = float(wt_plf) * float(group.get("total_span_ft", 0.0))

            rows.append(
                [
                    f"G{idx:03d}",
                    self._fmt_int(group.get("count", 0)),
                    self._fmt_num(group.get("required_capacity_lbs", 0.0), 2),
                    self._fmt_ft_arch(group.get("required_length_ft", 0.0)),
                    self._fmt_int(group.get("required_joist_n", 0)),
                    self._fmt_num(group.get("max_depth_in", 0.0), 2),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_column_rows(self):
        rows = []
        groups = (self.last_column_result or {}).get("column_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = group["group_id"]
            assigned = self.column_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            group_wt = None
            if wt_plf is not None:
                group_wt = float(wt_plf) * float(group.get("total_height_ft", 0.0))

            rows.append(
                [
                    f"C{idx:03d}",
                    self._fmt_int(group.get("count", 0)),
                    self._fmt_num(group.get("required_capacity_kips", 0.0), 2),
                    self._fmt_ft_arch(group.get("avg_height_ft", 0.0)),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_mezz_joist_rows(self):
        rows = []
        groups = (self.last_mezz_result or {}).get("mezzanine_joist_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = str(group.get("group_id", ""))
            assigned = self.mezz_joist_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            group_wt = None
            if wt_plf is not None:
                group_wt = float(wt_plf) * float(group.get("total_span_ft", 0.0) or 0.0)
            rows.append(
                [
                    f"MJ{idx:03d}",
                    self._fmt_int(group.get("count", 0)),
                    self._fmt_num(group.get("required_capacity_plf", 0.0), 2),
                    self._fmt_ft_arch(group.get("required_length_ft", 0.0)),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_mezz_girder_rows(self):
        rows = []
        groups = (self.last_mezz_result or {}).get("mezzanine_girder_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = str(group.get("group_id", ""))
            assigned = self.mezz_girder_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            group_wt = None
            if wt_plf is not None:
                group_wt = float(wt_plf) * float(group.get("total_span_ft", 0.0) or 0.0)
            rows.append(
                [
                    f"MG{idx:03d}",
                    self._fmt_int(group.get("count", 0)),
                    self._fmt_num(group.get("required_capacity_lbs", 0.0), 2),
                    self._fmt_ft_arch(group.get("required_length_ft", 0.0)),
                    self._fmt_int(group.get("required_joist_n", 0)),
                    self._fmt_num(group.get("min_depth_in", group.get("max_depth_in", 30.0)), 2),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_mezz_column_rows(self):
        rows = []
        groups = (self.last_mezz_result or {}).get("mezzanine_column_demand_groups", [])
        for idx, group in enumerate(groups, start=1):
            group_id = str(group.get("group_id", ""))
            assigned = self.mezz_column_selection_by_group.get(group_id, {})
            designation = str(assigned.get("designation", "") or "-")
            depth_in = assigned.get("depth_in")
            wt_plf = assigned.get("weight_plf")
            group_wt = None
            if wt_plf is not None:
                total_height_ft = float(group.get("total_height_ft", 0.0) or 0.0)
                if total_height_ft <= 0.0:
                    height_ft = float(group.get("column_height_ft", group.get("avg_height_ft", 0.0)) or 0.0)
                    total_height_ft = max(0.0, height_ft) * float(group.get("count", 0) or 0)
                group_wt = float(wt_plf) * total_height_ft
            rows.append(
                [
                    f"MC{idx:03d}",
                    self._fmt_int(group.get("count", 0)),
                    self._fmt_num(group.get("required_capacity_kips", 0.0), 2),
                    self._fmt_ft_arch(group.get("column_height_ft", 0.0)),
                    str(group.get("main_or_mezz_column", "Mezz")),
                    designation,
                    self._fmt_num(depth_in, 2) if depth_in is not None else "-",
                    self._fmt_num(wt_plf, 2) if wt_plf is not None else "-",
                    self._fmt_num(group_wt, 2) if group_wt is not None else "-",
                ]
            )
        return rows

    def _build_pdf_mezz_footing_rows(self):
        rows = []
        for row in (self.last_mezz_footing_result or {}).get("column_footings", []):
            rows.append(
                [
                    str(row.get("column_id", "-")),
                    str(row.get("grid", "-")),
                    str(row.get("zone_name", "-")),
                    self._fmt_num(float(row.get("required_capacity_kips", 0.0) or 0.0), 2),
                    self._fmt_ft_arch(float(row.get("footing_size_raw_ft", 0.0) or 0.0)),
                    self._fmt_ft_arch(float(row.get("footing_size_ft", 0.0) or 0.0)),
                    self._fmt_ft_arch(float(row.get("footing_depth_ft", 0.0) or 0.0)),
                    self._fmt_num(float(row.get("footing_volume_cy", 0.0) or 0.0), 3),
                ]
            )
        return rows

    def _add_mezzanine_zone_drawing_pages(self, pdf):
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        zones = list((self.last_mezz_result or {}).get("mezzanine_zones", []))
        if not zones:
            return

        palette = self._report_palette()
        mezz_joist_rows = list((self.last_mezz_result or {}).get("mezzanine_joist_calculations", []))
        mezz_girder_rows = list((self.last_mezz_result or {}).get("mezzanine_girder_calculations", []))
        mezz_columns = list((self.last_mezz_result or {}).get("mezzanine_column_calculations", []))

        def _build_nodes(total_ft, segments):
            nodes = [0.0]
            run = 0.0
            for seg in self._fit_mezz_zone_segments(total_ft, segments):
                run += float(seg)
                nodes.append(min(run, float(total_ft)))
            if abs(nodes[-1] - total_ft) > 1e-6:
                nodes.append(float(total_ft))
            return nodes

        def _joist_group_id(row):
            existing = str(row.get("group_id", "") or "").strip()
            if existing:
                return existing
            req = round(float(row.get("required_capacity_plf", 0.0) or 0.0), 2)
            span = round(float(row.get("joist_span_ft", 0.0) or 0.0), 2)
            return f"{req:.2f}|{span:.2f}"

        def _girder_group_id(row):
            existing = str(row.get("group_id", "") or "").strip()
            if existing:
                return existing
            req = round(float(row.get("required_capacity_lbs", 0.0) or 0.0), 2)
            span = round(float(row.get("span_ft", 0.0) or 0.0), 2)
            req_n = int(row.get("required_joist_n", 0) or 0)
            max_depth = round(float(row.get("max_depth_in", 30.0) or 30.0), 2)
            return f"{req:.2f}|{span:.2f}|{req_n}|{max_depth:.2f}"

        def _column_group_id(row):
            existing = str(row.get("group_id", "") or "").strip()
            if existing:
                return existing
            req = round(float(row.get("required_capacity_kips", 0.0) or 0.0), 2)
            hgt = round(float(row.get("column_height_ft", 0.0) or 0.0), 2)
            ctype = str(row.get("main_or_mezz_column", "Mezz"))
            return f"{req:.2f}|{hgt:.2f}|{ctype}"

        def _parse_panel_id(panel_id):
            token = str(panel_id or "")
            m = re.search(r"P(\d{2})(\d{2})$", token)
            if not m:
                return None
            return int(m.group(1)), int(m.group(2))

        def _parse_girder_id(gid):
            token = str(gid or "")
            m = re.search(r"-G-(\d+)-(\d+)$", token)
            if not m:
                return None
            return int(m.group(1)), int(m.group(2))

        for idx, zone in enumerate(zones, start=1):
            width_ft = float(zone.get("width_ft", 0.0) or 0.0)
            length_ft = float(zone.get("length_ft", 0.0) or 0.0)
            if width_ft <= 0.0 or length_ft <= 0.0:
                continue

            x0_ft = float(zone.get("x_start_ft", 0.0) or 0.0)
            y0_ft = float(zone.get("y_start_ft", 0.0) or 0.0)
            x1_ft = x0_ft + width_ft
            y1_ft = y0_ft + length_ft

            x_nodes = _build_nodes(width_ft, zone.get("internal_x_spacings_ft", []))
            y_nodes = _build_nodes(length_ft, zone.get("internal_y_spacings_ft", []))
            joist_dir = str(zone.get("joist_direction", "vertical")).strip().lower()
            default_spaces = max(1, int(zone.get("joist_spaces_per_bay", 1) or 1))
            override_spaces = {}
            for k, v in dict(zone.get("joist_spaces_overrides", {}) or {}).items():
                if not self._parse_mezz_panel_key(k):
                    continue
                try:
                    override_spaces[str(k)] = max(1, int(v))
                except (TypeError, ValueError):
                    continue

            zone_name = str(zone.get("name", f"Zone {idx}"))
            zone_id = str(zone.get("zone_id", zone.get("id", "")) or "")
            zone_joists = [
                row
                for row in mezz_joist_rows
                if (str(row.get("zone_id", "")) == zone_id) or (str(row.get("zone_name", "")) == zone_name)
            ]
            zone_girders = [
                row
                for row in mezz_girder_rows
                if (str(row.get("zone_id", "")) == zone_id) or (str(row.get("zone_name", "")) == zone_name)
            ]
            zone_columns = [
                row
                for row in mezz_columns
                if ((str(row.get("zone_id", "")) == zone_id) or (str(row.get("zone_name", "")) == zone_name))
                and str(row.get("main_or_mezz_column", "Mezz")).strip().lower() != "main"
            ]

            joist_design_by_panel = {}
            for row in zone_joists:
                panel_key = _parse_panel_id(row.get("panel_id", ""))
                if not panel_key:
                    continue
                group_id = _joist_group_id(row)
                selected = self.mezz_joist_selection_by_group.get(group_id, {})
                designation = str(selected.get("designation", "") or "").strip()
                if designation:
                    joist_design_by_panel[(panel_key[0], panel_key[1])] = designation

            girder_labels = []
            for row in zone_girders:
                parsed_gid = _parse_girder_id(row.get("girder_id", ""))
                if not parsed_gid:
                    continue
                group_id = _girder_group_id(row)
                selected = self.mezz_girder_selection_by_group.get(group_id, {})
                designation = str(selected.get("designation", "") or "").strip()
                if not designation:
                    continue
                girder_labels.append((parsed_gid[0], parsed_gid[1], designation))

            column_labels = []
            for row in zone_columns:
                group_id = _column_group_id(row)
                selected = self.mezz_column_selection_by_group.get(group_id, {})
                designation = str(selected.get("designation", "") or "").strip()
                if not designation:
                    continue
                cx = float(row.get("x_ft", 0.0) or 0.0) - x0_ft
                cy = float(row.get("y_ft", 0.0) or 0.0) - y0_ft
                if -1e-6 <= cx <= width_ft + 1e-6 and -1e-6 <= cy <= length_ft + 1e-6:
                    column_labels.append((cx, cy, designation))

            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            fig.patch.set_facecolor("#ffffff")
            ax.set_facecolor("#ffffff")

            # Outer frame / boundary
            ax.plot([0, width_ft], [0, 0], color="#111111", linewidth=1.8)
            ax.plot([0, width_ft], [length_ft, length_ft], color="#111111", linewidth=1.8)
            ax.plot([0, 0], [0, length_ft], color="#111111", linewidth=1.8)
            ax.plot([width_ft, width_ft], [0, length_ft], color="#111111", linewidth=1.8)

            # Internal bay/grid lines.
            for xv in x_nodes[1:-1]:
                ax.plot([xv, xv], [0, length_ft], color="#666666", linewidth=0.8, linestyle=(0, (4, 3)))
            for yv in y_nodes[1:-1]:
                ax.plot([0, width_ft], [yv, yv], color="#666666", linewidth=0.8, linestyle=(0, (4, 3)))

            # Girders (perpendicular to joists).
            if joist_dir.startswith("h"):
                for xv in x_nodes:
                    ax.plot([xv, xv], [0, length_ft], color="#000000", linewidth=1.0)
            else:
                for yv in y_nodes:
                    ax.plot([0, width_ft], [yv, yv], color="#000000", linewidth=1.0)

            # Joist lines and panel labels with per-panel spacing.
            panel_count_x = max(1, len(x_nodes) - 1)
            panel_count_y = max(1, len(y_nodes) - 1)
            avg_panel_w = width_ft / float(panel_count_x)
            avg_panel_h = length_ft / float(panel_count_y)
            dense_layout = (panel_count_x * panel_count_y) >= 18 or min(avg_panel_w, avg_panel_h) < 10.0
            show_panel_text = avg_panel_w >= 8.0 and avg_panel_h >= 7.0 and (panel_count_x * panel_count_y) <= 200
            joist_label_stride_x = 1 if avg_panel_w >= 18.0 else (2 if avg_panel_w >= 10.0 else 3)
            joist_label_stride_y = 1 if avg_panel_h >= 16.0 else (2 if avg_panel_h >= 9.0 else 3)
            if dense_layout:
                joist_label_stride_x = max(2, joist_label_stride_x)
                joist_label_stride_y = max(2, joist_label_stride_y)
            joist_fs = 6.6 if dense_layout else 7.1
            girder_fs = 6.1 if dense_layout else 6.6
            column_fs = 5.8 if dense_layout else 6.3
            placed_labels = {"joist": [], "girder": [], "column": []}
            shown_joist_labels = 0
            shown_girder_labels = 0
            shown_column_labels = 0

            def _can_place_label(xv, yv, min_dx_ft, min_dy_ft, bucket="joist"):
                entries = placed_labels.setdefault(str(bucket), [])
                for px, py in entries:
                    if abs(float(px) - float(xv)) < float(min_dx_ft) and abs(float(py) - float(yv)) < float(min_dy_ft):
                        return False
                entries.append((float(xv), float(yv)))
                return True

            for ix in range(1, len(x_nodes)):
                for iy in range(1, len(y_nodes)):
                    x_left = x_nodes[ix - 1]
                    x_right = x_nodes[ix]
                    y_bot = y_nodes[iy - 1]
                    y_top = y_nodes[iy]
                    pkey = f"{ix},{iy}"
                    spaces = max(1, int(override_spaces.get(pkey, default_spaces)))
                    if joist_dir.startswith("h"):
                        step = (y_top - y_bot) / float(spaces)
                        for i in range(spaces + 1):
                            yj = y_bot + (i * step)
                            ax.plot([x_left, x_right], [yj, yj], color="#2f3f56", linewidth=0.6, alpha=0.95)
                    else:
                        step = (x_right - x_left) / float(spaces)
                        for i in range(spaces + 1):
                            xj = x_left + (i * step)
                            ax.plot([xj, xj], [y_bot, y_top], color="#2f3f56", linewidth=0.6, alpha=0.95)

                    if show_panel_text and ((ix - 1) % joist_label_stride_x == 0) and ((iy - 1) % joist_label_stride_y == 0):
                        designation = joist_design_by_panel.get((ix, iy), "")
                        label = designation if designation else f"J{spaces}"
                        tx = (x_left + x_right) / 2.0
                        ty = (y_bot + y_top) / 2.0
                        if not _can_place_label(
                            tx, ty, max(4.0, avg_panel_w * 0.45), max(3.0, avg_panel_h * 0.45), bucket="joist"
                        ):
                            continue
                        ax.text(
                            tx,
                            ty,
                            label,
                            ha="center",
                            va="center",
                            fontsize=joist_fs,
                            color="#111827",
                            fontweight="bold",
                            bbox=dict(facecolor="#ffffff", edgecolor="none", alpha=0.35, pad=0.4),
                            zorder=6,
                        )
                        shown_joist_labels += 1

            # Girder labels per segment.
            girder_seg_stride = 1 if max(panel_count_x, panel_count_y) <= 8 else 2
            girder_line_stride = 1 if min(panel_count_x, panel_count_y) <= 6 else 2
            for line_idx, seg_idx, designation in girder_labels:
                if ((seg_idx - 1) % girder_seg_stride) != 0:
                    continue
                if ((line_idx - 1) % girder_line_stride) != 0:
                    continue
                if joist_dir.startswith("h"):
                    # Horizontal joists => girders on vertical x-lines.
                    if not (1 <= line_idx <= len(x_nodes) and 1 <= seg_idx <= (len(y_nodes) - 1)):
                        continue
                    gx = x_nodes[line_idx - 1]
                    gy = (y_nodes[seg_idx - 1] + y_nodes[seg_idx]) / 2.0
                    tx = gx + (0.40 if (seg_idx % 2) else -0.40)
                    ty = gy
                    if not _can_place_label(
                        tx, ty, max(4.0, avg_panel_w * 0.55), max(2.4, avg_panel_h * 0.40), bucket="girder"
                    ):
                        continue
                    ax.text(
                        tx,
                        ty,
                        designation,
                        ha="left" if (seg_idx % 2) else "right",
                        va="center",
                        fontsize=girder_fs,
                        color="#0b1220",
                        bbox=dict(facecolor="#ffffff", edgecolor="none", alpha=0.45, pad=0.25),
                        zorder=7,
                    )
                    shown_girder_labels += 1
                else:
                    # Vertical joists => girders on horizontal y-lines.
                    if not (1 <= line_idx <= len(y_nodes) and 1 <= seg_idx <= (len(x_nodes) - 1)):
                        continue
                    gx = (x_nodes[seg_idx - 1] + x_nodes[seg_idx]) / 2.0
                    gy = y_nodes[line_idx - 1]
                    tx = gx
                    ty = gy + (0.40 if (seg_idx % 2) else -0.40)
                    if not _can_place_label(
                        tx, ty, max(4.0, avg_panel_w * 0.55), max(2.4, avg_panel_h * 0.40), bucket="girder"
                    ):
                        continue
                    ax.text(
                        tx,
                        ty,
                        designation,
                        ha="center",
                        va="bottom" if (seg_idx % 2) else "top",
                        fontsize=girder_fs,
                        color="#0b1220",
                        bbox=dict(facecolor="#ffffff", edgecolor="none", alpha=0.45, pad=0.25),
                        zorder=7,
                    )
                    shown_girder_labels += 1

            # Mezz columns as filled squares with designation callouts.
            seen_col = set()
            for cx, cy, designation in column_labels:
                key = (round(cx, 3), round(cy, 3), designation)
                if key in seen_col:
                    continue
                seen_col.add(key)
                col_size = max(width_ft, length_ft) * 0.012
                col_size = min(1.0, max(0.25, col_size))
                ax.add_patch(
                    mpatches.Rectangle(
                        (cx - col_size / 2.0, cy - col_size / 2.0),
                        col_size,
                        col_size,
                        facecolor="#0d1117",
                        edgecolor="#0d1117",
                        linewidth=0.6,
                        zorder=8,
                    )
                )
                tx = cx + 0.65
                ty = cy + 0.55
                if not _can_place_label(
                    tx, ty, max(4.0, avg_panel_w * 0.60), max(2.6, avg_panel_h * 0.45), bucket="column"
                ):
                    continue
                ax.text(
                    tx,
                    ty,
                    designation,
                    ha="left",
                    va="bottom",
                    fontsize=column_fs,
                    color="#111827",
                    bbox=dict(facecolor="#ffffff", edgecolor="none", alpha=0.45, pad=0.25),
                    zorder=9,
                )
                shown_column_labels += 1

            # Dimension chains (top and left).
            pad_x = max(8.0, width_ft * 0.20)
            pad_y = max(8.0, length_ft * 0.20)
            top_dim_y = length_ft + pad_y * 0.32
            left_dim_x = -pad_x * 0.32
            for i in range(len(x_nodes) - 1):
                xa = x_nodes[i]
                xb = x_nodes[i + 1]
                ax.annotate(
                    "",
                    xy=(xb, top_dim_y),
                    xytext=(xa, top_dim_y),
                    arrowprops=dict(arrowstyle="<->", lw=0.7, color="#2a2a2a"),
                )
                ax.text(
                    (xa + xb) / 2.0,
                    top_dim_y + pad_y * 0.04,
                    self._fmt_ft_arch(xb - xa),
                    ha="center",
                    va="bottom",
                    fontsize=7.2,
                    color="#222222",
                )
                ax.plot([xa, xa], [length_ft, top_dim_y], color="#888888", linewidth=0.6)
                if i == len(x_nodes) - 2:
                    ax.plot([xb, xb], [length_ft, top_dim_y], color="#888888", linewidth=0.6)

            for i in range(len(y_nodes) - 1):
                ya = y_nodes[i]
                yb = y_nodes[i + 1]
                ax.annotate(
                    "",
                    xy=(left_dim_x, yb),
                    xytext=(left_dim_x, ya),
                    arrowprops=dict(arrowstyle="<->", lw=0.7, color="#2a2a2a"),
                )
                ax.text(
                    left_dim_x - pad_x * 0.04,
                    (ya + yb) / 2.0,
                    self._fmt_ft_arch(yb - ya),
                    ha="right",
                    va="center",
                    fontsize=7.2,
                    color="#222222",
                    rotation=90,
                )
                ax.plot([0, left_dim_x], [ya, ya], color="#888888", linewidth=0.6)
                if i == len(y_nodes) - 2:
                    ax.plot([0, left_dim_x], [yb, yb], color="#888888", linewidth=0.6)

            # Grid bubbles / line markers.
            x_start_label = str(zone.get("x_start_label", "1"))
            x_end_label = str(zone.get("x_end_label", "2"))
            x_labels = [x_start_label]
            for i in range(1, max(1, len(x_nodes) - 1)):
                if i == len(x_nodes) - 1:
                    break
                x_labels.append(f"{x_start_label}.{i}")
            x_labels.append(x_end_label)
            x_labels = x_labels[: len(x_nodes)]

            y_start_label = str(zone.get("y_start_label", "A"))
            y_end_label = str(zone.get("y_end_label", "B"))
            y_labels = [y_start_label]
            for i in range(1, max(1, len(y_nodes) - 1)):
                if i == len(y_nodes) - 1:
                    break
                y_labels.append(f"{y_start_label}.{i}")
            y_labels.append(y_end_label)
            y_labels = y_labels[: len(y_nodes)]

            bubble_y = length_ft + pad_y * 0.62
            for xv, label in zip(x_nodes, x_labels):
                ax.scatter([xv], [bubble_y], s=410, facecolors="#ffffff", edgecolors="#1a1a1a", linewidths=0.9, zorder=6)
                ax.text(xv, bubble_y, label, ha="center", va="center", fontsize=8.1, color="#1a1a1a", zorder=7, fontweight="bold")

            bubble_x = -pad_x * 0.62
            for yv, label in zip(y_nodes, y_labels):
                ax.scatter([bubble_x], [yv], s=410, facecolors="#ffffff", edgecolors="#1a1a1a", linewidths=0.9, zorder=6)
                ax.text(bubble_x, yv, label, ha="center", va="center", fontsize=8.1, color="#1a1a1a", zorder=7, fontweight="bold")

            # Joist direction arrow.
            if joist_dir.startswith("h"):
                y_arrow = max(0.5, length_ft * 0.08)
                ax.annotate(
                    "",
                    xy=(width_ft * 0.85, y_arrow),
                    xytext=(width_ft * 0.15, y_arrow),
                    arrowprops=dict(arrowstyle="-|>", lw=1.2, color="#1f2937"),
                )
            else:
                x_arrow = max(0.5, width_ft * 0.08)
                ax.annotate(
                    "",
                    xy=(x_arrow, length_ft * 0.85),
                    xytext=(x_arrow, length_ft * 0.15),
                    arrowprops=dict(arrowstyle="-|>", lw=1.2, color="#1f2937"),
                )

            # Summary labels.
            ax.text(
                width_ft * 0.5,
                length_ft + pad_y * 0.14,
                f"Labels shown: Joists {shown_joist_labels} | Girders {shown_girder_labels} | Columns {shown_column_labels}",
                ha="center",
                va="center",
                fontsize=8.4,
                color="#111827",
            )

            # Title / notes.
            fig.text(
                0.5,
                0.955,
                f"{zone_name.upper()} MEZZANINE FRAMING PLAN",
                ha="center",
                va="center",
                fontsize=18,
                fontweight="bold",
                color=palette["header"],
            )
            fig.text(
                0.5,
                0.925,
                (
                    f"Elev {self._fmt_ft_arch(zone.get('elevation_ft', 0.0))} | "
                    f"DL {self._fmt_num(zone.get('dead_load_psf', 0.0), 2)} psf | "
                    f"LL {self._fmt_num(zone.get('live_load_psf', 0.0), 2)} psf | "
                    f"Default J Spaces/Bay {self._fmt_int(zone.get('joist_spaces_per_bay', 0))}"
                ),
                ha="center",
                va="center",
                fontsize=9.6,
                color=palette["muted"],
            )
            fig.text(
                0.055,
                0.08,
                (
                    "NOTES:\n"
                    "1. Mezzanine joists auto-assigned from LH Joist Table.\n"
                    "2. Member labels are shown per panel/segment/node using assigned schedules.\n"
                    "3. Column markers shown are mezzanine-only columns.\n"
                    "4. Main-building column locations are reused and not double-counted in mezz steel weight."
                ),
                ha="left",
                va="bottom",
                fontsize=8.0,
                color="#333333",
            )

            ax.set_xlim(-pad_x, width_ft + pad_x)
            ax.set_ylim(-pad_y, length_ft + pad_y)
            ax.set_aspect("equal", adjustable="box")
            ax.axis("off")

            fig.tight_layout(rect=(0.02, 0.10, 0.98, 0.90))
            pdf.savefig(fig)
            plt.close(fig)

    def _build_company_pdf_report(self, output_path: Path, run_notes):
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        output_path = Path(output_path)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")

        palette = self._report_palette()
        weights = self._collect_weight_summary()
        joist_rows = self._build_pdf_joist_rows()
        girder_rows = self._build_pdf_girder_rows()
        column_rows = self._build_pdf_column_rows()
        mezz_joist_rows = self._build_pdf_mezz_joist_rows()
        mezz_girder_rows = self._build_pdf_mezz_girder_rows()
        mezz_column_rows = self._build_pdf_mezz_column_rows()
        mezz_footing_rows = self._build_pdf_mezz_footing_rows()
        footing_rows = []
        if self.last_footing_result:
            for row in self.last_footing_result.get("column_footings", []):
                footing_rows.append(
                    [
                        str(row["column_id"]),
                        str(row["grid"]),
                        self._fmt_num(float(row["required_capacity_kips"]), 2),
                        self._fmt_ft_arch(float(row["footing_size_raw_ft"])),
                        self._fmt_ft_arch(float(row["footing_size_ft"])),
                        self._fmt_ft_arch(float(row["footing_depth_ft"])),
                        self._fmt_num(float(row["footing_volume_cy"]), 3),
                    ]
                )

        tilt_summary = (self.last_tilt_result or {}).get("summary", {})
        footing_summary = (self.last_footing_result or {}).get("summary", {})
        mezz_summary = (self.last_mezz_result or {}).get("summary", {})
        mezz_footing_summary = (self.last_mezz_footing_result or {}).get("summary", {})
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        with PdfPages(output_path) as pdf:
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            fig.patch.set_facecolor(palette["bg"])
            ax.axis("off")
            fig.patches.append(
                mpatches.Rectangle((0.0, 0.915), 1.0, 0.085, transform=fig.transFigure, facecolor=palette["header"], edgecolor="none")
            )
            fig.text(
                0.03,
                0.955,
                "Structural Steel & Envelope Takeoff Report",
                fontsize=23,
                fontweight="bold",
                color=palette["header_text"],
                va="center",
            )
            fig.text(0.03, 0.908, f"Generated: {generated_at}", fontsize=10, color=palette["muted"])
            fig.text(
                0.03,
                0.885,
                f"Grid: {len(self.model.x_spans)} X-bays x {len(self.model.y_spans)} Y-bays | "
                f"Roof: {self.roof_type_var.get()} | Break CH: {'Yes' if self.break_clear_height_var.get() else 'No'}",
                fontsize=10,
                color=palette["muted"],
            )

            summary_rows = [
                ["Main Joist Weight (lbs)", self._fmt_num(weights["joist_lbs"], 2)],
                ["Main Girder Weight (lbs)", self._fmt_num(weights["girder_lbs"], 2)],
                ["Main Column Weight (lbs)", self._fmt_num(weights["column_lbs"], 2)],
                ["Main Steel Subtotal (lbs)", self._fmt_num(weights["total_steel_main_lbs"], 2)],
                ["Mezz Joist Weight (lbs)", self._fmt_num(weights["mezz_joist_lbs"], 2)],
                ["Mezz Girder Weight (lbs)", self._fmt_num(weights["mezz_girder_lbs"], 2)],
                ["Mezz Column Weight (lbs)", self._fmt_num(weights["mezz_column_lbs"], 2)],
                ["Mezz Steel Subtotal (lbs)", self._fmt_num(weights["total_steel_mezz_lbs"], 2)],
                ["Total Structural Steel Weight (lbs)", self._fmt_num(weights["total_steel_lbs"], 2)],
                ["Building Area (sf)", self._fmt_num(weights["building_area_sf"], 2)],
                [
                    "(Main Joist + Main Girder) / Building Area (psf)",
                    f"{self._fmt_num(weights['joist_girder_psf'], 3)} (Target {self._fmt_num(weights['target_psf'], 2)})",
                ],
                ["Mezzanine Area (sf)", self._fmt_num(float(mezz_summary.get("total_mezzanine_area_sf", 0.0)), 2)],
                ["Total Tilt Wall Area (sf)", self._fmt_num(float(tilt_summary.get("total_area_sf", 0.0)), 2)],
                [
                    "Main Pad Footing Concrete (CY, incl. 10% waste)",
                    self._fmt_num(float(footing_summary.get("total_cy_with_waste", 0.0)), 3),
                ],
                [
                    "Mezz Pad Footing Concrete (CY, incl. 10% waste)",
                    self._fmt_num(float(mezz_footing_summary.get("total_cy_with_waste", 0.0)), 3),
                ],
            ]
            tbl = ax.table(
                cellText=summary_rows,
                colLabels=["Metric", "Value"],
                loc="upper left",
                cellLoc="left",
                colLoc="left",
                bbox=[0.03, 0.43, 0.58, 0.38],
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(10.8)
            for (r, c), cell in tbl.get_celld().items():
                if r == 0:
                    cell.set_facecolor(palette["header"])
                    cell.set_text_props(color=palette["header_text"], fontweight="bold")
                else:
                    cell.set_facecolor(palette["alt"] if r % 2 == 0 else "#ffffff")
                cell.set_edgecolor(palette["border"])

            location_parts = [str(self.location_city_var.get() or "").strip(), str(self.location_state_var.get() or "").strip()]
            location_display = ", ".join([part for part in location_parts if part]) or "Not set"

            # Show the effective reduced snow load used by calculations.
            effective_snow_code = self._normalize_snow_code(self.snow_code_var.get())
            effective_reduced_snow = None
            effective_reduced_source = ""
            load_inputs_used = (self.last_joist_result or {}).get("load_inputs_psf", {})
            if load_inputs_used:
                effective_snow_code = self._normalize_snow_code(load_inputs_used.get("snow_code", effective_snow_code))
                effective_reduced_snow = load_inputs_used.get("reduced_snow_load_psf")
                effective_reduced_source = str(load_inputs_used.get("reduced_snow_load_source") or "").strip()

            if effective_reduced_snow is None:
                try:
                    snow_psf = float(self.snow_load_var.get())
                except (TypeError, ValueError):
                    snow_psf = 0.0
                if effective_snow_code == "ASCE 7-22":
                    try:
                        effective_reduced_snow = float(self.reduced_snow_load_manual_var.get())
                    except (TypeError, ValueError):
                        effective_reduced_snow = 0.0
                    effective_reduced_source = "Manual"
                else:
                    if snow_psf <= 20.0:
                        effective_reduced_snow = (snow_psf * 0.7) + 5.0
                    else:
                        effective_reduced_snow = max(snow_psf * 0.7, 20.0)
                    effective_reduced_source = "Auto"

            if not effective_reduced_source:
                effective_reduced_source = "Manual" if effective_snow_code == "ASCE 7-22" else "Auto"
            addl_layer_texts = []
            for layer in self.additional_load_layers:
                name = str(layer.get("name", "Additional")).strip() or "Additional"
                try:
                    psf = float(layer.get("psf", 0.0))
                except (TypeError, ValueError):
                    psf = 0.0
                addl_layer_texts.append(f"{name}({self._fmt_num(psf, 2)} psf)")
            addl_layers_display = ", ".join(addl_layer_texts) if addl_layer_texts else "None"
            if len(addl_layers_display) > 140:
                addl_layers_display = addl_layers_display[:137] + "..."

            inputs = (
                f"Loads (psf): DL={self.dead_load_var.get()} | LL={self.live_load_var.get()} | "
                f"SL={self.snow_load_var.get()} | Collateral+={self.collateral_addition_var.get()} | "
                f"Additional Layers={len(self.additional_load_layers)} | "
                f"Snow Code={effective_snow_code} | Reduced SL Used ({effective_reduced_source})="
                f"{self._fmt_num(effective_reduced_snow, 2)}\n"
                f"Additional Load Definitions: {addl_layers_display}\n"
                f"Location: {location_display}\n"
                f"Clear Height={self._fmt_ft_arch(self.clear_height_var.get())} | Joist Seat Depth={self.joist_seat_depth_var.get()} in | "
                f"Deck={self.metal_deck_thickness_var.get()} in | Insulation={self.insulation_depth_var.get()} in\n"
                f"Footing Depth={self._fmt_ft_arch(self.footing_depth_var.get())} | Bearing Pressure={self.bearing_pressure_var.get()} psi"
            )
            fig.text(0.03, 0.42, "Project Inputs", fontsize=12, fontweight="bold", color=palette["header"])
            fig.text(0.03, 0.386, inputs, fontsize=9.6, color=palette["text"], va="top")

            # Right-side highlight cards
            card_x = 0.66
            card_y = 0.73
            card_w = 0.30
            card_h = 0.10
            cards = [
                ("Total Steel", f"{self._fmt_num(weights['total_steel_lbs'], 0)} lbs"),
                ("(Main J+G)/Area Check", f"{self._fmt_num(weights['joist_girder_psf'], 3)} psf"),
                (
                    "Footing Concrete",
                    f"{self._fmt_num(float(footing_summary.get('total_cy_with_waste', 0.0) + mezz_footing_summary.get('total_cy_with_waste', 0.0)), 2)} CY",
                ),
            ]
            for title, value in cards:
                fig.patches.append(
                    mpatches.FancyBboxPatch(
                        (card_x, card_y),
                        card_w,
                        card_h,
                        boxstyle="round,pad=0.008,rounding_size=0.008",
                        transform=fig.transFigure,
                        facecolor="#ffffff",
                        edgecolor=palette["border"],
                        linewidth=1.0,
                    )
                )
                fig.text(card_x + 0.015, card_y + 0.064, title, fontsize=9, color=palette["muted"])
                fig.text(card_x + 0.015, card_y + 0.025, value, fontsize=15, fontweight="bold", color=palette["header"])
                card_y -= 0.125

            if run_notes:
                fig.text(0.03, 0.23, "Run Notes", fontsize=12, fontweight="bold", color=palette["header"])
                fig.text(0.03, 0.20, run_notes, fontsize=9, color=palette["text"], va="top")

            pdf.savefig(fig)
            plt.close(fig)

            fig = self._build_grid_plan_report_figure()
            pdf.savefig(fig)
            plt.close(fig)

            fig = self._build_roof_report_figure()
            pdf.savefig(fig)
            plt.close(fig)

            fig = self._build_tilt_wall_report_figure()
            pdf.savefig(fig)
            plt.close(fig)

            self._add_table_pages(
                pdf,
                title="Joist Assignment Schedule",
                headers=[
                    "Group",
                    "Qty",
                    "Req (plf)",
                    "Len (ft)",
                    "Joist",
                    "Depth (in)",
                    "Wt (plf)",
                    "Adj Group Wt (lbs)",
                ],
                rows=joist_rows,
                subtitle=f"Total Joist Weight = {self._fmt_num(weights['joist_lbs'], 2)} lbs",
                max_rows=28,
                col_widths=[0.09, 0.07, 0.13, 0.11, 0.16, 0.11, 0.11, 0.12],
                right_align_cols={1, 2, 3, 5, 6, 7},
            )

            self._add_table_pages(
                pdf,
                title="Girder Assignment Schedule",
                    headers=[
                        "Group",
                        "Qty",
                        "Req Cap (lbs)",
                        "Len (ft)",
                        "N",
                        "Min D (in)",
                        "Girder",
                        "Depth (in)",
                        "Wt (plf)",
                        "Group Wt (lbs)",
                    ],
                rows=girder_rows,
                subtitle=f"Total Girder Weight = {self._fmt_num(weights['girder_lbs'], 2)} lbs",
                max_rows=24,
                col_widths=[0.08, 0.06, 0.14, 0.09, 0.05, 0.09, 0.15, 0.10, 0.10, 0.14],
                right_align_cols={1, 2, 3, 4, 5, 7, 8, 9},
            )

            self._add_table_pages(
                pdf,
                title="Column Assignment Schedule",
                headers=[
                    "Group",
                    "Qty",
                    "Req (kips)",
                    "Avg Ht (ft)",
                    "Column",
                    "Depth (in)",
                    "Wt (plf)",
                    "Group Wt (lbs)",
                ],
                rows=column_rows,
                subtitle=f"Total Column Weight = {self._fmt_num(weights['column_lbs'], 2)} lbs",
                max_rows=28,
                col_widths=[0.09, 0.08, 0.14, 0.12, 0.20, 0.11, 0.11, 0.15],
                right_align_cols={1, 2, 3, 5, 6, 7},
            )

            if bool((self.last_mezz_result or {}).get("mezzanine_enabled")):
                fig, ax = plt.subplots(figsize=(11.69, 8.27))
                fig.patch.set_facecolor(palette["bg"])
                ax.axis("off")
                fig.patches.append(
                    mpatches.Rectangle(
                        (0.0, 0.915), 1.0, 0.085, transform=fig.transFigure, facecolor=palette["header"], edgecolor="none"
                    )
                )
                fig.text(
                    0.03,
                    0.955,
                    "Mezzanine Structural Takeoff",
                    fontsize=22,
                    fontweight="bold",
                    color=palette["header_text"],
                    va="center",
                )
                fig.text(
                    0.03,
                    0.89,
                    (
                        f"Zones: {self._fmt_int(mezz_summary.get('zone_count', 0))} | "
                        f"Area: {self._fmt_num(mezz_summary.get('total_mezzanine_area_sf', 0.0), 2)} sf | "
                        f"Panels: {self._fmt_int(mezz_summary.get('panel_count', 0))} | "
                        f"Reused Main Columns: {self._fmt_int(mezz_summary.get('reused_main_column_count', 0))}"
                    ),
                    fontsize=11,
                    color=palette["text"],
                )
                fig.text(
                    0.03,
                    0.855,
                    (
                        f"Assigned Mezz Steel: {self._fmt_num(weights.get('total_steel_mezz_lbs', 0.0), 2)} lbs "
                        f"(Joists {self._fmt_num(weights.get('mezz_joist_lbs', 0.0), 2)}, "
                        f"Girders {self._fmt_num(weights.get('mezz_girder_lbs', 0.0), 2)}, "
                        f"Columns {self._fmt_num(weights.get('mezz_column_lbs', 0.0), 2)})"
                    ),
                    fontsize=10.5,
                    color=palette["text"],
                )
                fig.text(
                    0.03,
                    0.825,
                    (
                        f"Mezz Footing Concrete (CY +10% waste): "
                        f"{self._fmt_num(mezz_footing_summary.get('total_cy_with_waste', 0.0), 3)}"
                    ),
                    fontsize=10.5,
                    color=palette["text"],
                )
                fig.text(
                    0.03,
                    0.79,
                    "Notes: Mezzanine girder assignment uses minimum depth 30 in (deeper only when required). "
                    "Roof slope and tilt-wall takeoff are not applied to mezzanine calculations.",
                    fontsize=9.4,
                    color=palette["muted"],
                )
                pdf.savefig(fig)
                plt.close(fig)

                # Mezzanine framing layout pages immediately follow mezz title page.
                self._add_mezzanine_zone_drawing_pages(pdf)

                self._add_table_pages(
                    pdf,
                    title="Mezz Joist Assignment Schedule",
                    headers=[
                        "Group",
                        "Qty",
                        "Req (plf)",
                        "Len (ft)",
                        "Joist",
                        "Depth (in)",
                        "Wt (plf)",
                        "Group Wt (lbs)",
                    ],
                    rows=mezz_joist_rows,
                    subtitle=f"Mezz Joist Weight = {self._fmt_num(weights['mezz_joist_lbs'], 2)} lbs",
                    max_rows=28,
                    col_widths=[0.10, 0.07, 0.13, 0.11, 0.16, 0.11, 0.11, 0.12],
                    right_align_cols={1, 2, 3, 5, 6, 7},
                )

                self._add_table_pages(
                    pdf,
                    title="Mezz Girder Assignment Schedule",
                    headers=[
                        "Group",
                        "Qty",
                        "Req Cap (lbs)",
                        "Len (ft)",
                        "N",
                        "Min D (in)",
                        "Girder",
                        "Depth (in)",
                        "Wt (plf)",
                        "Group Wt (lbs)",
                    ],
                    rows=mezz_girder_rows,
                    subtitle="Mezz girder auto-selection: minimum depth 30.00 in (deeper only when required).",
                    max_rows=24,
                    col_widths=[0.08, 0.06, 0.14, 0.09, 0.05, 0.09, 0.15, 0.10, 0.10, 0.14],
                    right_align_cols={1, 2, 3, 4, 5, 7, 8, 9},
                )

                self._add_table_pages(
                    pdf,
                    title="Mezz Column Assignment Schedule",
                    headers=[
                        "Group",
                        "Qty",
                        "Req (kips)",
                        "Height (ft)",
                        "Type",
                        "Column",
                        "Depth (in)",
                        "Wt (plf)",
                        "Group Wt (lbs)",
                    ],
                    rows=mezz_column_rows,
                    subtitle=f"Mezz Column Weight = {self._fmt_num(weights['mezz_column_lbs'], 2)} lbs",
                    max_rows=26,
                    col_widths=[0.08, 0.06, 0.12, 0.12, 0.09, 0.17, 0.10, 0.10, 0.13],
                    right_align_cols={1, 2, 3, 6, 7, 8},
                )

                self._add_table_pages(
                    pdf,
                    title="Mezz Pad Footing Quantity Schedule",
                    headers=[
                        "Column",
                        "Grid",
                        "Zone",
                        "Load (kips)",
                        "Size Raw (ft)",
                        "Size Used (ft)",
                        "Depth (ft)",
                        "Volume (CY)",
                    ],
                    rows=mezz_footing_rows,
                    subtitle=(
                        f"Subtotal CY = {self._fmt_num(float(mezz_footing_summary.get('total_cy', 0.0)), 3)} | "
                        f"Final CY (+10% waste) = {self._fmt_num(float(mezz_footing_summary.get('total_cy_with_waste', 0.0)), 3)}"
                    ),
                    max_rows=28,
                    col_widths=[0.13, 0.09, 0.11, 0.12, 0.13, 0.13, 0.10, 0.12],
                    right_align_cols={3, 4, 5, 6, 7},
                )

            self._add_table_pages(
                pdf,
                title="Pad Footing Quantity Schedule",
                headers=[
                    "Column",
                    "Grid",
                    "Load (kips)",
                    "Size Raw (ft)",
                    "Size Used (ft)",
                    "Depth (ft)",
                    "Volume (CY)",
                ],
                rows=footing_rows,
                subtitle=(
                    f"Subtotal CY = {self._fmt_num(float(footing_summary.get('total_cy', 0.0)), 3)} | "
                    f"Final CY (+10% waste) = {self._fmt_num(float(footing_summary.get('total_cy_with_waste', 0.0)), 3)}"
                ),
                max_rows=30,
                col_widths=[0.12, 0.10, 0.15, 0.15, 0.14, 0.12, 0.14],
                right_align_cols={2, 3, 4, 5, 6},
            )

            # Final deliverable page: labeled steel framing plan.
            fig = self._build_member_labeled_plan_report_figure()
            pdf.savefig(fig)
            plt.close(fig)

        return output_path

    def recalculate_all_no_export(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before recalculating.")
            return

        self._clear_report_log()
        self.report_status_var.set("Recalculating all takeoffs and auto-assignments...")
        self._append_report_log("Starting full recalculation.")
        run_notes = []
        try:
            self._append_report_log("1/10 Main joists...")
            self.calculate_joists()
            if not self.last_joist_result:
                raise InputValidationError("Joist calculation did not complete.")
            joist_rows = self._load_joist_catalog_rows()
            joist_groups = self.last_joist_result.get("joist_demand_groups", [])
            (
                joist_assignments,
                joist_missing,
                joist_fallback_assigned,
                joist_fallback_source,
                joist_fallback_error,
            ) = self._compute_main_joist_assignments_with_lh_fallback(joist_groups, joist_rows)
            self.joist_selection_by_group.update(joist_assignments)
            self._refresh_joist_selection_table()
            self.redraw_roof_section()
            self._append_report_log(f"Joists assigned: {len(joist_assignments)}/{len(joist_groups)} groups.")
            if joist_fallback_assigned:
                self._append_report_log(
                    f"LH fallback assignments: {joist_fallback_assigned}"
                    + (f" via {joist_fallback_source}" if joist_fallback_source else "")
                )
            if joist_missing:
                run_notes.append(f"Joist missing groups: {len(joist_missing)}")
            if joist_fallback_error:
                run_notes.append(f"LH fallback unavailable: {joist_fallback_error}")

            self._append_report_log("2/10 Main girders...")
            self.calculate_girders()
            if not self.last_girder_result:
                raise InputValidationError("Girder calculation did not complete.")
            self._load_girder_catalog_rows()
            girder_groups = self.last_girder_result.get("girder_demand_groups", [])
            girder_assignments, girder_missing = self._compute_girder_auto_assignments(
                girder_groups, self.girder_catalog_index or {}
            )
            self.girder_selection_by_group.update(girder_assignments)
            self._refresh_girder_selection_table()
            self._append_report_log(f"Girders assigned: {len(girder_assignments)}/{len(girder_groups)} groups.")
            if girder_missing:
                run_notes.append(f"Girder missing groups: {len(girder_missing)}")

            self._append_report_log("3/10 Main columns...")
            self.calculate_columns()
            if not self.last_column_result:
                raise InputValidationError("Column calculation did not complete.")
            column_rows = self._load_column_catalog_rows()
            clear_height_ft = self._parse_positive_input("Clear Height", self.clear_height_var.get())
            column_groups = self.last_column_result.get("column_demand_groups", [])
            column_assignments, column_missing, used_kl = self._compute_column_auto_assignments(
                column_groups, column_rows, clear_height_ft
            )
            self.column_selection_by_group.update(column_assignments)
            self._refresh_column_selection_table()
            self._append_report_log(
                f"Columns assigned: {len(column_assignments)}/{len(column_groups)} groups (KL={self._fmt_ft_arch(used_kl)})."
            )
            if column_missing:
                run_notes.append(f"Column missing groups: {len(column_missing)}")

            if bool(self.mezzanine_enabled_var.get() and self.mezz_zones):
                self._append_report_log("4/10 Mezzanines...")
                self.calculate_mezzanines()
                if not self.last_mezz_result:
                    raise InputValidationError("Mezzanine calculation did not complete.")
                mezz_assign = self._auto_assign_mezz_members(show_messages=False) or {}
                self.calculate_mezz_pad_footings()
                self._append_report_log(
                    "Mezz assigned: Joists {mj}/{mjt}, Girders {mg}/{mgt}, Columns {mc}/{mct} groups.".format(
                        mj=int(mezz_assign.get("joist_assigned_groups", 0)),
                        mjt=int(mezz_assign.get("joist_total_groups", 0)),
                        mg=int(mezz_assign.get("girder_assigned_groups", 0)),
                        mgt=int(mezz_assign.get("girder_total_groups", 0)),
                        mc=int(mezz_assign.get("column_assigned_groups", 0)),
                        mct=int(mezz_assign.get("column_total_groups", 0)),
                    )
                )
            else:
                self.last_mezz_result = None
                self.last_mezz_footing_result = None
                self.mezz_joist_selection_by_group = {}
                self.mezz_girder_selection_by_group = {}
                self.mezz_column_selection_by_group = {}
                self._refresh_joist_selection_table()
                self._refresh_girder_selection_table()
                self._refresh_column_selection_table()
                self._append_report_log("4/10 Mezzanines skipped.")

            self._append_report_log("5/10 Tilt walls...")
            self.last_tilt_result = None
            self.calculate_tilt_walls()
            if not self.last_tilt_result:
                raise InputValidationError("Tilt wall calculation did not complete.")

            self._append_report_log("6/10 Footings...")
            self.last_footing_result = None
            self.calculate_pad_footings()
            if not self.last_footing_result:
                raise InputValidationError("Pad footing calculation did not complete.")

            weights = self._collect_weight_summary()
            ratio_psf = float(weights.get("joist_girder_psf", 0.0))
            target_psf = float(weights.get("target_psf", 2.13))
            check_status = "OK" if abs(ratio_psf - target_psf) <= 0.25 else "Review"
            check_line = (
                f"Check (Main Joist + Main Girder)/Area = {self._fmt_num(ratio_psf, 3)} psf "
                f"vs target {self._fmt_num(target_psf, 2)} [{check_status}]"
            )
            self._append_report_log(check_line)

            note = " | ".join(run_notes) if run_notes else "all primary groups assigned"
            self.report_status_var.set(f"Recalculate complete: {note}.")
            self.project_status_var.set("Recalculated")
            self.save_project(self._autosave_path, silent=True)
            messagebox.showinfo("Recalculate complete", f"All calculations refreshed.\n\n{check_line}")
        except InputValidationError as exc:
            self.report_status_var.set("Recalculate failed due to input/catalog issue.")
            self._append_report_log(f"Failed: {exc}")
            messagebox.showerror("Recalculate failed", str(exc))
        except Exception as exc:
            self.report_status_var.set("Recalculate failed due to unexpected error.")
            self._append_report_log(f"Unexpected failure: {exc}")
            messagebox.showerror("Recalculate failed", f"Unexpected error:\n{exc}")

    def run_all_calculations_and_export_pdf(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before running/exporting.")
            return

        default_name = f"Structural_Steel_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        save_path = filedialog.asksaveasfilename(
            title="Export Company PDF Report",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF Files", "*.pdf")],
        )
        if not save_path:
            return

        if hasattr(self, "run_all_report_btn"):
            self.run_all_report_btn.configure(state="disabled")
        self._clear_report_log()
        self.report_status_var.set("Running all calculations and assignments...")
        self._append_report_log("Starting full run.")

        run_notes = []
        try:
            self._append_report_log("1/11 Running main-building joist calculations...")
            self.calculate_joists()
            if not self.last_joist_result:
                raise InputValidationError("Joist calculation did not complete.")

            self._append_report_log("2/11 Auto-assigning main-building joists from catalog...")
            joist_rows = self._load_joist_catalog_rows()
            joist_groups = self.last_joist_result.get("joist_demand_groups", [])
            (
                joist_assignments,
                joist_missing,
                joist_fallback_assigned,
                joist_fallback_source,
                joist_fallback_error,
            ) = self._compute_main_joist_assignments_with_lh_fallback(joist_groups, joist_rows)
            self.joist_selection_by_group.update(joist_assignments)
            self._refresh_joist_selection_table()
            self.redraw_roof_section()
            self._append_report_log(f"Joists assigned: {len(joist_assignments)}/{len(joist_groups)} groups.")
            if joist_fallback_assigned:
                self._append_report_log(
                    f"Main LH fallback assignments: {joist_fallback_assigned}"
                    + (f" via {joist_fallback_source}" if joist_fallback_source else "")
                )
            if joist_missing:
                note = f"Joist auto-assign missing groups: {len(joist_missing)}"
                run_notes.append(note)
                self._append_report_log(note)
            if joist_fallback_error:
                note = f"Main LH fallback unavailable: {joist_fallback_error}"
                run_notes.append(note)
                self._append_report_log(note)

            self._append_report_log("3/11 Running main-building girder calculations...")
            self.calculate_girders()
            if not self.last_girder_result:
                raise InputValidationError("Girder calculation did not complete.")

            self._append_report_log("4/11 Auto-assigning main-building girders from catalog...")
            self._load_girder_catalog_rows()
            girder_groups = self.last_girder_result.get("girder_demand_groups", [])
            girder_assignments, girder_missing = self._compute_girder_auto_assignments(
                girder_groups, self.girder_catalog_index or {}
            )
            self.girder_selection_by_group.update(girder_assignments)
            self._refresh_girder_selection_table()
            self._append_report_log(f"Girders assigned: {len(girder_assignments)}/{len(girder_groups)} groups.")
            if girder_missing:
                note = f"Girder auto-assign missing groups: {len(girder_missing)}"
                run_notes.append(note)
                self._append_report_log(note)

            self._append_report_log("5/11 Running main-building column calculations...")
            self.calculate_columns()
            if not self.last_column_result:
                raise InputValidationError("Column calculation did not complete.")

            self._append_report_log("6/11 Auto-assigning main-building columns from catalog...")
            column_rows = self._load_column_catalog_rows()
            clear_height_ft = self._parse_positive_input("Clear Height", self.clear_height_var.get())
            column_groups = self.last_column_result.get("column_demand_groups", [])
            column_assignments, column_missing, used_kl = self._compute_column_auto_assignments(
                column_groups, column_rows, clear_height_ft
            )
            self.column_selection_by_group.update(column_assignments)
            self._refresh_column_selection_table()
            self._append_report_log(
                f"Columns assigned: {len(column_assignments)}/{len(column_groups)} groups (KL={self._fmt_ft_arch(used_kl)})."
            )
            if column_missing:
                note = f"Column auto-assign missing groups: {len(column_missing)}"
                run_notes.append(note)
                self._append_report_log(note)

            mezz_enabled = bool(self.mezzanine_enabled_var.get() and self.mezz_zones)
            if mezz_enabled:
                self._append_report_log("7/11 Running mezzanine calculations...")
                self.calculate_mezzanines()
                if not self.last_mezz_result:
                    raise InputValidationError("Mezzanine calculation did not complete.")

                self._append_report_log("8/11 Auto-assigning mezzanine joists/girders/columns...")
                mezz_assign = self._auto_assign_mezz_members(show_messages=False) or {}
                mj = int(mezz_assign.get("joist_assigned_groups", 0))
                mjt = int(mezz_assign.get("joist_total_groups", 0))
                mg = int(mezz_assign.get("girder_assigned_groups", 0))
                mgt = int(mezz_assign.get("girder_total_groups", 0))
                mc = int(mezz_assign.get("column_assigned_groups", 0))
                mct = int(mezz_assign.get("column_total_groups", 0))
                self._append_report_log(
                    f"Mezz assignments: Joists {mj}/{mjt}, Girders {mg}/{mgt}, Columns {mc}/{mct} groups."
                )
                if mezz_assign.get("joist_missing"):
                    note = f"Mezz joist auto-assign missing groups: {len(mezz_assign.get('joist_missing', []))}"
                    run_notes.append(note)
                    self._append_report_log(note)
                if mezz_assign.get("girder_missing"):
                    note = f"Mezz girder auto-assign missing groups: {len(mezz_assign.get('girder_missing', []))}"
                    run_notes.append(note)
                    self._append_report_log(note)
                if mezz_assign.get("column_missing"):
                    note = f"Mezz column auto-assign missing groups: {len(mezz_assign.get('column_missing', []))}"
                    run_notes.append(note)
                    self._append_report_log(note)

                self._append_report_log("9/11 Running mezzanine footing calculations...")
                self.calculate_mezz_pad_footings()
            else:
                self.last_mezz_result = None
                self.last_mezz_footing_result = None
                self.mezz_joist_selection_by_group = {}
                self.mezz_girder_selection_by_group = {}
                self.mezz_column_selection_by_group = {}
                self._refresh_joist_selection_table()
                self._refresh_girder_selection_table()
                self._refresh_column_selection_table()
                self._append_report_log("7/11 Mezzanine calculations skipped (disabled or no zones).")
                self._append_report_log("8/11 Mezzanine auto-assignment skipped.")
                self._append_report_log("9/11 Mezzanine footing calculations skipped.")

            self._append_report_log("10/11 Running tilt wall and main footing calculations...")
            self.last_tilt_result = None
            self.calculate_tilt_walls()
            if not self.last_tilt_result:
                raise InputValidationError("Tilt wall calculation did not complete.")
            self.last_footing_result = None
            self.calculate_pad_footings()
            if not self.last_footing_result:
                raise InputValidationError("Pad footing calculation did not complete.")

            weights = self._collect_weight_summary()
            ratio_psf = float(weights.get("joist_girder_psf", 0.0))
            target_psf = float(weights.get("target_psf", 2.13))
            deviation = ratio_psf - target_psf
            check_status = "OK" if abs(deviation) <= 0.25 else "Review"
            check_line = (
                f"Check (Main Joist + Main Girder)/Area = {self._fmt_num(ratio_psf, 3)} psf "
                f"vs target {self._fmt_num(target_psf, 2)} [{check_status}]"
            )
            run_notes.append(check_line)
            self._append_report_log(check_line)

            self._append_report_log("11/11 Building professional PDF report...")
            report_file = self._build_company_pdf_report(Path(save_path), "\n".join(run_notes))

            self.report_status_var.set(f"Report complete: {report_file}")
            self._append_report_log(f"PDF exported successfully: {report_file}")
            messagebox.showinfo("Export complete", f"Company report generated:\n{report_file}")
        except InputValidationError as exc:
            self.report_status_var.set("Run failed due to input/catalog issue.")
            self._append_report_log(f"Failed: {exc}")
            messagebox.showerror("Run failed", str(exc))
        except Exception as exc:
            self.report_status_var.set("Run failed due to unexpected error.")
            self._append_report_log(f"Unexpected failure: {exc}")
            messagebox.showerror("Run failed", f"Unexpected error:\n{exc}")
        finally:
            if hasattr(self, "run_all_report_btn"):
                self.run_all_report_btn.configure(state="normal")

    def calculate_joists(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before running joist calculations.")
            return
        try:
            result = calculate_joist_takeoff(self.collect_joist_layout_data())
        except InputValidationError as exc:
            messagebox.showerror("Input error", str(exc))
            return

        summary = result["summary"]
        self.last_joist_result = result
        self.joist_calc_status_var.set(
            "Calculated {members} unique joists across {bays} bays. "
            "Demand Groups: {groups} | Average spacing: {spacing} | "
            "Average tributary area: {trib:.2f} sf | Average total load: {total:.2f} psf".format(
                members=summary["joist_member_count"],
                bays=summary["bay_count"],
                groups=summary["demand_group_count"],
                spacing=self._fmt_ft_arch(summary["average_joist_spacing_ft"]),
                trib=summary["average_tributary_area_sf"],
                total=summary["average_total_load_psf"],
            )
        )

        lines = [
            "Bay | Spaces | Joists | Width(ft) | Length(ft) | Spacing(ft) | Trib Area(sf) | Red LL(psf) | Red Snow(psf) | Base TL(psf) | Coll+(psf) | Addl+(psf) | Total TL(psf) | Ctrl"
        ]
        lines.append("-" * 185)
        for item in result["joist_bay_calculations"]:
            spaces = int(item.get("joist_spaces_per_bay", max(1, int(item.get("joists_per_bay", 1)) - 1)))
            lines.append(
                "{bay:>4} | {spaces:>6} | {count:>6} | {width:>9} | {length:>10} | {spacing:>11} | "
                "{trib:>12.2f} | {red_ll:>10.2f} | {red_snow:>13.2f} | {base_total:>12.2f} | "
                "{coll_add:>10.2f} | {addl_add:>10.2f} | {total:>13.2f} | {ctrl}".format(
                    bay=item["bay"],
                    spaces=spaces,
                    count=item["joists_per_bay"],
                    width=self._fmt_ft_arch(item["bay_width_ft"]),
                    length=self._fmt_ft_arch(item["bay_length_ft"]),
                    spacing=self._fmt_ft_arch(item["joist_spacing_ft"]),
                    trib=item["tributary_area_sf"],
                    red_ll=item["reduced_live_load_psf"],
                    red_snow=item["reduced_snow_load_psf"],
                    base_total=item["base_total_load_psf"],
                    coll_add=item["collateral_addition_applied_psf"],
                    addl_add=item.get("additional_load_addition_applied_psf", item.get("custom_load_addition_applied_psf", 0.0)),
                    total=item["total_load_psf"],
                    ctrl="RLL" if item["controlling_load_type"] == "Reduced Live Load" else "RSL",
                )
            )
        mezz_result = self._get_mezz_result_for_tab_display()
        self._append_mezz_joist_section(lines, mezz_result)
        self._set_joist_results_text("\n".join(lines))
        self._refresh_joist_selection_table()
        self.redraw_roof_section()

    def calculate_girders(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before running girder calculations.")
            return
        try:
            result = calculate_girder_takeoff(self.collect_joist_layout_data())
        except InputValidationError as exc:
            messagebox.showerror("Input error", str(exc))
            return

        self.last_girder_result = result
        summary = result["summary"]
        if summary["girder_count"] == 0:
            self.girder_calc_status_var.set(
                "No girders calculated for current active bays and perimeter load-bearing wall selections."
            )
            lines = ["No girder segments available for this layout/wall selection."]
            mezz_result = self._get_mezz_result_for_tab_display()
            self._append_mezz_girder_section(lines, mezz_result)
            self._set_girder_results_text("\n".join(lines))
            self.last_girder_result["girder_demand_groups"] = []
            self._refresh_girder_selection_table()
            return

        self.girder_calc_status_var.set(
            "Calculated {count} girders | Average At: {at:.2f} sf | "
            "Average TL: {tl:.2f} psf | Average Required Capacity: {cap:.2f} lbs".format(
                count=summary["girder_count"],
                at=summary["average_tributary_area_sf"],
                tl=summary["average_total_load_psf"],
                cap=summary["average_required_capacity_lbs"],
            )
        )

        lines = [
            "Girder | Line | XBay | Width(ft) | TribY(ft) | At(sf) | R1 | Red LL | Red SL | Base TL | Coll+ | Addl+ | TL | Avg JS(ft) | Req Cap (lbs)"
        ]
        lines.append("-" * 165)
        for item in result["girder_calculations"]:
            lines.append(
                "{gid:>10} | {line:>4} | {xbay:>4} | {w:>9} | {avg:>8} | {at:>7.2f} | {r1:>4.3f} | "
                "{rll:>6.2f} | {rsl:>6.2f} | {base:>7.2f} | {coll:>5.2f} | {custom:>7.2f} | {tl:>6.2f} | {js:>10} | {req:>13.2f}".format(
                    gid=item["girder_id"],
                    line=item["line_label"],
                    xbay=item["x_bay_index"],
                    w=self._fmt_ft_arch(item["bay_width_ft"]),
                    avg=self._fmt_ft_arch(item["average_bay_length_ft"]),
                    at=item["tributary_area_sf"],
                    r1=item["reduced_live_factor_r1"],
                    rll=item["reduced_live_load_psf"],
                    rsl=item["reduced_snow_load_psf"],
                    base=item["base_total_load_psf"],
                    coll=item["collateral_addition_applied_psf"],
                    custom=item.get("additional_load_addition_applied_psf", item.get("custom_load_addition_applied_psf", 0.0)),
                    tl=item["total_load_psf"],
                    js=self._fmt_ft_arch(item["average_joist_spacing_ft"]),
                    req=item["required_capacity_lbs"],
                )
            )
        mezz_result = self._get_mezz_result_for_tab_display()
        self._append_mezz_girder_section(lines, mezz_result)
        self._set_girder_results_text("\n".join(lines))
        self.last_girder_result["girder_demand_groups"] = self._build_girder_demand_groups(
            self.last_girder_result.get("girder_calculations", [])
        )
        self._refresh_girder_selection_table()

    def calculate_columns(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before running column calculations.")
            return
        try:
            result = calculate_column_takeoff(self.collect_joist_layout_data())
        except InputValidationError as exc:
            messagebox.showerror("Input error", str(exc))
            return

        self.last_column_result = result
        self.last_footing_result = None
        self.footing_calc_status_var.set("No footing calculation run yet.")
        self._set_footing_results_text("")
        summary = result["summary"]
        if summary["column_count"] == 0:
            self.column_calc_status_var.set(
                "No columns calculated for current active bays and perimeter load-bearing wall selections."
            )
            lines = ["No steel-supported column intersections available for this layout/wall selection."]
            mezz_result = self._get_mezz_result_for_tab_display()
            self._append_mezz_column_section(lines, mezz_result)
            self._set_column_results_text("\n".join(lines))
            self.last_column_result["column_demand_groups"] = []
            self._refresh_column_selection_table()
            return

        self.column_calc_status_var.set(
            "Calculated {count} columns | Average At: {at:.2f} sf | "
            "Average TL: {tl:.2f} psf | Average Required Capacity: {cap:.2f} kips".format(
                count=summary["column_count"],
                at=summary["average_tributary_area_sf"],
                tl=summary["average_total_load_psf"],
                cap=summary["average_required_capacity_kips"],
            )
        )

        lines = [
            "Column | Grid | AvgX(ft) | AvgY(ft) | At(sf) | R1 | Red LL | Red SL | Base TL | Coll+ | Addl+ | TL | Req Cap (kips) | Ctrl"
        ]
        lines.append("-" * 178)
        for item in result["column_calculations"]:
            lines.append(
                "{cid:>8} | {grid:>4} | {avgx:>8} | {avgy:>8} | {at:>7.2f} | {r1:>4.3f} | "
                "{rll:>6.2f} | {rsl:>6.2f} | {base:>7.2f} | {coll:>5.2f} | {custom:>7.2f} | {tl:>6.2f} | {req:>14.2f} | {ctrl}".format(
                    cid=item["column_id"],
                    grid=f"{item['line_label']}{item['grid_number']}",
                    avgx=self._fmt_ft_arch(item["average_bay_width_ft"]),
                    avgy=self._fmt_ft_arch(item["average_bay_length_ft"]),
                    at=item["tributary_area_sf"],
                    r1=item["reduced_live_factor_r1"],
                    rll=item["reduced_live_load_psf"],
                    rsl=item["reduced_snow_load_psf"],
                    base=item["base_total_load_psf"],
                    coll=item["collateral_addition_applied_psf"],
                    custom=item.get("additional_load_addition_applied_psf", item.get("custom_load_addition_applied_psf", 0.0)),
                    tl=item["total_load_psf"],
                    req=item["required_capacity_kips"],
                    ctrl="RLL" if item["controlling_load_type"] == "Reduced Live Load" else "RSL",
                )
            )
        mezz_result = self._get_mezz_result_for_tab_display()
        self._append_mezz_column_section(lines, mezz_result)
        self._set_column_results_text("\n".join(lines))
        self.last_column_result["column_demand_groups"] = self._build_column_demand_groups(
            self.last_column_result.get("column_calculations", [])
        )
        self._refresh_column_selection_table()

    def calculate_pad_footings(self):
        if not self.model.x_spans or not self.model.y_spans:
            messagebox.showerror("Grid required", "Add X and Y bays before running pad footing calculations.")
            return

        try:
            footing_depth_ft = self._parse_positive_input("Footing Depth", self.footing_depth_var.get())
            bearing_pressure_psi = self._parse_positive_input("Bearing Pressure", self.bearing_pressure_var.get())
        except InputValidationError as exc:
            messagebox.showerror("Input error", str(exc))
            return

        if not self.last_column_result:
            self.calculate_columns()
            if not self.last_column_result:
                return

        column_calcs = list(self.last_column_result.get("column_calculations", []))
        if not column_calcs:
            self.last_footing_result = {
                "footing_depth_ft": footing_depth_ft,
                "bearing_pressure_psi": bearing_pressure_psi,
                "column_footings": [],
                "summary": {"column_count": 0, "total_cy": 0.0, "total_cy_with_waste": 0.0},
            }
            self.footing_calc_status_var.set("No pad footings calculated. No steel-supported columns are available.")
            self._set_footing_results_text("No steel-supported columns available for pad footing takeoff.")
            return

        bearing_ksf = bearing_pressure_psi / 1000.0
        denom = math.sqrt(bearing_ksf)
        column_footings = []
        total_cy = 0.0
        for item in column_calcs:
            required_capacity_kips = max(0.0, float(item.get("required_capacity_kips", 0.0)))
            footing_size_raw_ft = math.sqrt(required_capacity_kips) / denom if denom > 0 else 0.0
            footing_size_ft = self._ceil_to_increment(footing_size_raw_ft, 0.25)
            footing_volume_cy = (footing_size_ft * footing_size_ft * footing_depth_ft) / 27.0
            total_cy += footing_volume_cy
            column_footings.append(
                {
                    "column_id": str(item.get("column_id", "")),
                    "grid": f"{item.get('line_label', '')}{item.get('grid_number', '')}",
                    "required_capacity_kips": round(required_capacity_kips, 3),
                    "footing_size_raw_ft": round(footing_size_raw_ft, 4),
                    "footing_size_ft": round(footing_size_ft, 2),
                    "footing_depth_ft": round(footing_depth_ft, 3),
                    "footing_volume_cy": round(footing_volume_cy, 4),
                }
            )

        total_cy_with_waste = total_cy * 1.1
        self.last_footing_result = {
            "footing_depth_ft": round(footing_depth_ft, 3),
            "bearing_pressure_psi": round(bearing_pressure_psi, 3),
            "column_footings": column_footings,
            "summary": {
                "column_count": len(column_footings),
                "total_cy": round(total_cy, 4),
                "total_cy_with_waste": round(total_cy_with_waste, 4),
            },
        }

        self.footing_calc_status_var.set(
            "Calculated pad footings for {count} columns | Total: {total:.2f} CY | With 10% waste: {waste:.2f} CY".format(
                count=len(column_footings),
                total=total_cy,
                waste=total_cy_with_waste,
            )
        )

        lines = [
            "Pad Footing Takeoff",
            "-" * 108,
            "Column | Grid | Load (kips) | Size Raw (ft) | Size Used (ft) | Depth (ft) | Volume (CY)",
            "-" * 108,
        ]
        for row in column_footings:
            lines.append(
                "{cid:>8} | {grid:>4} | {load:>11.2f} | {raw:>13} | {size:>14} | {depth:>10} | {cy:>11.3f}".format(
                    cid=row["column_id"],
                    grid=row["grid"],
                    load=row["required_capacity_kips"],
                    raw=self._fmt_ft_arch(row["footing_size_raw_ft"]),
                    size=self._fmt_ft_arch(row["footing_size_ft"]),
                    depth=self._fmt_ft_arch(row["footing_depth_ft"]),
                    cy=row["footing_volume_cy"],
                )
            )
        lines.extend(
            [
                "-" * 108,
                f"Subtotal Footing Concrete: {total_cy:.3f} CY",
                f"Final Footing Concrete (+10% waste): {total_cy_with_waste:.3f} CY",
            ]
        )
        self._set_footing_results_text("\n".join(lines))

    def fit_to_view(self):
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        total_w = max(1.0, x_lines[-1] - x_lines[0])
        total_h = max(1.0, y_lines[-1] - y_lines[0])
        cw = max(300, self.canvas.winfo_width())
        ch = max(300, self.canvas.winfo_height())
        target_w = cw - 220
        target_h = ch - 180
        self.zoom = min(target_w / total_w, target_h / total_h)
        self.zoom = max(MIN_ZOOM_PX_PER_FT, min(MAX_ZOOM_PX_PER_FT, self.zoom))
        self.offset_x = (cw - total_w * self.zoom) / 2
        self.offset_y = (ch - total_h * self.zoom) / 2
        self.redraw()

    def on_mouse_wheel(self, event):
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        elif getattr(event, "delta", 0) > 0:
            delta = 1
        elif getattr(event, "delta", 0) < 0:
            delta = -1
        if delta == 0:
            return

        ctrl_down = bool(event.state & 0x0004)
        shift_down = bool(event.state & 0x0001)
        if ctrl_down:
            old_zoom = self.zoom
            factor = 1.1 if delta > 0 else 1 / 1.1
            self.zoom = max(MIN_ZOOM_PX_PER_FT, min(MAX_ZOOM_PX_PER_FT, self.zoom * factor))
            if abs(old_zoom - self.zoom) < 1e-9:
                return
            wx, wy = self.screen_to_world(event.x, event.y)
            self.offset_x = event.x - wx * self.zoom
            self.offset_y = event.y - wy * self.zoom
        else:
            pan_step_px = 48
            if shift_down:
                self.offset_x += delta * pan_step_px
            else:
                self.offset_y += delta * pan_step_px
        self.redraw()

    def on_pan_start(self, event):
        self.pan_anchor = (event.x, event.y)

    def on_pan_drag(self, event):
        if not self.pan_anchor:
            return
        ax, ay = self.pan_anchor
        dx, dy = event.x - ax, event.y - ay
        self.offset_x += dx
        self.offset_y += dy
        self.pan_anchor = (event.x, event.y)
        self.redraw()

    def find_near_line(self, x_px: float, y_px: float):
        threshold = 7.0
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        best = None
        best_dist = 1e9

        for idx, xv in enumerate(x_lines):
            if idx == 0 or idx == len(x_lines) - 1:
                continue
            sx, _ = self.world_to_screen(xv, 0)
            dist = abs(sx - x_px)
            if dist < threshold and dist < best_dist:
                best = ("v", idx)
                best_dist = dist

        for idx, yv in enumerate(y_lines):
            if idx == 0 or idx == len(y_lines) - 1:
                continue
            _, sy = self.world_to_screen(0, yv)
            dist = abs(sy - y_px)
            if dist < threshold and dist < best_dist:
                best = ("h", idx)
                best_dist = dist

        return best

    def on_left_down(self, event):
        mode = self.interaction_mode.get()
        if mode == "collateral":
            self.toggle_collateral_bay(event.x, event.y)
            self.drag_line = None
            return
        if mode == "custom_load":
            self.toggle_custom_load_bay(event.x, event.y)
            self.drag_line = None
            return
        if mode == "speed_rows":
            self.toggle_speed_bay_row_from_click(event.x, event.y)
            self.drag_line = None
            return
        if mode == "lb_walls":
            self.toggle_load_bearing_perimeter_segment(event.x, event.y)
            self.drag_line = None
            return
        if mode == "shape":
            self.toggle_inactive_bay(event.x, event.y)
            self.drag_line = None
            return
        if mode == "joists":
            self.assign_joists_to_bay(event.x, event.y)
            self.drag_line = None
            return
        self.drag_line = self.find_near_line(event.x, event.y)

    def on_left_drag(self, event):
        if self.interaction_mode.get() != "edit" or not self.drag_line:
            return
        kind, idx = self.drag_line
        wx, wy = self.screen_to_world(event.x, event.y)
        if kind == "v":
            self.model.move_vertical_line(idx, wx)
        else:
            self.model.move_horizontal_line(idx, wy)
        self.redraw()

    def on_left_up(self, _event):
        self.drag_line = None

    def find_bay_index(self, x_ft: float, y_ft: float):
        if not self.model.x_spans or not self.model.y_spans:
            return None
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        x_idx = None
        y_idx = None
        for i in range(len(x_lines) - 1):
            if x_lines[i] < x_ft < x_lines[i + 1]:
                x_idx = i
                break
        for i in range(len(y_lines) - 1):
            if y_lines[i] < y_ft < y_lines[i + 1]:
                y_idx = i
                break
        if x_idx is None or y_idx is None:
            return None
        return x_idx, y_idx

    def _distance_point_to_segment_px(self, px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / ((dx * dx) + (dy * dy))
        t = max(0.0, min(1.0, t))
        cx = x1 + t * dx
        cy = y1 + t * dy
        return math.hypot(px - cx, py - cy)

    def _edge_to_world_segment(self, edge):
        orient, line_idx, seg_idx = edge
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        if orient == "H":
            if not (0 <= line_idx < len(y_lines) and 0 <= seg_idx < len(x_lines) - 1):
                return None
            return (x_lines[seg_idx], y_lines[line_idx], x_lines[seg_idx + 1], y_lines[line_idx])
        if orient == "V":
            if not (0 <= line_idx < len(x_lines) and 0 <= seg_idx < len(y_lines) - 1):
                return None
            return (x_lines[line_idx], y_lines[seg_idx], x_lines[line_idx], y_lines[seg_idx + 1])
        return None

    def find_boundary_segment(self, x_ft: float, y_ft: float):
        if not self.model.x_spans or not self.model.y_spans:
            return None
        px, py = self.world_to_screen(x_ft, y_ft)
        threshold_px = 10.0
        best = None
        best_dist = 1e9
        for edge in self._current_boundary_segments():
            seg = self._edge_to_world_segment(edge)
            if not seg:
                continue
            x1, y1, x2, y2 = seg
            sx1, sy1 = self.world_to_screen(x1, y1)
            sx2, sy2 = self.world_to_screen(x2, y2)
            dist = self._distance_point_to_segment_px(px, py, sx1, sy1, sx2, sy2)
            if dist < threshold_px and dist < best_dist:
                best = edge
                best_dist = dist
        return best

    def set_dock_line_from_click(self, x_px: float, y_px: float):
        _x_ft, y_ft = self.screen_to_world(x_px, y_px)
        y_lines = self.model.y_lines
        if len(y_lines) < 2:
            return
        tol_ft = max(0.25, 8.0 / max(self.zoom, 0.001))
        best_idx = None
        best_dist = 1e9
        for idx in range(0, len(y_lines) - 1):
            dist = abs(y_ft - y_lines[idx])
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is None or best_dist > tol_ft:
            return
        self.dock_line_var.set(axis_letter(best_idx))
        self.redraw()

    def toggle_speed_bay_row_from_click(self, x_px: float, y_px: float):
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        bay = self.find_bay_index(x_ft, y_ft)
        if bay is None:
            return
        _x_idx, y_idx = bay
        if y_idx in self.speed_bay_rows:
            self.speed_bay_rows.remove(y_idx)
        else:
            self.speed_bay_rows.add(y_idx)
        self._refresh_dock_line_options()

    def toggle_load_bearing_perimeter_segment(self, x_px: float, y_px: float):
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        segment = self.find_boundary_segment(x_ft, y_ft)
        if segment is None:
            return
        if segment in self.load_bearing_perimeter:
            self.load_bearing_perimeter.remove(segment)
        else:
            self.load_bearing_perimeter.add(segment)
        self.redraw()

    def toggle_collateral_bay(self, x_px: float, y_px: float):
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        bay = self.find_bay_index(x_ft, y_ft)
        if bay is None:
            return
        if bay in self.inactive_bays:
            return
        if bay in self.collateral_bays:
            self.collateral_bays.remove(bay)
        else:
            self.collateral_bays.add(bay)
        self.redraw()

    def toggle_custom_load_bay(self, x_px: float, y_px: float):
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        bay = self.find_bay_index(x_ft, y_ft)
        if bay is None:
            return
        if bay in self.inactive_bays:
            return
        layer = self._get_selected_additional_load_layer()
        if layer is None:
            if not self.additional_load_layers:
                self.add_additional_load_layer()
            else:
                self.selected_additional_load_layer_id = str(self.additional_load_layers[0].get("id"))
            layer = self._get_selected_additional_load_layer()
            if layer is None:
                return
        layer_bays = set(layer.get("bays", set()))
        if bay in layer_bays:
            layer_bays.remove(bay)
        else:
            layer_bays.add(bay)
        layer["bays"] = layer_bays
        self._refresh_additional_load_layer_tree()
        self.redraw()

    def toggle_inactive_bay(self, x_px: float, y_px: float):
        old_boundaries = self._current_boundary_segments()
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        bay = self.find_bay_index(x_ft, y_ft)
        if bay is None:
            return
        if bay in self.inactive_bays:
            self.inactive_bays.remove(bay)
        else:
            self.inactive_bays.add(bay)
            self.collateral_bays.discard(bay)
            for layer in self.additional_load_layers:
                layer["bays"] = set(layer.get("bays", set()))
                layer["bays"].discard(bay)
            self.joists_per_bay.pop(bay, None)
            self._refresh_additional_load_layer_tree()
        self._sync_load_bearing_perimeter(old_boundaries)
        self.redraw()

    def assign_joists_to_bay(self, x_px: float, y_px: float):
        try:
            count = self.get_default_joist_count()
        except InputValidationError as exc:
            messagebox.showerror("Invalid joist spaces", str(exc))
            return
        x_ft, y_ft = self.screen_to_world(x_px, y_px)
        bay = self.find_bay_index(x_ft, y_ft)
        if bay is None:
            return
        if bay in self.inactive_bays:
            return
        self.joists_per_bay[bay] = count
        self.redraw()

    def prune_inactive_bays(self):
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        self.inactive_bays = {
            (x_idx, y_idx)
            for (x_idx, y_idx) in self.inactive_bays
            if 0 <= x_idx < max_x and 0 <= y_idx < max_y
        }

    def prune_collateral_bays(self):
        self.prune_inactive_bays()
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        self.collateral_bays = {
            (x_idx, y_idx)
            for (x_idx, y_idx) in self.collateral_bays
            if 0 <= x_idx < max_x and 0 <= y_idx < max_y and (x_idx, y_idx) not in self.inactive_bays
        }

    def prune_custom_load_bays(self):
        self.prune_inactive_bays()
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        cleaned_layers = []
        for layer in self.additional_load_layers:
            bays = set(layer.get("bays", set()))
            bays = {
                (x_idx, y_idx)
                for (x_idx, y_idx) in bays
                if 0 <= x_idx < max_x and 0 <= y_idx < max_y and (x_idx, y_idx) not in self.inactive_bays
            }
            cleaned = dict(layer)
            cleaned["bays"] = bays
            cleaned_layers.append(cleaned)
        self.additional_load_layers = cleaned_layers

    def prune_joist_assignments(self):
        self.prune_inactive_bays()
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        self.joists_per_bay = {
            (x_idx, y_idx): count
            for (x_idx, y_idx), count in self.joists_per_bay.items()
            if 0 <= x_idx < max_x and 0 <= y_idx < max_y and (x_idx, y_idx) not in self.inactive_bays
        }

    def prune_speed_bay_rows(self):
        row_count = len(self.model.y_spans)
        cleaned = set()
        for idx in self.speed_bay_rows:
            if isinstance(idx, (int, float)):
                parsed = int(idx)
                if 0 <= parsed < row_count:
                    cleaned.add(parsed)
        self.speed_bay_rows = cleaned

    def draw_speed_bay_rows(self):
        speed_rows = self._get_selected_speed_bay_rows()
        if not speed_rows:
            return
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        active_bays = self.get_active_bays()
        for y_idx in speed_rows:
            if y_idx >= len(self.model.y_spans):
                continue
            for x_idx in range(len(self.model.x_spans)):
                if (x_idx, y_idx) not in active_bays:
                    continue
                x0, y0 = x_lines[x_idx], y_lines[y_idx]
                x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
                sx0, sy0 = self.world_to_screen(x0, y0)
                sx1, sy1 = self.world_to_screen(x1, y1)
                self.canvas.create_rectangle(
                    sx0,
                    sy0,
                    sx1,
                    sy1,
                    fill=self._cv["speed_bay_fill"],
                    outline="",
                    stipple="gray75",
                )

    def draw_collateral_bays(self):
        if not self.collateral_bays:
            return
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        for x_idx, y_idx in self.collateral_bays:
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            x0, y0 = x_lines[x_idx], y_lines[y_idx]
            x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
            sx0, sy0 = self.world_to_screen(x0, y0)
            sx1, sy1 = self.world_to_screen(x1, y1)
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1, fill=self._cv["collateral_fill"], outline="")

    def draw_custom_load_bays(self):
        if not self.additional_load_layers:
            return
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        bay_colors = {}
        for layer in self.additional_load_layers:
            color = self._normalize_hex_color(layer.get("color", "#f7d8a8"), "#f7d8a8")
            for x_idx, y_idx in layer.get("bays", set()):
                bay_colors.setdefault((x_idx, y_idx), []).append(color)

        for (x_idx, y_idx), colors in bay_colors.items():
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            if not colors:
                continue
            x0, y0 = x_lines[x_idx], y_lines[y_idx]
            x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
            sx0, sy0 = self.world_to_screen(x0, y0)
            sx1, sy1 = self.world_to_screen(x1, y1)
            if len(colors) == 1:
                self.canvas.create_rectangle(sx0, sy0, sx1, sy1, fill=colors[0], outline="", stipple="gray50")
                continue

            n = len(colors)
            w = sx1 - sx0
            for i, color in enumerate(colors):
                seg_x0 = sx0 + (w * i / n)
                seg_x1 = sx0 + (w * (i + 1) / n)
                self.canvas.create_rectangle(seg_x0, sy0, seg_x1, sy1, fill=color, outline="", stipple="gray50")

    def draw_inactive_bays(self):
        if not self.inactive_bays:
            return
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        for x_idx, y_idx in self.inactive_bays:
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            x0, y0 = x_lines[x_idx], y_lines[y_idx]
            x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
            sx0, sy0 = self.world_to_screen(x0, y0)
            sx1, sy1 = self.world_to_screen(x1, y1)
            self.canvas.create_rectangle(
                sx0,
                sy0,
                sx1,
                sy1,
                fill=self._cv["inactive_fill"],
                outline=self._cv["inactive_outline"],
                width=1,
                stipple="gray50",
            )

    def draw_load_bearing_perimeter(self):
        if not self.load_bearing_perimeter:
            return
        self.prune_load_bearing_perimeter()
        color = self._cv["lb_wall"]
        width = 4

        for edge in sorted(self.load_bearing_perimeter):
            seg = self._edge_to_world_segment(edge)
            if not seg:
                continue
            x1, y1, x2, y2 = seg
            sx1, sy1 = self.world_to_screen(x1, y1)
            sx2, sy2 = self.world_to_screen(x2, y2)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill=color, width=width)

    def _horizontal_segment_has_steel_girder(
        self, y_line_idx: int, x_seg_idx: int, active_bays=None, boundary_segments=None
    ):
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        if not (0 <= x_seg_idx < max_x and 0 <= y_line_idx <= max_y):
            return False
        if active_bays is None:
            active_bays = self.get_active_bays()
        if boundary_segments is None:
            boundary_segments = self._boundary_segments_for_active(active_bays, max_x, max_y)

        top_bay = (x_seg_idx, y_line_idx - 1) if y_line_idx > 0 else None
        bottom_bay = (x_seg_idx, y_line_idx) if y_line_idx < max_y else None
        top_active = bool(top_bay is not None and top_bay in active_bays)
        bottom_active = bool(bottom_bay is not None and bottom_bay in active_bays)
        if not (top_active or bottom_active):
            return False
        if top_active and bottom_active:
            return True

        edge = ("H", y_line_idx, x_seg_idx)
        if edge not in boundary_segments:
            return False
        return edge not in self.load_bearing_perimeter

    def _column_has_steel_support(self, x_line_idx: int, y_line_idx: int, active_bays=None, boundary_segments=None):
        max_x = len(self.model.x_spans)
        max_y = len(self.model.y_spans)
        if max_x <= 0 or max_y <= 0:
            return False
        if active_bays is None:
            active_bays = self.get_active_bays()
        if not (0 <= x_line_idx <= max_x and 0 <= y_line_idx <= max_y):
            return False

        surrounding = []
        for dx in (-1, 0):
            for dy in (-1, 0):
                bx = x_line_idx + dx
                by = y_line_idx + dy
                if 0 <= bx < max_x and 0 <= by < max_y and (bx, by) in active_bays:
                    surrounding.append((bx, by))
        if not surrounding:
            return False

        if boundary_segments is None:
            boundary_segments = self._boundary_segments_for_active(active_bays, max_x, max_y)
        # No column is allowed directly on a load-bearing wall segment.
        touching_edges = []
        if x_line_idx > 0:
            touching_edges.append(("H", y_line_idx, x_line_idx - 1))
        if x_line_idx < max_x:
            touching_edges.append(("H", y_line_idx, x_line_idx))
        if y_line_idx > 0:
            touching_edges.append(("V", x_line_idx, y_line_idx - 1))
        if y_line_idx < max_y:
            touching_edges.append(("V", x_line_idx, y_line_idx))
        if any(edge in boundary_segments and edge in self.load_bearing_perimeter for edge in touching_edges):
            return False

        has_left = (
            x_line_idx > 0
            and self._horizontal_segment_has_steel_girder(
                y_line_idx, x_line_idx - 1, active_bays=active_bays, boundary_segments=boundary_segments
            )
        )
        has_right = (
            x_line_idx < max_x
            and self._horizontal_segment_has_steel_girder(
                y_line_idx, x_line_idx, active_bays=active_bays, boundary_segments=boundary_segments
            )
        )
        return has_left or has_right

    def draw_joists(self):
        if not self.joists_per_bay:
            return
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        active_bays = self.get_active_bays()
        boundary_segments = self._boundary_segments_for_active(active_bays)
        for (x_idx, y_idx), spaces in self.joists_per_bay.items():
            if x_idx >= len(self.model.x_spans) or y_idx >= len(self.model.y_spans):
                continue
            spaces = int(spaces)
            if spaces <= 0:
                continue
            if (x_idx, y_idx) not in active_bays:
                continue
            x0, y0 = x_lines[x_idx], y_lines[y_idx]
            x1, y1 = x_lines[x_idx + 1], y_lines[y_idx + 1]
            member_count = spaces + 1

            sx_left, sy_top = self.world_to_screen(x0, y0)
            sx_right, sy_bot = self.world_to_screen(x1, y1)
            y_pad = 0
            line_width = 2 if self.zoom >= 0.8 else 1
            spacing_ft = (x1 - x0) / spaces

            step = spacing_ft
            x_positions = [x0 + (i * step) for i in range(member_count)]

            drawn_count = 0
            for i, x_pos in enumerate(x_positions):
                if i == 0:
                    west_edge = ("V", x_idx, y_idx)
                    left_active = (x_idx - 1, y_idx) in active_bays
                    if left_active:
                        continue
                    if west_edge in boundary_segments and west_edge in self.load_bearing_perimeter:
                        continue
                if i == (member_count - 1):
                    east_edge = ("V", x_idx + 1, y_idx)
                    if east_edge in boundary_segments and east_edge in self.load_bearing_perimeter:
                        continue
                sx, _ = self.world_to_screen(x_pos, y0)
                self.canvas.create_line(sx, sy_top + y_pad, sx, sy_bot - y_pad, fill=self._cv["joist_line"], width=line_width)
                drawn_count += 1

            if drawn_count > 0 and abs(sx_right - sx_left) > 26 and abs(sy_bot - sy_top) > 18:
                tx, ty = self.world_to_screen((x0 + x1) / 2, (y0 + y1) / 2)
                self.canvas.create_text(
                    tx,
                    ty,
                    text=f"Sp{spaces}  S={self._fmt_ft_arch(spacing_ft)}",
                    fill=self._cv["joist_label"],
                    font=("Segoe UI", 9, "bold"),
                )

    def draw_columns(self):
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        if len(x_lines) < 2 or len(y_lines) < 2:
            return
        size = 3
        active_bays = self.get_active_bays()
        boundary_segments = self._boundary_segments_for_active(active_bays)
        for x_idx in range(0, len(x_lines)):
            for y_idx in range(0, len(y_lines)):
                if not self._column_has_steel_support(x_idx, y_idx, active_bays, boundary_segments):
                    continue
                sx, sy = self.world_to_screen(x_lines[x_idx], y_lines[y_idx])
                self.canvas.create_rectangle(
                    sx - size,
                    sy - size,
                    sx + size,
                    sy + size,
                    fill=self._cv["column_fill"],
                    outline=self._cv["column_outline"],
                )

    def build_girders(self):
        if not self.model.x_spans or not self.model.y_spans:
            return []
        self.prune_load_bearing_perimeter()
        girders = []
        active_bays = self.get_active_bays()
        boundary_segments = self._boundary_segments_for_active(active_bays)
        for y_idx in range(len(self.model.y_spans) + 1):
            y_label = axis_letter(y_idx)
            for x_idx, span in enumerate(self.model.x_spans):
                if not self._horizontal_segment_has_steel_girder(
                    y_idx, x_idx, active_bays=active_bays, boundary_segments=boundary_segments
                ):
                    continue
                start_col = x_idx + 1
                end_col = x_idx + 2
                girders.append(
                    {
                        "id": f"G-{y_label}{start_col}-{y_label}{end_col}",
                        "grid_row": y_label,
                        "x_bay": x_idx + 1,
                        "start_grid": f"{y_label}{start_col}",
                        "end_grid": f"{y_label}{end_col}",
                        "length_ft": round(span, 3),
                    }
                )
        return girders

    def build_columns(self):
        self.prune_load_bearing_perimeter()
        columns = []
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        active_bays = self.get_active_bays()
        boundary_segments = self._boundary_segments_for_active(active_bays)
        for x_idx in range(0, len(x_lines)):
            for y_idx in range(0, len(y_lines)):
                if not self._column_has_steel_support(x_idx, y_idx, active_bays, boundary_segments):
                    continue
                columns.append(
                    {
                        "grid": f"{axis_letter(y_idx)}{x_idx + 1}",
                        "x_grid_index": x_idx + 1,
                        "y_grid_label": axis_letter(y_idx),
                        "x_ft": round(x_lines[x_idx], 3),
                        "y_ft": round(y_lines[y_idx], 3),
                    }
                )
        return columns

    def draw_minor_lines(self):
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        if len(x_lines) < 2 or len(y_lines) < 2:
            return
        if self.zoom >= 12:
            minor_step = 1
        elif self.zoom >= 6:
            minor_step = 2
        elif self.zoom >= 3:
            minor_step = 5
        else:
            minor_step = 10

        x0, x1 = x_lines[0], x_lines[-1]
        y0, y1 = y_lines[0], y_lines[-1]

        for i in range(len(x_lines) - 1):
            start, end = x_lines[i], x_lines[i + 1]
            pos = (math.floor(start / minor_step) + 1) * minor_step
            while pos < end:
                sx, sy0 = self.world_to_screen(pos, y0)
                _, sy1 = self.world_to_screen(pos, y1)
                self.canvas.create_line(sx, sy0, sx, sy1, fill=self._cv["minor_line"], dash=(2, 5))
                pos += minor_step

        for i in range(len(y_lines) - 1):
            start, end = y_lines[i], y_lines[i + 1]
            pos = (math.floor(start / minor_step) + 1) * minor_step
            while pos < end:
                sx0, sy = self.world_to_screen(x0, pos)
                sx1, _ = self.world_to_screen(x1, pos)
                self.canvas.create_line(sx0, sy, sx1, sy, fill=self._cv["minor_line"], dash=(2, 5))
                pos += minor_step

    def draw_major_lines_and_labels(self):
        x_lines = self.model.x_lines
        y_lines = self.model.y_lines
        if len(x_lines) < 2 or len(y_lines) < 2:
            return

        x0, x1 = x_lines[0], x_lines[-1]
        y0, y1 = y_lines[0], y_lines[-1]
        transition_lines = set(self._get_speed_bay_transition_line_indices())

        for i, x in enumerate(x_lines):
            sx, sy0 = self.world_to_screen(x, y0)
            _, sy1 = self.world_to_screen(x, y1)
            self.canvas.create_line(sx, sy0, sx, sy1, fill=self._cv["major_line"], width=2)

            label_r = 12
            lx, ly = sx, sy0 - 32
            self.canvas.create_oval(
                lx - label_r, ly - label_r, lx + label_r, ly + label_r,
                fill=self._cv["major_oval_fill"], outline=self._cv["major_oval_out"]
            )
            self.canvas.create_text(lx, ly, text=str(i + 1), fill=self._cv["major_label_fill"], font=("Segoe UI", 10, "bold"))

        for i, y in enumerate(y_lines):
            sx0, sy = self.world_to_screen(x0, y)
            sx1, _ = self.world_to_screen(x1, y)
            line_color = self._cv["transition_line"] if i in transition_lines else self._cv["major_line"]
            line_width = 3 if i in transition_lines else 2
            self.canvas.create_line(sx0, sy, sx1, sy, fill=line_color, width=line_width)

            label_r = 12
            lx, ly = sx0 - 32, sy
            self.canvas.create_oval(
                lx - label_r, ly - label_r, lx + label_r, ly + label_r,
                fill=self._cv["major_oval_fill"], outline=self._cv["major_oval_out"]
            )
            self.canvas.create_text(lx, ly, text=axis_letter(i), fill=line_color, font=("Segoe UI", 10, "bold"))

        for x in x_lines:
            for y in y_lines:
                sx, sy = self.world_to_screen(x, y)
                self.canvas.create_line(sx - 3, sy, sx + 3, sy, fill=self._cv["crosshair"])
                self.canvas.create_line(sx, sy - 3, sx, sy + 3, fill=self._cv["crosshair"])

        for i, span in enumerate(self.model.x_spans):
            mid = (x_lines[i] + x_lines[i + 1]) / 2
            tx, ty = self.world_to_screen(mid, y0)
            self.canvas.create_text(tx, ty - 56, text=self._fmt_ft_arch(span), fill=self._cv["span_label"], font=("Segoe UI", 9))

        for i, span in enumerate(self.model.y_spans):
            mid = (y_lines[i] + y_lines[i + 1]) / 2
            tx, ty = self.world_to_screen(x0, mid)
            self.canvas.create_text(tx - 58, ty, text=self._fmt_ft_arch(span), fill=self._cv["span_label"], font=("Segoe UI", 9))

    def redraw(self):
        self.canvas.delete("all")
        self.prune_inactive_bays()
        self.prune_collateral_bays()
        self.prune_custom_load_bays()
        self.prune_joist_assignments()
        self.prune_speed_bay_rows()
        self.prune_mezz_zones()
        self._sync_speed_bay_summary_vars()
        self.prune_load_bearing_perimeter()
        self._update_recommended_joist_spacing()
        self.draw_speed_bay_rows()
        self.draw_collateral_bays()
        self.draw_custom_load_bays()
        self.draw_inactive_bays()
        self.draw_minor_lines()
        self.draw_major_lines_and_labels()
        self.draw_load_bearing_perimeter()
        self.draw_joists()
        self.draw_columns()
        self.redraw_roof_section()
        self.redraw_tilt_wall_preview()
        self.redraw_mezzanine_preview()
        if not self.model.x_spans or not self.model.y_spans:
            cw = self.canvas.winfo_width() / 2
            ch = self.canvas.winfo_height() / 2
            self.canvas.create_text(
                cw,
                ch,
                text="Grid is empty.\nAdd X and Y bays (ft) to start.",
                fill=self._cv["empty_text"],
                font=("Segoe UI", 12),
                justify="center",
            )


def main():
    root = ttk_bs.Window(
        title="Structural Steel Grid Designer",
        themename="litera",
        size=(1480, 920),
        minsize=(1100, 740),
        resizable=(True, True),
    )
    app = SteelGridApp(root)
    app.fit_to_view()
    root.mainloop()


if __name__ == "__main__":
    main()
