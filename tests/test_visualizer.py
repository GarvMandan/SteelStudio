"""Regression tests for Steel Studio's calculation adapter and local HTTP API.

Run from the project root: .venv/Scripts/python.exe -m unittest discover -s tests -v
The fixtures deliberately use the original engine as the takeoff authority.
"""

import copy
import http.client
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import calculation_engine as engine
import steel_model
import visualizer


def project_fixture():
    project = steel_model.defaults()
    project.update({
        "name": "Adapter regression model",
        "x_spans_ft": [24.0, 36.0],
        "y_spans_ft": [30.0, 40.0],
        "roof_height_ft": 22.0,
        "roof_type": "Flat",
        "roof_rise_ft": 0.0,
        "joist_spaces": 4,
        "joists_per_bay": [
            {"x_bay": 1, "y_bay": "A", "joist_count": 4},
            {"x_bay": 2, "y_bay": "A", "joist_count": 3},
            {"x_bay": 1, "y_bay": "B", "joist_count": 4},
            {"x_bay": 2, "y_bay": "B", "joist_count": 3},
        ],
        "inactive_bays": [],
        "load_bearing_wall_segments": [],
        "collateral_bays": [{"x_bay": 2, "y_bay": "A"}],
        "additional_load_layers": [{
            "name": "Equipment", "psf": 6.0,
            "bays": [{"x_bay": 1, "y_bay": "B"}],
        }],
        "load_inputs_psf": {
            "dead_load_psf": 18.0,
            "live_load_psf": 20.0,
            "snow_load_psf": 25.0,
            "snow_code": "ASCE 7-16",
            "collateral_addition_psf": 5.0,
        },
        "mezzanine_enabled": False,
        "mezzanines": [],
        "member_overrides": {},
    })
    project.pop("active_bays", None)
    return project


def original_layout(project):
    """Translate only the Studio inactive-bay field into the engine's format."""
    layout = copy.deepcopy(project)
    inactive = {(b["x_bay"], b["y_bay"]) for b in project["inactive_bays"]}
    layout["active_bays"] = [
        {"x_bay": x + 1, "y_bay": engine.axis_letter(y)}
        for x in range(len(project["x_spans_ft"]))
        for y in range(len(project["y_spans_ft"]))
        if (x + 1, engine.axis_letter(y)) not in inactive
    ]
    return layout


