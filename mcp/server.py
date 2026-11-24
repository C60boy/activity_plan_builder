#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Activity Plan Builder - zero-dependency MCP stdio server.

Works with any MCP client (Claude Desktop, Cursor, TRAE, etc.) through
newline-delimited JSON-RPC 2.0 on stdin/stdout.

Tools:
    list_modules, list_table_styles, create_plan, open_studio,
    wait_for_handoff, get_plan, import_school_style, build_docx, validate
"""
from __future__ import annotations

import copy
import json
import sys
import threading
import time
import traceback
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent
SKILL_DIR = MCP_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apb_core
from apb_core import (
    load_modules,
    load_table_styles,
    new_plan,
    normalize_plan,
    plan_summary,
    sanitize_filename,
    validate_plan,
    write_json,
)

try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

def _skill_version() -> str:
    path = SKILL_DIR / "VERSION"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "1.0.0"


SERVER_INFO = {"name": "activity-plan-builder", "version": _skill_version()}
PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}

_SERVERS: dict[str, dict] = {}
_SERVER_LOCK = threading.Lock()


def log(message: str) -> None:
    print(f"[apb-mcp] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _plan_file(args: dict, required: bool = True) -> Path:
    raw = args.get("planPath") or args.get("plan_path")
    if raw:
        path = Path(str(raw)).expanduser().resolve()
    else:
        directory = args.get("directory") or args.get("dir")
        if not directory:
            if required:
                raise ValueError("请提供 planPath，或提供 directory。")
            return Path()
        filename = args.get("filename") or "plan.json"
        path = (Path(str(directory)).expanduser().resolve() / filename).resolve()
    return path


def _read_plan(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"方案文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as fh:
        return normalize_plan(json.load(fh))


def _table_style_ids() -> set[str]:
    return {s["id"] for s in load_table_styles()["styles"]}


def _module_ids() -> set[str]:
    return {m["id"] for m in load_modules()["modules"]}


def _apply_profile(plan: dict, profile: dict) -> dict:
    from style_extract import merge_profile

    style_only = {
        key: value
        for key, value in profile.items()
        if key not in ("source", "tableStyleGuess", "evidence")
    }
    plan["style"] = merge_profile(plan.get("style") or apb_core.style_preset(), style_only)
    plan["styleRef"] = "school-import"
    if profile.get("source"):
        plan["style"]["source"] = copy.deepcopy(profile["source"])
    guess = profile.get("tableStyleGuess")
    if guess and guess in _table_style_ids():
        plan.setdefault("tableStyles", {}).setdefault("global", "gov-grid")
        plan["tableStyles"]["global"] = guess
        plan["style"]["tableStyleGuess"] = guess
    return plan


def _ok(payload: dict | list) -> dict:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload if isinstance(payload, dict) else {"items": payload},
        "isError": False,
    }


def _fail(message: str) -> dict:
    return {"content": [{"type": "text", "text": f"错误：{message}"}], "isError": True}


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
def tool_list_modules(args: dict) -> dict:
    data = load_modules()
    category = (args.get("category") or "").strip()
    modules = []
    for item in data["modules"]:
        if category and item.get("category") != category:
            continue
        modules.append({
            "id": item["id"],
            "title": item["title"],
            "category": item.get("category"),
            "description": item.get("description"),
            "badge": item.get("badge", ""),
            "defaultEnabled": bool(item.get("defaultEnabled")),
            "hasDefaultTable": bool(item.get("defaultTable")),
            "hasAttachments": bool(item.get("defaultAttachments")),
            "agentHint": item.get("agentHint", ""),
        })
    return _ok({"categories": data.get("categories", []), "modules": modules})


def tool_list_table_styles(args: dict) -> dict:
    data = load_table_styles()
    styles = [{
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description", ""),
        "tags": item.get("tags", []),
        "fontSizePt": item.get("fontSizePt"),
        "headerFill": (item.get("header") or {}).get("fill", ""),
        "zebra": bool((item.get("body") or {}).get("zebraFill")),
    } for item in data["styles"]]
    return _ok({"default": data.get("default"), "styles": styles})


def tool_create_plan(args: dict) -> dict:
    plan_path = _plan_file(args)
    if plan_path.exists() and not args.get("overwrite"):
        raise ValueError(f"方案已存在：{plan_path}。如需覆盖请设置 overwrite=true。")
    modules = args.get("modules") or None
    if modules is not None:
        unknown = [m for m in modules if m not in _module_ids()]
        if unknown:
            raise ValueError("未知模块 id：" + ", ".join(unknown))
    event = {
        "title": args.get("title") or "【活动名称】",
        "type": args.get("type") or "综合活动",
        "theme": args.get("theme") or "",
        "date": args.get("date") or "",
        "time": args.get("time") or "",
        "location": args.get("location") or "",
        "audience": args.get("audience") or "",
        "organizer": args.get("organizer") or "",
        "undertaker": args.get("undertaker") or "",
        "brief": args.get("brief") or "",
    }
    plan = new_plan(
        event=event,
        module_ids=modules,
        style_id=args.get("stylePreset") or "campus-sample",
        table_style_id=args.get("tableStyle") or "three-line",
        include_defaults=bool(args.get("includeDefaults", True)),
    )
    write_json(plan_path, plan)
    return _ok({
        "planPath": str(plan_path),
        "summary": plan_summary(plan),
        "next": "必须调用 open_studio 打开交互式配置台，等待用户在浏览器完成模块勾选、"
                "学校格式导入与表格样式选择（工具会阻塞等待，用户点击“交给 Agent”后自动返回）。",
    })


def _wait_handoff(plan_path: Path, timeout: float, interval: float) -> tuple[bool, dict | None]:
    """Poll until plan status is ready/built or timeout. Returns (done, plan)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if plan_path.exists():
            try:
                plan = _read_plan(plan_path)
                if str(plan.get("meta", {}).get("status", "draft")) in ("ready", "built"):
                    return True, plan
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(interval)
    return False, None


