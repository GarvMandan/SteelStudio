"""Concrete takeoff: tilt wall panels and slab on grade.

Builds on the wall areas and footing quantities the steel estimator
already produces, turning them into concrete volumes -- the first trade
added to the structural steel base.

Tilt wall thickness uses the fast H/50 sizing rule rather than a full
ACI 318 service-load analysis:

    thickness = unsupported height (in) / 50
    rounded UP to the nearest 1/2 inch, never below 7.5 in

The unsupported height is the building clear height -- the span between
the slab and the roof diaphragm that braces the panel top. It is not the
full panel height, which also carries roof slope, parapet and the foot of
panel below grade, none of which is unsupported.

This is a preliminary estimating rule for standard commercial and
industrial panels under roughly 15-20 psf wind, not a panel design. It
does not perform the ACI 318 out-of-plane P-Delta check, size
reinforcement, or verify deflection against H/150. A panel that is
unusually tall, heavily loaded, or carrying large openings must be
designed properly.

Slab thickness is a direct input, not a calculation.
"""
from __future__ import annotations

import math

from calculation_engine import InputValidationError

# Sizing rule constants.
HEIGHT_DIVISOR = 50.0
THICKNESS_STEP_IN = 0.5
MIN_THICKNESS_IN = 7.5

# The original footing takeoff reports a 10% waste allowance; concrete
# quantities here follow the same convention so totals stay comparable.
WASTE_FACTOR = 1.10
CUBIC_FEET_PER_YARD = 27.0

WALL_KEYS = ("north_wall", "south_wall", "east_wall", "west_wall")


def required_thickness_in(height_ft):
    """Tilt panel thickness for an unsupported height, per the H/50 rule."""
    height_in = max(0.0, float(height_ft)) * 12.0
    raw = height_in / HEIGHT_DIVISOR
    stepped = math.ceil((raw - 1e-9) / THICKNESS_STEP_IN) * THICKNESS_STEP_IN
    return round(max(MIN_THICKNESS_IN, stepped), 2)


def _wall_height(wall):
    """Governing (tallest) unsupported height for a wall.

    North and south walls report one height. East and west step with the
    roof and carry per-segment heights; the tallest segment governs the
    panel thickness for that elevation.
    """
    if not isinstance(wall, dict):
        return 0.0
    heights = [float(wall.get("wall_height_ft") or 0.0)]
    for segment in wall.get("step_segments") or []:
        if isinstance(segment, dict):
            heights.append(float(segment.get("wall_height_ft") or 0.0))
    # Dock sides carry a taller centre panel than their edges.
    for key in ("center_height_ft", "edge_height_ft"):
        if wall.get(key) is not None:
            heights.append(float(wall[key]))
    return max(heights) if heights else 0.0


def calculate_tilt_wall_concrete(walls, clear_height_ft=None):
    """Panel thickness and concrete volume for each tilt wall elevation.

    `clear_height_ft` is the unsupported height that governs thickness. When
    it is not supplied the full wall height is used, which is conservative.
    """
    if not isinstance(walls, dict):
        raise InputValidationError("Wall takeoff data is unavailable.")
    panels = []
    total_cy = 0.0
    for key in WALL_KEYS:
        wall = walls.get(key)
        if not isinstance(wall, dict):
            continue
        area_sf = float(wall.get("area_sf") or 0.0)
        height_ft = _wall_height(wall)
        # Thickness follows the unsupported (clear) height; the panel's own
        # height still drives its area and therefore its concrete volume.
        unsupported_ft = float(clear_height_ft) if clear_height_ft else height_ft
        thickness_in = required_thickness_in(unsupported_ft)
        raw_in = round(unsupported_ft * 12.0 / HEIGHT_DIVISOR, 3)
        volume_cy = area_sf * (thickness_in / 12.0) / CUBIC_FEET_PER_YARD
        total_cy += volume_cy
        panels.append({
            "wall": key.replace("_wall", "").title(),
            "key": key,
            "length_ft": round(float(wall.get("length_ft") or 0.0), 3),
            "panel_height_ft": round(height_ft, 3),
            "unsupported_height_ft": round(unsupported_ft, 3),
            "governing_height_ft": round(unsupported_ft, 3),
            "area_sf": round(area_sf, 3),
            "required_thickness_raw_in": raw_in,
            "thickness_in": thickness_in,
            "governed_by_minimum": thickness_in <= MIN_THICKNESS_IN + 1e-9 and raw_in < MIN_THICKNESS_IN,
            "volume_cy": round(volume_cy, 4),
        })
    return {
        "panels": panels,
        "method": "Clear height / 50, rounded up to the nearest 1/2 in, minimum 7.5 in",
        "minimum_thickness_in": MIN_THICKNESS_IN,
        "basis": (
            "Thickness from the unsupported (clear) height between slab and "
            "roof diaphragm. Preliminary estimating rule for standard panels "
            "under roughly 15-20 psf wind. Not an ACI 318 panel design: no "
            "out-of-plane P-Delta check, no reinforcement sizing, no H/150 "
            "deflection verification."
        ),
        "summary": {
            "panel_count": len(panels),
            "max_thickness_in": max((p["thickness_in"] for p in panels), default=0.0),
            "total_area_sf": round(sum(p["area_sf"] for p in panels), 3),
            "total_cy": round(total_cy, 4),
            "total_cy_with_waste": round(total_cy * WASTE_FACTOR, 4),
        },
    }


