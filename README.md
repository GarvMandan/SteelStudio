# Structural Steel Studio

An interactive building layout and takeoff workspace connected to the original Python calculation and automatic section-selection routines, with optional 3D review.

## Open Steel Studio

Double-click **Start Steel Studio.cmd** in this folder. It opens the local app in your browser; keep its server window running while you work. The frontend is already built, so Node.js is not needed to use it.

You can also run:

```powershell
.\.venv\Scripts\python.exe .\visualizer.py
```

From the original desktop application, **Open 3D Studio** opens a copy of your current project, including unsaved inputs and section assignments. The original desktop reports and tools remain available.

- Open on the estimator home page: projects, the buildings each contains, and a status per trade.
- **Add building** runs a guided setup - overall size, bay spacing, clear height - with a live plan preview.
- Look up a ground snow load by city and state, or paste the ASCE Hazard Tool output.
- Work is autosaved to the browser and recovered after an unexpected close; buildings are stored on disk under `projects/`.
- Start with an editable building plan: drag interior grid lines, select bay dimensions, or create a regular grid.
- Use full-width workspaces for building layout, mezzanines, roof design, loads and foundations, and takeoffs. **Grid & dimensions** opens a wide grid editor.
- Draw, move, and resize mezzanine areas on the plan. Set their elevation, floor loads, joist direction, internal framing bays, and individual panel joist spaces, then review dedicated mezzanine calculations and exports.
- Paint footprint, joist spaces, collateral loads, bearing walls, and speed bays directly on the plan.
- Automatically recalculate joists, girders, columns, pad footings, and gross wall area as you edit. **Recalculate all** is also available.
- See roof slopes, elevations, clear height, and speed-bay transitions in an annotated section below the plan.
- Open **Takeoffs** for quantities and CSV exports, or **3D review** to zoom into members, inspect steel descriptions, and pin catalog or custom sections.
- Save/open project JSON, import original desktop projects, and export a member schedule CSV or model PNG.
- Use **PDF report** in the top bar to download a landscape report with a clean 3D model, north-up plans, roof profile, mezzanine sheets, and grouped steel, footing, and wall quantities. Add company, preparer, project number, and revision details before exporting.

See [the Steel Studio guide](docs/STEEL_STUDIO.md) for controls, data behavior, and development commands.

The 3D profiles are schematic. The original engine calculates takeoff demands; it does not verify structural adequacy, connections, lateral stability, or code compliance. Unassigned sections contribute no weight, and all assigned sections remain unchecked.

## Hosted deployment

A live instance runs at <https://steel-studio.onrender.com>.

The same `visualizer.py` entrypoint serves both the local app and a hosted
one; deployment is controlled entirely by environment variables, so local
behaviour is unchanged when they are unset:

| Variable | Purpose |
| --- | --- |
| `HOST` | Bind address. Defaults to `127.0.0.1`; set to `0.0.0.0` to accept connections from a proxy. |
| `PORT` | Port to bind. Most platforms set this automatically. |
| `TRUST_PROXY_HOST` | Set to `1` when running behind a TLS-terminating proxy. Relaxes the localhost-only host check while still requiring a request's `Origin` to match its own `Host`, so cross-site calls stay blocked. |
| `STEEL_STUDIO_DATA_DIR` | Where saved projects are written. Point this at a mounted persistent disk on a host with an ephemeral filesystem. |

