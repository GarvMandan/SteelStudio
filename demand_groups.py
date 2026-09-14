"""Demand group construction.

Extracted from SteelGridApp so the takeoff workflow no longer depends on
the tkinter desktop application. Demand groups collapse individual
members onto the distinct (capacity, span, panel count, depth limit)
combinations a section must satisfy, so one catalog choice covers every
member sharing that demand.

Group IDs are part of the saved project format -- imported assignments
are keyed by them -- so their exact string form is load bearing.
"""
from __future__ import annotations

from calculation_engine import _fmt_ft_arch


def axis_label_to_index(label):
    """Lettered grid label to zero-based index; None when unparseable.

    Deliberately lenient rather than reusing calculation_engine.axis_index,
    which raises: girder grouping treats an unknown line as depth 0.0, and
    raising there would change behaviour on malformed input.
    """
    label = str(label or "").strip().upper()
    if not label:
        return None
    total = 0
    for ch in label:
        if not ("A" <= ch <= "Z"):
            return None
        total = (total * 26) + (ord(ch) - ord("A") + 1)
    return total - 1


def column_height_by_line_ft(profile, fallback_clear_height_ft=36.0):
    """Top-of-column elevation per Y line: TOJ less the joist seat depth."""
    if not profile:
        return {}, float(fallback_clear_height_ft)
    seat_depth_ft = float(profile.get("joist_seat_depth_in",
                                     profile.get("joist_depth_thickness_in", 0.0))) / 12.0
    toj_by_line = profile.get("line_toj_elevations_ft", profile.get("line_roof_heights", []))
    return ({idx: max(0.0, float(h) - seat_depth_ft) for idx, h in enumerate(toj_by_line)},
            float(profile["clear_height_ft"]))


def mezz_girder_groups_for_assignment(mezz_result):
    groups = []
    for group in (mezz_result or {}).get("mezzanine_girder_demand_groups", []):
        groups.append({
            "group_id": str(group.get("group_id", "")),
            "required_capacity_lbs": float(group.get("required_capacity_lbs", 0.0) or 0.0),
            "required_length_ft": float(group.get("required_length_ft", 0.0) or 0.0),
            "required_joist_n": int(group.get("required_joist_n", 0) or 0),
            "min_depth_in": float(group.get("min_depth_in", 30.0) or 30.0),
            "max_depth_in": float(group.get("max_depth_in", 30.0) or 30.0),
            "count": int(group.get("count", 0) or 0),
            "total_span_ft": float(group.get("total_span_ft", 0.0) or 0.0),
        })
    return groups


def format_girder_group_id(required_capacity_lbs, required_length_ft,
                           required_joist_n, max_depth_in):
    return (
        f"{round(float(required_capacity_lbs), 2):.2f}|"
        f"{round(float(required_length_ft), 2):.2f}|"
        f"{int(required_joist_n)}|"
        f"{round(float(max_depth_in), 2):.2f}"
    )


def build_girder_demand_groups(girder_calcs, allowed_depth_by_line):
    groups = {}
    for item in girder_calcs:
        line_idx = axis_label_to_index(item["line_label"])
        max_depth_in = allowed_depth_by_line.get(line_idx)
        if max_depth_in is None:
            max_depth_in = 0.0
        required_capacity_lbs = round(float(item["required_capacity_lbs"]), 2)
        required_length_ft = round(float(item["bay_width_ft"]), 2)
        required_joist_n = int(item.get("required_joist_count_n", 0) or 0)
        key = (required_capacity_lbs, required_length_ft, required_joist_n, round(float(max_depth_in), 2))
        group_id = format_girder_group_id(key[0], key[1], key[2], key[3])
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
                    f"at {_fmt_ft_arch(grp['required_length_ft'])}, {int(grp['required_joist_n'])}N, "
                    f"max depth {grp['max_depth_in']:.2f} in. Choose girder:"
                ),
            }
        )
    output.sort(
        key=lambda x: (x["required_capacity_lbs"], x["required_length_ft"], x["required_joist_n"], x["max_depth_in"])
    )
    return output


def build_column_demand_groups(column_calcs, line_height_map, clear_height_ft):
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
                    f"at avg TOC/JB {_fmt_ft_arch(avg_height_ft)}. Choose column:"
                ),
            }
        )
    output.sort(key=lambda x: x["required_capacity_kips"])
    return output
