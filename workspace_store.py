"""Project and building storage on disk.

The application previously held exactly one project, in memory, for the
lifetime of the server process. This adds the durable structure the
estimator needs:

    projects/
      <project-id>/
        project.json              name, number, client, created/updated
        buildings/
          <building-id>.json      one building's full design payload

A project is a job. A building belongs to a project, and each building
carries its trades -- structural steel today, concrete and the MEP
disciplines later. Files stay individually readable and portable: a
single building can be copied, emailed or archived on its own.

Writes are atomic (temp file then replace) so an interrupted save cannot
leave a half-written design behind.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from calculation_engine import InputValidationError

ROOT = Path(__file__).resolve().parent / "projects"
MAX_NAME = 120
# A project with this many buildings is far past anything real; the cap
# exists so a runaway client cannot fill the disk.
MAX_BUILDINGS = 200
MAX_PROJECTS = 500

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _check_id(value, label):
    """Validate an identifier before it is used as a path segment."""
    text = str(value or "")
    if not _ID.match(text):
        raise InputValidationError(f"{label} is not a valid identifier.")
    return text


def _text(value, label, limit=MAX_NAME, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise InputValidationError(f"{label} must be text.")
    cleaned = value.strip()[:limit]
    if required and not cleaned:
        raise InputValidationError(f"{label} is required.")
    return cleaned


def _read_json(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path, payload):
    """Write atomically so a crash cannot truncate an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, allow_nan=False)
    temp.replace(path)


def _project_dir(project_id):
    return ROOT / _check_id(project_id, "Project id")


def _building_path(project_id, building_id):
    return _project_dir(project_id) / "buildings" / f"{_check_id(building_id, 'Building id')}.json"


# --- projects ---------------------------------------------------------

def list_projects():
    """Every project with its building summaries, newest first."""
    if not ROOT.is_dir():
        return []
    out = []
    for folder in ROOT.iterdir():
        if not folder.is_dir() or not _ID.match(folder.name):
            continue
        meta = _read_json(folder / "project.json")
        if not isinstance(meta, dict):
            continue
        meta["id"] = folder.name
        meta["buildings"] = list_buildings(folder.name)
        meta["building_count"] = len(meta["buildings"])
        out.append(meta)
    out.sort(key=lambda p: str(p.get("updated_at") or ""), reverse=True)
    return out


def get_project(project_id):
    meta = _read_json(_project_dir(project_id) / "project.json")
    if not isinstance(meta, dict):
        raise InputValidationError("That project could not be found.")
    meta["id"] = _check_id(project_id, "Project id")
    meta["buildings"] = list_buildings(project_id)
    return meta


