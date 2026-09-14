# Steel Studio guide

## Start and open a project

Double-click `Start Steel Studio.cmd`. The Python server opens the bundled interface on your computer at `http://127.0.0.1:8765`; it uses a free port if that port is occupied. Keep the launcher window open while working. Stop the server with Ctrl+C when finished.

Use **Open** to select a saved `.json` project. Studio accepts its own projects and original Grid Designer projects. The original application's **Open 3D Studio** button transfers its current unsaved inputs to a separate Studio session. Edits in Studio do not automatically write back into the original application.

```powershell
.\.venv\Scripts\python.exe .\visualizer.py --project "C:\path\project.json"
```

The launcher uses the project's virtual environment. If it is unavailable, install the dependencies in `requirements.txt` into your Python environment, then run `py -3 visualizer.py`. Studio reuses the original desktop calculation workflow, including its workbook readers. The compiled frontend in `visualizer/dist` is included; Node.js is only needed for frontend development. All frontend assets are local.

## Design workflow

1. Click the project name in the top bar to rename it.
2. Start in **Building layout**. Open **Grid & dimensions** for a wide editor with individual X/Y dimensions and **Build a regular grid**.
3. In **Select / drag grids** mode, drag an interior grid line to redistribute neighboring bays while preserving the overall dimension. Click a bay to edit its dimensions and joist spaces in the horizontal controls above the plan. Minimum bay spacing is 0.5 ft.
4. Choose **Footprint**, **Joist spaces**, **Collateral**, **Bearing walls**, or **Speed bays**, then click the corresponding plan bay or wall edge. The joist tool applies the current default spacing count. Right-drag to pan; use the plan zoom and fit controls as needed.
5. Open **Roof section** for the roof type, clear height, slope direction, and speed-bay clear-height controls beside the large annotated section. The building plan also has a collapsible slope preview.
6. Set roof loads in **Loads & foundations**. Imported custom load layers are preserved. Design mezzanines and set their separate floor loads in **Mezzanines**. Geometry and elevations use feet.
7. Set footing depth, soil bearing capacity in psf, deck thickness, and insulation depth in the wide **Loads & foundations** form.
8. **Auto update** recalculates after you pause typing. **Recalculate all** runs the same complete workflow on demand. Turn Auto update off when making several changes together. Invalid input keeps the last successful calculation visible; pending edits remain marked.

Undo/redo applies to successful calculations. Undo can also discard pending form edits. **Advanced project data** exposes the saved payload for settings without dedicated controls.

## Automatic calculations

Studio uses the original joist-first workflow: calculate member demands, select joists from the K/LH catalogs, establish roof heights and girder depth limits, select girders and columns, and calculate pad footings and gross tilt-wall area. Mezzanine framing and its additional footings follow the original routines. Columns use the original ASD selection with clear-height-based effective length.

**Automatically select steel sections** is enabled by default. Manual member/group selections and imported assignments take priority and stay pinned after recalculation. If no catalog section meets the original selection rules, the member remains unassigned and the interface reports the missing choice. An automatic catalog match retains the same limitations as the original program; it is not a structural adequacy approval.

The bottom quantity bar keeps calculated joist, girder, column, footing, and wall totals visible. Click a quantity or open **Takeoffs** to view detailed rows and export CSV. **Building level** filters main-building or mezzanine members and footings. Steel weight excludes unassigned members. Joist and girder takeoff weights use the original plan spans; displayed 3D member lengths include slope. Column weights use their modeled length.

If an automatic catalog estimate produces a non-positive or invalid weight, Studio leaves that member unassigned and reports the issue instead of stopping the full calculation. The original demand remains available for a manual section choice.

## Mezzanine designer

Open **Mezzanines** from the main navigation. The designer uses the full workspace, with a building plan followed by wide geometry, framing, and calculation panels.

