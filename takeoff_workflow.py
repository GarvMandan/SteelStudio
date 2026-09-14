"""Run the desktop application's established takeoff workflow without opening Tk.

The catalog selectors, roof constraints, footing math, and wall takeoff are the
original SteelGridApp methods. Only their UI state is replaced by small values.
This keeps the desktop and Studio on the same calculation rules.
"""
from copy import deepcopy
from functools import lru_cache
import math
from pathlib import Path

import catalogs
import roof as roof_profile
import selection
from calculation_engine import InputValidationError
from grid_gui import GridModel, SteelGridApp


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@lru_cache(maxsize=1)
def catalog_rows():
    # The original Excel readers, now in catalogs.py; cached between live updates.
    root = Path(__file__).resolve().parent
    joists = catalogs.parse_joist_catalog_excel(root / "Joist Table 2.xlsx")
    lh = catalogs.parse_joist_catalog_excel(root / "LH Joist Table.xlsx")
    girders = catalogs.parse_girder_catalog_excel(root / "Expanded Vulcraft Joist Girder Catalog.xlsx")
    columns = catalogs.parse_column_catalog_excel(root / "Column Table.xlsx")
    return joists, lh, catalogs.build_girder_catalog_index(girders), columns


class Workflow(SteelGridApp):
    """A calculation-only context; no Tk root, widgets, or desktop init."""

    def __init__(self, project, results):
        self.project = project
        self.model = GridModel(project["x_spans_ft"], project["y_spans_ft"])
        self.last_joist_result = results["joists"]
        self.last_girder_result = results["girders"]
        self.last_column_result = results["columns"]
        self.last_mezz_result = results["mezzanine"]
        self.profile = None
        self.notes = []
        self.auto = {}
        self.groups = {}
        self.joist_selection_by_group = {}
        self.girder_selection_by_group = {}
        self.column_selection_by_group = {}
        self.clear_height_var = Value(project["clear_height_ft"])
        self.roof_type_var = Value("Double Slope" if project["roof_type"] == "Gable" else project["roof_type"])
        self.single_slope_direction_var = Value(project["single_slope_direction"])
        self.break_clear_height_var = Value(project["break_clear_height"])
        self.joist_seat_depth_var = Value(project["joist_seat_depth_in"])
        self.footing_depth_var = Value(project["footing_depth_ft"])
        # Historical key says psi, but the original formula divides by 1000 to
        # obtain ksf: its input value is psf. Preserve numeric behavior and label
        # the Studio control correctly instead of silently changing takeoffs.
        self.bearing_pressure_var = Value(project["bearing_capacity_psf"])
        self.metal_deck_thickness_var = Value(project["metal_deck_thickness_in"])
        self.insulation_depth_var = Value(project["insulation_depth_in"])
        self.footing_calc_status_var = Value("")
        self.speed_bay_rows = set(project["speed_bay_rows"])
        self.mezz_joist_catalog_rows = None
        self.mezz_joist_catalog_source = "LH Joist Table.xlsx"

    def _set_footing_results_text(self, text):
        self.footing_text = text

    def _build_roof_profile_data(self):
        if self.profile is not None:
            return self.profile
        return roof_profile.build_roof_profile_data(
            y_spans=self.model.y_spans,
            roof_type=self.roof_type_var.get(),
            single_slope_direction=self.single_slope_direction_var.get(),
            break_clear_height=self.break_clear_height_var.get(),
            clear_height_ft=self.clear_height_var.get(),
            joist_seat_depth_in=self.joist_seat_depth_var.get(),
            speed_bay_rows=self.speed_bay_rows,
            joist_result=self.last_joist_result,
            joist_selection_by_group=self.joist_selection_by_group,
        )

    def _get_allowed_girder_depth_by_line_in(self):
        return roof_profile.allowed_girder_depth_by_line_in(self._build_roof_profile_data())

    def _record(self, category, groups, calculate):
        self.groups[category] = groups
        if not groups or not self.project["auto_select_sections"]:
            self.auto[category] = {}
            return
        try:
            response = calculate()
            valid = {}
            for key, chosen in response[0].items():
                weight = chosen.get("weight_plf")
                if not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
                    self.notes.append(
                        f"{category.replace('_', ' ').title()}: automatic catalog estimate returned an invalid weight "
                        f"for {chosen.get('designation', key)}; left unassigned. Choose a section for this demand group."
                    )
                else:
                    valid[key] = chosen
            self.auto[category] = {
                key: dict(value, source="Original automatic catalog selection", auto_selected=True)
                for key, value in valid.items()
            }
            if response[1]:
                self.notes.append(f"{category.replace('_', ' ').title()}: no catalog match for {len(response[1])} group(s): " + "; ".join(response[1][:6]))
        except (InputValidationError, OSError) as exc:
            self.auto[category] = {}
            self.notes.append(f"{category.replace('_', ' ').title()}: {exc}")

    def select_joists(self):
        if self.project["auto_select_sections"]:
            try:
                self.joist_rows, self.mezz_joist_catalog_rows, self.girder_index, self.column_rows = catalog_rows()
            except (InputValidationError, OSError, ImportError) as exc:
                self.notes.append(f"Automatic catalog selection unavailable: {exc}")
                self.joist_rows, self.mezz_joist_catalog_rows, self.girder_index, self.column_rows = [], [], {}, []
        else:
            self.joist_rows, self.mezz_joist_catalog_rows, self.girder_index, self.column_rows = [], [], {}, []
        groups = self.last_joist_result["joist_demand_groups"]
        self._record("joists", groups, lambda: selection.compute_main_joist_assignments_with_lh_fallback(groups, self.joist_rows))
        self.joist_selection_by_group = {**self.auto["joists"], **self.project["assignments"].get("joists", {})}
        groups = self.last_mezz_result["mezzanine_joist_demand_groups"]
        self._record("mezz_joists", groups, lambda: selection.compute_joist_auto_assignments(groups, self.mezz_joist_catalog_rows, prefer_lightest_over_tier=True))

    def set_profile(self, heights):
        # Build a fresh base profile, bypassing any cached self.profile.
        saved, self.profile = self.profile, None
        try:
            profile = deepcopy(self._build_roof_profile_data())
        finally:
            self.profile = saved
        ys = self.model.y_lines
        profile.update(line_toj_elevations_ft=heights, line_roof_heights=heights,
                       bay_slopes_ft_per_ft=[(heights[i + 1] - heights[i]) / span for i, span in enumerate(self.model.y_spans)])
        self.profile = profile
        return profile

    def select_remaining(self):
        groups = self._build_girder_demand_groups(self.last_girder_result["girder_calculations"])
        self._record("girders", groups, lambda: selection.compute_girder_auto_assignments(groups, self.girder_index))
        groups = self._build_column_demand_groups(self.last_column_result["column_calculations"])
        self._record("columns", groups, lambda: selection.compute_column_auto_assignments(groups, self.column_rows, self.project["clear_height_ft"]))
        groups = self._build_mezz_girder_groups_for_assignment()
        self._record("mezz_girders", groups, lambda: selection.compute_girder_auto_assignments(groups, self.girder_index))
        groups = self.last_mezz_result["mezzanine_column_demand_groups"]
        self._record("mezz_columns", groups, lambda: selection.compute_mezz_column_auto_assignments(groups, self.column_rows))

    def concrete_and_walls(self):
        self.calculate_pad_footings()
        self.calculate_mezz_pad_footings()
        walls = self._calculate_tilt_wall_takeoff()
        # The original tilt takeoff measures the bounding rectangle, even where
        # the steel footprint has voids. Keep that convention explicit.
        walls["basis"] = "Original exterior-envelope takeoff; gross area, before openings."
        if self.project["inactive_bays"]:
            self.notes.append("Wall area follows the original bounding-rectangle envelope; footprint voids and door/window openings are not deducted.")
        return {"footings": self.last_footing_result, "mezzanine_footings": self.last_mezz_footing_result, "walls": walls}
