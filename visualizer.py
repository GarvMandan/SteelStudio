"""Launch Steel Studio locally, backed by the existing calculation engine.

Run ``python visualizer.py`` and keep the process running while using the browser.
Only the compiled frontend is served; workbook and project files stay private.
"""

from __future__ import annotations

import argparse
import importlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "visualizer" / "dist"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 24 * 1024 * 1024


def _reject_constant(value):
    raise ValueError(f"Non-finite number {value} is not supported.")


def _parse_json(data):
    return json.loads(data, parse_constant=_reject_constant)


def _load_adapter():
    try:
        return importlib.import_module("steel_model")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Steel Studio needs the missing Python module '{exc.name}'. "
            "Run the project virtual environment or install requirements.txt."
        ) from exc


class SteelStudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, static_dir, adapter, project_result):
        self.static_dir = Path(static_dir).resolve()
        self.adapter = adapter
        self.project_result = project_result
        self.calculation_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), SteelStudioHandler)


class SteelStudioHandler(BaseHTTPRequestHandler):
    server_version = "SteelStudio/1.0"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _headers(self, status, content_type, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _json_response(self, status, value, head=False):
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data))
        if not head:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _local_request(self, head=False):
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed_hosts.update({"127.0.0.1", "localhost"})
        host = self.headers.get("Host", "").lower()
        if len(self.headers.get_all("Host", [])) != 1 or host not in allowed_hosts:
            self._json_response(403, {"error": "This service is available only on localhost."}, head)
            return False
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0] != f"http://{host}"):
            self._json_response(403, {"error": "Cross-origin requests are not permitted."}, head)
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._json_response(403, {"error": "Cross-site requests are not permitted."}, head)
            return False
        return True

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if not self._local_request(head):
            return
        try:
            path = urlsplit(self.path).path
            if path == "/api/health":
                self._json_response(200, {"status": "ok", "app": "Steel Studio"}, head)
            elif path == "/api/project":
                with self.server.calculation_lock:
                    result = self.server.project_result
                self._json_response(200, result, head)
            elif path == "/api/catalog":
                self._json_response(200, self.server.adapter.catalogs(), head)
            elif path == "/api/workspace":
                import workspace_store
                self._json_response(200, {"projects": workspace_store.list_projects()}, head)
            elif path.startswith("/api/workspace/"):
                import workspace_store
                parts = [p for p in path[len("/api/workspace/"):].split("/") if p]
                if len(parts) == 1:
                    self._json_response(200, workspace_store.get_project(parts[0]), head)
                elif len(parts) == 3 and parts[1] == "buildings":
                    self._json_response(200, workspace_store.get_building(parts[0], parts[2]), head)
                else:
                    self._json_response(404, {"error": "Unknown workspace path."}, head)
            elif path.startswith("/api/"):
                self._json_response(404, {"error": "Unknown API endpoint."}, head)
            else:
                self._serve_static(path, head)
        except self.server.adapter.InputValidationError as exc:
            self._json_response(404, {"error": str(exc)}, head)
        except (ValueError, TypeError, OSError) as exc:
            self.log_error("Request failed: %s", exc)
            self._json_response(500, {"error": "The requested resource could not be loaded."}, head)

    def _serve_static(self, path, head):
        decoded = unquote(path)
        parts = decoded.replace("\\", "/").split("/")
        if ".." in parts or "\x00" in decoded or ":" in decoded:
            self._json_response(404, {"error": "File not found."}, head)
            return
        root = self.server.static_dir
        requested = (root / decoded.lstrip("/\\")).resolve()
        if not requested.is_relative_to(root):
            self._json_response(404, {"error": "File not found."}, head)
            return
        if requested.is_dir():
            requested = (requested / "index.html").resolve()
        if not requested.is_file() and not Path(decoded).suffix:
            requested = root / "index.html"
        if not requested.is_file() or not requested.is_relative_to(root):
            self._json_response(404, {"error": "File not found."}, head)
            return
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        # Windows registry MIME mappings can assign .js to text/plain.
        if requested.suffix in {".js", ".mjs"}:
            content_type = "text/javascript"
        elif requested.suffix == ".css":
            content_type = "text/css"
        with requested.open("rb") as handle:
            self._headers(200, content_type, os.fstat(handle.fileno()).st_size)
            if not head:
                try:
                    shutil.copyfileobj(handle, self.wfile)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def do_POST(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if not (path in {"/api/calculate", "/api/import", "/api/report", "/api/snow-lookup"}
                or path.startswith("/api/workspace")):
            self._json_response(404, {"error": "Unknown API endpoint."})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json_response(400, {"error": "Use Content-Length for project uploads."})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            self._json_response(411, {"error": "A valid Content-Length is required."})
            return
        length = int(lengths[0])
        if length > (MAX_REPORT_BYTES if path == "/api/report" else MAX_BODY_BYTES):
            self._json_response(413, {"error": "Report request must be smaller than 24 MB." if path == "/api/report" else "Project JSON must be smaller than 4 MB."})
            return
        if self.headers.get_content_type() != "application/json":
            self._json_response(415, {"error": "Send project data as application/json."})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("The project upload was incomplete.")
            project = _parse_json(raw)
            if not isinstance(project, dict):
                raise ValueError("The project must be a JSON object.")
            if path == "/api/report":
                from steel_report import build_report, report_filename, validate_image
                payload = project
                project = payload.get("project")
                if not isinstance(project, dict):
                    raise ValueError("The report must include a project snapshot.")
                if len(json.dumps(project).encode("utf-8")) > MAX_BODY_BYTES:
                    raise ValueError("The report project snapshot must be smaller than 4 MB.")
                validate_image(payload.get("model_image"))
                with self.server.calculation_lock:
                    result = self.server.adapter.calculate_project(project)
                    report = build_report(result, payload.get("model_image"), payload.get("report"))
                # Export is a snapshot operation; never replace a newer session model.
                self._headers(200, "application/pdf", len(report), {"Content-Disposition": f'attachment; filename="{report_filename(project)}"'})
                try:
                    self.wfile.write(report)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path.startswith("/api/workspace"):
                import workspace_store
                parts = [p for p in path[len("/api/workspace"):].split("/") if p]
                action = str(project.get("action") or "")
                if not parts:
                    if action == "create":
                        self._json_response(200, workspace_store.create_project(project))
                    else:
                        raise ValueError("Unknown workspace action.")
                elif len(parts) == 1:
                    if action == "update":
                        self._json_response(200, workspace_store.update_project(parts[0], project))
                    elif action == "delete":
                        self._json_response(200, workspace_store.delete_project(parts[0]))
                    else:
                        raise ValueError("Unknown workspace action.")
                elif len(parts) == 2 and parts[1] == "buildings":
                    self._json_response(200, workspace_store.create_building(parts[0], project))
                elif len(parts) == 3 and parts[1] == "buildings":
                    if action == "delete":
                        self._json_response(200, workspace_store.delete_building(parts[0], parts[2]))
                    elif action == "duplicate":
                        self._json_response(200, workspace_store.duplicate_building(parts[0], parts[2], project.get("name")))
                    else:
                        self._json_response(200, workspace_store.save_building(parts[0], parts[2], project))
                else:
                    raise ValueError("Unknown workspace path.")
                return
            if path == "/api/snow-lookup":
                import snow_lookup
                # Two upstream hops (geocode, then ASCE GIS) can outlast the
                # default socket timeout; widen it for this request only.
                self.connection.settimeout(40)
                # No calculation_lock: this is third-party network I/O and must
                # not block recalculation. It never touches project_result.
                if project.get("paste"):
                    self._json_response(200, snow_lookup.parse_pasted(project.get("paste")))
                else:
                    self._json_response(200, snow_lookup.lookup(
                        project.get("city", ""), project.get("state", ""),
                        project.get("snow_code", "ASCE 7-16")))
                return
            with self.server.calculation_lock:
                result = self.server.adapter.calculate_project(project)
                # Validate before replacing the last successful session model.
                json.dumps(result, allow_nan=False)
                self.server.project_result = result
            self._json_response(200, result)
        except (self.server.adapter.InputValidationError, ValueError, UnicodeError, RecursionError) as exc:
            self._json_response(400, {"error": str(exc) or "Invalid project JSON."})
        except (TimeoutError, socket.timeout):
            self._json_response(408, {"error": "The project upload timed out."})
        except Exception as exc:
            self.log_error("Calculation failed: %s", exc)
            self._json_response(500, {"error": "Calculation failed. Check the server console for details."})

    def do_OPTIONS(self):
        self._json_response(405, {"error": "Only same-origin GET and POST requests are supported."})


def create_server(port=0, initial_project=None, static_dir=STATIC_DIR, adapter=None):
    """Create a loopback server; callers may serve it in a background thread."""
    root = Path(static_dir).resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError(
            "The Steel Studio frontend has not been built. "
            "Run 'npm install' and 'npm run build' in the visualizer folder first."
        )
    adapter = adapter or _load_adapter()
    project = adapter.defaults() if initial_project is None else initial_project
    result = adapter.calculate_project(project)
    json.dumps(result, allow_nan=False)
    return SteelStudioServer(port, root, adapter, result)


def _write_status(path, payload):
    if path:
        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        temporary.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the local Steel Studio 3D design engine.")
    parser.add_argument("--port", type=int, default=None, help="Port to use (default: 8765 or a free port).")
    parser.add_argument("--no-browser", action="store_true", help="Start the server without opening a browser.")
    parser.add_argument("--project", type=Path, help="Open a saved Steel Studio or legacy project JSON.")
    parser.add_argument("--status-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    server = None
    try:
        initial_project = None
        if args.project:
            with args.project.open("rb") as handle:
                raw = handle.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ValueError("Project JSON must be smaller than 4 MB.")
            initial_project = _parse_json(raw)
            if not isinstance(initial_project, dict):
                raise ValueError("The project must be a JSON object.")
        port = DEFAULT_PORT if args.port is None else args.port
        try:
            server = create_server(port, initial_project)
        except OSError as exc:
            if args.port is not None or exc.errno not in {48, 98, 10048}:
                raise
            server = create_server(0, initial_project)
        url = f"http://127.0.0.1:{server.server_port}"
        _write_status(args.status_file, {"status": "ready", "url": url})
        print(f"Steel Studio is ready at {url}\nKeep this process open. Press Ctrl+C to stop.", flush=True)
        if not args.no_browser:
            threading.Timer(0.3, webbrowser.open, args=(url,)).start()
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nSteel Studio stopped.")
    except Exception as exc:
        message = f"Steel Studio could not start: {exc}"
        print(message, file=sys.stderr, flush=True)
        try:
            _write_status(args.status_file, {"status": "error", "error": message})
        except OSError:
            pass
        return 1
    finally:
        if server is not None:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
