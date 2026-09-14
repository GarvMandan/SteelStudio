"""Compare the restored Studio workflow to the original desktop methods."""
import copy
import unittest

import steel_model
from grid_gui import GridModel, SteelGridApp
from takeoff_workflow import Value, catalog_rows


def desktop_context(project, model):
    ref = object.__new__(SteelGridApp)
    ref.model = GridModel(project["x_spans_ft"], project["y_spans_ft"])
    for attr, value in {
        "clear_height_var": project["clear_height_ft"],
        "roof_type_var": "Double Slope" if project["roof_type"] == "Gable" else project["roof_type"],
        "single_slope_direction_var": project["single_slope_direction"],
        "break_clear_height_var": project["break_clear_height"],
        "joist_seat_depth_var": project["joist_seat_depth_in"],
        "footing_depth_var": project["footing_depth_ft"],
        "bearing_pressure_var": project["bearing_capacity_psf"],
        "metal_deck_thickness_var": project["metal_deck_thickness_in"],
        "insulation_depth_var": project["insulation_depth_in"],
        "footing_calc_status_var": "",
    }.items():
        setattr(ref, attr, Value(value))
    ref.speed_bay_rows = set(project["speed_bay_rows"])
    ref.last_joist_result = model["results"]["joists"]
    ref.last_girder_result = model["results"]["girders"]
    ref.last_column_result = model["results"]["columns"]
    ref.last_mezz_result = model["results"]["mezzanine"]
    ref._set_footing_results_text = lambda value: None
    ref.mezz_joist_catalog_rows = catalog_rows()[1]
    ref.mezz_joist_catalog_source = "LH Joist Table.xlsx"
    return ref


