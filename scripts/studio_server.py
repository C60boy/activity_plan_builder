# -*- coding: utf-8 -*-
"""Local HTTP server for the Activity Plan Builder Studio."""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"

import apb_core
from apb_core import (
    apply_event_bindings,
    new_plan,
    normalize_plan,
    plan_summary,
    sanitize_filename,
    validate_plan,
    write_json,
)

MAX_BODY = 25 * 1024 * 1024


class StudioState:
    def __init__(self, project_dir: Path, plan_path: Path, wait_mode: bool = False):
        self.project_dir = project_dir
        self.plan_path = plan_path
        self.wait_mode = wait_mode
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.last_build: Path | None = None

    def load_plan(self) -> dict:
        if not self.plan_path.exists():
            plan = new_plan()
            write_json(self.plan_path, plan)
        with open(self.plan_path, "r", encoding="utf-8") as fh:
            return normalize_plan(json.load(fh))

    def save_plan(self, plan: dict, handoff: bool = False) -> dict:
        with self.lock:
            plan = normalize_plan(plan)
            plan.setdefault("meta", {})["status"] = "ready" if handoff else "draft"
            plan["meta"]["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            write_json(self.plan_path, plan)
            if handoff:
                self.ready.set()
            return plan


class Handler(BaseHTTPRequestHandler):
    state: StudioState = None  # type: ignore
    server_version = "APBStudio/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[studio] %s - %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

    # ---------- helpers ----------
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Invalid request size.")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _read_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("文件为空或超过 25MB 限制。")
        return self.rfile.read(length)

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() in (".html", ".css", ".js", ".json", ".svg"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _safe_download(self, name: str) -> Path | None:
        target = (self.state.project_dir / name).resolve()
        try:
            target.relative_to(self.state.project_dir.resolve())
        except ValueError:
            return None
        return target

    # ---------- routes ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route in ("/", "/index.html"):
                self._serve_file(ASSETS_DIR / "studio.html")
                return
            if route == "/studio.css":
                self._serve_file(ASSETS_DIR / "studio.css")
                return
            if route == "/studio.js":
                self._serve_file(ASSETS_DIR / "studio.js")
                return
            if route == "/api/bootstrap":
                plan = self.state.load_plan()
                self._json({
                    "ok": True,
                    "plan": plan,
                    "planPath": str(self.state.plan_path),
                    "projectDir": str(self.state.project_dir),
                    "skillDir": str(SKILL_DIR),
                    "waitMode": self.state.wait_mode,
                    "modules": apb_core.load_modules(),
                    "tableStyles": apb_core.load_table_styles(),
                    "stylePresets": apb_core.load_style_presets(),
                    "summary": plan_summary(plan),
                })
                return
            if route == "/api/status":
                plan = self.state.load_plan()
                self._json({
                    "ok": True,
                    "status": plan.get("meta", {}).get("status", "draft"),
                    "planPath": str(self.state.plan_path),
                    "updatedAt": plan.get("meta", {}).get("updatedAt"),
                })
                return
            if route == "/api/download":
                query = urllib.parse.parse_qs(parsed.query)
                name = (query.get("file") or [""])[0]
                target = self._safe_download(urllib.parse.unquote(name))
                if target is None:
                    self._error("非法下载路径。", 403)
                    return
                self._serve_file(target)
                return
            if route == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            self.send_error(404, "Not found")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(str(exc), 500)

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/save":
                payload = self._read_json()
                plan = payload.get("plan") or payload
                handoff = bool(payload.get("handoff"))
                saved = self.state.save_plan(plan, handoff=handoff)
                self._json({"ok": True, "plan": saved, "summary": plan_summary(saved),
                            "handoff": handoff})
                return
            if route == "/api/build":
                payload = self._read_json()
                plan = payload.get("plan") or self.state.load_plan()
                plan = self.state.save_plan(plan, handoff=False)
                from docx_engine import build_docx
                title = plan.get("event", {}).get("title", "活动方案")
                filename = f"{sanitize_filename(title)}活动方案.docx"
                out_path = self.state.project_dir / filename
                build_docx(plan, out_path)
                plan.setdefault("meta", {})["status"] = "built"
                write_json(self.state.plan_path, plan)
                self.state.last_build = out_path
                self._json({
                    "ok": True,
                    "path": str(out_path),
                    "filename": out_path.name,
                    "download": f"/api/download?file={urllib.parse.quote(out_path.name)}",
                    "summary": plan_summary(plan),
                })
                return
            if route == "/api/import-style":
                raw = self._read_bytes()
                filename = self.headers.get("X-Filename", "template.docx")
                temp = self.state.project_dir / f".apb-import-{int(time.time() * 1000)}.docx"
                temp.write_bytes(raw)
                try:
                    from style_extract import extract_from_docx
                    profile = extract_from_docx(temp)
                finally:
                    try:
                        temp.unlink()
                    except OSError:
                        pass
                profile["source"]["file"] = urllib.parse.unquote(filename)
                self._json({"ok": True, "profile": profile})
                return
            if route == "/api/parse-style":
                payload = self._read_json()
                from style_extract import parse_style_text
                profile = parse_style_text(str(payload.get("text", "")))
                self._json({"ok": True, "profile": profile})
                return
            if route == "/api/sync-event":
                payload = self._read_json()
                plan = normalize_plan(payload.get("plan") or {})
                apply_event_bindings(plan, force=True)
                self._json({"ok": True, "plan": plan})
                return
            if route == "/api/validate":
                payload = self._read_json()
                plan = normalize_plan(payload.get("plan") or {})
                self._json({"ok": True, "result": validate_plan(plan)})
                return
            self.send_error(404, "Not found")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(str(exc), 500)


def run_studio(directory: Path, plan_name: str = "plan.json", host: str = "127.0.0.1",
               port: int = 0, open_browser: bool = False, wait: bool = False,
               wait_timeout: int = 1800, seed_title: str = "", seed_type: str = "",
               seed_brief: str = "", quiet: bool = False,
               on_url=None) -> int:
    """Start the Studio. `quiet` sends runtime logs to stderr (for MCP stdio)."""
    def log(message: str) -> None:
        print(message, file=sys.stderr if quiet else sys.stdout,
              flush=True)

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = (directory / plan_name).resolve()
    if not plan_path.exists():
        event = {}
        if seed_title:
            event["title"] = seed_title
        if seed_type:
            event["type"] = seed_type
        if seed_brief:
            event["brief"] = seed_brief
        plan = new_plan(event=event)
        write_json(plan_path, plan)

    state = StudioState(directory, plan_path, wait_mode=wait)
    Handler.state = state

    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"ERROR 无法启动本地服务：{exc}", file=sys.stderr)
        return 1
    httpd.daemon_threads = True
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}/"
    log(f"STUDIO {url}")
    log(f"PLAN {plan_path}")
    log("在浏览器中完成配置后点击“交给 Agent”；或在页面内直接生成 DOCX。")
    if on_url is not None:
        try:
            on_url(url, str(plan_path))
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        if wait:
            deadline = time.time() + max(30, int(wait_timeout))
            while time.time() < deadline:
                if state.ready.wait(timeout=0.5):
                    break
            if state.ready.is_set():
                log(f"READY {plan_path}")
                return 0
            print("TIMEOUT 未等到用户完成配置。", file=sys.stderr)
            return 2
        while thread.is_alive():
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        httpd.shutdown()
        httpd.server_close()