class AdapterTests(unittest.TestCase):
    def test_original_takeoffs_are_preserved_exactly(self):
        project = project_fixture()
        snapshot = copy.deepcopy(project)
        result = steel_model.calculate_project(project)
        layout = original_layout(project)
        for key, calculate in (
            ("joists", engine.calculate_joist_takeoff),
            ("girders", engine.calculate_girder_takeoff),
            ("columns", engine.calculate_column_takeoff),
            ("mezzanine", engine.calculate_mezzanine_takeoff),
        ):
            with self.subTest(takeoff=key):
                self.assertEqual(result["results"][key], calculate(layout))
        self.assertEqual(project, snapshot, "Calculation must not mutate the editor state")

    def test_adapter_invokes_each_original_engine_calculation(self):
        names = ("calculate_joist_takeoff", "calculate_girder_takeoff", "calculate_column_takeoff", "calculate_mezzanine_takeoff")
        patches = [patch.object(engine, name, wraps=getattr(engine, name)) for name in names]
        calls = [item.start() for item in patches]
        try:
            steel_model.calculate_project(project_fixture())
            for call in calls:
                call.assert_called_once()
        finally:
            for item in reversed(patches):
                item.stop()

    def test_shared_joists_have_exactly_one_member_at_engine_coordinates(self):
        project = project_fixture()
        result = steel_model.calculate_project(project)
        members = {m["engine_id"]: m for m in result["members"] if m["type"] == "joist"}
        rows = result["results"]["joists"]["joist_members"]
        self.assertEqual(len(members), 16)  # (4 + 3 + 1 unique joists) in each row
        self.assertEqual(len(members), len(rows))
        coordinates = set()
        spaces = {(v["x_bay"], v["y_bay"]): v["joist_count"] for v in project["joists_per_bay"]}
        for row in rows:
            member = members[row["id"]]
            x_index = row["x_bay_index"] - 1
            y_index = engine.axis_index(row["y_row_label"])
            x = sum(project["x_spans_ft"][:x_index]) + (
                (row["member_index_in_bay"] - 1) * project["x_spans_ft"][x_index]
                / spaces[(x_index + 1, row["y_row_label"])]
            )
            y = sum(project["y_spans_ft"][:y_index])
            self.assertAlmostEqual(member["start"][0], x, places=5)
            self.assertAlmostEqual(member["start"][1], y, places=5)
            self.assertAlmostEqual(member["end"][0], x, places=5)
            self.assertAlmostEqual(member["end"][1], y + row["span_ft"], places=5)
            self.assertAlmostEqual(member["length_ft"], row["span_ft"], places=3)
            coordinates.add((tuple(member["start"]), tuple(member["end"])))
        self.assertEqual(len(coordinates), len(rows), "Shared-edge members must not be duplicated")

    def test_void_bay_and_load_bearing_walls_match_engine_omissions(self):
        project = project_fixture()
        project["inactive_bays"] = [{"x_bay": 2, "y_bay": "B"}]
        project["load_bearing_wall_segments"] = [
            {"orientation": "H", "line_index": 1, "segment_index": 1},
            {"orientation": "V", "line_index": 1, "segment_index": 1},
            {"orientation": "V", "line_index": 2, "segment_index": 2},
        ]
        result = steel_model.calculate_project(project)
        layout = original_layout(project)
        expected = {
            "joist": {m["id"] for m in engine.calculate_joist_takeoff(layout)["joist_members"]},
            "girder": {m["girder_id"] for m in engine.calculate_girder_takeoff(layout)["girder_calculations"]},
            "column": {m["column_id"] for m in engine.calculate_column_takeoff(layout)["column_calculations"]},
        }
        for kind, expected_ids in expected.items():
            with self.subTest(member_type=kind):
                self.assertEqual({m["engine_id"] for m in result["members"] if m["type"] == kind}, expected_ids)
        self.assertNotIn("G-A1-A2", expected["girder"])
        self.assertNotIn("C-A1", expected["column"])

    def test_dimensions_rebuild_geometry_and_load_demands(self):
        project = project_fixture()
        before = steel_model.calculate_project(project)
        project["x_spans_ft"][0] = 48.0
        after = steel_model.calculate_project(project)
        self.assertEqual(after["grid"]["width_ft"], 84.0)
        self.assertEqual(after["grid"]["length_ft"], 70.0)
        self.assertNotEqual(before["results"]["joists"], after["results"]["joists"])
        rightmost = max(max(m["start"][0], m["end"][0]) for m in after["members"])
        self.assertAlmostEqual(rightmost, 84.0)

    def test_nonfinite_dimensions_and_loads_are_rejected(self):
        for invalid in (math.nan, math.inf, -math.inf, "NaN", "Infinity"):
            for field in ("x_spans_ft", "roof_height_ft", "dead_load_psf"):
                with self.subTest(field=field, value=invalid):
                    project = project_fixture()
                    if field == "x_spans_ft":
                        project[field][0] = invalid
                    elif field == "dead_load_psf":
                        project["load_inputs_psf"][field] = invalid
                    else:
                        project[field] = invalid
                    with self.assertRaises(steel_model.InputValidationError):
                        steel_model.calculate_project(project)

    def test_invalid_grid_and_empty_footprint_are_rejected(self):
        for change in ({"x_spans_ft": []}, {"x_spans_ft": [0]}, {"joist_spaces": 0}, {
            "inactive_bays": [{"x_bay": x, "y_bay": y} for x in (1, 2) for y in ("A", "B")],
        }):
            with self.subTest(change=change):
                project = project_fixture()
                project.update(change)
                with self.assertRaises(steel_model.InputValidationError):
                    steel_model.calculate_project(project)

    def test_roof_heights_and_member_lengths_are_finite(self):
        for roof in ("Flat", "Gable", "Single Slope"):
            with self.subTest(roof=roof):
                project = project_fixture()
                project.update(roof_type=roof, roof_rise_ft=6.0)
                result = steel_model.calculate_project(project)
                for member in result["members"]:
                    self.assertGreater(member["length_ft"], 0)
                    self.assertTrue(all(math.isfinite(v) for v in member["start"] + member["end"]))
                    self.assertGreaterEqual(member["length_ft"] + 0.005, math.dist(member["start"], member["end"]))
                    if roof == "Flat":
                        self.assertAlmostEqual(member["length_ft"], math.dist(member["start"], member["end"]), places=2)

    def test_mezzanine_geometry_matches_all_calculated_members(self):
        project = project_fixture()
        project["mezzanine_enabled"] = True
        project["mezzanines"] = [{
            "id": "MZ001", "name": "Office mezzanine", "enabled": True,
            "x_start_line_index": 1, "x_end_line_index": 2,
            "y_start_line_index": 1, "y_end_line_index": 2,
            "elevation_ft": 12, "dead_load_psf": 25, "live_load_psf": 80,
            "joist_spaces_per_bay": 4,
        }]
        result = steel_model.calculate_project(project)
        mezz = result["results"]["mezzanine"]
        self.assertEqual(mezz, engine.calculate_mezzanine_takeoff(original_layout(project)))
        expected = {
            "joist": len(result["results"]["joists"]["joist_members"]) + sum(r["joist_count"] for r in mezz["mezzanine_joist_calculations"]),
            "girder": len(result["results"]["girders"]["girder_calculations"]) + len(mezz["mezzanine_girder_calculations"]),
            "column": len(result["results"]["columns"]["column_calculations"]) + len(mezz["mezzanine_column_calculations"]),
        }
        for kind, count in expected.items():
            self.assertEqual(sum(m["type"] == kind for m in result["members"]), count)
        self.assertEqual(len({m["id"] for m in result["members"]}), len(result["members"]))

    def test_legacy_project_import_keeps_footprint_loads_and_assignments(self):
        project = project_fixture()
        project["inactive_bays"] = [{"x_bay": 2, "y_bay": "B"}]
        group = engine.calculate_joist_takeoff(original_layout(project))["joist_demand_groups"][0]
        assigned = {"designation": "Existing selected joist", "depth_in": 30.0, "weight_plf": 16.5}
        legacy = {
            "app": "Structural Steel Takeoff", "project_version": 1,
            "inputs": {
                **project["load_inputs_psf"], "joist_spaces_default": "4",
                "clear_height_ft": "22", "roof_type": "Flat",
            },
            "grid": {
                key: copy.deepcopy(project[key]) for key in (
                    "x_spans_ft", "y_spans_ft", "inactive_bays", "collateral_bays",
                    "load_bearing_wall_segments", "additional_load_layers",
                )
            },
            "assignments": {"joists": {group["group_id"]: assigned}},
            "mezzanines": [],
        }
        legacy["grid"]["joists_per_bay"] = [
            {"x_bay": b["x_bay"], "y_bay": b["y_bay"], "joist_spaces": b["joist_count"]}
            for b in project["joists_per_bay"]
        ]
        imported = steel_model.calculate_project(legacy)
        self.assertEqual(imported["results"]["joists"], engine.calculate_joist_takeoff(original_layout(project)))
        self.assertEqual(imported["grid"]["width_ft"], 60.0)
        assigned_members = [m for m in imported["members"] if m["type"] == "joist" and m["assignment_group_id"] == group["group_id"]]
        self.assertEqual(len(assigned_members), group["count"])
        for member in assigned_members:
            self.assertEqual(member["section"]["designation"], assigned["designation"])
            self.assertEqual(member["section"]["weight_plf"], assigned["weight_plf"])
        reloaded = steel_model.calculate_project(json.loads(json.dumps(imported["project"])))
        self.assertEqual(reloaded["members"], imported["members"])

    def test_legacy_manual_snow_field_preserves_7_22_demand(self):
        legacy = {
            "app": "Structural Steel Takeoff", "project_version": 1,
            "grid": {"x_spans_ft": [24], "y_spans_ft": [30], "load_bearing_wall_segments": []},
            "inputs": {
                "dead_load_psf": "18", "live_load_psf": "20", "snow_load_psf": "50",
                "snow_code": "ASCE 7-22", "reduced_snow_load_manual_psf": "37.5",
                "joist_spaces_default": "4", "clear_height_ft": "22",
            },
        }
        imported = steel_model.calculate_project(legacy)
        self.assertEqual(imported["results"]["joists"]["load_inputs_psf"]["reduced_snow_load_psf"], 37.5)
        self.assertEqual(imported["results"]["joists"]["joist_bay_calculations"][0]["total_load_psf"], 55.5)

    def test_member_override_updates_weight_and_survives_json_roundtrip(self):
        project = project_fixture()
        project["auto_select_sections"] = False
        original = steel_model.calculate_project(project)
        member = next(m for m in original["members"] if m["type"] == "joist")
        self.assertEqual(original["summary"]["total_weight_lbs"], 0.0)
        project["member_overrides"][member["id"]] = {
            "designation": "Custom review joist", "depth_in": 32.0, "weight_plf": 14.75,
        }
        selected = steel_model.calculate_project(project)
        updated = next(m for m in selected["members"] if m["id"] == member["id"])
        self.assertEqual(updated["section"]["designation"], "Custom review joist")
        self.assertEqual(updated["section"]["depth_in"], 32.0)
        self.assertEqual(updated["section"]["weight_plf"], 14.75)
        self.assertEqual(updated["weight_lbs"], round(member["length_ft"] * 14.75, 2))
        self.assertEqual(selected["summary"]["total_weight_lbs"], updated["weight_lbs"])
        self.assertEqual(selected["summary"]["unassigned_count"], len(selected["members"]) - 1)
        self.assertEqual(updated["check_status"], "unchecked")
        reloaded = steel_model.calculate_project(json.loads(json.dumps(selected["project"], allow_nan=False)))
        self.assertEqual(reloaded["members"], selected["members"])
        self.assertEqual(reloaded["summary"], selected["summary"])
        self.assertEqual(reloaded["results"], original["results"], "Profile selections must not alter demand calculations")

    def test_global_wall_mode_tracks_footprint_and_emits_wall_geometry(self):
        project = steel_model.defaults()
        project["perimeter_support"] = "walls"
        model = steel_model.calculate_project(project)
        self.assertEqual(len(model["walls"]), 10)
        self.assertEqual(model["summary"]["column_count"], 2)
        project["inactive_bays"] = [{"x_bay": 3, "y_bay": "B"}]
        model = steel_model.calculate_project(project)
        self.assertEqual(len(model["walls"]), 10)
        self.assertTrue(any(w["start"][0] == 80 and w["start"][1] == 40 for w in model["walls"]))
        project["perimeter_support"] = "steel"
        self.assertEqual(steel_model.calculate_project(project)["walls"], [])

    def test_catalog_selection_changes_section_and_rejects_unknown_id(self):
        project = project_fixture()
        model = steel_model.calculate_project(project)
        member = next(m for m in model["members"] if m["type"] == "column")
        section = model["catalog"]["column"][0]
        project["member_overrides"][member["id"]] = {"section_id": section["id"]}
        selected = steel_model.calculate_project(project)
        changed = next(m for m in selected["members"] if m["id"] == member["id"])
        self.assertEqual(changed["section"]["designation"], section["designation"])
        self.assertEqual(changed["section"]["weight_plf"], section["weight_plf"])
        self.assertEqual(changed["check_status"], "unchecked")
        project["member_overrides"][member["id"]] = {"section_id": "missing-catalog-section"}
        with self.assertRaises(steel_model.InputValidationError):
            steel_model.calculate_project(project)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.static = root / "static"
        cls.static.mkdir()
        (cls.static / "index.html").write_text("<!doctype html><title>Steel Studio test</title>", encoding="utf-8")
        (cls.static / "studio.js").write_text("window.steelStudio = true;", encoding="utf-8")
        (root / "private.txt").write_text("PRIVATE TEST SENTINEL", encoding="utf-8")
        cls.server = visualizer.create_server(port=0, initial_project=project_fixture(), static_dir=cls.static)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post(self, path, project):
        return self.request(path, "POST", json.dumps(project), {"Content-Type": "application/json"})

    def test_health_project_and_catalog_are_readable(self):
        for path in ("/api/health", "/api/project", "/api/catalog"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn("application/json", headers["Content-Type"])
                self.assertIsInstance(json.loads(body), dict)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_calculate_and_import_are_complete_json_models(self):
        for path in ("/api/calculate", "/api/import"):
            with self.subTest(path=path):
                status, _, body = self.post(path, project_fixture())
                self.assertEqual(status, 200, body.decode())
                model = json.loads(body)
                self.assertTrue(model["members"])
                self.assertEqual(model["grid"]["width_ft"], 60.0)
                self.assertIn("joists", model["results"])

    def test_invalid_requests_do_not_replace_current_project(self):
        self.post("/api/calculate", project_fixture())
        before = self.request("/api/project")[2]
        for body in ('{"x_spans_ft": [NaN]}', '{"x_spans_ft": [Infinity]}', "{broken", "[]"):
            with self.subTest(body=body):
                status, _, result = self.request("/api/calculate", "POST", body, {"Content-Type": "application/json"})
                self.assertEqual(status, 400, result.decode())
                self.assertIn("error", json.loads(result))
        self.assertEqual(self.request("/api/project")[2], before)

    def test_wrong_content_type_and_foreign_origin_are_rejected(self):
        status, _, _ = self.request("/api/calculate", "POST", "{}", {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, _ = self.request("/api/calculate", "POST", "{}", {
            "Content-Type": "application/json", "Origin": "https://unrelated.example",
        })
        self.assertEqual(status, 403)
        status, _, _ = self.request("/api/project", headers={"Host": "unrelated.example"})
        self.assertEqual(status, 403)

    def test_static_files_and_traversal(self):
        for path in ("/", "/studio.js"):
            self.assertEqual(self.request(path)[0], 200)
        for path in ("/../private.txt", "/%2e%2e/private.txt", "/%2e%2e%5cprivate.txt", "/missing.js"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"PRIVATE TEST SENTINEL", body)

    def test_oversized_body_is_rejected_before_read(self):
        status, _, _ = self.request("/api/calculate", "POST", "{}", {
            "Content-Type": "application/json", "Content-Length": str(visualizer.MAX_BODY_BYTES + 1),
        })
        self.assertEqual(status, 413)

    def test_pdf_export_does_not_replace_the_live_project(self):
        from test_report import image_fixture
        self.post('/api/calculate', project_fixture())
        before = self.request('/api/project')[2]
        snapshot = project_fixture()
        snapshot['name'] = 'Separate report snapshot'
        snapshot['x_spans_ft'][0] = 28
        status, headers, body = self.post('/api/report', {
            'project': snapshot, 'model_image': image_fixture(), 'report': {'revision': '03'},
        })
        self.assertEqual(status, 200, body[:200])
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        self.assertIn('Separate report snapshot', headers['Content-Disposition'])
        self.assertTrue(body.startswith(b'%PDF-'))
        self.assertEqual(self.request('/api/project')[2], before)

    def test_pdf_requires_valid_image_and_obeys_origin_and_size_limits(self):
        before = self.request('/api/project')[2]
        for payload in [{}, {'project': project_fixture()},
                        {'project': project_fixture(), 'model_image': 'data:image/png;base64,bad'}]:
            self.assertEqual(self.post('/api/report', payload)[0], 400)
        self.assertEqual(self.request('/api/report', 'POST', '{}', {
            'Content-Type': 'application/json', 'Origin': 'https://unrelated.example',
        })[0], 403)
        self.assertEqual(self.request('/api/report', 'POST', '{}', {
            'Content-Type': 'application/json', 'Content-Length': str(visualizer.MAX_REPORT_BYTES + 1),
        })[0], 413)
        self.assertEqual(self.request('/api/project')[2], before)


if __name__ == "__main__":
    unittest.main()
