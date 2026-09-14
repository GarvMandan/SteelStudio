"""Automatic catalog section selection.

Extracted verbatim from SteelGridApp so the takeoff workflow no longer
depends on the tkinter desktop application. These are the original
selection rules -- tiered span matching (exact -> interpolate ->
extrapolate -> single), K-series joists with an LH fallback, girder
weight interpolation along depth/panel-load curves, and ASD column
selection by effective length. Behaviour is deliberately unchanged.

Selecting a section here is a takeoff input, never an engineering
approval: capacity, connections, bracing and code compliance are not
verified.
"""
from __future__ import annotations

import math
import re

import catalogs
from calculation_engine import InputValidationError, _fmt_ft_arch


def _load_lh_catalog_rows():
    """Read the LH joist table used as the main-joist fallback."""
    path = catalogs.find_mezz_joist_catalog_excel_path()
    if path is None or not path.exists():
        raise InputValidationError(
            "No LH Joist Table Excel found for mezzanine joist auto-assignment. "
            "Expected a file like 'LH Joist Table.xlsx' in the working/app folder."
        )
    return catalogs.parse_joist_catalog_excel(path), str(path)


def _format_compact_number(value: float, decimals: int = 2):
    text = f"{float(value):.{decimals}f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def _format_girder_designation(depth_in: float, joist_n: int, capacity_kips: float):
    depth_txt = _format_compact_number(depth_in, 2)
    cap_txt = _format_compact_number(capacity_kips, 2)
    if int(joist_n) > 0:
        return f"{depth_txt}G {int(joist_n)}N {cap_txt}K"
    return f"{depth_txt}G {cap_txt}K"


def _estimate_value_by_span_points(span_points, req_span_ft: float, tol: float = 0.01):
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

def compute_joist_auto_assignments(groups, catalog_rows, prefer_lightest_over_tier: bool = False):
        assignments = {}
        missing = []
        by_designation = catalogs.build_joist_designation_index(catalog_rows)
        tier_rank = {"exact": 0, "interpolate": 1, "extrapolate": 2, "single": 3}

        for group in groups:
            req_capacity = float(group["required_capacity_plf"])
            req_length = round(float(group.get("required_length_ft", 0.0)), 2)
            candidates_by_tier = {name: [] for name in tier_rank}
            for designation, item in by_designation.items():
                span_caps = item.get("span_caps", {})
                if not span_caps:
                    continue
                est_capacity, tier = _estimate_value_by_span_points(
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
                missing.append(f"{req_capacity:.2f} plf @ {_fmt_ft_arch(req_length)}")
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

def compute_main_joist_assignments_with_lh_fallback(main_groups, main_catalog_rows):
        main_assignments, _main_missing = compute_joist_auto_assignments(main_groups, main_catalog_rows)
        unresolved = [
            group for group in (main_groups or [])
            if str(group.get("group_id", "")) not in main_assignments
        ]
        fallback_assigned_count = 0
        fallback_source = ""
        fallback_error = ""
        if unresolved:
            try:
                lh_rows, lh_path = _load_lh_catalog_rows()
                fallback_source = lh_path
                lh_assignments, _lh_missing = compute_joist_auto_assignments(
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
            f"{_fmt_ft_arch(float(group.get('required_length_ft', 0.0) or 0.0))}"
            for group in still_unresolved
        ]
        return main_assignments, missing, int(fallback_assigned_count), str(fallback_source), str(fallback_error)

def _interpolate_weight_from_curve(curve, req_load_kips: float):
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
            weight_plf = _interpolate_weight_from_curve(curve, req_load_kips)
            if weight_plf is None:
                continue
            span_weight_points.append((float(span_key), float(weight_plf)))
        return _estimate_value_by_span_points(span_weight_points, req_span_ft, tol=0.01)

def compute_girder_auto_assignments(groups, catalog_index):
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
                f"{req_capacity_lbs:.2f} lbs @ {_fmt_ft_arch(req_span_ft)}, {req_joist_n}N, "
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
                est_weight, tier = _estimate_girder_weight_by_span(
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
                "designation": _format_girder_designation(float(best["depth_in"]), req_joist_n, req_load_kips),
            }
        return assignments, missing

def compute_column_auto_assignments(groups, catalog_rows, clear_height_ft: float):
        target_kl_ft = int(math.ceil(clear_height_ft - 1e-9))
        available_kl = sorted({int(row["kl_ft"]) for row in catalog_rows})
        if not available_kl:
            raise InputValidationError("No KL rows available in column catalog.")
        if target_kl_ft < available_kl[0] or target_kl_ft > available_kl[-1]:
            raise InputValidationError(
                (
                    f"KL={_fmt_ft_arch(target_kl_ft)} (from clear height {_fmt_ft_arch(clear_height_ft)}) is out of catalog range "
                    f"{_fmt_ft_arch(available_kl[0])}-{_fmt_ft_arch(available_kl[-1])}."
                )
            )

        kl_rows = [row for row in catalog_rows if int(row["kl_ft"]) == target_kl_ft]
        if not kl_rows:
            raise InputValidationError(f"No entries found at KL={_fmt_ft_arch(target_kl_ft)} in column catalog.")

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

def compute_mezz_column_auto_assignments(groups, catalog_rows):
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
                        f"{group_id}: {req_kips:.2f} kips @ KL={_fmt_ft_arch(target_kl_ft)} "
                        f"(catalog {_fmt_ft_arch(available_kl[0])}-{_fmt_ft_arch(available_kl[-1])})"
                    )
                )
                continue

            kl_rows = [row for row in catalog_rows if int(row["kl_ft"]) == target_kl_ft]
            if not kl_rows:
                missing.append(f"{group_id}: no KL row at {_fmt_ft_arch(target_kl_ft)}")
                continue
            candidates = [row for row in kl_rows if float(row["asd_capacity_kips"]) + 1e-9 >= req_kips]
            if not candidates:
                missing.append(f"{group_id}: {req_kips:.2f} kips @ KL={_fmt_ft_arch(target_kl_ft)}")
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