class RestoredWorkflowTests(unittest.TestCase):
    def test_all_original_auto_selection_and_concrete_wall_results_match(self):
        for roof, direction, speed, broken in [
            ("Single Slope", "North", [], False),
            ("Single Slope", "South", [0], True),
            ("Gable", "North", [0, 3], True),
        ]:
            with self.subTest(roof=roof, direction=direction, speed=speed):
                p = steel_model.defaults()
                p.update(x_spans_ft=[54, 54, 54], y_spans_ft=[40, 50, 50, 40],
                         joist_spaces=7, clear_height_ft=36, roof_height_ft=36,
                         roof_type=roof, single_slope_direction=direction,
                         speed_bay_rows=speed, break_clear_height=broken,
                         perimeter_support="walls")
                model = steel_model.calculate_project(p)
                p = model["project"]
                ref = desktop_context(p, model)
                joists, lh, girder_index, columns = catalog_rows()
                expected_joists = ref._compute_main_joist_assignments_with_lh_fallback(
                    ref.last_joist_result["joist_demand_groups"], joists)[0]
                ref.joist_selection_by_group = expected_joists
                original_profile = ref._build_roof_profile_data()
                self.assertEqual(model["grid"]["roof_heights_ft"], original_profile["line_toj_elevations_ft"])
                girder_groups = ref._build_girder_demand_groups(ref.last_girder_result["girder_calculations"])
                expected_girders = ref._compute_girder_auto_assignments(girder_groups, girder_index)[0]
                column_groups = ref._build_column_demand_groups(ref.last_column_result["column_calculations"])
                expected_columns = ref._compute_column_auto_assignments(column_groups, columns, p["clear_height_ft"])[0]
                for kind, expected in [("joists", expected_joists), ("girders", expected_girders), ("columns", expected_columns)]:
                    actual = p["auto_assignments"][kind]
                    self.assertEqual(set(actual), set(expected))
                    for group, selection in expected.items():
                        for key, value in selection.items():
                            self.assertEqual(actual[group][key], value, (kind, group, key))
                for kind, group_key, expected in [("joist", "joist_demand_groups", expected_joists), ("girder", None, expected_girders)]:
                    groups = ref.last_joist_result[group_key] if group_key else girder_groups
                    original_weight = sum(group["total_span_ft"] * expected.get(group["group_id"], {}).get("weight_plf", 0) for group in groups)
                    studio_weight = sum(member["weight_lbs"] or 0 for member in model["members"] if member["type"] == kind and member["level"] == "roof")
                    self.assertAlmostEqual(studio_weight, original_weight, delta=1.0)
                ref.calculate_pad_footings()
                self.assertEqual(model["takeoffs"]["footings"], ref.last_footing_result)
                wall = ref._calculate_tilt_wall_takeoff()
                for key in ("summary", "north_wall", "south_wall", "east_wall", "west_wall"):
                    self.assertEqual(model["takeoffs"]["walls"][key], wall[key])

    def test_bearing_and_depth_changes_follow_original_footing_rules(self):
        p = steel_model.defaults()
        first = steel_model.calculate_project(p)
        p["footing_depth_ft"] = 2
        deeper = steel_model.calculate_project(p)
        self.assertAlmostEqual(deeper["takeoffs"]["footings"]["summary"]["total_cy"], first["takeoffs"]["footings"]["summary"]["total_cy"] * 2, places=3)
        p["bearing_capacity_psf"] = 6000
        stronger = steel_model.calculate_project(p)
        self.assertLess(stronger["takeoffs"]["footings"]["summary"]["total_cy"], deeper["takeoffs"]["footings"]["summary"]["total_cy"])

    def test_manual_pin_survives_automatic_recalculation_and_save_reload(self):
        p = steel_model.defaults()
        first = steel_model.calculate_project(p)
        member = next(m for m in first["members"] if m["type"] == "joist")
        p = first["project"]
        p["member_overrides"][member["id"]] = {"designation": "Pinned joist", "depth_in": 36, "weight_plf": 18}
        p["load_inputs_psf"]["dead_load_psf"] = 35
        updated = steel_model.calculate_project(p)
        selected = next(m for m in updated["members"] if m["id"] == member["id"])
        self.assertEqual(selected["section"]["designation"], "Pinned joist")
        self.assertEqual(selected["section"]["weight_plf"], 18)
        again = steel_model.calculate_project(copy.deepcopy(updated["project"]))
        self.assertEqual(updated["summary"], again["summary"])

    def test_initial_studio_projects_keep_explicit_eave_geometry(self):
        old = {"visualizer_version": 1, "x_spans_ft": [40, 40], "y_spans_ft": [40, 40],
               "roof_type": "Gable", "roof_height_ft": 24, "roof_rise_ft": 6}
        model = steel_model.calculate_project(old)
        self.assertEqual(model["grid"]["roof_heights_ft"], [24, 30, 24])
        self.assertEqual(model["project"]["roof_calculation_mode"], "eave")
        self.assertGreater(model["takeoffs"]["footings"]["summary"]["total_cy"], 0)

    def test_mezzanine_footings_follow_original_deduplication(self):
        p = steel_model.defaults()
        p.update(mezzanine_enabled=True, mezzanines=[{
            "id": "MZ1", "name": "Office", "x_start_ft": 0, "x_end_ft": 40,
            "y_start_ft": 0, "y_end_ft": 30, "elevation_ft": 12,
            "dead_load_psf": 80, "live_load_psf": 100, "joist_spaces_per_bay": 6,
        }])
        model = steel_model.calculate_project(p)
        ref = desktop_context(model["project"], model)
        self.assertEqual(model["takeoffs"]["mezzanine_footings"], ref.calculate_mezz_pad_footings())
        self.assertGreater(model["takeoffs"]["mezzanine_footings"]["summary"]["column_count"], 0)

    def test_negative_catalog_extrapolation_leaves_girder_unassigned_without_losing_mezzanine(self):
        p = steel_model.defaults()
        p.update(mezzanine_enabled=True, mezzanines=[{
            "id": "MZ1", "name": "Office", "x_start_ft": 0, "x_end_ft": 40,
            "y_start_ft": 0, "y_end_ft": 30, "elevation_ft": 12,
            "dead_load_psf": 40, "live_load_psf": 150, "joist_spaces_per_bay": 6,
            "joist_direction": "horizontal", "internal_x_spacings_ft": [20, 20],
            "internal_y_spacings_ft": [15, 15], "joist_spaces_overrides": {"1,1": 9},
        }])
        model = steel_model.calculate_project(p)
        self.assertEqual(model["results"]["mezzanine"]["summary"]["total_mezzanine_area_sf"], 1200)
        girder = next(m for m in model["members"] if m["id"] == "MZ1-G-1-1")
        self.assertFalse(girder["section"]["assigned"])
        self.assertIsNone(girder["weight_lbs"])
        self.assertGreater(girder["demand"]["required_capacity_lbs"], 0)
        self.assertTrue(any("invalid weight" in note for note in model["notices"]))
        self.assertGreater(model["takeoffs"]["mezzanine_footings"]["summary"]["total_cy"], 0)


if __name__ == "__main__":
    unittest.main()
