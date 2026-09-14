"""Ground snow load lookup against the public ASCE hazard services.

Extracted from SteelGridApp so the web application can offer the same
lookup the desktop program had. Geocoding uses OpenStreetMap Nominatim;
snow values come from the ASCE ArcGIS tile services (7-16 and 7-22).

These are third-party services reached over the network. They can be
unavailable, rate limited, or return a case-study zone with no direct
value, so every failure surfaces as InputValidationError for the caller
to report rather than raising an opaque network error.

A returned value is a published ground snow load (pg) for the located
point. It is not a site-specific determination.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from calculation_engine import InputValidationError

ASCE_716_MAP = "https://gis.asce.org/arcgis/rest/services/ASCE/Snow_2016_Tile/MapServer"
ASCE_722_MAP = "https://gis.asce.org/arcgis/rest/services/ASCE722/s2022_Tile_RC_II/MapServer"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
HAZARD_TOOL_URL = "https://ascehazardtool.org/"


def _http_get_json(base_url: str, params=None, headers=None, timeout_sec: float = 6.0):
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

def _to_float_or_none(value):
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

def _extract_first_numeric_attr(attrs: dict, keys):
    for key in keys:
        val = _to_float_or_none(attrs.get(key))
        if val is not None:
            return val, key
    return None, None

def _arcgis_point_query(map_server_url: str, layer_id: int, lat: float, lon: float):
    point = {
        "x": float(lon),
        "y": float(lat),
        "spatialReference": {"wkid": 4326},
    }
    payload = _http_get_json(
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

def _geocode_city_state(city: str, state: str):
    city_text = str(city or "").strip()
    state_text = str(state or "").strip()
    if not city_text and not state_text:
        raise InputValidationError("Enter at least City or State for backend lookup.")
    query = ", ".join(part for part in [city_text, state_text, "USA"] if part)
    result = _http_get_json(
        NOMINATIM,
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
    lat = _to_float_or_none(first.get("lat"))
    lon = _to_float_or_none(first.get("lon"))
    if lat is None or lon is None:
        raise InputValidationError(f"Could not geocode '{query}'.")
    display_name = str(first.get("display_name") or query)
    return lat, lon, display_name

def _lookup_snow_load_asce_716(lat: float, lon: float):
    base = ASCE_716_MAP
    lookup_fields = ("Load1_1", "Load1", "Load", "SI", "value")
    for layer_id in (1, 2):
        attrs_list = _arcgis_point_query(base, layer_id, lat, lon)
        if not attrs_list:
            continue

        positive_candidates = []
        details_url = ""
        for attrs in attrs_list:
            value, field_name = _extract_first_numeric_attr(attrs, lookup_fields)
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

def _lookup_snow_load_asce_722(lat: float, lon: float):
    base = ASCE_722_MAP
    attrs_list = _arcgis_point_query(base, 0, lat, lon)
    if not attrs_list:
        raise InputValidationError("No ASCE 7-22 snow value found for that location.")

    lookup_fields = ("SI", "value", "Load1_1", "Load", "Pg")
    positive_candidates = []
    from_label = ""
    for attrs in attrs_list:
        value, from_field = _extract_first_numeric_attr(attrs, lookup_fields)
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

def _extract_snow_psf_from_text(text: str) -> float:
    """Extract a ground snow load from text pasted out of the ASCE tool.

    Deliberately stricter than the desktop original, which stripped commas
    before matching and so read "Ground Snow Load 1,200 ft" as 1 psf -- a
    silently wrong design load. Here a thousands separator keeps its digits,
    a value must not be immediately followed by a non-psf unit, and an
    implausible magnitude is rejected rather than returned.
    """
    source = str(text or "").strip()
    if not source:
        raise InputValidationError("Paste ASCE output text first.")
    # Join thousands separators into the number instead of splitting it.
    flat = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", source)

    def _accept(token, tail):
        # Reject a number that is actually carrying a different unit.
        if re.match(r"\s*(?:ft|feet|in|inches|m(?![a-z])|mph|lb|kip|deg|%|year)", tail or "", re.IGNORECASE):
            return None
        value = _non_negative_load(token)
        # Published ground snow loads are well inside this range; anything
        # outside it is a mis-parse, not a real load.
        if not 0 <= value <= 500:
            return None
        return value

    labelled = [
        r"(?:ground\s+snow\s+load|snow\s+load|p_g|pg|p\s*g)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)",
        r"(?:ground\s+snow|snow)\s*\(?\s*pg\s*\)?\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in labelled:
        for match in re.finditer(pattern, flat, flags=re.IGNORECASE):
            value = _accept(match.group(1), flat[match.end():match.end() + 12])
            if value is not None:
                return value

    # Fall back to any "<n> psf" near snow wording.
    for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*psf", flat, flags=re.IGNORECASE):
        context = flat[max(0, match.start() - 60):match.end() + 60].lower()
        if "snow" in context or "ground" in context or "pg" in context:
            value = _accept(match.group(1), "")
            if value is not None:
                return value

    raise InputValidationError(
        "Could not detect a ground snow load in that text. Include a line "
        "containing Ground Snow Load or pg with a value in psf."
    )


def _non_negative_load(value):
    """Parse a psf value, rejecting negatives and non-numbers."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InputValidationError("Snow Load must be a number.") from exc
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        raise InputValidationError("Snow Load must be zero or greater.")
    return number


def lookup(city, state, snow_code="ASCE 7-16"):
    """Geocode a city/state and return the published ground snow load.

    Returns {ground_snow_load_psf, source, location, latitude, longitude}.
    Raises InputValidationError with a reportable message on any failure.
    """
    latitude, longitude, display_name = _geocode_city_state(city, state)
    code = str(snow_code or "").strip()
    if "7-22" in code:
        value, source = _lookup_snow_load_asce_722(latitude, longitude)
    else:
        value, source = _lookup_snow_load_asce_716(latitude, longitude)
    return {
        "ground_snow_load_psf": round(float(value), 2),
        "source": source,
        "location": display_name,
        "latitude": round(float(latitude), 6),
        "longitude": round(float(longitude), 6),
    }


def parse_pasted(text):
    """Extract a ground snow load from text pasted out of the ASCE tool."""
    return {"ground_snow_load_psf": round(_extract_snow_psf_from_text(text), 2),
            "source": "Pasted ASCE output"}