def tool_open_studio(args: dict) -> dict:
    from studio_server import run_studio

    plan_path = _plan_file(args)
    if not plan_path.exists():
        raise ValueError(f"方案文件不存在：{plan_path}。请先调用 create_plan。")
    wait_handoff = bool(args.get("waitForHandoff", True))
    timeout = max(10, min(int(args.get("timeoutSeconds") or 900), 3600))

    key = str(plan_path)
    with _SERVER_LOCK:
        existing = _SERVERS.get(key)
        if existing and existing["thread"].is_alive():
            url = existing["url"]
        else:
            existing = None
            url = None

    if url is None:
        ready = threading.Event()
        captured: dict = {}

        def on_url(url: str, plan: str) -> None:
            captured["url"] = url
            captured["planPath"] = plan
            ready.set()

        thread = threading.Thread(
            target=run_studio,
            kwargs={
                "directory": plan_path.parent,
                "plan_name": plan_path.name,
                "host": args.get("host") or "127.0.0.1",
                "port": int(args.get("port") or 0),
                "open_browser": bool(args.get("openBrowser", True)),
                "wait": False,
                "quiet": True,
                "on_url": on_url,
            },
            daemon=True,
            name="apb-studio",
        )
        thread.start()
        if not ready.wait(timeout=12):
            raise RuntimeError("Studio 启动超时，请检查端口是否被占用。")
        url = captured["url"]
        with _SERVER_LOCK:
            _SERVERS[key] = {"url": url, "thread": thread}

    if not wait_handoff:
        return _ok({
            "url": url,
            "planPath": key,
            "alreadyRunning": existing is not None,
            "next": "浏览器已打开（或已在运行）。请用户完成配置后，调用 wait_for_handoff 等待交接。",
        })

    done, plan = _wait_handoff(plan_path, timeout, max(0.5, float(args.get("pollSeconds") or 1.0)))
    if done:
        return _ok({
            "url": url,
            "planPath": key,
            "status": str(plan["meta"].get("status", "ready")),
            "summary": plan_summary(plan),
            "next": "用户已完成配置。用 get_plan 读取并补全内容，再调用 build_docx。",
        })
    return _ok({
        "url": url,
        "planPath": key,
        "status": "draft",
        "timedOut": True,
        "next": f"已等待 {timeout} 秒，用户尚未在 Studio 点击“交给 Agent”。"
                "Studio 仍在运行：请先询问用户是否还需要在浏览器里配置（可再次调用 "
                "wait_for_handoff 续接）；若浏览器没有自动打开，请把上面的 url 发给用户，"
                "让用户手动在浏览器打开。若 Studio 运行在远程/沙箱环境、用户无法访问该地址，"
                "说明交互界面不可用，改为直接生成：get_plan 读取内容、补全后 build_docx。",
    })