def create_project(payload):
    if len(list_projects()) >= MAX_PROJECTS:
        raise InputValidationError(f"A maximum of {MAX_PROJECTS} projects is supported.")
    project_id = _new_id("p")
    meta = {
        "id": project_id,
        "name": _text((payload or {}).get("name"), "Project name", required=True),
        "number": _text((payload or {}).get("number"), "Project number"),
        "client": _text((payload or {}).get("client"), "Client"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write_json(_project_dir(project_id) / "project.json", meta)
    meta["buildings"] = []
    return meta


def update_project(project_id, payload):
    meta = _read_json(_project_dir(project_id) / "project.json")
    if not isinstance(meta, dict):
        raise InputValidationError("That project could not be found.")
    for key, label in (("name", "Project name"), ("number", "Project number"), ("client", "Client")):
        if key in (payload or {}):
            meta[key] = _text(payload[key], label, required=(key == "name"))
    meta["id"] = _check_id(project_id, "Project id")
    meta["updated_at"] = _now()
    _write_json(_project_dir(project_id) / "project.json", meta)
    meta["buildings"] = list_buildings(project_id)
    return meta


def delete_project(project_id):
    folder = _project_dir(project_id)
    if not folder.is_dir():
        raise InputValidationError("That project could not be found.")
    shutil.rmtree(folder)
    return {"deleted": _check_id(project_id, "Project id")}


def _touch_project(project_id):
    path = _project_dir(project_id) / "project.json"
    meta = _read_json(path)
    if isinstance(meta, dict):
        meta["updated_at"] = _now()
        _write_json(path, meta)


# --- buildings --------------------------------------------------------

def _summary(building):
    """The listing view of a building: metadata without the design payload."""
    return {
        "id": building.get("id", ""),
        "name": building.get("name", ""),
        "created_at": building.get("created_at", ""),
        "updated_at": building.get("updated_at", ""),
        "trades": building.get("trades", {}),
        "summary": building.get("summary", {}),
    }


def list_buildings(project_id):
    folder = _project_dir(project_id) / "buildings"
    if not folder.is_dir():
        return []
    out = []
    for path in folder.glob("*.json"):
        record = _read_json(path)
        if isinstance(record, dict):
            record.setdefault("id", path.stem)
            out.append(_summary(record))
    out.sort(key=lambda b: str(b.get("created_at") or ""))
    return out


def get_building(project_id, building_id):
    record = _read_json(_building_path(project_id, building_id))
    if not isinstance(record, dict):
        raise InputValidationError("That building could not be found.")
    record["id"] = _check_id(building_id, "Building id")
    return record


def create_building(project_id, payload):
    if not _project_dir(project_id).is_dir():
        raise InputValidationError("That project could not be found.")
    if len(list_buildings(project_id)) >= MAX_BUILDINGS:
        raise InputValidationError(f"A project supports at most {MAX_BUILDINGS} buildings.")
    payload = payload or {}
    building_id = _new_id("b")
    record = {
        "id": building_id,
        "project_id": _check_id(project_id, "Project id"),
        "name": _text(payload.get("name"), "Building name", required=True),
        "created_at": _now(),
        "updated_at": _now(),
        # Steel is designed today; the other trades are declared so the
        # home page can show real progress before they are implemented.
        "trades": {"steel": "in_progress", "concrete": "not_started",
                   "hvac": "not_started", "electrical": "not_started",
                   "plumbing": "not_started"},
        "project": payload.get("project") or {},
        "summary": {},
    }
    _write_json(_building_path(project_id, building_id), record)
    _touch_project(project_id)
    return record


def save_building(project_id, building_id, payload):
    """Persist a building's design. Only known fields are written."""
    record = get_building(project_id, building_id)
    payload = payload or {}
    if "name" in payload:
        record["name"] = _text(payload["name"], "Building name", required=True)
    if "project" in payload:
        if not isinstance(payload["project"], dict):
            raise InputValidationError("The building design must be an object.")
        record["project"] = payload["project"]
    if "summary" in payload:
        if not isinstance(payload["summary"], dict):
            raise InputValidationError("The building summary must be an object.")
        # Keep the few headline numbers the home page shows, not the
        # whole calculated result.
        keep = ("member_count", "total_weight_lbs", "weight_tons",
                "floor_area_sf", "bay_count", "concrete_total_cy")
        record["summary"] = {k: payload["summary"][k] for k in keep if k in payload["summary"]}
    if "trades" in payload:
        if not isinstance(payload["trades"], dict):
            raise InputValidationError("Trades must be an object.")
        allowed = {"not_started", "in_progress", "complete"}
        for trade, status in payload["trades"].items():
            if trade in record["trades"] and status in allowed:
                record["trades"][trade] = status
    record["updated_at"] = _now()
    _write_json(_building_path(project_id, building_id), record)
    _touch_project(project_id)
    return record


def delete_building(project_id, building_id):
    path = _building_path(project_id, building_id)
    if not path.is_file():
        raise InputValidationError("That building could not be found.")
    path.unlink()
    _touch_project(project_id)
    return {"deleted": _check_id(building_id, "Building id")}


def duplicate_building(project_id, building_id, name=None):
    source = get_building(project_id, building_id)
    copy = create_building(project_id, {
        "name": _text(name or f"{source.get('name', 'Building')} copy", "Building name", required=True),
        "project": source.get("project") or {},
    })
    copy["trades"] = dict(source.get("trades") or copy["trades"])
    copy["summary"] = dict(source.get("summary") or {})
    _write_json(_building_path(project_id, copy["id"]), copy)
    return copy