- **Add over a building bay** places a new area over the selected active building bay. **Draw mezzanine** lets you drag a rectangular area between two points.
- **Select / move** lets you select and drag an area. Drag its four corner handles to resize it. Snapping can use building grid lines or half-foot increments. Resize operations scale the existing internal bay widths with the footprint.
- **Focus area** zooms toward the selected mezzanine. Fit returns to the building plan; right-drag pans.
- Edit name, X/Y location, width, length, elevation, dead/live loads, joist span direction, default joist spaces, and internal X/Y bay counts below the plan. Counts create equal framing bays. Expand **Custom framing bay widths & panel overrides** for comma-separated bay widths; press Enter or leave the field to apply.
- **Edit joist panels** lets you select a panel and change its joist spaces. Panel overrides persist through recalculation and save/reopen. Changing an internal bay count clears panel overrides for the new grid.
- Select a named area above the plan to switch between mezzanines. Each area can be excluded or removed, with Undo available. The **Calculate mezzanines** checkbox includes/excludes all areas without deleting them.
- **Calculations** jumps to the selected area's results: floor area, joists, girders, additional columns, additional pad footings, and supported floor load. Show calculation details for member demands, sections, and weights; click a row to inspect or choose steel in 3D. Export that area's members as CSV.

The original engine requires at least two perimeter connections to building columns and/or bearing walls. Blue squares and brown wall segments identify these supports. Unsupported or invalid layouts keep the last valid calculation visible and show the engine's error. Reused main columns and their pads are not counted again as additional mezzanine quantities. Combined roof/mezzanine demand on those supports still requires separate verification.

Pad footing sizes follow the original quarter-foot rounding and include a separately shown 10% concrete waste allowance. The bearing capacity field uses psf; legacy `bearing_pressure_psi` project values are imported using the original numerical convention (for example, 3000 becomes 3000 psf).

Wall area follows the original gross rectangular envelope, dock-height, and stepped-wall conventions, including deck and insulation. It does not subtract openings or follow cutouts from inactive footprint bays. The takeoff reports this basis and flags inactive bays so the quantity can be interpreted correctly.

## Roof profile

**Original slope & clear-height rules** uses the original quarter-inch-per-foot main roof slope and speed-bay rules, together with selected joist depth and clear height. Double-slope roofs follow the original ridge conventions. The section labels each station elevation and each bay slope; its vertical scale is expanded and explicitly identified to make shallow roof slopes readable.

**Explicit eave & rise** allows a specified top-of-joist eave elevation and roof rise. Gable ridges follow a Y grid line and require at least two Y bays. Older Studio projects retain this mode to preserve their geometry. Imported desktop projects use the original roof conventions. Changing a roof field keeps the selected calculation mode.

## Inspect and select steel

Open **3D review** when you want to inspect the model. Click a member or schedule row to see endpoints, physical length, nominal depth, description, demand, and takeoff weight. **Choose steel section** opens the supplied workbook catalog. Search by designation or depth and apply to a member, demand group, or all members of the same type. **Specify a custom section** accepts designation, depth, and unit weight. Choosing **Unassigned** removes its takeoff weight and prevents automatic replacement for that override.

Catalog girder weights depend on span and panel load; the chooser uses available project-related entries. Review pinned manual choices after changing geometry or loads. Steel grade is unspecified. HSS and open-web geometry are schematic, with no fabrication detailing or capacity verification. Connections, bridging, deck, and miscellaneous steel are excluded from member weights. Combined roof/mezzanine demand on reused columns is not verified.

| 3D action | Control |
| --- | --- |
| Orbit | Left-drag |
| Pan | Right-drag |
| Zoom | Mouse wheel, pinch, or zoom buttons |
| Select | Click a member or schedule row |
| Focus | Double-click a member or press F |
| Fit building | H |
| Dimensions | D |
| Measure | M, then click near two member endpoints |
| Clear selection / isolation | Esc |
| Save project | Ctrl/Command + S outside text fields |
| Undo | Ctrl/Command + Z outside text fields |

