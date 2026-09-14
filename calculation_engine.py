from statistics import mean
from fractions import Fraction


class InputValidationError(ValueError):
    """Raised when layout or calculation inputs are invalid."""


def axis_letter(index: int) -> str:
    index += 1
    letters = []
    while index:
        index, rem = divmod(index - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def axis_index(label: str) -> int:
    if not label:
        raise InputValidationError("Axis label cannot be empty.")
    label = str(label).strip().upper()
    total = 0
    for ch in label:
        if not ("A" <= ch <= "Z"):
            raise InputValidationError(f"Invalid axis label: {label}")
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return total - 1


def _joist_count_map(joists_per_bay):
    output = {}
    for item in joists_per_bay or []:
        x_idx = int(item["x_bay"]) - 1
        y_idx = axis_index(item["y_bay"])
        spaces = int(item["joist_count"])
        if spaces < 1:
            raise InputValidationError("Joist spaces per bay must be >= 1.")
        output[(x_idx, y_idx)] = spaces
    return output


def _get_non_negative_float(value, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{label} must be numeric.") from exc
    if parsed < 0:
        raise InputValidationError(f"{label} must be >= 0.")
    return parsed


def _fmt_ft_arch(value, inch_resolution: float = 0.5) -> str:
    feet_value = float(value)
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
        inch_text = f'{inch_whole}"'
    else:
        frac = Fraction(inch_frac).limit_denominator(64)
        if inch_whole > 0:
            inch_text = f'{inch_whole} {frac.numerator}/{frac.denominator}"'
        else:
            inch_text = f'{frac.numerator}/{frac.denominator}"'
    return f"{sign}{feet_int}'-{inch_text}"


def _bay_set(bays):
    output = set()
    for item in bays or []:
        x_idx = int(item["x_bay"]) - 1
        y_idx = axis_index(item["y_bay"])
        output.add((x_idx, y_idx))
    return output


def _collateral_bay_set(collateral_bays):
    return _bay_set(collateral_bays)


def _custom_load_bay_set(custom_load_bays):
    return _bay_set(custom_load_bays)


def _normalize_additional_load_layers(layout_data, load_inputs):
    output = []
    for idx, layer in enumerate(layout_data.get("additional_load_layers") or [], start=1):
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name") or f"Additional {idx}").strip() or f"Additional {idx}"
        psf = _get_non_negative_float(layer.get("psf", layer.get("load_psf", 0.0)), f"Additional Load '{name}'")
        bays = _bay_set(layer.get("bays"))
        color = str(layer.get("color") or "#f7d8a8")
        output.append(
            {
                "name": name,
                "psf": float(psf),
                "color": color,
                "bays": bays,
            }
        )

    # Backward compatibility for old single custom-load payload.
    if not output:
        legacy_psf = _get_non_negative_float(load_inputs.get("custom_load_addition_psf", 0.0), "Custom Load Addition")
        legacy_bays = _custom_load_bay_set(layout_data.get("custom_load_bays"))
        if legacy_psf > 0 and legacy_bays:
            output.append(
                {
                    "name": "Custom Load",
                    "psf": float(legacy_psf),
                    "color": "#f7d8a8",
                    "bays": legacy_bays,
                }
            )
    return output


def _parse_float_list(values, label: str):
    if values is None:
        return []
    if isinstance(values, str):
        raw = [v.strip() for v in values.split(",")]
    elif isinstance(values, (list, tuple)):
        raw = list(values)
    else:
        raise InputValidationError(f"{label} must be a comma-separated list or array.")

    output = []
    for item in raw:
        token = str(item).strip()
        if not token:
            continue
        try:
            parsed = float(token)
        except (TypeError, ValueError) as exc:
            raise InputValidationError(f"{label} contains non-numeric value: '{token}'.") from exc
        if parsed <= 0:
            raise InputValidationError(f"{label} values must be > 0.")
        output.append(parsed)
    return output


def _fit_segments_to_total(total_ft: float, custom_segments_ft, label: str):
    total = float(total_ft)
    if total <= 0:
        raise InputValidationError(f"{label} total length must be > 0.")
    if not custom_segments_ft:
        return [round(total, 3)]

    segments = []
    running = 0.0
    tol = 1e-6
    for seg in custom_segments_ft:
        seg_val = float(seg)
        if seg_val <= 0:
            raise InputValidationError(f"{label} segment values must be > 0.")
        nxt = running + seg_val
        if nxt > total + tol:
            raise InputValidationError(
                f"{label} segments exceed zone length ({running + seg_val:.3f} > {total:.3f} ft)."
            )
        segments.append(seg_val)
        running = nxt
        if abs(running - total) <= tol:
            running = total
            break

    if running < total - tol:
        rem = total - running
        # Avoid near-zero trailing bays caused by floating precision residue.
        if rem < 0.25 and segments:
            segments[-1] = float(segments[-1]) + float(rem)
        else:
            segments.append(rem)

    clean = [round(float(v), 3) for v in segments if float(v) > tol]
    if not clean:
        raise InputValidationError(f"{label} segments are empty after normalization.")
    return clean


def _normalize_mezzanine_direction(value):
    token = str(value or "").strip().lower()
    if token.startswith("h"):
        return "horizontal"
    if token.startswith("v"):
        return "vertical"
    if "e-w" in token or "east" in token or "west" in token:
        return "horizontal"
    return "vertical"


def _find_line_index_for_coordinate(lines, value, tol=1e-6):
    target = float(value)
    for idx, v in enumerate(lines):
        if abs(float(v) - target) <= tol:
            return idx
    return None


def _parse_mezz_panel_key(token):
    text = str(token or "").strip().upper()
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


def _additional_load_map_by_bay(additional_layers):
    output = {}
    for layer in additional_layers or []:
        psf = float(layer.get("psf", 0.0) or 0.0)
        if psf <= 0:
            continue
        for bay in layer.get("bays", set()) or set():
            output[bay] = output.get(bay, 0.0) + psf
    return output


def _active_bay_set(layout_data, x_spans, y_spans):
    max_x = len(x_spans)
    max_y = len(y_spans)
    items = layout_data.get("active_bays")
    if not items:
        return {(x_idx, y_idx) for x_idx in range(max_x) for y_idx in range(max_y)}

    output = set()
    for item in items:
        x_idx = int(item["x_bay"]) - 1
        y_idx = axis_index(item["y_bay"])
        if 0 <= x_idx < max_x and 0 <= y_idx < max_y:
            output.add((x_idx, y_idx))
    if not output:
        raise InputValidationError("No active bays found. Re-enable at least one bay in the building shape.")
    return output


def _all_perimeter_segments_for_counts(x_count: int, y_count: int):
    if x_count <= 0 or y_count <= 0:
        return set()
    output = set()
    for x_idx in range(x_count):
        output.add(("N", x_idx))
        output.add(("S", x_idx))
    for y_idx in range(y_count):
        output.add(("W", y_idx))
        output.add(("E", y_idx))
    return output


def _active_boundary_segment_set(active_set, x_spans, y_spans):
    max_x = len(x_spans)
    max_y = len(y_spans)
    output = set()
    for x_idx, y_idx in active_set:
        if y_idx == 0 or (x_idx, y_idx - 1) not in active_set:
            output.add(("H", y_idx, x_idx))
        if y_idx == max_y - 1 or (x_idx, y_idx + 1) not in active_set:
            output.add(("H", y_idx + 1, x_idx))
        if x_idx == 0 or (x_idx - 1, y_idx) not in active_set:
            output.add(("V", x_idx, y_idx))
        if x_idx == max_x - 1 or (x_idx + 1, y_idx) not in active_set:
            output.add(("V", x_idx + 1, y_idx))
    return output


def _legacy_outer_edge_from_side(side: str, seg_idx: int, x_spans, y_spans):
    side = str(side or "").strip().upper()
    if side == "N":
        return ("H", 0, seg_idx)
    if side == "S":
        return ("H", len(y_spans), seg_idx)
    if side == "W":
        return ("V", 0, seg_idx)
    if side == "E":
        return ("V", len(x_spans), seg_idx)
    return None


def _boundary_load_bearing_set(layout_data, x_spans, y_spans, active_set):
    valid_boundary = _active_boundary_segment_set(active_set, x_spans, y_spans)
    if not valid_boundary:
        return set()

    items = layout_data.get("load_bearing_wall_segments")
    if items is not None:
        output = set()
        for item in items:
            orient = str(item.get("orientation", item.get("orient", ""))).strip().upper()
            if orient not in {"H", "V"}:
                continue
            try:
                line_idx = int(item.get("line_index", item.get("line", item.get("line_idx")))) - 1
                seg_idx = int(item.get("segment_index", item.get("segment", item.get("index")))) - 1
            except (TypeError, ValueError):
                continue
            edge = (orient, line_idx, seg_idx)
            if edge in valid_boundary:
                output.add(edge)
        return output

    # Legacy payload support.
    legacy = layout_data.get("perimeter_load_bearing_segments")
    if legacy is not None:
        output = set()
        for item in legacy:
            side = str(item.get("side", "")).strip().upper()
            try:
                seg_idx = int(item.get("segment_index", item.get("segment", item.get("index")))) - 1
            except (TypeError, ValueError):
                continue
            edge = _legacy_outer_edge_from_side(side, seg_idx, x_spans, y_spans)
            if edge in valid_boundary:
                output.add(edge)
        return output

    # Backward compatibility: if nothing provided, assume all active boundary walls are load-bearing.
    return set(valid_boundary)


def _horizontal_segment_has_steel(y_line_idx, x_seg_idx, x_spans, y_spans, active_set, boundary_set, lb_set):
    max_x = len(x_spans)
    max_y = len(y_spans)
    if not (0 <= x_seg_idx < max_x and 0 <= y_line_idx <= max_y):
        return False

    top_bay = (x_seg_idx, y_line_idx - 1) if y_line_idx > 0 else None
    bottom_bay = (x_seg_idx, y_line_idx) if y_line_idx < max_y else None
    top_active = bool(top_bay is not None and top_bay in active_set)
    bottom_active = bool(bottom_bay is not None and bottom_bay in active_set)
    if not (top_active or bottom_active):
        return False
    if top_active and bottom_active:
        return True

    edge = ("H", y_line_idx, x_seg_idx)
    if edge not in boundary_set:
        return False
    return edge not in lb_set


def _column_has_steel_support(x_line_idx, y_line_idx, x_spans, y_spans, active_set, boundary_set, lb_set):
    max_x = len(x_spans)
    max_y = len(y_spans)
    if max_x <= 0 or max_y <= 0:
        return False

    surrounding = []
    for dx in (-1, 0):
        for dy in (-1, 0):
            bx = x_line_idx + dx
            by = y_line_idx + dy
            if 0 <= bx < max_x and 0 <= by < max_y and (bx, by) in active_set:
                surrounding.append((bx, by))
    if not surrounding:
        return False

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
    if any(edge in boundary_set and edge in lb_set for edge in touching_edges):
        return False

    has_left = (
        x_line_idx > 0
        and _horizontal_segment_has_steel(y_line_idx, x_line_idx - 1, x_spans, y_spans, active_set, boundary_set, lb_set)
    )
    has_right = (
        x_line_idx < max_x
        and _horizontal_segment_has_steel(y_line_idx, x_line_idx, x_spans, y_spans, active_set, boundary_set, lb_set)
    )
    return has_left or has_right


def _load_bearing_wall_connections_for_rect(
    x0,
    y0,
    x1,
    y1,
    x_lines,
    y_lines,
    x_spans,
    y_spans,
    boundary_set,
    lb_set,
    tol_ft=1.5,
):
    touched = set()
    min_overlap = 0.5
    for edge in lb_set:
        if edge not in boundary_set:
            continue
        orient, line_idx, seg_idx = edge
        if orient == "H":
            if not (0 <= line_idx < len(y_lines) and 0 <= seg_idx < len(x_spans)):
                continue
            y_line = float(y_lines[line_idx])
            seg_x0 = float(x_lines[seg_idx])
            seg_x1 = float(x_lines[seg_idx + 1])
            overlap = max(0.0, min(x1, seg_x1) - max(x0, seg_x0))
            if overlap <= min_overlap:
                continue
            if abs(y_line - y0) <= tol_ft or abs(y_line - y1) <= tol_ft:
                touched.add(edge)
        elif orient == "V":
            if not (0 <= line_idx < len(x_lines) and 0 <= seg_idx < len(y_spans)):
                continue
            x_line = float(x_lines[line_idx])
            seg_y0 = float(y_lines[seg_idx])
            seg_y1 = float(y_lines[seg_idx + 1])
            overlap = max(0.0, min(y1, seg_y1) - max(y0, seg_y0))
            if overlap <= min_overlap:
                continue
            if abs(x_line - x0) <= tol_ft or abs(x_line - x1) <= tol_ft:
                touched.add(edge)
    return touched


def _girder_reduced_live_factor(tributary_area_sf: float) -> float:
    if tributary_area_sf <= 200.0:
        return 1.0
    if tributary_area_sf < 600.0:
        return 1.2 - (0.001 * tributary_area_sf)
    return 0.6


def _normalize_snow_code(value) -> str:
    token = str(value or "").strip().upper().replace("–", "-")
    if token in {"ASCE 7-22", "7-22", "ASCE722", "ASCE 722"}:
        return "ASCE 7-22"
    return "ASCE 7-16"


def _resolve_reduced_snow_load(load_inputs):
    snow_load = _get_non_negative_float(load_inputs.get("snow_load_psf", 0), "Snow Load")
    snow_code = _normalize_snow_code(load_inputs.get("snow_code", "ASCE 7-16"))

    if snow_code == "ASCE 7-22":
        reduced_snow_load = _get_non_negative_float(
            load_inputs.get("reduced_snow_load_psf_manual", 0),
            "Reduced Snow Load (ASCE 7-22 Manual)",
        )
        return snow_load, reduced_snow_load, "ASCE 7-22", "Manual"

    # ASCE 7-16 logic:
    # if SL <= 20: Reduced SL = 0.7*SL + 5
    # if SL > 20: Reduced SL = max(0.7*SL, 20)
    if snow_load <= 20.0:
        reduced_snow_load = (snow_load * 0.7) + 5.0
    else:
        reduced_snow_load = max(snow_load * 0.7, 20.0)
    return snow_load, reduced_snow_load, "ASCE 7-16", "Auto"


def calculate_joist_takeoff(layout_data):
    x_spans = [float(v) for v in (layout_data.get("x_spans_ft") or [])]
    y_spans = [float(v) for v in (layout_data.get("y_spans_ft") or [])]
    joist_counts = _joist_count_map(layout_data.get("joists_per_bay"))
    collateral_set = _collateral_bay_set(layout_data.get("collateral_bays"))

    load_inputs = layout_data.get("load_inputs_psf") or {}
    additional_layers = _normalize_additional_load_layers(layout_data, load_inputs)
    additional_psf_by_bay = _additional_load_map_by_bay(additional_layers)
    dead_load = _get_non_negative_float(load_inputs.get("dead_load_psf", 0), "Dead Load")
    live_load = _get_non_negative_float(load_inputs.get("live_load_psf", 0), "Live Load")
    snow_load, reduced_snow_load, snow_code, reduced_snow_load_source = _resolve_reduced_snow_load(load_inputs)
    collateral_add = _get_non_negative_float(
        load_inputs.get("collateral_addition_psf", 0), "Collateral Load Addition"
    )

    if not x_spans or not y_spans:
        raise InputValidationError("Grid must include at least one X bay and one Y bay.")
    active_set = _active_bay_set(layout_data, x_spans, y_spans)
    boundary_set = _active_boundary_segment_set(active_set, x_spans, y_spans)
    lb_set = _boundary_load_bearing_set(layout_data, x_spans, y_spans, active_set)

    x_lines = [0.0]
    running_x = 0.0
    for span in x_spans:
        running_x += span
        x_lines.append(running_x)

    bay_calcs = []
    joist_members_by_key = {}
    for x_idx, bay_width in enumerate(x_spans):
        for y_idx, bay_length in enumerate(y_spans):
            if (x_idx, y_idx) not in active_set:
                continue
            spaces = joist_counts.get((x_idx, y_idx))
            if not spaces:
                raise InputValidationError(
                    f"Missing joist spaces for bay {axis_letter(y_idx)}{x_idx + 1}. "
                    "Assign joist spaces per bay (or use Apply Joists To All Bays)."
                )
            member_count = int(spaces) + 1

            # User-defined step:
            # 1) Joist spacing = bay width (x) / joist spaces per bay
            spacing = round(bay_width / spaces, 2)
            # 2) Tributary area = joist spacing * bay length
            tributary_area = spacing * bay_length
            # 3) Reduced live load = (1.2 - 0.001 * tributary area) * live load
            reduced_live_load = (1.2 - (0.001 * tributary_area)) * live_load
            # 4) Base total load:
            # If Reduced LL > Reduced Snow => DL + Reduced LL
            # Else => DL + Reduced Snow
            if reduced_live_load > reduced_snow_load:
                controlling_variable_load = reduced_live_load
                controlling_load_type = "Reduced Live Load"
            else:
                controlling_variable_load = reduced_snow_load
                controlling_load_type = "Reduced Snow Load"
            base_total_load_psf = dead_load + controlling_variable_load

            # 5) Collateral adjustment only for collateral bays
            collateral_applied = (x_idx, y_idx) in collateral_set
            collateral_addition_applied = collateral_add if collateral_applied else 0.0
            additional_load_addition_applied = float(additional_psf_by_bay.get((x_idx, y_idx), 0.0))
            additional_load_applied = additional_load_addition_applied > 0.0
            total_load_psf = base_total_load_psf + collateral_addition_applied + additional_load_addition_applied
            required_capacity_plf = total_load_psf * spacing

            bay_label = f"{axis_letter(y_idx)}{x_idx + 1}"
            bay_calcs.append(
                {
                    "bay": bay_label,
                    "x_bay_index": x_idx + 1,
                    "y_row_label": axis_letter(y_idx),
                    "joist_spaces_per_bay": int(spaces),
                    "joists_per_bay": member_count,
                    "bay_width_ft": round(bay_width, 3),
                    "bay_length_ft": round(bay_length, 3),
                    "joist_spacing_ft": round(spacing, 2),
                    "tributary_area_sf": round(tributary_area, 3),
                    "reduced_live_load_psf": round(reduced_live_load, 3),
                    "dead_load_psf": round(dead_load, 3),
                    "snow_load_psf": round(snow_load, 3),
                    "reduced_snow_load_psf": round(reduced_snow_load, 3),
                    "controlling_load_type": controlling_load_type,
                    "selected_variable_load_psf": round(controlling_variable_load, 3),
                    "base_total_load_psf": round(base_total_load_psf, 3),
                    "collateral_applied": collateral_applied,
                    "collateral_addition_applied_psf": round(collateral_addition_applied, 3),
                    "additional_load_applied": additional_load_applied,
                    "additional_load_addition_applied_psf": round(additional_load_addition_applied, 3),
                    # Legacy alias retained.
                    "custom_load_applied": additional_load_applied,
                    "custom_load_addition_applied_psf": round(additional_load_addition_applied, 3),
                    "total_load_psf": round(total_load_psf, 3),
                    "required_capacity_plf": round(required_capacity_plf, 3),
                }
            )

            draw_step = bay_width / float(spaces)

            for member_num in range(1, member_count + 1):
                is_edge_member = member_num == 1 or member_num == member_count
                edge_side = None
                if is_edge_member:
                    edge_side = "W" if member_num == 1 else "E"

                # In collateral bays, all joists in that bay carry collateral addition
                # (including edge joists), unless the joist is removed by LB wall logic.
                member_collateral_psf = collateral_addition_applied if collateral_applied else 0.0
                member_additional_psf = additional_load_addition_applied if additional_load_applied else 0.0
                member_total_load_psf = base_total_load_psf + member_collateral_psf + member_additional_psf
                member_required_capacity_plf = member_total_load_psf * spacing

                x_pos_ft = x_lines[x_idx] + (member_num - 1) * draw_step

                if is_edge_member:
                    x_line_idx = x_idx if edge_side == "W" else (x_idx + 1)
                    boundary_edge = ("V", x_line_idx, y_idx)
                    if boundary_edge in boundary_set and boundary_edge in lb_set:
                        continue
                    merge_key = ("EDGE", y_idx, x_line_idx, round(bay_length, 3))
                else:
                    merge_key = ("INT", y_idx, x_idx, member_num, round(bay_length, 3))

                candidate = {
                    "id": "",
                    "bay": bay_label,
                    "x_bay_index": x_idx + 1,
                    "y_row_label": axis_letter(y_idx),
                    "y_row_index": y_idx,
                    "member_index_in_bay": member_num,
                    "span_ft": round(bay_length, 3),
                    "spacing_ft": round(spacing, 2),
                    "tributary_area_sf": round(tributary_area, 3),
                    "total_load_psf": round(member_total_load_psf, 3),
                    "required_capacity_plf": round(member_required_capacity_plf, 3),
                    "x_position_ft": round(x_pos_ft, 6),
                }

                existing = joist_members_by_key.get(merge_key)
                if existing is None:
                    joist_members_by_key[merge_key] = candidate
                    continue

                # Shared edge joists are kept once; use the controlling (higher-demand) side.
                if candidate["required_capacity_plf"] > existing["required_capacity_plf"]:
                    existing.update(
                        {
                            "bay": candidate["bay"],
                            "x_bay_index": candidate["x_bay_index"],
                            "member_index_in_bay": candidate["member_index_in_bay"],
                            "spacing_ft": candidate["spacing_ft"],
                            "tributary_area_sf": candidate["tributary_area_sf"],
                            "total_load_psf": candidate["total_load_psf"],
                            "required_capacity_plf": candidate["required_capacity_plf"],
                            "x_position_ft": candidate["x_position_ft"],
                        }
                    )

    if not bay_calcs:
        raise InputValidationError("No active bays available for joist calculation.")

    joist_members = []
    sorted_members = sorted(
        joist_members_by_key.values(),
        key=lambda m: (
            int(m.get("y_row_index", 0)),
            float(m.get("x_position_ft", 0.0)),
            int(m.get("member_index_in_bay", 0)),
        ),
    )
    for idx, member in enumerate(sorted_members, start=1):
        member_id = f"J-{member['y_row_label']}{idx:04d}"
        row = dict(member)
        row["id"] = member_id
        row.pop("y_row_index", None)
        row.pop("x_position_ft", None)
        joist_members.append(row)

    demand_groups_by_load = {}
    for member in joist_members:
        required_capacity_plf = round(member["required_capacity_plf"], 2)
        required_length_ft = round(float(member["span_ft"]), 2)
        group_id = f"{required_capacity_plf:.2f}|{required_length_ft:.2f}"
        if group_id not in demand_groups_by_load:
            demand_groups_by_load[group_id] = {
                "group_id": group_id,
                "required_capacity_plf": required_capacity_plf,
                "required_length_ft": required_length_ft,
                "count": 0,
                "total_span_ft": 0.0,
            }
        demand_groups_by_load[group_id]["count"] += 1
        demand_groups_by_load[group_id]["total_span_ft"] += member["span_ft"]

    joist_demand_groups = sorted(
        (
            {
                "group_id": grp["group_id"],
                "required_capacity_plf": grp["required_capacity_plf"],
                "required_length_ft": grp["required_length_ft"],
                "count": grp["count"],
                "total_span_ft": round(grp["total_span_ft"], 3),
                "requirement_text": (
                    f"{grp['count']} x Unique Joists require {grp['required_capacity_plf']:.2f} plf "
                    f"at {_fmt_ft_arch(grp['required_length_ft'])}. Choose joist:"
                ),
            }
            for grp in demand_groups_by_load.values()
        ),
        key=lambda item: (item["required_capacity_plf"], item["required_length_ft"]),
    )

    return {
        "load_inputs_psf": {
            "dead_load_psf": round(dead_load, 3),
            "live_load_psf": round(live_load, 3),
            "snow_load_psf": round(snow_load, 3),
            "reduced_snow_load_psf": round(reduced_snow_load, 3),
            "snow_code": snow_code,
            "reduced_snow_load_source": reduced_snow_load_source,
            "collateral_addition_psf": round(collateral_add, 3),
            "additional_load_layers": [
                {
                    "name": str(layer["name"]),
                    "psf": round(float(layer["psf"]), 3),
                    "bay_count": len(layer.get("bays", set()) or set()),
                }
                for layer in additional_layers
            ],
        },
        "joist_bay_calculations": bay_calcs,
        "joist_members": joist_members,
        "joist_demand_groups": joist_demand_groups,
        "summary": {
            "bay_count": len(bay_calcs),
            "joist_member_count": len(joist_members),
            "average_joist_spacing_ft": round(mean([item["joist_spacing_ft"] for item in bay_calcs]), 2),
            "average_tributary_area_sf": round(mean([item["tributary_area_sf"] for item in bay_calcs]), 3),
            "average_total_load_psf": round(mean([item["total_load_psf"] for item in bay_calcs]), 3),
            "demand_group_count": len(joist_demand_groups),
        },
    }


def calculate_girder_takeoff(layout_data):
    x_spans = [float(v) for v in (layout_data.get("x_spans_ft") or [])]
    y_spans = [float(v) for v in (layout_data.get("y_spans_ft") or [])]
    joist_counts = _joist_count_map(layout_data.get("joists_per_bay"))
    collateral_set = _collateral_bay_set(layout_data.get("collateral_bays"))

    load_inputs = layout_data.get("load_inputs_psf") or {}
    additional_layers = _normalize_additional_load_layers(layout_data, load_inputs)
    additional_psf_by_bay = _additional_load_map_by_bay(additional_layers)
    dead_load = _get_non_negative_float(load_inputs.get("dead_load_psf", 0), "Dead Load")
    live_load = _get_non_negative_float(load_inputs.get("live_load_psf", 0), "Live Load")
    snow_load, reduced_snow_load, snow_code, reduced_snow_load_source = _resolve_reduced_snow_load(load_inputs)
    collateral_add = _get_non_negative_float(
        load_inputs.get("collateral_addition_psf", 0), "Collateral Load Addition"
    )

    if not x_spans or not y_spans:
        raise InputValidationError("Grid must include at least one X bay and one Y bay.")
    active_set = _active_bay_set(layout_data, x_spans, y_spans)
    boundary_set = _active_boundary_segment_set(active_set, x_spans, y_spans)
    lb_set = _boundary_load_bearing_set(layout_data, x_spans, y_spans, active_set)

    girder_calcs = []
    for y_line_idx in range(0, len(y_spans) + 1):
        line_label = axis_letter(y_line_idx)

        for x_idx, bay_width in enumerate(x_spans):
            top_bay_y_idx = y_line_idx - 1 if y_line_idx > 0 else None
            bottom_bay_y_idx = y_line_idx if y_line_idx < len(y_spans) else None

            top_active = bool(top_bay_y_idx is not None and (x_idx, top_bay_y_idx) in active_set)
            bottom_active = bool(bottom_bay_y_idx is not None and (x_idx, bottom_bay_y_idx) in active_set)
            if not (top_active or bottom_active):
                continue

            edge = ("H", y_line_idx, x_idx)
            if not (top_active and bottom_active) and (edge in boundary_set) and (edge in lb_set):
                continue

            top_len = y_spans[top_bay_y_idx] if top_active else 0.0
            bottom_len = y_spans[bottom_bay_y_idx] if bottom_active else 0.0
            top_contrib = (top_len / 2.0) if top_active else 0.0
            bottom_contrib = (bottom_len / 2.0) if bottom_active else 0.0
            tributary_length_ft = top_contrib + bottom_contrib
            if tributary_length_ft <= 0:
                continue

            adjacent_bays = []
            if top_active:
                adjacent_bays.append((x_idx, top_bay_y_idx))
            if bottom_active:
                adjacent_bays.append((x_idx, bottom_bay_y_idx))

            joist_spacings = []
            joist_count_values = []
            collateral_count = 0
            additional_load_count = 0
            additional_load_total_psf = 0.0
            for bay in adjacent_bays:
                joist_count = joist_counts.get(bay)
                bay_label = f"{axis_letter(bay[1])}{bay[0] + 1}"
                if not joist_count:
                    raise InputValidationError(
                        f"Missing joist spaces for bay {bay_label}. "
                        "Assign joist spaces per bay (or use Apply Joists To All Bays)."
                    )
                joist_spacings.append(round(bay_width / joist_count, 2))
                joist_count_values.append(int(joist_count))
                if bay in collateral_set:
                    collateral_count += 1
                bay_addl_psf = float(additional_psf_by_bay.get(bay, 0.0))
                if bay_addl_psf > 0.0:
                    additional_load_count += 1
                    additional_load_total_psf += bay_addl_psf

            average_joist_spacing = mean(joist_spacings) if joist_spacings else 0.0
            average_joist_count = mean(joist_count_values) if joist_count_values else 0.0
            required_joist_count_n = int(round(average_joist_count)) if joist_count_values else 0
            tributary_area = tributary_length_ft * bay_width
            reduced_live_factor = _girder_reduced_live_factor(tributary_area)
            reduced_live_load = reduced_live_factor * live_load

            if reduced_live_load > reduced_snow_load:
                controlling_variable_load = reduced_live_load
                controlling_load_type = "Reduced Live Load"
            else:
                controlling_variable_load = reduced_snow_load
                controlling_load_type = "Reduced Snow Load"

            base_total_load_psf = dead_load + controlling_variable_load
            collateral_addition_applied = collateral_add * (collateral_count / max(1, len(adjacent_bays)))
            additional_load_addition_applied = additional_load_total_psf / max(1, len(adjacent_bays))
            total_load_psf = base_total_load_psf + collateral_addition_applied + additional_load_addition_applied

            required_capacity_lbs = tributary_length_ft * average_joist_spacing * total_load_psf
            uniform_load_plf = required_capacity_lbs / bay_width if bay_width else 0.0

            girder_calcs.append(
                {
                    "girder_id": f"G-{line_label}{x_idx + 1}-{line_label}{x_idx + 2}",
                    "line_label": line_label,
                    "x_bay_index": x_idx + 1,
                    "bay_width_ft": round(bay_width, 3),
                    "top_bay_length_ft": round(top_len, 3),
                    "bottom_bay_length_ft": round(bottom_len, 3),
                    # Tributary strip depth on the girder line (half-bay from each active side).
                    "average_bay_length_ft": round(tributary_length_ft, 3),
                    "tributary_area_sf": round(tributary_area, 3),
                    "reduced_live_factor_r1": round(reduced_live_factor, 4),
                    "reduced_live_load_psf": round(reduced_live_load, 3),
                    "reduced_snow_load_psf": round(reduced_snow_load, 3),
                    "controlling_load_type": controlling_load_type,
                    "selected_variable_load_psf": round(controlling_variable_load, 3),
                    "base_total_load_psf": round(base_total_load_psf, 3),
                    "collateral_bays_count": collateral_count,
                    "collateral_addition_applied_psf": round(collateral_addition_applied, 3),
                    "additional_load_bays_count": additional_load_count,
                    "additional_load_addition_applied_psf": round(additional_load_addition_applied, 3),
                    # Legacy aliases retained.
                    "custom_load_bays_count": additional_load_count,
                    "custom_load_addition_applied_psf": round(additional_load_addition_applied, 3),
                    "total_load_psf": round(total_load_psf, 3),
                    "average_joist_spacing_ft": round(average_joist_spacing, 3),
                    "average_joist_count_n": round(average_joist_count, 3),
                    "required_joist_count_n": required_joist_count_n,
                    "required_capacity_lbs": round(required_capacity_lbs, 3),
                    "uniform_load_plf": round(uniform_load_plf, 3),
                }
            )

    avg_at = round(mean([item["tributary_area_sf"] for item in girder_calcs]), 3) if girder_calcs else 0.0
    avg_tl = round(mean([item["total_load_psf"] for item in girder_calcs]), 3) if girder_calcs else 0.0
    avg_req = round(mean([item["required_capacity_lbs"] for item in girder_calcs]), 3) if girder_calcs else 0.0

    return {
        "load_inputs_psf": {
            "dead_load_psf": round(dead_load, 3),
            "live_load_psf": round(live_load, 3),
            "snow_load_psf": round(snow_load, 3),
            "reduced_snow_load_psf": round(reduced_snow_load, 3),
            "snow_code": snow_code,
            "reduced_snow_load_source": reduced_snow_load_source,
            "collateral_addition_psf": round(collateral_add, 3),
            "additional_load_layers": [
                {
                    "name": str(layer["name"]),
                    "psf": round(float(layer["psf"]), 3),
                    "bay_count": len(layer.get("bays", set()) or set()),
                }
                for layer in additional_layers
            ],
        },
        "girder_calculations": girder_calcs,
        "summary": {
            "girder_count": len(girder_calcs),
            "average_tributary_area_sf": avg_at,
            "average_total_load_psf": avg_tl,
            "average_required_capacity_lbs": avg_req,
        },
    }


def calculate_column_takeoff(layout_data):
    x_spans = [float(v) for v in (layout_data.get("x_spans_ft") or [])]
    y_spans = [float(v) for v in (layout_data.get("y_spans_ft") or [])]
    if not x_spans or not y_spans:
        raise InputValidationError("Grid must include at least one X bay and one Y bay.")
    active_set = _active_bay_set(layout_data, x_spans, y_spans)
    boundary_set = _active_boundary_segment_set(active_set, x_spans, y_spans)
    lb_set = _boundary_load_bearing_set(layout_data, x_spans, y_spans, active_set)

    load_inputs = layout_data.get("load_inputs_psf") or {}
    additional_layers = _normalize_additional_load_layers(layout_data, load_inputs)
    additional_psf_by_bay = _additional_load_map_by_bay(additional_layers)
    dead_load = _get_non_negative_float(load_inputs.get("dead_load_psf", 0), "Dead Load")
    live_load = _get_non_negative_float(load_inputs.get("live_load_psf", 0), "Live Load")
    snow_load, reduced_snow_load, snow_code, reduced_snow_load_source = _resolve_reduced_snow_load(load_inputs)
    collateral_add = _get_non_negative_float(
        load_inputs.get("collateral_addition_psf", 0), "Collateral Load Addition"
    )
    collateral_set = _collateral_bay_set(layout_data.get("collateral_bays"))

    column_calcs = []
    for x_line_idx in range(0, len(x_spans) + 1):
        left_width = x_spans[x_line_idx - 1] if x_line_idx > 0 else 0.0
        right_width = x_spans[x_line_idx] if x_line_idx < len(x_spans) else 0.0

        for y_line_idx in range(0, len(y_spans) + 1):
            top_len = y_spans[y_line_idx - 1] if y_line_idx > 0 else 0.0
            bottom_len = y_spans[y_line_idx] if y_line_idx < len(y_spans) else 0.0

            surrounding_bays = [
                (x_line_idx - 1, y_line_idx - 1),  # top-left
                (x_line_idx, y_line_idx - 1),      # top-right
                (x_line_idx - 1, y_line_idx),      # bottom-left
                (x_line_idx, y_line_idx),          # bottom-right
            ]
            active_surrounding_bays = [bay for bay in surrounding_bays if bay in active_set]
            if not active_surrounding_bays:
                continue

            if not _column_has_steel_support(
                x_line_idx,
                y_line_idx,
                x_spans,
                y_spans,
                active_set,
                boundary_set,
                lb_set,
            ):
                continue

            left_has = bool(
                (x_line_idx - 1, y_line_idx - 1) in active_set or (x_line_idx - 1, y_line_idx) in active_set
            )
            right_has = bool(
                (x_line_idx, y_line_idx - 1) in active_set or (x_line_idx, y_line_idx) in active_set
            )
            top_has = bool(
                (x_line_idx - 1, y_line_idx - 1) in active_set or (x_line_idx, y_line_idx - 1) in active_set
            )
            bottom_has = bool(
                (x_line_idx - 1, y_line_idx) in active_set or (x_line_idx, y_line_idx) in active_set
            )

            avg_bay_width = ((left_width if left_has else 0.0) + (right_width if right_has else 0.0)) / 2.0
            avg_bay_length = ((top_len if top_has else 0.0) + (bottom_len if bottom_has else 0.0)) / 2.0
            if avg_bay_width <= 0 or avg_bay_length <= 0:
                continue
            tributary_area = avg_bay_width * avg_bay_length
            collateral_count = sum(1 for bay in active_surrounding_bays if bay in collateral_set)
            additional_load_count = 0
            additional_load_total_psf = 0.0
            for bay in active_surrounding_bays:
                bay_addl_psf = float(additional_psf_by_bay.get(bay, 0.0))
                if bay_addl_psf > 0.0:
                    additional_load_count += 1
                    additional_load_total_psf += bay_addl_psf

            # At-based reduced load comparison.
            reduced_live_factor = _girder_reduced_live_factor(tributary_area)
            reduced_live_load = reduced_live_factor * live_load
            if reduced_live_load > reduced_snow_load:
                controlling_load_type = "Reduced Live Load"
                controlling_variable_load = reduced_live_load
            else:
                controlling_load_type = "Reduced Snow Load"
                controlling_variable_load = reduced_snow_load

            base_total_load_psf = dead_load + controlling_variable_load
            collateral_addition_applied_psf = collateral_add * (collateral_count / max(1, len(active_surrounding_bays)))
            additional_load_addition_applied_psf = additional_load_total_psf / max(1, len(active_surrounding_bays))
            total_load_psf = base_total_load_psf + collateral_addition_applied_psf + additional_load_addition_applied_psf

            required_capacity_kips = (tributary_area * total_load_psf) / 1000.0
            line_label = axis_letter(y_line_idx)
            grid_number = x_line_idx + 1

            column_calcs.append(
                {
                    "column_id": f"C-{line_label}{grid_number}",
                    "line_label": line_label,
                    "grid_number": grid_number,
                    "x_line_index": x_line_idx,
                    "y_line_index": y_line_idx,
                    "average_bay_width_ft": round(avg_bay_width, 3),
                    "average_bay_length_ft": round(avg_bay_length, 3),
                    "tributary_area_sf": round(tributary_area, 3),
                    "top_left_bay": (
                        f"{axis_letter(y_line_idx - 1)}{x_line_idx}"
                        if y_line_idx > 0 and x_line_idx > 0
                        else "-"
                    ),
                    "top_right_bay": (
                        f"{axis_letter(y_line_idx - 1)}{x_line_idx + 1}"
                        if y_line_idx > 0 and x_line_idx < len(x_spans)
                        else "-"
                    ),
                    "bottom_left_bay": (
                        f"{axis_letter(y_line_idx)}{x_line_idx}"
                        if y_line_idx < len(y_spans) and x_line_idx > 0
                        else "-"
                    ),
                    "bottom_right_bay": (
                        f"{axis_letter(y_line_idx)}{x_line_idx + 1}"
                        if y_line_idx < len(y_spans) and x_line_idx < len(x_spans)
                        else "-"
                    ),
                    "reduced_live_factor_r1": round(reduced_live_factor, 4),
                    "reduced_live_load_psf": round(reduced_live_load, 3),
                    "reduced_snow_load_psf": round(reduced_snow_load, 3),
                    "controlling_load_type": controlling_load_type,
                    "base_total_load_psf": round(base_total_load_psf, 3),
                    "collateral_bays_count": collateral_count,
                    "collateral_addition_applied_psf": round(collateral_addition_applied_psf, 3),
                    "additional_load_bays_count": additional_load_count,
                    "additional_load_addition_applied_psf": round(additional_load_addition_applied_psf, 3),
                    # Legacy aliases retained.
                    "custom_load_bays_count": additional_load_count,
                    "custom_load_addition_applied_psf": round(additional_load_addition_applied_psf, 3),
                    "total_load_psf": round(total_load_psf, 3),
                    # Keep for GUI compatibility.
                    "average_total_load_psf": round(total_load_psf, 3),
                    "required_capacity_kips": round(required_capacity_kips, 3),
                }
            )

    avg_at = round(mean([item["tributary_area_sf"] for item in column_calcs]), 3) if column_calcs else 0.0
    avg_tl = round(mean([item["total_load_psf"] for item in column_calcs]), 3) if column_calcs else 0.0
    avg_req = round(mean([item["required_capacity_kips"] for item in column_calcs]), 3) if column_calcs else 0.0

    return {
        "load_inputs_psf": {
            "dead_load_psf": round(dead_load, 3),
            "live_load_psf": round(live_load, 3),
            "snow_load_psf": round(snow_load, 3),
            "reduced_snow_load_psf": round(reduced_snow_load, 3),
            "snow_code": snow_code,
            "reduced_snow_load_source": reduced_snow_load_source,
            "collateral_addition_psf": round(collateral_add, 3),
            "additional_load_layers": [
                {
                    "name": str(layer["name"]),
                    "psf": round(float(layer["psf"]), 3),
                    "bay_count": len(layer.get("bays", set()) or set()),
                }
                for layer in additional_layers
            ],
        },
        "column_calculations": column_calcs,
        "summary": {
            "column_count": len(column_calcs),
            "average_tributary_area_sf": avg_at,
            "average_total_load_psf": avg_tl,
            "average_required_capacity_kips": avg_req,
        },
    }


def calculate_mezzanine_takeoff(layout_data):
    x_spans = [float(v) for v in (layout_data.get("x_spans_ft") or [])]
    y_spans = [float(v) for v in (layout_data.get("y_spans_ft") or [])]
    if not x_spans or not y_spans:
        raise InputValidationError("Grid must include at least one X bay and one Y bay.")

    active_set = _active_bay_set(layout_data, x_spans, y_spans)
    boundary_set = _active_boundary_segment_set(active_set, x_spans, y_spans)
    lb_set = _boundary_load_bearing_set(layout_data, x_spans, y_spans, active_set)
    x_lines = [0.0]
    for span in x_spans:
        x_lines.append(x_lines[-1] + float(span))
    y_lines = [0.0]
    for span in y_spans:
        y_lines.append(y_lines[-1] + float(span))

    main_column_nodes = set()
    for x_line_idx in range(0, len(x_spans) + 1):
        for y_line_idx in range(0, len(y_spans) + 1):
            if _column_has_steel_support(
                x_line_idx, y_line_idx, x_spans, y_spans, active_set, boundary_set, lb_set
            ):
                main_column_nodes.add((x_line_idx, y_line_idx))
    main_column_nodes_coords = [
        (float(x_lines[x_idx]), float(y_lines[y_idx]), x_idx, y_idx)
        for x_idx, y_idx in sorted(main_column_nodes)
    ]

    mezz_items = layout_data.get("mezzanines") or []
    mezz_enabled = bool(layout_data.get("mezzanine_enabled", False))
    if not mezz_enabled:
        return {
            "mezzanine_enabled": False,
            "mezzanine_zones": [],
            "mezzanine_panel_calculations": [],
            "mezzanine_joist_calculations": [],
            "mezzanine_girder_calculations": [],
            "mezzanine_column_calculations": [],
            "mezzanine_joist_demand_groups": [],
            "mezzanine_girder_demand_groups": [],
            "mezzanine_column_demand_groups": [],
            "summary": {
                "zone_count": 0,
                "panel_count": 0,
                "joist_count": 0,
                "girder_count": 0,
                "column_count": 0,
                "total_mezzanine_area_sf": 0.0,
                "total_mezzanine_load_kips": 0.0,
            },
        }

    zone_summaries = []
    panel_rows = []
    joist_rows = []
    girder_rows = []
    column_rows = []

    for idx, zone in enumerate(mezz_items, start=1):
        if not isinstance(zone, dict):
            continue
        if not bool(zone.get("enabled", True)):
            continue

        zone_id = str(zone.get("id") or f"MZ{idx:03d}").strip() or f"MZ{idx:03d}"
        name = str(zone.get("name") or f"Mezzanine {idx}").strip() or f"Mezzanine {idx}"
        direction = _normalize_mezzanine_direction(zone.get("joist_direction", "vertical"))
        elevation_ft = _get_non_negative_float(zone.get("elevation_ft", 0.0), f"{name} elevation")
        dead_load = _get_non_negative_float(zone.get("dead_load_psf", 0.0), f"{name} dead load")
        live_load = _get_non_negative_float(zone.get("live_load_psf", 0.0), f"{name} live load")
        total_load_psf = dead_load + live_load
        joist_spaces = int(zone.get("joist_spaces_per_bay", 7) or 7)
        if joist_spaces < 1:
            raise InputValidationError(f"{name}: joist spaces per bay must be >= 1.")

        x_start_idx = None
        x_end_idx = None
        y_start_idx = None
        y_end_idx = None
        use_abs_rect = (
            "x_start_ft" in zone and "x_end_ft" in zone and "y_start_ft" in zone and "y_end_ft" in zone
        )

        if use_abs_rect:
            x0 = min(float(zone.get("x_start_ft")), float(zone.get("x_end_ft")))
            x1 = max(float(zone.get("x_start_ft")), float(zone.get("x_end_ft")))
            y0 = min(float(zone.get("y_start_ft")), float(zone.get("y_end_ft")))
            y1 = max(float(zone.get("y_start_ft")), float(zone.get("y_end_ft")))
            x0 = max(float(x_lines[0]), min(x0, float(x_lines[-1])))
            x1 = max(float(x_lines[0]), min(x1, float(x_lines[-1])))
            y0 = max(float(y_lines[0]), min(y0, float(y_lines[-1])))
            y1 = max(float(y_lines[0]), min(y1, float(y_lines[-1])))
            if x1 - x0 <= 1e-6 or y1 - y0 <= 1e-6:
                raise InputValidationError(f"{name}: mezzanine rectangle has zero width or length.")

            rect_area = (x1 - x0) * (y1 - y0)
            covered_area = 0.0
            overlapped_active = set()
            inactive_hit = None
            for bx in range(len(x_spans)):
                bx0 = float(x_lines[bx])
                bx1 = float(x_lines[bx + 1])
                ovx = max(0.0, min(x1, bx1) - max(x0, bx0))
                if ovx <= 1e-9:
                    continue
                for by in range(len(y_spans)):
                    by0 = float(y_lines[by])
                    by1 = float(y_lines[by + 1])
                    ovy = max(0.0, min(y1, by1) - max(y0, by0))
                    if ovy <= 1e-9:
                        continue
                    ov_area = ovx * ovy
                    if (bx, by) in active_set:
                        covered_area += ov_area
                        overlapped_active.add((bx, by))
                    else:
                        if inactive_hit is None:
                            inactive_hit = (bx, by)
            if inactive_hit is not None:
                raise InputValidationError(
                    f"{name}: mezzanine footprint overlaps void/inactive bay {axis_letter(inactive_hit[1])}{inactive_hit[0] + 1}."
                )
            if covered_area < rect_area - 1e-3:
                raise InputValidationError(f"{name}: mezzanine footprint extends outside active building area.")
            if not overlapped_active:
                raise InputValidationError(f"{name}: mezzanine footprint does not cover active bays.")

            x_start_idx = min(bx for bx, _ in overlapped_active)
            x_end_idx = max(bx for bx, _ in overlapped_active) + 1
            y_start_idx = min(by for _, by in overlapped_active)
            y_end_idx = max(by for _, by in overlapped_active) + 1
            zone_width_ft = x1 - x0
            zone_length_ft = y1 - y0
        else:
            try:
                x_start_idx = int(zone.get("x_start_line_index", zone.get("x_start_line", 1))) - 1
                x_end_idx = int(zone.get("x_end_line_index", zone.get("x_end_line", 2))) - 1
                y_start_idx = int(zone.get("y_start_line_index", zone.get("y_start_line", 1))) - 1
                y_end_idx = int(zone.get("y_end_line_index", zone.get("y_end_line", 2))) - 1
            except (TypeError, ValueError) as exc:
                raise InputValidationError(f"{name}: start/end lines must be numeric.") from exc

            if not (0 <= x_start_idx < x_end_idx <= len(x_spans)):
                raise InputValidationError(
                    f"{name}: X line range is invalid. Use start/end lines within 1..{len(x_spans) + 1} and start < end."
                )
            if not (0 <= y_start_idx < y_end_idx <= len(y_spans)):
                raise InputValidationError(
                    f"{name}: Y line range is invalid. Use start/end lines within 1..{len(y_spans) + 1} and start < end."
                )
            zone_bays = {
                (bx, by)
                for bx in range(x_start_idx, x_end_idx)
                for by in range(y_start_idx, y_end_idx)
            }
            inactive_hits = [b for b in sorted(zone_bays) if b not in active_set]
            if inactive_hits:
                first = inactive_hits[0]
                raise InputValidationError(
                    f"{name}: mezzanine footprint includes void/inactive bay {axis_letter(first[1])}{first[0] + 1}. "
                    "Mezzanine zones must be fully inside active bays."
                )
            zone_width_ft = sum(x_spans[x_start_idx:x_end_idx])
            zone_length_ft = sum(y_spans[y_start_idx:y_end_idx])
            x0 = float(x_lines[x_start_idx])
            x1 = float(x_lines[x_end_idx])
            y0 = float(y_lines[y_start_idx])
            y1 = float(y_lines[y_end_idx])
        x_internal_raw = _parse_float_list(zone.get("internal_x_spacings_ft", []), f"{name} internal X spacing")
        y_internal_raw = _parse_float_list(zone.get("internal_y_spacings_ft", []), f"{name} internal Y spacing")
        x_segments = _fit_segments_to_total(zone_width_ft, x_internal_raw, f"{name} internal X spacing")
        y_segments = _fit_segments_to_total(zone_length_ft, y_internal_raw, f"{name} internal Y spacing")

        # Optional per-panel joist spacing overrides.
        # Keys supported: "ix,iy", "ix:iy", "Pix-iy" (1-based panel indices).
        raw_overrides = zone.get("joist_spaces_overrides", {}) or {}
        joist_spaces_by_panel = {}
        if isinstance(raw_overrides, dict):
            for key, value in raw_overrides.items():
                parsed_key = _parse_mezz_panel_key(key)
                if not parsed_key:
                    continue
                ix, iy = parsed_key
                if not (1 <= ix <= len(x_segments) and 1 <= iy <= len(y_segments)):
                    continue
                try:
                    spacing_count = int(value)
                except (TypeError, ValueError):
                    continue
                if spacing_count < 1:
                    continue
                joist_spaces_by_panel[(ix, iy)] = spacing_count

        # Determine if this mezz perimeter edge is supported by building LB walls.
        x0_line_idx = _find_line_index_for_coordinate(x_lines, x0, tol=1e-5)
        x1_line_idx = _find_line_index_for_coordinate(x_lines, x1, tol=1e-5)
        y0_line_idx = _find_line_index_for_coordinate(y_lines, y0, tol=1e-5)
        y1_line_idx = _find_line_index_for_coordinate(y_lines, y1, tol=1e-5)

        north_lb = (
            y0_line_idx is not None
            and any(("H", y0_line_idx, seg) in lb_set for seg in range(x_start_idx, x_end_idx))
        )
        south_lb = (
            y1_line_idx is not None
            and any(("H", y1_line_idx, seg) in lb_set for seg in range(x_start_idx, x_end_idx))
        )
        west_lb = (
            x0_line_idx is not None
            and any(("V", x0_line_idx, seg) in lb_set for seg in range(y_start_idx, y_end_idx))
        )
        east_lb = (
            x1_line_idx is not None
            and any(("V", x1_line_idx, seg) in lb_set for seg in range(y_start_idx, y_end_idx))
        )

        # Validate mezzanine has at least 2 support connections:
        # main columns and/or load-bearing walls along mezz perimeter.
        perimeter_support_nodes = set()
        conn_tol_ft = float(zone.get("support_connection_tolerance_ft", 1.5) or 1.5)
        for nx, ny, nxi, nyi in main_column_nodes_coords:
            if nx < (x0 - conn_tol_ft) or nx > (x1 + conn_tol_ft) or ny < (y0 - conn_tol_ft) or ny > (y1 + conn_tol_ft):
                continue
            on_vertical = (abs(nx - x0) <= conn_tol_ft or abs(nx - x1) <= conn_tol_ft) and (y0 - conn_tol_ft) <= ny <= (y1 + conn_tol_ft)
            on_horizontal = (abs(ny - y0) <= conn_tol_ft or abs(ny - y1) <= conn_tol_ft) and (x0 - conn_tol_ft) <= nx <= (x1 + conn_tol_ft)
            if on_vertical or on_horizontal:
                perimeter_support_nodes.add((nxi, nyi))
        wall_support_segments = _load_bearing_wall_connections_for_rect(
            x0,
            y0,
            x1,
            y1,
            x_lines,
            y_lines,
            x_spans,
            y_spans,
            boundary_set,
            lb_set,
            tol_ft=conn_tol_ft,
        )
        total_support_connections = len(perimeter_support_nodes) + len(wall_support_segments)
        if total_support_connections < 2:
            raise InputValidationError(
                f"{name}: mezzanine requires at least 2 support connections "
                "(main columns and/or load-bearing walls)."
            )

        panel_count = len(x_segments) * len(y_segments)
        zone_area_sf = zone_width_ft * zone_length_ft
        zone_load_kips = (zone_area_sf * total_load_psf) / 1000.0
        zone_summaries.append(
            {
                "zone_id": zone_id,
                "name": name,
                "x_start_line_index": x_start_idx + 1,
                "x_end_line_index": x_end_idx + 1,
                "y_start_line_index": y_start_idx + 1,
                "y_end_line_index": y_end_idx + 1,
                "x_start_label": str(x_start_idx + 1),
                "x_end_label": str(x_end_idx + 1),
                "y_start_label": axis_letter(y_start_idx),
                "y_end_label": axis_letter(y_end_idx),
                "width_ft": round(zone_width_ft, 3),
                "length_ft": round(zone_length_ft, 3),
                "area_sf": round(zone_area_sf, 3),
                "dead_load_psf": round(dead_load, 3),
                "live_load_psf": round(live_load, 3),
                "total_load_psf": round(total_load_psf, 3),
                "joist_direction": direction,
                "joist_spaces_per_bay": joist_spaces,
                "joist_spaces_overrides": {f"{ix},{iy}": int(v) for (ix, iy), v in sorted(joist_spaces_by_panel.items())},
                "elevation_ft": round(elevation_ft, 3),
                "internal_x_spacings_ft": [round(v, 3) for v in x_segments],
                "internal_y_spacings_ft": [round(v, 3) for v in y_segments],
                "panel_count": panel_count,
                "support_connections": int(total_support_connections),
                "main_support_connections": int(len(perimeter_support_nodes)),
                "lb_wall_support_connections": int(len(wall_support_segments)),
                "north_lb_wall": bool(north_lb),
                "south_lb_wall": bool(south_lb),
                "west_lb_wall": bool(west_lb),
                "east_lb_wall": bool(east_lb),
                "estimated_supported_load_kips": round(zone_load_kips, 3),
            }
        )

        # Build local node coordinates (absolute ft) for custom bay geometry.
        x_nodes = [x0]
        running = x0
        for seg in x_segments:
            running += float(seg)
            x_nodes.append(running)
        y_nodes = [y0]
        running = y0
        for seg in y_segments:
            running += float(seg)
            y_nodes.append(running)

        # Panel calculations + mezz joist line demand.
        for ix, x_seg in enumerate(x_segments, start=1):
            for iy, y_seg in enumerate(y_segments, start=1):
                spaces_for_panel = int(joist_spaces_by_panel.get((ix, iy), joist_spaces))
                if spaces_for_panel < 1:
                    spaces_for_panel = int(joist_spaces)
                joist_span_ft = y_seg if direction == "vertical" else x_seg
                tributary_width_ft = x_seg if direction == "vertical" else y_seg
                required_capacity_plf = total_load_psf * tributary_width_ft
                joist_spacing_ft = round(tributary_width_ft / spaces_for_panel, 2)
                panel_rows.append(
                    {
                        "zone_id": zone_id,
                        "zone_name": name,
                        "panel_id": f"{zone_id}-P{ix:02d}{iy:02d}",
                        "panel_x_index": ix,
                        "panel_y_index": iy,
                        "panel_width_ft": round(x_seg, 3),
                        "panel_length_ft": round(y_seg, 3),
                        "panel_area_sf": round(x_seg * y_seg, 3),
                        "joist_direction": direction,
                        "joist_spaces_per_bay": int(spaces_for_panel),
                        "joist_spacing_ft": joist_spacing_ft,
                        "joist_span_ft": round(joist_span_ft, 3),
                        "tributary_width_ft": round(tributary_width_ft, 3),
                        "dead_load_psf": round(dead_load, 3),
                        "live_load_psf": round(live_load, 3),
                        "total_load_psf": round(total_load_psf, 3),
                        "required_capacity_plf": round(required_capacity_plf, 3),
                    }
                )

                # Count actual joist member lines without double-counting shared edges.
                if joist_span_ft <= 1e-6 or joist_spacing_ft <= 1e-6:
                    continue
                if direction == "vertical":
                    edge_a = 1 if (ix == 1 and not west_lb) else 0
                    edge_b = 1 if ix < len(x_segments) else (0 if east_lb else 1)
                    infill = max(0, int(spaces_for_panel) - 1)
                else:
                    edge_a = 1 if (iy == 1 and not north_lb) else 0
                    edge_b = 1 if iy < len(y_segments) else (0 if south_lb else 1)
                    infill = max(0, int(spaces_for_panel) - 1)
                actual_count = int(max(0, infill + edge_a + edge_b))
                if actual_count <= 0:
                    continue
                joist_rows.append(
                    {
                        "zone_id": zone_id,
                        "zone_name": name,
                        "panel_id": f"{zone_id}-P{ix:02d}{iy:02d}",
                        "joist_direction": direction,
                        "joist_span_ft": round(joist_span_ft, 3),
                        "joist_spaces_per_bay": int(spaces_for_panel),
                        "joist_count": int(actual_count),
                        "joist_spacing_ft": joist_spacing_ft,
                        "tributary_area_sf": round(joist_spacing_ft * joist_span_ft, 3),
                        "total_load_psf": round(total_load_psf, 3),
                        "required_capacity_plf": round(total_load_psf * joist_spacing_ft, 3),
                    }
                )

        # Girder calculations (analogous to main building, using mezz internal bays).
        if direction == "vertical":
            # Girders on each y-line segment across x-bays.
            for y_idx in range(0, len(y_segments) + 1):
                if (y_idx == 0 and north_lb) or (y_idx == len(y_segments) and south_lb):
                    continue
                for x_idx, bay_width_ft in enumerate(x_segments):
                    top_len = y_segments[y_idx - 1] if y_idx > 0 else 0.0
                    bottom_len = y_segments[y_idx] if y_idx < len(y_segments) else 0.0
                    tributary_length_ft = (top_len / 2.0) + (bottom_len / 2.0)
                    if tributary_length_ft <= 0:
                        continue
                    spacing_samples = []
                    n_samples = []
                    if y_idx > 0:
                        panel_spaces = int(joist_spaces_by_panel.get((x_idx + 1, y_idx), joist_spaces))
                        if panel_spaces > 0:
                            spacing_samples.append(round(bay_width_ft / panel_spaces, 2))
                            n_samples.append(panel_spaces)
                    if y_idx < len(y_segments):
                        panel_spaces = int(joist_spaces_by_panel.get((x_idx + 1, y_idx + 1), joist_spaces))
                        if panel_spaces > 0:
                            spacing_samples.append(round(bay_width_ft / panel_spaces, 2))
                            n_samples.append(panel_spaces)
                    if not spacing_samples:
                        continue
                    avg_spacing = sum(spacing_samples) / float(len(spacing_samples))
                    if avg_spacing <= 1e-6:
                        continue
                    required_capacity_lbs = tributary_length_ft * avg_spacing * total_load_psf
                    girder_rows.append(
                        {
                            "zone_id": zone_id,
                            "zone_name": name,
                            "girder_id": f"{zone_id}-G-{y_idx + 1}-{x_idx + 1}",
                            "joist_direction": direction,
                            "line_index": y_idx + 1,
                            "span_ft": round(bay_width_ft, 3),
                            "tributary_length_ft": round(tributary_length_ft, 3),
                            "average_joist_spacing_ft": round(avg_spacing, 3),
                            "required_joist_n": int(max(n_samples) if n_samples else joist_spaces),
                            "min_depth_in": 30.0,
                            "max_depth_in": 30.0,
                            "total_load_psf": round(total_load_psf, 3),
                            "required_capacity_lbs": round(required_capacity_lbs, 3),
                        }
                    )
        else:
            # Horizontal joists => girders on x-lines, spanning y-bays.
            for x_idx in range(0, len(x_segments) + 1):
                if (x_idx == 0 and west_lb) or (x_idx == len(x_segments) and east_lb):
                    continue
                for y_idx, bay_len_ft in enumerate(y_segments):
                    left_w = x_segments[x_idx - 1] if x_idx > 0 else 0.0
                    right_w = x_segments[x_idx] if x_idx < len(x_segments) else 0.0
                    tributary_width_ft = (left_w / 2.0) + (right_w / 2.0)
                    if tributary_width_ft <= 0:
                        continue
                    spacing_samples = []
                    n_samples = []
                    if x_idx > 0:
                        panel_spaces = int(joist_spaces_by_panel.get((x_idx, y_idx + 1), joist_spaces))
                        if panel_spaces > 0:
                            spacing_samples.append(round(bay_len_ft / panel_spaces, 2))
                            n_samples.append(panel_spaces)
                    if x_idx < len(x_segments):
                        panel_spaces = int(joist_spaces_by_panel.get((x_idx + 1, y_idx + 1), joist_spaces))
                        if panel_spaces > 0:
                            spacing_samples.append(round(bay_len_ft / panel_spaces, 2))
                            n_samples.append(panel_spaces)
                    if not spacing_samples:
                        continue
                    avg_spacing = sum(spacing_samples) / float(len(spacing_samples))
                    if avg_spacing <= 1e-6:
                        continue
                    required_capacity_lbs = tributary_width_ft * avg_spacing * total_load_psf
                    girder_rows.append(
                        {
                            "zone_id": zone_id,
                            "zone_name": name,
                            "girder_id": f"{zone_id}-G-{x_idx + 1}-{y_idx + 1}",
                            "joist_direction": direction,
                            "line_index": x_idx + 1,
                            "span_ft": round(bay_len_ft, 3),
                            "tributary_length_ft": round(tributary_width_ft, 3),
                            "average_joist_spacing_ft": round(avg_spacing, 3),
                            "required_joist_n": int(max(n_samples) if n_samples else joist_spaces),
                            "min_depth_in": 30.0,
                            "max_depth_in": 30.0,
                            "total_load_psf": round(total_load_psf, 3),
                            "required_capacity_lbs": round(required_capacity_lbs, 3),
                        }
                    )

        # Column calculations with classification main vs mezz columns.
        x_node_count = len(x_segments) + 1
        y_node_count = len(y_segments) + 1
        for ix in range(x_node_count):
            left_w = x_segments[ix - 1] if ix > 0 else 0.0
            right_w = x_segments[ix] if ix < len(x_segments) else 0.0
            trib_x = (left_w + right_w) / 2.0
            for iy in range(y_node_count):
                if (
                    (ix == 0 and west_lb)
                    or (ix == x_node_count - 1 and east_lb)
                    or (iy == 0 and north_lb)
                    or (iy == y_node_count - 1 and south_lb)
                ):
                    continue
                top_l = y_segments[iy - 1] if iy > 0 else 0.0
                bottom_l = y_segments[iy] if iy < len(y_segments) else 0.0
                trib_y = (top_l + bottom_l) / 2.0
                tributary_area = trib_x * trib_y
                if tributary_area <= 1e-6:
                    continue
                required_capacity_kips = (tributary_area * total_load_psf) / 1000.0
                abs_x = x_nodes[ix]
                abs_y = y_nodes[iy]
                global_x_line = _find_line_index_for_coordinate(x_lines, abs_x, tol=1e-5)
                global_y_line = _find_line_index_for_coordinate(y_lines, abs_y, tol=1e-5)
                is_main_col = (
                    global_x_line is not None
                    and global_y_line is not None
                    and (global_x_line, global_y_line) in main_column_nodes
                )
                column_rows.append(
                    {
                        "zone_id": zone_id,
                        "zone_name": name,
                        "column_id": (
                            f"{zone_id}-C-{axis_letter(global_y_line)}{global_x_line + 1}"
                            if global_x_line is not None and global_y_line is not None
                            else f"{zone_id}-C-L{ix + 1}-{iy + 1}"
                        ),
                        "x_line_index": (global_x_line + 1) if global_x_line is not None else None,
                        "y_line_index": (global_y_line + 1) if global_y_line is not None else None,
                        "x_line_label": str(global_x_line + 1) if global_x_line is not None else f"L{ix + 1}",
                        "y_line_label": axis_letter(global_y_line) if global_y_line is not None else f"L{iy + 1}",
                        "main_or_mezz_column": "Main" if is_main_col else "Mezz",
                        "tributary_width_ft": round(trib_x, 3),
                        "tributary_length_ft": round(trib_y, 3),
                        "tributary_area_sf": round(tributary_area, 3),
                        "total_load_psf": round(total_load_psf, 3),
                        "required_capacity_kips": round(required_capacity_kips, 3),
                        "column_height_ft": round(elevation_ft, 3),
                        "x_ft": round(abs_x, 3),
                        "y_ft": round(abs_y, 3),
                    }
                )

    if not zone_summaries:
        raise InputValidationError("Mezzanine is enabled, but no valid mezzanine zones were defined.")

    joist_group_map = {}
    for row in joist_rows:
        row_count = int(row.get("joist_count", 0) or 0)
        if row_count <= 0:
            continue
        req = round(float(row["required_capacity_plf"]), 2)
        span = round(float(row["joist_span_ft"]), 2)
        if req <= 0.0 or span <= 0.0:
            continue
        group_id = f"{req:.2f}|{span:.2f}"
        row["group_id"] = group_id
        grp = joist_group_map.setdefault(
            group_id,
            {
                "group_id": group_id,
                "required_capacity_plf": req,
                "required_length_ft": span,
                "count": 0,
                "total_span_ft": 0.0,
                "zones": set(),
            },
        )
        grp["count"] += row_count
        grp["total_span_ft"] += float(row.get("joist_span_ft", 0.0)) * float(row_count)
        grp["zones"].add(str(row.get("zone_name", "")))

    joist_demand_groups = sorted(
        (
            {
                "group_id": grp["group_id"],
                "required_capacity_plf": grp["required_capacity_plf"],
                "required_length_ft": grp["required_length_ft"],
                "count": grp["count"],
                "total_span_ft": round(float(grp.get("total_span_ft", 0.0)), 3),
                "zones": sorted(grp["zones"]),
                "requirement_text": (
                    f"{grp['count']} x Mezz Joists require {grp['required_capacity_plf']:.2f} plf "
                    f"at {_fmt_ft_arch(grp['required_length_ft'])}."
                ),
            }
            for grp in joist_group_map.values()
        ),
        key=lambda item: (item["required_capacity_plf"], item["required_length_ft"]),
    )

    girder_group_map = {}
    for row in girder_rows:
        req = round(float(row["required_capacity_lbs"]), 2)
        span = round(float(row["span_ft"]), 2)
        req_n = int(row.get("required_joist_n", 0) or 0)
        min_depth = round(float(row.get("min_depth_in", 30.0) or 30.0), 2)
        max_depth = round(float(row.get("max_depth_in", 30.0) or 30.0), 2)
        if req <= 0.0 or span <= 0.0 or req_n <= 0:
            continue
        group_id = f"{req:.2f}|{span:.2f}|{req_n}|{min_depth:.2f}|{max_depth:.2f}"
        row["group_id"] = group_id
        grp = girder_group_map.setdefault(
            group_id,
            {
                "group_id": group_id,
                "required_capacity_lbs": req,
                "required_length_ft": span,
                "required_joist_n": req_n,
                "min_depth_in": min_depth,
                "max_depth_in": max_depth,
                "count": 0,
                "total_span_ft": 0.0,
                "zones": set(),
            },
        )
        grp["count"] += 1
        grp["total_span_ft"] += float(row.get("span_ft", 0.0))
        grp["zones"].add(str(row.get("zone_name", "")))

    girder_demand_groups = sorted(
        (
            {
                "group_id": grp["group_id"],
                "required_capacity_lbs": grp["required_capacity_lbs"],
                "required_length_ft": grp["required_length_ft"],
                "required_joist_n": int(grp.get("required_joist_n", 0)),
                "min_depth_in": round(float(grp.get("min_depth_in", 30.0)), 2),
                "max_depth_in": round(float(grp.get("max_depth_in", 30.0)), 2),
                "count": grp["count"],
                "total_span_ft": round(float(grp.get("total_span_ft", 0.0)), 3),
                "zones": sorted(grp["zones"]),
                "requirement_text": (
                    f"{grp['count']} x Mezz Girders require {grp['required_capacity_lbs']:.2f} lbs "
                    f"at {_fmt_ft_arch(grp['required_length_ft'])} "
                    f"(N={int(grp.get('required_joist_n', 0))}, Dmin={round(float(grp.get('min_depth_in', 30.0)), 2):.2f} in)."
                ),
            }
            for grp in girder_group_map.values()
        ),
        key=lambda item: (
            item["required_capacity_lbs"],
            item["required_length_ft"],
            item["required_joist_n"],
            item["max_depth_in"],
        ),
    )

    mezz_only_column_rows = [col for col in column_rows if str(col.get("main_or_mezz_column", "Mezz")) != "Main"]
    reused_main_column_count = max(0, len(column_rows) - len(mezz_only_column_rows))

    group_map = {}
    for col in mezz_only_column_rows:
        req_kips = round(float(col["required_capacity_kips"]), 2)
        hgt_ft = round(float(col["column_height_ft"]), 2)
        col_type = str(col.get("main_or_mezz_column", "Mezz"))
        if req_kips <= 0.0 or hgt_ft <= 0.0:
            continue
        group_id = f"{req_kips:.2f}|{hgt_ft:.2f}|{col_type}"
        col["group_id"] = group_id
        grp = group_map.setdefault(
            group_id,
            {
                "group_id": group_id,
                "required_capacity_kips": req_kips,
                "column_height_ft": hgt_ft,
                "main_or_mezz_column": col_type,
                "count": 0,
                "zones": set(),
            },
        )
        grp["count"] += 1
        grp["zones"].add(str(col.get("zone_name", "")))

    column_demand_groups = sorted(
        (
            {
                "group_id": grp["group_id"],
                "required_capacity_kips": grp["required_capacity_kips"],
                "column_height_ft": grp["column_height_ft"],
                "main_or_mezz_column": grp["main_or_mezz_column"],
                "count": grp["count"],
                "zones": sorted(grp["zones"]),
                "requirement_text": (
                    f"{grp['count']} x {grp['main_or_mezz_column']} Columns require {grp['required_capacity_kips']:.2f} kips "
                    f"at {grp['column_height_ft']:.2f} ft."
                ),
            }
            for grp in group_map.values()
        ),
        key=lambda item: (item["required_capacity_kips"], item["column_height_ft"], item["main_or_mezz_column"]),
    )

    total_area_sf = sum(float(zone.get("area_sf", 0.0)) for zone in zone_summaries)
    total_load_kips = sum(float(zone.get("estimated_supported_load_kips", 0.0)) for zone in zone_summaries)
    return {
        "mezzanine_enabled": True,
        "mezzanine_zones": zone_summaries,
        "mezzanine_panel_calculations": panel_rows,
        "mezzanine_joist_calculations": joist_rows,
        "mezzanine_girder_calculations": girder_rows,
        "mezzanine_column_calculations": mezz_only_column_rows,
        "mezzanine_joist_demand_groups": joist_demand_groups,
        "mezzanine_girder_demand_groups": girder_demand_groups,
        "mezzanine_column_demand_groups": column_demand_groups,
        "summary": {
            "zone_count": len(zone_summaries),
            "panel_count": len(panel_rows),
            "joist_count": len(joist_rows),
            "girder_count": len(girder_rows),
            "column_count": len(mezz_only_column_rows),
            "reused_main_column_count": int(reused_main_column_count),
            "total_mezzanine_area_sf": round(total_area_sf, 3),
            "total_mezzanine_load_kips": round(total_load_kips, 3),
        },
    }