def tool_wait_for_handoff(args: dict) -> dict:
    plan_path = _plan_file(args)
    timeout = max(10, min(int(args.get("timeoutSeconds") or 600), 3600))
    interval = max(0.5, float(args.get("pollSeconds") or 1.0))
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        if plan_path.exists():
            try:
                plan = _read_plan(plan_path)
                last_status = str(plan.get("meta", {}).get("status", "draft"))
                if last_status in ("ready", "built"):
                    return _ok({
                        "planPath": str(plan_path),
                        "status": last_status,
                        "summary": plan_summary(plan),
                        "next": "方案已交回。用 get_plan 读取并补全内容，再调用 build_docx。",
                    })
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(interval)
    return _ok({
        "planPath": str(plan_path),
        "status": last_status or "unknown",
        "timedOut": True,
        "next": "用户可能仍在配置。可以先询问用户，或再次调用 wait_for_handoff。",
    })


def tool_get_plan(args: dict) -> dict:
    plan_path = _plan_file(args)
    plan = _read_plan(plan_path)
    return _ok({
        "planPath": str(plan_path),
        "plan": plan,
        "summary": plan_summary(plan),
        "validation": validate_plan(plan),
    })


def tool_import_school_style(args: dict) -> dict:
    from style_extract import extract_from_docx, parse_style_text

    docx_path = args.get("docxPath")
    text = args.get("text")
    profile = args.get("profile")
    if docx_path:
        path = Path(str(docx_path)).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"找不到 DOCX：{path}")
        profile = extract_from_docx(path)
    elif text:
        profile = parse_style_text(str(text))
    elif not isinstance(profile, dict):
        raise ValueError("请提供 docxPath、text 或 profile 之一。")

    plan_path_raw = args.get("applyToPlanPath") or args.get("planPath")
    applied = False
    if plan_path_raw:
        plan_path = Path(str(plan_path_raw)).expanduser().resolve()
        plan = _read_plan(plan_path)
        _apply_profile(plan, profile)
        write_json(plan_path, plan)
        applied = True

    return _ok({
        "profile": profile,
        "applied": applied,
        "planPath": str(Path(str(plan_path_raw)).expanduser().resolve()) if plan_path_raw else "",
        "next": "格式已应用到方案。" if applied else "如需写入方案，请传 applyToPlanPath。",
    })


def tool_build_docx(args: dict) -> dict:
    from docx_engine import build_docx

    plan_path = _plan_file(args, required=not isinstance(args.get("plan"), dict))
    if isinstance(args.get("plan"), dict):
        plan = normalize_plan(copy.deepcopy(args["plan"]))
    else:
        plan = _read_plan(plan_path)

    if args.get("outputPath"):
        out_path = Path(str(args["outputPath"])).expanduser().resolve()
    else:
        title = plan.get("event", {}).get("title") or "活动方案"
        out_path = plan_path.parent / f"{sanitize_filename(title)}活动方案.docx"

    style_override = args.get("styleOverride") if isinstance(args.get("styleOverride"), dict) else None
    build_docx(
        plan,
        out_path,
        style_override=style_override,
        table_style_override=args.get("tableStyle") or None,
    )
    result = validate_plan(plan)
    status = str(plan.get("meta", {}).get("status", "draft"))
    note = ""
    if status == "draft":
        note = ("注意：该方案未经用户在 Studio 中确认（状态仍为 draft）。"
                "如需交互式配置（模块勾选、学校格式、表格样式），应先调用 open_studio。")
    return _ok({
        "path": str(out_path),
        "filename": out_path.name,
        "summary": plan_summary(plan),
        "validation": result,
        "note": note,
    })


def tool_validate(args: dict) -> dict:
    if isinstance(args.get("plan"), dict):
        plan = normalize_plan(copy.deepcopy(args["plan"]))
        source = "inline"
    else:
        plan_path = _plan_file(args)
        plan = _read_plan(plan_path)
        source = str(plan_path)
    return _ok({"source": source, "result": validate_plan(plan)})


def tool_update(args: dict) -> dict:
    from updater import apply_update, current_version, update_from_url

    before = current_version(SKILL_DIR)
    url = args.get("url")
    zip_path = args.get("zipPath")
    backup = bool(args.get("backup", True))
    if url:
        result = update_from_url(SKILL_DIR, str(url), backup=backup)
    elif zip_path:
        result = apply_update(SKILL_DIR, Path(str(zip_path)).expanduser().resolve(), backup=backup)
    else:
        raise ValueError("请提供 url（如 GitHub Releases 的 zip 地址）或 zipPath（本地压缩包路径）。")
    result["before"] = before
    result["next"] = ("更新完成。当前 MCP 进程仍运行旧代码：请重启 MCP 客户端（或重新发起对话）"
                      "后生效；正在运行的 Studio 也需重新启动。")
    return _ok(result)