`render.yaml` defines the service for [Render](https://render.com); deploy it
via **New + → Blueprint**. Note that Render does not always apply new
`envVars` from a Blueprint on a plain auto-deploy, so confirm
`TRUST_PROXY_HOST=1` is present under the service's Environment tab.

Install `requirements-web.txt` rather than `requirements.txt` for a server:
it omits the desktop-only packages (matplotlib, PyInstaller, ttkbootstrap,
pywin32) that only `grid_gui.py` needs.

Two caveats for the free tier: the service sleeps after inactivity and takes
roughly 30-50 seconds to wake, and its filesystem is ephemeral, so saved
projects are lost on redeploy unless `STEEL_STUDIO_DATA_DIR` points at a
persistent disk.

## Original desktop application

Interactive grid modeling for structural steel takeoffs with a joist-first calculation step.

## Run

```powershell
py -3 .\grid_gui.py
```

## Program structure

- `grid_gui.py`
  - Main desktop GUI
  - Tabs:
    - `Grid Layout`
    - `Load Inputs (psf)`
    - `Girder Calculation`
    - `Roof Layout`
- `calculation_engine.py`
  - Separate joist and girder calculation module

## Grid features

- CAD-style grid with numbered and lettered axes
- Add/remove X and Y bays in feet
- Fit, zoom, pan, and edit interior lines by drag
- Collateral load bay highlighting (green)
- Joists-per-bay assignment by click
- `Apply Joists To All Bays` for fast global assignment
- Strong visual vertical joist members per bay
- Tiny interior column squares at 4-bay intersections

## Current calculation step: Joists

Use `Calculate Joists` in the `Load Inputs (psf)` tab.

Per bay formulas:

- `Joist spacing = bay width (x) / joists per bay`
- `Tributary area = joist spacing * bay length`
- `Reduced Live Load = (1.2 - (0.001 * tributary area)) * live load`
- `Reduced Snow Load = (Snow Load * 0.7) + 5`
- If `Reduced Live Load > Reduced Snow Load`: `Total Load = Dead Load + Reduced Live Load`
- Else: `Total Load = Dead Load + Reduced Snow Load`
- For collateral bays: `Total Load += Collateral Load Addition`
- `Required joist capacity (plf) = Total Load * Joist Spacing`

Joist selection workflow:

- Joists are grouped by required capacity (e.g., `20 x Joists require 216.00 plf`)
- User assigns `chosen depth (in)` and `chosen weight (plf)` per group
- Program computes `group weight (lbs) = chosen weight (plf) * total span (ft) in group`
- Program shows `total assigned joist weight (lbs)` across all groups
- Final weight adjustment rule:
  - For each row, subtract one end joist (rightmost bay) from weight totals
  - Equivalent deduction per row: `chosen weight (plf) * bay length (ft)` of that row-end bay
  - For rows containing collateral bays, subtract one additional collateral joist from collateral-demand weight
  - For each row containing collateral bays, add one joist with regular-bay demand in that row

Results are shown in-app in a calculation table.

## Girder calculation tab

Use `Calculate Girders` in the `Girder Calculation` tab.

Girder assumptions and formulas:

- Girders are horizontal members on each line (A/B/C...) between columns.
- First and last perimeter lines are tilt walls and are excluded from girders.
- Girder length is the bay width in X for its segment.
- Average Bay Length (Y) at each girder segment:
  - `Avg Y = (top bay length + bottom bay length) / 2`
- Tributary area:
  - `At = Avg Y * bay width (x)`
- Reduced live load factor (`R1`) based on `At`:
  - `R1 = 1.0` for `At <= 200`
  - `R1 = 1.2 - 0.001*At` for `200 < At < 600`
  - `R1 = 0.6` for `At >= 600`
- `Reduced LL = R1 * LL`
- Reduced snow load:
  - `Reduced SL = (SL * 0.7) + 5`
- TL logic matches joists using reduced LL vs reduced SL.
- Collateral TL adjustment for the two bays adjacent to the girder:
  - 1 collateral bay adjacent: add `Collateral Load Addition / 2`
  - 2 collateral bays adjacent: add full `Collateral Load Addition`
- Required girder load capacity:
  - `Required Capacity (lbs) = Avg Y * Avg Joist Spacing * TL`

## Roof layout tab

- Shows a Y-Y cross-section of the building using current X-bay layout.
- Draws:
  - Roof profile (Flat / Gable / Single Slope)
  - Columns at X-grid lines
  - Bay width labels and grid markers
- Inputs:
  - Roof Type
  - Eave Height (ft)
  - Roof Rise (ft)

## Notes

- Minimum bay spacing is `0.5 ft`.
- Default joist assignment is `7` joists/bay (editable).
