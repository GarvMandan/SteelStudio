"""Pad footing and tilt wall takeoff.

Extracted from SteelGridApp so the takeoff workflow no longer depends on
the tkinter desktop application.

The desktop program carried two separate implementations of identical
pad-footing math -- one for main columns, one for mezzanine columns.
They are unified here into _pad_footing_rows(); the two public wrappers
keep their original row keys and result shapes so downstream consumers
(reports, CSV export, the web takeoff tables) are unaffected.

Sizing follows the original convention:
    size_ft   = ceil(sqrt(P_kips) / sqrt(bearing_ksf), 0.25 ft)
    volume_cy = size_ft^2 * depth_ft / 27
with a 10% concrete waste allowance reported separately.

Quantities are takeoff estimates. Bearing capacity, reinforcement,
punching shear and settlement are not verified here.
"""
from __future__ import annotations

import math

from calculation_engine import InputValidationError

WASTE_FACTOR = 1.10
SIZE_INCREMENT_FT = 0.25


def ceil_to_increment(value: float, increment: float):
    if increment <= 0:
        return round(float(value), 2)
    stepped = math.ceil((float(value) - 1e-12) / increment) * increment
    return round(stepped, 2)


def _empty_result(footing_depth_ft=0.0, bearing_pressure_psf=0.0):
    return {
        "footing_depth_ft": round(float(footing_depth_ft), 3),
        "bearing_pressure_psi": round(float(bearing_pressure_psf), 3),
        "column_footings": [],
        "summary": {"column_count": 0, "total_cy": 0.0, "total_cy_with_waste": 0.0},
    }


def _pad_footing_rows(columns, footing_depth_ft, bearing_pressure_psf, describe):
    """Shared sizing loop. `describe` maps an engine column row to extra keys."""
    # Historical key says psi, but the original formula divides by 1000 to
    # obtain ksf: the input value is psf. Numeric behaviour is preserved.
    denom = math.sqrt(float(bearing_pressure_psf) / 1000.0)
    if denom <= 0:
        raise InputValidationError("Bearing Pressure must be > 0.")
    rows, total_cy = [], 0.0
    for item in columns:
        kips = max(0.0, float(item.get("required_capacity_kips", 0.0) or 0.0))
        raw_ft = math.sqrt(kips) / denom
        size_ft = ceil_to_increment(raw_ft, SIZE_INCREMENT_FT)
        volume_cy = (size_ft * size_ft * float(footing_depth_ft)) / 27.0
        total_cy += volume_cy
        row = {
            "required_capacity_kips": round(kips, 3),
            "footing_size_raw_ft": round(raw_ft, 4),
            "footing_size_ft": round(size_ft, 2),
            "footing_depth_ft": round(float(footing_depth_ft), 3),
            "footing_volume_cy": round(volume_cy, 4),
        }
        row.update(describe(item))
        rows.append(row)
    return rows, total_cy


def _result(rows, total_cy, footing_depth_ft, bearing_pressure_psf):
    return {
        "footing_depth_ft": round(float(footing_depth_ft), 3),
        "bearing_pressure_psi": round(float(bearing_pressure_psf), 3),
        "column_footings": rows,
        "summary": {
            "column_count": len(rows),
            "total_cy": round(total_cy, 4),
            "total_cy_with_waste": round(total_cy * WASTE_FACTOR, 4),
        },
    }


def calculate_pad_footings(column_result, footing_depth_ft, bearing_pressure_psf):
    """Main building pad footings, one per steel-supported column."""
    columns = list((column_result or {}).get("column_calculations", []))
    if not columns:
        return _empty_result(footing_depth_ft, bearing_pressure_psf)

    def describe(item):
        return {
            "column_id": str(item.get("column_id", "")),
            "grid": f"{item.get('line_label', '')}{item.get('grid_number', '')}",
        }

    rows, total_cy = _pad_footing_rows(columns, footing_depth_ft, bearing_pressure_psf, describe)
    return _result(rows, total_cy, footing_depth_ft, bearing_pressure_psf)


def calculate_mezz_pad_footings(mezz_result, footing_depth_ft, bearing_pressure_psf):
    """Additional pad footings for mezzanine-only columns.

    Columns reused from the main building already have a pad and are
    excluded so their concrete is not counted twice.
    """
    if not mezz_result:
        return _empty_result()
    columns = [
        row for row in list((mezz_result or {}).get("mezzanine_column_calculations", []))
        if str(row.get("main_or_mezz_column", "Mezz")).strip().lower() != "main"
    ]
    if not columns:
        return _empty_result(footing_depth_ft, bearing_pressure_psf)

    def describe(item):
        return {
            "column_id": str(item.get("column_id", "-")),
            "grid": f"{item.get('y_line_label', '-')}{item.get('x_line_label', '-')}",
            "zone_name": str(item.get("zone_name", "-")),
            "column_type": str(item.get("main_or_mezz_column", "Mezz")),
        }

    rows, total_cy = _pad_footing_rows(columns, footing_depth_ft, bearing_pressure_psf, describe)
    return _result(rows, total_cy, footing_depth_ft, bearing_pressure_psf)


def calculate_tilt_wall_takeoff(x_spans, y_spans, profile,
                                metal_deck_thickness_in, insulation_depth_in):
    """Gross exterior tilt panel area, before openings.

    Measures the bounding rectangle of the building envelope: footprint
    voids and door/window openings are not deducted. East/West walls step
    with the roof profile; dock (speed bay) sides carry the taller center
    panel.
    """
    if not x_spans or not y_spans:
        raise InputValidationError("Add X and Y bays before calculating tilt walls.")
    if not profile:
        raise InputValidationError("Roof profile unavailable for tilt wall calculation.")

    deck_in = float(metal_deck_thickness_in)
    insulation_in = float(insulation_depth_in)
    deck_ft = deck_in / 12.0
    insulation_ft = insulation_in / 12.0
    x_spans = list(x_spans)
    y_spans = list(y_spans)
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