TOOLS = [
    {
        "name": "list_modules",
        "description": "列出活动方案可选章节模块（核心/推荐/进阶），含模块 id、说明与默认表格信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["core", "recommended", "advanced"],
                    "description": "可选：只返回某一类模块。"
                }
            },
            "additionalProperties": False
        },
        "annotations": {"title": "列出模块", "readOnlyHint": True},
    },
    {
        "name": "list_table_styles",
        "description": "列出 9 套预设表格样式（政府网格、三线表、深色表头、斑马纹、预算表等）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"title": "列出表格样式", "readOnlyHint": True},
    },
    {
        "name": "create_plan",
        "description": "在指定目录创建 plan.json（活动方案结构化文件），可预设活动信息与模块。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "方案目录，不存在会自动创建。"},
                "filename": {"type": "string", "description": "方案文件名，默认 plan.json。"},
                "title": {"type": "string", "description": "活动名称，如“联合研究生院元旦晚会”。"},
                "type": {"type": "string", "description": "活动类型，如 晚会/音乐节/升旗仪式/迎新活动。"},
                "theme": {"type": "string", "description": "活动主题。"},
                "date": {"type": "string", "description": "日期 YYYY-MM-DD。"},
                "time": {"type": "string", "description": "时段，如 19:00—21:30。"},
                "location": {"type": "string", "description": "活动地点。"},
                "audience": {"type": "string", "description": "活动对象与预计人数。"},
                "organizer": {"type": "string", "description": "主办单位。"},
                "undertaker": {"type": "string", "description": "承办单位。"},
                "brief": {"type": "string", "description": "3—5 句活动简述。"},
                "modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "模块 id 列表；留空使用核心 + 默认推荐模块。"
                },
                "stylePreset": {"type": "string", "description": "版式预设 id，默认 campus-sample。"},
                "tableStyle": {"type": "string", "description": "全局表格样式 id，默认 three-line。"},
                "includeDefaults": {"type": "boolean", "description": "是否带上默认推荐模块，默认 true。"},
                "overwrite": {"type": "boolean", "description": "是否覆盖已有方案，默认 false。"}
            },
            "required": ["directory"],
            "additionalProperties": False
        },
        "annotations": {"title": "创建方案", "destructiveHint": False},
    },
    {
        "name": "open_studio",
        "description": "启动本地交互式 Studio 并在浏览器打开，让用户勾选模块、导入学校字体格式、挑选表格样式。"
                       "默认阻塞等待：用户点击“交给 Agent”（或直接生成 DOCX）后本调用才返回。"
                       "生成活动方案时应先调用本工具，等返回后再继续；不要跳过。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "planPath": {"type": "string", "description": "plan.json 的绝对路径。"},
                "directory": {"type": "string", "description": "方案目录（与 filename 搭配）。"},
                "filename": {"type": "string", "description": "方案文件名，默认 plan.json。"},
                "port": {"type": "integer", "description": "端口，0 表示自动分配。"},
                "openBrowser": {"type": "boolean", "description": "是否自动打开浏览器，默认 true。"},
                "waitForHandoff": {"type": "boolean", "description": "是否阻塞等待用户完成配置，默认 true。"},
                "timeoutSeconds": {"type": "integer", "description": "最长等待秒数，默认 900。"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "打开配置台", "openWorldHint": False},
    },
    {
        "name": "wait_for_handoff",
        "description": "等待用户在 Studio 点击“交给 Agent”（或直接生成 DOCX），返回最新方案摘要。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "planPath": {"type": "string", "description": "plan.json 的绝对路径。"},
                "directory": {"type": "string", "description": "方案目录（与 filename 搭配）。"},
                "filename": {"type": "string", "description": "方案文件名，默认 plan.json。"},
                "timeoutSeconds": {"type": "integer", "description": "最长等待秒数，默认 600。"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "等待用户完成", "readOnlyHint": True},
    },
    {
        "name": "get_plan",
        "description": "读取 plan.json 全文、摘要与校验结果，用于补全内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "planPath": {"type": "string"},
                "directory": {"type": "string"},
                "filename": {"type": "string"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "读取方案", "readOnlyHint": True},
    },
    {
        "name": "import_school_style",
        "description": "从学校 DOCX 模板或文字版格式要求中提取版式，可一键写入方案。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "docxPath": {"type": "string", "description": "学校模板 DOCX 路径。"},
                "text": {"type": "string", "description": "文字版格式要求，如“正文仿宋_GB2312三号，行距28磅”。"},
                "profile": {"type": "object", "description": "已提取的格式 JSON。"},
                "applyToPlanPath": {"type": "string", "description": "要写入的 plan.json 路径。"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "导入学校格式"},
    },
    {
        "name": "build_docx",
        "description": "由 plan.json 生成符合学校格式的 DOCX，返回文件路径与校验结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "planPath": {"type": "string"},
                "directory": {"type": "string"},
                "filename": {"type": "string"},
                "plan": {"type": "object", "description": "也可直接传方案对象。"},
                "outputPath": {"type": "string", "description": "输出 DOCX 路径。"},
                "tableStyle": {"type": "string", "description": "强制覆盖全局表格样式 id。"},
                "styleOverride": {"type": "object", "description": "临时覆盖版式字段。"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "生成 DOCX"},
    },
    {
        "name": "validate",
        "description": "校验方案结构、占位符、预算合计与页数估算。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "planPath": {"type": "string"},
                "directory": {"type": "string"},
                "filename": {"type": "string"},
                "plan": {"type": "object"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "校验方案", "readOnlyHint": True},
    },
    {
        "name": "update",
        "description": "把本技能更新到新版本。提供更新包下载地址（如 GitHub Releases 的 zip）或本地 zip 路径，"
                       "更新后需重启 MCP 客户端生效。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "更新包 zip 下载地址，如 https://github.com/<user>/<repo>/releases/latest/download/activity-plan-builder-share.zip"},
                "zipPath": {"type": "string", "description": "本地更新包 zip 路径。"},
                "backup": {"type": "boolean", "description": "更新前是否备份当前版本，默认 true。"}
            },
            "additionalProperties": False
        },
        "annotations": {"title": "更新技能", "destructiveHint": False},
    },
]