def calculate_slab(bays, thickness_in, include_inactive=False):
    """Slab on grade over the active footprint, at a given thickness."""
    try:
        thickness = float(thickness_in)
    except (TypeError, ValueError) as exc:
        raise InputValidationError("Slab thickness must be a number.") from exc
    if not 0 < thickness <= 36:
        raise InputValidationError("Slab thickness must be between 0 and 36 inches.")
    area_sf = 0.0
    for bay in bays or []:
        if not isinstance(bay, dict):
            continue
        if not include_inactive and not bay.get("active", True):
            continue
        area_sf += float(bay.get("width_ft") or 0.0) * float(bay.get("length_ft") or 0.0)
    volume_cy = area_sf * (thickness / 12.0) / CUBIC_FEET_PER_YARD
    return {
        "thickness_in": round(thickness, 2),
        "area_sf": round(area_sf, 3),
        "volume_cy": round(volume_cy, 4),
        "volume_cy_with_waste": round(volume_cy * WASTE_FACTOR, 4),
        "basis": "Slab on grade over the active footprint. Thickness is an input, not a calculation.",
    }


def summarize(walls_concrete, slab, footings, mezz_footings=None):
    """Roll the concrete quantities into one set of totals."""
    def cy(block, key="total_cy_with_waste"):
        summary = (block or {}).get("summary") or {}
        return float(summary.get(key) or 0.0)

    footing_cy = cy(footings) + cy(mezz_footings)
    wall_cy = float(((walls_concrete or {}).get("summary") or {}).get("total_cy_with_waste") or 0.0)
    slab_cy = float((slab or {}).get("volume_cy_with_waste") or 0.0)
    return {
        "tilt_wall_cy": round(wall_cy, 3),
        "slab_cy": round(slab_cy, 3),
        "footing_cy": round(footing_cy, 3),
        "total_cy": round(wall_cy + slab_cy + footing_cy, 3),
        "includes_waste_allowance": True,
        "waste_factor": WASTE_FACTOR,
    }