Measurement snaps to the nearest endpoint of each clicked member and reports the three-dimensional distance. **Display** controls member types, roof/mezzanine visibility, grid, dimensions, and walls. The section-cut slider clips steel along X. The 3D renderer only runs while 3D review is open.

The camera presets are **Isometric**, **Plan - north up**, **South elevation**, and **East elevation**. Row A is north; numbered grids increase eastward, and lettered grids increase southward. The plan and 3D model use the same orientation. Isometric views start southeast of the building and fit the available viewport.

## Save and export

**Save project** downloads inputs and assignments as `.steel.json`, including pending draft changes. Opening the file recalculates it. Successful calculations remain in the running server session across page refreshes; stopping the server clears that in-memory session. Save before closing. Imported files are not overwritten.

Each **Takeoffs** table has a CSV export. **Member schedule > Export CSV** includes physical and takeoff lengths, section, weight, demand, units, and unchecked status. **Export model image**, available in 3D review, saves geometry as PNG; HTML dimension labels and interface controls are excluded.

**PDF report** is available in the top bar from any workspace. Enter company, prepared-by, project number, revision, and issue/purpose, then choose **Download PDF**. Details are retained with the project. The report recalculates current inputs before export and includes:

- A clean, high-resolution 3D framing image with a north arrow and quantity summary.
- Design inputs, a north-up building framing plan, and an enlarged roof profile with slopes and elevations.
- An individual plan and calculation summary for each enabled mezzanine.
- Grouped steel section schedules, pad footing sizes and concrete, gross wall area, and calculation notes.

The default landscape-letter report keeps individual member rows out of the main schedules. Enable **Include detailed member-by-member appendix** when those rows are needed. Project/revision information and page numbers repeat throughout. Export uses a separate full-model render, so hidden layers, isolated members, cut planes, and selections in the viewport cannot omit framing from the PDF. The drawings and tables share one calculation snapshot. Invalid inputs must be corrected before export; reports retain the original takeoff scope and clearly identify unassigned steel.

## Development and verification

`calculation_engine.py` remains unchanged and provides the four demand calculators. `steel_model.py` normalizes projects, runs those calculators, and builds physical members. `takeoff_workflow.py` orchestrates the takeoff; it is a plain class with no desktop dependency. `visualizer.py` provides the local HTTP API. React and Three.js sources live in `visualizer/src`.

The original selection and geometry rules were extracted out of the desktop application into GUI-free modules, each verified to reproduce the original results exactly:

| Module | Responsibility |
| --- | --- |
| `catalogs.py` | Excel catalog readers and section indexes |
| `selection.py` | Automatic joist, girder and column selection |
| `roof.py` | Roof profile, slopes, TOJ elevations, girder depth limits |
| `demand_groups.py` | Demand grouping and group IDs |
| `foundations.py` | Pad footings and tilt wall area |
| `grid_model.py` | Bay/grid geometry |

A calculation loads none of `tkinter`, `ttkbootstrap` or `grid_gui`.

```powershell
cd visualizer
npm ci
npm run build
npm run test:browser
npm run test:report
cd ..
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The Python tests compare restored selections, roof geometry, footing quantities, wall area, and takeoff weights against the original desktop routines. The browser smoke test starts an isolated server and exercises plan editing, automatic recalculation, roof views, exports, manual section pins, invalid input, and responsive layouts using headless Microsoft Edge. Set `BROWSER_CHANNEL=chrome` to use Chrome and `PYTHON` to override the Python executable. Screenshots are written to `visualizer/test-results`.

Python changes require a server restart; frontend rebuilds appear after browser refresh. The previous installer and packaged executable are unchanged. Use the source launcher for this interface.

`steel_report.py` uses ReportLab to create the PDF locally. Report tests check embedded images, quantities, page numbering, optional appendix pagination, and snapshot preservation. The report browser test also checks north-up orientation and downloads a real PDF after hiding a viewport layer. Set `STEEL_REPORT_PROJECT` to an absolute project JSON path to exercise a specific design; scratch reports are written to `tmp/pdfs`.