HANDLERS = {
    "list_modules": tool_list_modules,
    "list_table_styles": tool_list_table_styles,
    "create_plan": tool_create_plan,
    "open_studio": tool_open_studio,
    "wait_for_handoff": tool_wait_for_handoff,
    "get_plan": tool_get_plan,
    "import_school_style": tool_import_school_style,
    "build_docx": tool_build_docx,
    "validate": tool_validate,
    "update": tool_update,
}

INSTRUCTIONS = (
    "Activity Plan Builder：生成中国高校大型活动方案。交互式流程是首选且默认流程，"
    "用户要求生成活动方案时，必须先调用 open_studio（该工具会打开本地浏览器并阻塞，"
    "等待用户在 Studio 完成模块勾选、学校格式导入与表格样式选择后点击“交给 Agent”），"
    "收到返回后再读取方案、补全内容、调用 build_docx。禁止在用户完成配置前直接生成文件。"
    "只有在以下情况才可跳过交互：用户明确说“不用打开界面/直接生成”、open_studio 返回"
    "“Studio 运行在远程环境，无法在本机打开浏览器”等无法访问的信息。流程："
    "1) create_plan 创建方案；2) open_studio 阻塞等待用户配置；3) get_plan 读取 plan.json，"
    "按模块补全 blocks；4) build_docx 生成 DOCX。若客户端中断了 open_studio 调用，"
    "Studio 仍在后台运行，用 wait_for_handoff 续接。补全内容时只写有依据的信息，"
    "人名、电话、审批编号一律用【待定】，不得编造预算金额与单位名称。"
)


# --------------------------------------------------------------------------
# JSON-RPC
# --------------------------------------------------------------------------
def handle_request(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message

    if is_notification:
        return None
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": requested if requested in PROTOCOLS else "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": f"Unknown tool: {name}"},
            }
        try:
            result = handler(arguments)
        except Exception as exc:  # noqa: BLE001
            log(traceback.format_exc())
            result = _fail(str(exc))
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def send(payload) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    log(f"started, skill dir: {SKILL_DIR}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            send({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": f"Parse error: {exc}"}})
            continue
        if isinstance(message, list):
            responses = [r for r in (handle_request(m) for m in message) if r]
            if responses:
                send(responses)
            continue
        response = handle_request(message)
        if response is not None:
            send(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