def build_solids(bays, xs, ys, walls_concrete, slab, footings, mezz_footings=None,
                 column_positions=None):
    """Box geometry for the concrete elements, for the 3D model.

    Each solid is an axis-aligned box: `center` [x, y, z] in feet with Z up,
    and `size` [x, y, z] in feet. The viewer renders these as solids, unlike
    steel members which are lines between two endpoints.

    Elevation datum, matching the drawing convention: top of slab is grade,
    z = 0 (100'-0"). The slab occupies -t to 0, so top of footing sits at
    the underside of the slab, and each footing extends down from there.
    """
    solids = []
    slab_t = float((slab or {}).get("thickness_in") or 0.0) / 12.0

    # Slab on grade: top face at grade, thickness downward.
    if slab_t > 0 and bays:
        for bay in bays:
            if not isinstance(bay, dict) or not bay.get("active", True):
                continue
            w = float(bay.get("width_ft") or 0.0)
            l = float(bay.get("length_ft") or 0.0)
            if w <= 0 or l <= 0:
                continue
            solids.append({
                "id": f"SLAB-{bay.get('id', '')}",
                "type": "slab", "discipline": "concrete", "level": "roof",
                "label": f"Slab {bay.get('id', '')}",
                "center": [round(float(bay.get("x_ft", 0.0)) + w / 2, 4),
                           round(float(bay.get("y_ft", 0.0)) + l / 2, 4),
                           round(-slab_t / 2, 4)],
                "size": [round(w, 4), round(l, 4), round(slab_t, 4)],
                "thickness_in": (slab or {}).get("thickness_in"),
                "top_elevation_ft": 0.0,
                "description": (
                    f"Slab on grade, {(slab or {}).get('thickness_in')} in thick. "
                    "Top of slab is the 100'-0\" datum."
                ),
            })

    # Spread footings: top of footing at the underside of the slab.
    for source, level in ((footings, "roof"), (mezz_footings, "mezzanine")):
        for row in ((source or {}).get("column_footings") or []):
            size = float(row.get("footing_size_ft") or 0.0)
            depth = float(row.get("footing_depth_ft") or 0.0)
            position = (column_positions or {}).get(str(row.get("column_id", "")))
            if size <= 0 or depth <= 0 or not position:
                continue
            top = -slab_t
            solids.append({
                "id": f"FTG-{row.get('column_id', '')}",
                "type": "footing", "discipline": "concrete", "level": level,
                "label": f"Footing {row.get('grid', row.get('column_id', ''))}",
                "center": [round(position[0], 4), round(position[1], 4),
                           round(top - depth / 2, 4)],
                "size": [round(size, 4), round(size, 4), round(depth, 4)],
                "volume_cy": row.get("footing_volume_cy"),
                "required_capacity_kips": row.get("required_capacity_kips"),
                "top_elevation_ft": round(top, 4),
                "description": (
                    f"Spread footing {size:g} ft square x {depth:g} ft deep. "
                    f"Top of footing at {top:+.2f} ft, the underside of the slab."
                ),
            })

    # Tilt wall panels: one box per elevation, at its governing thickness,
    # sitting just outside the building line so the steel stays visible.
    width_ft = float(xs[-1]) if xs else 0.0
    length_ft = float(ys[-1]) if ys else 0.0
    for panel in ((walls_concrete or {}).get("panels") or []):
        t = float(panel.get("thickness_in") or 0.0) / 12.0
        height = float(panel.get("governing_height_ft") or 0.0)
        base = -1.0  # the original takeoff sets the panel base one foot below grade
        if t <= 0 or height <= 0:
            continue
        key = panel.get("key")
        if key in ("north_wall", "south_wall"):
            y = 0.0 if key == "north_wall" else length_ft
            centre = [width_ft / 2, y + (-t / 2 if key == "north_wall" else t / 2)]
            size = [width_ft, t]
        else:
            x = width_ft if key == "east_wall" else 0.0
            centre = [x + (t / 2 if key == "east_wall" else -t / 2), length_ft / 2]
            size = [t, length_ft]
        solids.append({
            "id": f"TW-{panel.get('wall', '')}",
            "type": "tilt_wall", "discipline": "concrete", "level": "roof",
            "label": f"{panel.get('wall', '')} tilt panel",
            "center": [round(centre[0], 4), round(centre[1], 4), round(base + height / 2, 4)],
            "size": [round(size[0], 4), round(size[1], 4), round(height, 4)],
            "thickness_in": panel.get("thickness_in"),
            "area_sf": panel.get("area_sf"),
            "volume_cy": panel.get("volume_cy"),
            "height_ft": round(height, 3),
            "description": (
                f"Tilt-up panel {panel.get('thickness_in')} in thick, "
                f"{panel.get('governing_height_ft')} ft tall, {panel.get('area_sf')} sf, "
                f"{panel.get('volume_cy')} CY. Thickness from H/50, minimum "
                f"{MIN_THICKNESS_IN} in."
            ),
        })
    return solids
