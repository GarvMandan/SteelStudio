"""Section catalog readers.

Extracted verbatim from SteelGridApp so the takeoff workflow no longer
depends on the tkinter desktop application. These parsers encode real
quirks of the supplied Vulcraft/column workbooks (OCR digit fixes, merged
header rows, ASD/LRFD block detection); behaviour is deliberately unchanged.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

from calculation_engine import InputValidationError


def coerce_catalog_number(token: str):
        token = str(token or "").strip().replace(",", "")
        if not token:
            return None
        if token in {"'6", "’6", "`6"}:
            token = "9.6"
        token = token.replace("O", "0").replace("o", "0")
        if token.startswith("."):
            token = "0" + token
        if token.endswith("."):
            token = token[:-1]
        if not re.fullmatch(r"-?\d+(\.\d+)?", token):
            return None
        try:
            return float(token)
        except ValueError:
            return None

def catalog_search_dirs():
        dirs = []
        try:
            dirs.append(Path.cwd())
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            try:
                dirs.append(Path(sys.executable).resolve().parent)
            except Exception:
                pass
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                try:
                    dirs.append(Path(meipass))
                except Exception:
                    pass
        try:
            dirs.append(Path(__file__).resolve().parent)
        except Exception:
            pass
        unique_dirs = []
        seen = set()
        for item in dirs:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            unique_dirs.append(item)
        return unique_dirs

def find_girder_catalog_path():
        for base_dir in catalog_search_dirs():
            preferred = base_dir / "Expanded Vulcraft Joist Girder Catalog.xlsx"
            if preferred.exists():
                return preferred
        for base_dir in catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            # Prefer filenames with "girder" if available.
            girder_candidates = [p for p in candidates if "girder" in p.name.lower()]
            if girder_candidates:
                return girder_candidates[0]
            return candidates[0]
        return None

def parse_joist_space_descriptor(space_text: str):
        text = str(space_text or "").replace("\n", " ").strip()
        n_match = re.search(r"(\d+)\s*[Nn]", text)
        s_match = re.search(r"@\s*([0-9]+(?:\.[0-9]+)?)", text)
        joist_n = int(n_match.group(1)) if n_match else None
        spacing_ft = float(s_match.group(1)) if s_match else None
        return joist_n, spacing_ft

def parse_girder_catalog_excel(excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        load_header_row = None
        load_col_start = None
        load_values = []
        scan_max_row = min(40, ws.max_row)
        for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=scan_max_row, values_only=True), start=1):
            row = list(row)
            for c_idx, value in enumerate(row, start=1):
                num = coerce_catalog_number(value)
                if num is None:
                    continue
                if c_idx >= 5 and 1 <= num <= 100:
                    trial = []
                    j = c_idx
                    while j <= len(row):
                        v = coerce_catalog_number(row[j - 1])
                        if v is None:
                            break
                        if not (1 <= v <= 100):
                            break
                        trial.append(float(v))
                        j += 1
                    if len(trial) >= 4:
                        load_header_row = r_idx
                        load_col_start = c_idx
                        load_values = trial
                        break
            if load_header_row is not None:
                break

        if load_header_row is None:
            raise InputValidationError("Could not locate girder load header row in catalog Excel.")

        rows = []
        current_span = None
        current_space = None
        for row in ws.iter_rows(min_row=load_header_row + 1, max_row=ws.max_row, values_only=True):
            row = list(row)
            span_num = coerce_catalog_number(row[1] if len(row) >= 2 else None)
            if span_num is not None and 10 <= span_num <= 400:
                current_span = round(float(span_num), 3)

            space_txt = row[2] if len(row) >= 3 else None
            if isinstance(space_txt, str) and space_txt.strip():
                current_space = space_txt.strip()

            depth_num = coerce_catalog_number(row[3] if len(row) >= 4 else None)
            if current_span is None or depth_num is None:
                continue
            depth_in = round(float(depth_num), 3)
            if depth_in <= 0:
                continue
            joist_n, joist_spacing_ft = parse_joist_space_descriptor(current_space or "")
            if joist_n is None:
                continue

            for offset, load_kips in enumerate(load_values):
                col_idx = load_col_start + offset
                if col_idx - 1 >= len(row):
                    continue
                wt_num = coerce_catalog_number(row[col_idx - 1])
                if wt_num is None or wt_num <= 0:
                    continue
                rows.append(
                    {
                        "span_ft": current_span,
                        "depth_in": depth_in,
                        "panel_load_kips": round(float(load_kips), 3),
                        "weight_plf": round(float(wt_num), 3),
                        "joist_spaces": current_space or "",
                        "joist_n": joist_n,
                        "joist_spacing_ft": joist_spacing_ft,
                    }
                )

        if not rows:
            raise InputValidationError(f"No usable catalog rows found in {excel_path.name}.")
        return rows

def build_girder_catalog_index(rows):
        # Index by exact span (2 decimals) and joist N.
        # Each bucket stores depth->sorted(load_kips, min_weight_plf) curve.
        index = {}
        buckets = {}
        for row in rows:
            span_key = round(float(row["span_ft"]), 2)
            joist_n = int(row.get("joist_n") or 0)
            if joist_n <= 0:
                continue
            depth = round(float(row["depth_in"]), 3)
            load_kips = round(float(row["panel_load_kips"]), 3)
            weight_plf = float(row["weight_plf"])
            key = (span_key, joist_n, depth)
            load_map = buckets.setdefault(key, {})
            prev = load_map.get(load_kips)
            if prev is None or weight_plf < prev:
                load_map[load_kips] = weight_plf

        for (span_key, joist_n, depth), load_map in buckets.items():
            curve = sorted(load_map.items(), key=lambda x: x[0])
            index.setdefault((span_key, joist_n), {})[depth] = curve
        return index

def parse_hss_depth_from_designation(designation: str):
        text = str(designation or "").strip().lower()
        if text.startswith("hss"):
            text = text[3:]
        match = re.match(r"^(\d+(?:\.\d+)?)x", text)
        if not match:
            return None
        try:
            depth_in = float(match.group(1))
        except ValueError:
            return None
        if depth_in <= 0:
            return None
        return round(depth_in, 3)

def find_column_catalog_path():
        for base_dir in catalog_search_dirs():
            preferred = base_dir / "Column Table.xlsx"
            if preferred.exists():
                return preferred
        for base_dir in catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            column_candidates = [p for p in candidates if "column" in p.name.lower()]
            if column_candidates:
                return column_candidates[0]
            return candidates[0]
        return None

def parse_column_catalog_excel(excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        # Expected layout:
        # - Row 2: designation in odd columns (3,5,...)
        # - Row 3: weight at same designation column
        # - Row 15: ASD/LRFD headers in paired columns
        # - Row 16+: KL table with KL in col 1 and ASD capacities in ASD columns
        row2 = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
        row3 = list(ws.iter_rows(min_row=3, max_row=3, values_only=True))[0]
        row15 = list(ws.iter_rows(min_row=15, max_row=15, values_only=True))[0]

        section_cols = []
        for col_idx, raw_name in enumerate(row2, start=1):
            name = str(raw_name or "").strip()
            if not name:
                continue
            if not re.search(r"^\d+(?:\.\d+)?x\d+(?:\.\d+)?x\d+/\d+$", name):
                continue
            asd_col = col_idx - 1
            if asd_col < 2:
                continue
            asd_header = str(row15[asd_col - 1] if asd_col - 1 < len(row15) else "").strip().upper()
            if asd_header != "ASD":
                continue
            weight = coerce_catalog_number(row3[col_idx - 1] if col_idx - 1 < len(row3) else None)
            if weight is None or weight <= 0:
                continue
            normalized_name = name if name.upper().startswith("HSS") else f"HSS{name}"
            section_cols.append(
                {
                    "designation": normalized_name,
                    "asd_col_idx": asd_col,
                    "depth_in": parse_hss_depth_from_designation(name),
                    "weight_plf": round(float(weight), 3),
                }
            )

        if not section_cols:
            raise InputValidationError(f"Could not parse section columns from {excel_path.name}.")

        rows = []
        for row in ws.iter_rows(min_row=17, max_row=ws.max_row, values_only=True):
            kl_val = coerce_catalog_number(row[0] if len(row) >= 1 else None)
            if kl_val is None:
                continue
            kl_ft = int(round(float(kl_val)))
            if kl_ft < 1:
                continue
            for section in section_cols:
                asd_col_idx = section["asd_col_idx"]
                if asd_col_idx - 1 >= len(row):
                    continue
                asd_kips = coerce_catalog_number(row[asd_col_idx - 1])
                if asd_kips is None or asd_kips <= 0:
                    continue
                rows.append(
                    {
                        "kl_ft": kl_ft,
                        "designation": section["designation"],
                        "depth_in": section["depth_in"] if section["depth_in"] is not None else 0.0,
                        "weight_plf": section["weight_plf"],
                        "asd_capacity_kips": round(float(asd_kips), 3),
                    }
                )

        if not rows:
            raise InputValidationError(f"No usable ASD column rows found in {excel_path.name}.")

        # Deduplicate by (KL, designation) and keep the lighter weight entry.
        dedup = {}
        for item in rows:
            key = (item["kl_ft"], item["designation"])
            current = dedup.get(key)
            if current is None or float(item["weight_plf"]) < float(current["weight_plf"]):
                dedup[key] = item
        return list(dedup.values())

def find_joist_catalog_excel_path():
        preferred_names = [
            "Joist Table 2.xlsx",
            "Joist Table2.xlsx",
            "Joist Table.xlsx",
        ]
        for base_dir in catalog_search_dirs():
            for name in preferred_names:
                candidate = base_dir / name
                if candidate.exists():
                    return candidate
        for base_dir in catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            joist_candidates = [
                p
                for p in candidates
                if "joist" in p.name.lower() and "girder" not in p.name.lower()
            ]
            if joist_candidates:
                joist_candidates.sort(key=lambda p: ("table 2" not in p.name.lower(), p.name.lower()))
                return joist_candidates[0]
        return None

def find_mezz_joist_catalog_excel_path():
        preferred_names = [
            "LH Joist Table.xlsx",
            "LH Joist Table 2.xlsx",
            "LH Joist Table2.xlsx",
            "LHJoistTable.xlsx",
            "LH Table.xlsx",
        ]
        for base_dir in catalog_search_dirs():
            for name in preferred_names:
                candidate = base_dir / name
                if candidate.exists():
                    return candidate
        for base_dir in catalog_search_dirs():
            candidates = sorted(base_dir.glob("*.xls*"))
            if not candidates:
                continue
            lh_candidates = [
                p
                for p in candidates
                if ("joist" in p.name.lower() and "lh" in p.name.lower() and "girder" not in p.name.lower())
            ]
            if lh_candidates:
                lh_candidates.sort(key=lambda p: p.name.lower())
                return lh_candidates[0]
        return None

def parse_joist_catalog_excel(excel_path: Path):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise InputValidationError("Excel parsing dependency missing. Install `openpyxl`.") from exc

        wb = load_workbook(excel_path, data_only=True, read_only=True)
        if not wb.sheetnames:
            raise InputValidationError(f"No worksheets found in {excel_path.name}.")
        ws = wb[wb.sheetnames[0]]

        span_header_row_idx = None
        designation_cols = []
        desig_pattern = re.compile(r"^\d{2,3}(?:K|LH)\d{1,2}$", flags=re.IGNORECASE)
        for r_idx in range(1, min(100, ws.max_row) + 1):
            row = list(ws.iter_rows(min_row=r_idx, max_row=r_idx, values_only=True))[0]
            first = str(row[0] or "").strip().lower()
            if "span" not in first:
                continue
            for c_idx, val in enumerate(row, start=1):
                txt = str(val or "").strip()
                if desig_pattern.fullmatch(txt):
                    designation_cols.append((c_idx, txt))
            if designation_cols:
                span_header_row_idx = r_idx
                break

        if span_header_row_idx is None:
            raise InputValidationError(f"Could not locate joist designation header row in {excel_path.name}.")

        depth_row = list(ws.iter_rows(min_row=span_header_row_idx + 1, max_row=span_header_row_idx + 1, values_only=True))[0]
        wt_row = list(ws.iter_rows(min_row=span_header_row_idx + 2, max_row=span_header_row_idx + 2, values_only=True))[0]

        cols = []
        for c_idx, designation in designation_cols:
            depth_val = coerce_catalog_number(depth_row[c_idx - 1] if c_idx - 1 < len(depth_row) else None)
            wt_val = coerce_catalog_number(wt_row[c_idx - 1] if c_idx - 1 < len(wt_row) else None)
            if depth_val is None or wt_val is None:
                continue
            if depth_val <= 0 or wt_val <= 0:
                continue
            cols.append(
                {
                    "col_idx": c_idx,
                    "designation": designation,
                    "depth_in": round(float(depth_val), 3),
                    "weight_plf": round(float(wt_val), 3),
                }
            )

        if not cols:
            raise InputValidationError(f"No usable joist designation columns found in {excel_path.name}.")

        rows = []
        for r_idx in range(span_header_row_idx + 3, ws.max_row + 1):
            row = list(ws.iter_rows(min_row=r_idx, max_row=r_idx, values_only=True))[0]
            span_val = coerce_catalog_number(row[0] if len(row) >= 1 else None)
            if span_val is None:
                continue
            span_ft = round(float(span_val), 3)
            if span_ft < 10 or span_ft > 150:
                continue

            for col in cols:
                c_idx = col["col_idx"]
                cap_val = coerce_catalog_number(row[c_idx - 1] if c_idx - 1 < len(row) else None)
                if cap_val is None or cap_val <= 0:
                    continue
                rows.append(
                    {
                        "designation": col["designation"],
                        "depth_in": col["depth_in"],
                        "weight_plf": col["weight_plf"],
                        "span_ft": span_ft,
                        "capacity_plf": round(float(cap_val), 3),
                    }
                )

        if not rows:
            raise InputValidationError(f"No joist capacity rows found in {excel_path.name}.")
        return rows

def build_joist_designation_index(catalog_rows):
        index = {}
        for row in catalog_rows or []:
            designation = str(row.get("designation", "")).strip()
            if not designation:
                continue
            span_ft = float(row.get("span_ft", 0.0))
            capacity_plf = float(row.get("capacity_plf", 0.0))
            depth_in = float(row.get("depth_in", 0.0))
            weight_plf = float(row.get("weight_plf", 0.0))
            if span_ft <= 0 or capacity_plf <= 0 or depth_in <= 0 or weight_plf <= 0:
                continue

            entry = index.setdefault(
                designation,
                {"designation": designation, "depth_in": depth_in, "weight_plf": weight_plf, "span_caps": {}},
            )
            # Keep the lightest/deepest metadata stable for this designation.
            if weight_plf < float(entry["weight_plf"]) - 1e-9:
                entry["weight_plf"] = weight_plf
                entry["depth_in"] = depth_in
            span_key = round(span_ft, 3)
            prev_cap = entry["span_caps"].get(span_key)
            if prev_cap is None or capacity_plf > prev_cap:
                entry["span_caps"][span_key] = capacity_plf
        return index
