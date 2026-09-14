"""Roof profile geometry.

Extracted verbatim from SteelGridApp so the takeoff workflow no longer
depends on the tkinter desktop application. Implements the original
quarter-inch-per-foot main roof slope, half-inch speed-bay slope,
double-slope ridge conventions and break-clear-height anchoring.

Elevations are top-of-joist (TOJ) in feet; the profile drives girder
depth limits and tilt wall heights, so its conventions are load bearing.
"""
from __future__ import annotations

from calculation_engine import axis_letter


def format_joist_group_id(required_capacity_plf, bay_length_ft):
    return f"{float(required_capacity_plf):.2f}|{float(bay_length_ft):.2f}"


def get_assigned_joist_depth_for_row(y_row_idx, joist_result, joist_selection_by_group):
    """Conservative (deepest) assigned joist depth across one lettered row."""
    if y_row_idx < 0 or not joist_result:
        return None
    row_label = axis_letter(y_row_idx)
    depths = []
    for bay_calc in joist_result.get("joist_bay_calculations", []):
        if bay_calc.get("y_row_label") != row_label:
            continue
        group_id = format_joist_group_id(bay_calc["required_capacity_plf"], bay_calc["bay_length_ft"])
        assigned = (joist_selection_by_group or {}).get(group_id)
        if assigned and float(assigned.get("depth_in", 0.0)) > 0:
            depths.append(float(assigned["depth_in"]))
    return max(depths) if depths else None


def selected_speed_bay_rows(speed_bay_rows, row_count):
    return {int(i) for i in (speed_bay_rows or set())
            if isinstance(i, (int, float)) and 0 <= int(i) < row_count}


def speed_bay_transition_line_indices(speed_bay_rows, row_count):
    speed_rows = selected_speed_bay_rows(speed_bay_rows, row_count)
    if row_count <= 0:
        return []
    return [i for i in range(1, row_count)
            if ((i - 1) in speed_rows) != (i in speed_rows)]


def _classify_speed_row_side(row_idx: int, speed_rows: set, row_count: int, single_slope_direction: str):
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

def _compute_bay_slopes_ft_per_ft(y_spans,
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
                side = _classify_speed_row_side(row_idx, speed_rows, row_count, single_slope_direction)
                sign = 1.0 if side == "North" else -1.0
                slopes.append(sign * slope_speed_ft_per_ft)
            else:
                slopes.append(main_sign * slope_main_ft_per_ft)

        return slopes


def build_roof_profile_data(y_spans, roof_type, single_slope_direction, break_clear_height,
                            clear_height_ft, joist_seat_depth_in, speed_bay_rows,
                            joist_result=None, joist_selection_by_group=None):
    """Original roof profile. Returns TOJ elevations and per-bay slopes."""
    y_spans = list(y_spans)
    if not y_spans:
        return None

    single_slope_direction = str(single_slope_direction or "North").strip().title()
    if single_slope_direction not in {"North", "South"}:
        single_slope_direction = "North"
    break_clear_height = bool(break_clear_height)
    clear_height_ft = float(clear_height_ft)
    joist_seat_depth_in = float(joist_seat_depth_in)
    y_lines = [0.0]
    running = 0.0
    for span in y_spans:
        running += span
        y_lines.append(running)
    total_len_ft = y_lines[-1]
    ridge_line_idx = len(y_lines) // 2
    ridge_station_ft = y_lines[ridge_line_idx]
    speed_rows = selected_speed_bay_rows(speed_bay_rows, len(y_spans))
    transition_lines = speed_bay_transition_line_indices(speed_bay_rows, len(y_spans))
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
    joist_depth_in = get_assigned_joist_depth_for_row(joist_depth_row_idx, joist_result, joist_selection_by_group)
    if joist_depth_in is None:
        joist_depth_in = 0.0
    start_height_ft = clear_height_ft + (joist_depth_in / 12.0)  # BMD == TOJ.

    bay_slopes_ft_per_ft = _compute_bay_slopes_ft_per_ft(
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


def allowed_girder_depth_by_line_in(profile):
    """Girder depth budget per Y line: TOJ above clear height, in inches."""
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


def jb_drop_in_by_line(profile):
    if not profile:
        return {}
    toj_list = profile.get("line_toj_elevations_ft", profile.get("line_roof_heights", []))
    if len(toj_list) <= 0:
        return {}
    seat = float(profile.get("joist_seat_depth_in", profile.get("joist_depth_thickness_in", 2.5)))
    return {idx: max(0.0, seat) for idx in range(len(toj_list))}
