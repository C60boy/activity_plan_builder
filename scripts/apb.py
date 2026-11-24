#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Activity Plan Builder CLI.

Typical flow:
    python scripts/apb.py new --dir ./my-plan --title "元旦晚会"
    python scripts/apb.py studio --dir ./my-plan --open --wait
    python scripts/apb.py build ./my-plan/plan.json -o ./my-plan/元旦晚会活动方案.docx
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import apb_core
from apb_core import (
    load_modules,
    load_style_presets,
    load_table_styles,
    new_plan,
    plan_summary,
    sanitize_filename,
    validate_plan,
    write_json,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _plan_path(args) -> Path:
    directory = Path(getattr(args, "dir", ".") or ".").resolve()
    plan_name = getattr(args, "out", None) or getattr(args, "plan", None) or "plan.json"
    return (directory / plan_name).resolve()


def _load_plan(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Plan not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return apb_core.normalize_plan(json.load(fh))


def cmd_new(args) -> int:
    plan_path = _plan_path(args)
    if plan_path.exists() and not args.force:
        raise SystemExit(f"Plan already exists: {plan_path}\nUse --force to overwrite.")
    event = {
        "title": args.title or "【活动名称】",
        "type": args.type or "综合活动",
        "theme": args.theme or "",
        "date": args.date or "",
        "time": args.time or "",
        "location": args.location or "",
        "audience": args.audience or "",
        "organizer": args.organizer or "",
        "undertaker": args.undertaker or "",
        "brief": args.brief or "",
    }
    module_ids = None
    if args.modules:
        module_ids = [x.strip() for x in args.modules.split(",") if x.strip()]
        for mid in module_ids:
            if mid not in apb_core.module_catalog():
                raise SystemExit(f"Unknown module: {mid}")
    plan = new_plan(event=event, module_ids=module_ids, style_id=args.style,
                    table_style_id=args.table_style)
    write_json(plan_path, plan)
    print(f"CREATED {plan_path}")
    print(f"Modules: {len([m for m in plan['modules'] if m.get('enabled', True)])}")
    print(f"Style: {plan.get('styleRef')}")
    print("Next: python scripts/apb.py studio --dir \"%s\" --open --wait" % plan_path.parent)
    return 0


def cmd_build(args) -> int:
    plan_path = Path(args.plan).resolve()
    plan = _load_plan(plan_path)
    style_override = None
    if args.style_json:
        with open(args.style_json, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        style_override = raw.get("style", raw)
    out = args.output or str(plan_path.parent / f"{sanitize_filename(plan['event'].get('title', '活动方案'))}.docx")
    out_path = Path(out).resolve()
    from docx_engine import build_docx
    build_docx(plan, out_path, style_override=style_override, table_style_override=args.table_style)
    summary = plan_summary(plan)
    print(f"BUILT {out_path}")
    print(f"Modules: {summary['stats']['modules']}  Placeholders: {summary['stats']['placeholders']}  "
          f"Estimated pages: {summary['stats']['estimatedPages']}")
    for warning in summary["warnings"]:
        print(f"WARN {warning}")
    for error in summary["errors"]:
        print(f"ERROR {error}")
    return 0 if summary["ok"] else 1


def cmd_import_style(args) -> int:
    from style_extract import extract_from_docx
    profile = extract_from_docx(args.docx)
    out = Path(args.output).resolve()
    write_json(out, profile)
    print(f"STYLE {out}")
    conf = profile.get("source", {}).get("confidence", {})
    print("Confidence: " + ", ".join(f"{k}={v}" for k, v in conf.items()))
    if profile.get("tableStyleGuess"):
        print(f"Table style guess: {profile['tableStyleGuess']}")
    return 0


def cmd_parse_style(args) -> int:
    from style_extract import parse_style_text
    text = args.text or ""
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit("Provide --text or --text-file.")
    profile = parse_style_text(text)
    out = Path(args.output).resolve() if args.output else None
    if out:
        write_json(out, profile)
        print(f"STYLE {out}")
    else:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args) -> int:
    plan = _load_plan(Path(args.plan).resolve())
    result = validate_plan(plan)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("OK" if result["ok"] else "FAILED")
        for error in result["errors"]:
            print(f"ERROR {error}")
        for warning in result["warnings"]:
            print(f"WARN {warning}")
        stats = result["stats"]
        print(f"Modules: {stats['modules']}  Placeholders: {stats['placeholders']}  "
              f"Estimated pages: {stats['estimatedPages']}")
    return 0 if result["ok"] else 1


def cmd_info(args) -> int:
    plan = _load_plan(Path(args.plan).resolve())
    print(json.dumps(plan_summary(plan), ensure_ascii=False, indent=2))
    return 0


def cmd_list(args) -> int:
    what = args.what
    if what == "modules":
        data = load_modules()
        for item in data["modules"]:
            flag = "*" if item.get("defaultEnabled") else " "
            print(f"{flag} {item['category']:<11} {item['id']:<14} {item['title']}")
    elif what == "tables":
        data = load_table_styles()
        for item in data["styles"]:
            print(f"{item['id']:<16} {item['name']:<8} {item['description']}")
    elif what == "styles":
        data = load_style_presets()
        for item in data["presets"]:
            print(f"{item['id']:<16} {item['name']:<12} {item['description']}")
    else:
        raise SystemExit(f"Unknown list target: {what}")
    return 0


def cmd_studio(args) -> int:
    from studio_server import run_studio
    return run_studio(
        directory=Path(args.dir).resolve() if args.dir else Path.cwd(),
        plan_name=args.plan or "plan.json",
        host=args.host,
        port=args.port,
        open_browser=args.open,
        wait=args.wait,
        wait_timeout=args.wait_timeout,
        seed_title=args.title,
        seed_type=args.type,
        seed_brief=args.brief,
    )


def cmd_version(args) -> int:
    import updater
    skill_dir = Path(__file__).resolve().parent.parent
    print(f"activity-plan-builder {updater.current_version(skill_dir)}")
    print(f"Skill dir: {skill_dir}")
    return 0


def cmd_update(args) -> int:
    import updater
    skill_dir = Path(__file__).resolve().parent.parent
    backup = not args.no_backup
    if args.url:
        result = updater.update_from_url(skill_dir, args.url, backup=backup)
    elif args.zip:
        result = updater.apply_update(skill_dir, Path(args.zip).resolve(), backup=backup)
    else:
        raise SystemExit("请提供 --url 或 --zip。\n"
                         "示例：python scripts/apb.py update --url "
                         "https://github.com/<user>/<repo>/releases/latest/download/activity-plan-builder-share.zip")
    print(f"UPDATED {result['from']} -> {result['to']}")
    print(f"Skill dir: {result['target']}")
    if result["backup"]:
        print(f"Backup: {result['backup']}")
    print("提示：正在运行的 Studio 需重启后生效；MCP 客户端需重连（重启客户端或对话）。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apb", description="大学大型活动方案生成器")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="创建空白方案 JSON")
    p_new.add_argument("--dir", default=".", help="方案目录")
    p_new.add_argument("--out", help="输出文件名，默认 plan.json")
    p_new.add_argument("--plan", help=argparse.SUPPRESS)
    p_new.add_argument("--title", default="", help="活动名称")
    p_new.add_argument("--type", default="综合活动", help="活动类型，如晚会/音乐节/升旗/迎新")
    p_new.add_argument("--theme", default="", help="活动主题")
    p_new.add_argument("--date", default="", help="活动日期 YYYY-MM-DD")
    p_new.add_argument("--time", default="", help="活动时段，如 19:00—21:30")
    p_new.add_argument("--location", default="", help="活动地点")
    p_new.add_argument("--audience", default="", help="活动对象")
    p_new.add_argument("--organizer", default="", help="主办单位")
    p_new.add_argument("--undertaker", default="", help="承办单位")
    p_new.add_argument("--brief", default="", help="活动简述")
    p_new.add_argument("--modules", default="", help="逗号分隔的模块 id；留空使用默认模块")
    p_new.add_argument("--style", default="campus-sample", help="格式预设 id")
    p_new.add_argument("--table-style", default="three-line", help="表格样式 id")
    p_new.add_argument("--force", action="store_true", help="覆盖已有方案")
    p_new.set_defaults(func=cmd_new)

    p_build = sub.add_parser("build", help="由方案 JSON 生成 DOCX")
    p_build.add_argument("plan", help="方案 JSON 路径")
    p_build.add_argument("-o", "--output", help="输出 DOCX 路径")
    p_build.add_argument("--style-json", help="学校格式 JSON 路径")
    p_build.add_argument("--table-style", help="强制使用某个表格样式 id")
    p_build.set_defaults(func=cmd_build)

    p_import = sub.add_parser("import-style", help="从学校 DOCX 模板提取格式")
    p_import.add_argument("docx", help="学校模板 DOCX 路径")
    p_import.add_argument("-o", "--output", default="school-profile.json", help="输出 JSON 路径")
    p_import.set_defaults(func=cmd_import_style)

    p_parse = sub.add_parser("parse-style", help="解析文字版格式要求")
    p_parse.add_argument("--text", default="", help="格式要求文字")
    p_parse.add_argument("--text-file", default="", help="格式要求文本文件")
    p_parse.add_argument("-o", "--output", help="输出 JSON 路径")
    p_parse.set_defaults(func=cmd_parse_style)

    p_validate = sub.add_parser("validate", help="校验方案完整性")
    p_validate.add_argument("plan", help="方案 JSON 路径")
    p_validate.add_argument("--json", action="store_true", help="输出 JSON")
    p_validate.set_defaults(func=cmd_validate)

    p_info = sub.add_parser("info", help="查看方案摘要")
    p_info.add_argument("plan", help="方案 JSON 路径")
    p_info.set_defaults(func=cmd_info)

    p_list = sub.add_parser("list", help="列出模块、表格样式或格式预设")
    p_list.add_argument("what", choices=["modules", "tables", "styles"])
    p_list.set_defaults(func=cmd_list)

    p_studio = sub.add_parser("studio", help="启动本地交互式配置台")
    p_studio.add_argument("--dir", default=".", help="方案目录")
    p_studio.add_argument("--plan", default="plan.json", help="方案文件名")
    p_studio.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_studio.add_argument("--port", type=int, default=0, help="端口，0 表示自动分配")
    p_studio.add_argument("--open", action="store_true", help="自动打开浏览器")
    p_studio.add_argument("--wait", action="store_true", help="等待用户点击“交给 Agent”后退出")
    p_studio.add_argument("--wait-timeout", type=int, default=1800, help="等待秒数")
    p_studio.add_argument("--title", default="", help="新建方案时的活动名称")
    p_studio.add_argument("--type", default="", help="新建方案时的活动类型")
    p_studio.add_argument("--brief", default="", help="新建方案时的活动简述")
    p_studio.set_defaults(func=cmd_studio)

    p_version = sub.add_parser("version", help="查看技能版本")
    p_version.set_defaults(func=cmd_version)

    p_update = sub.add_parser("update", help="从压缩包或 URL 更新技能")
    p_update.add_argument("--zip", help="本地更新包 zip 路径")
    p_update.add_argument("--url", help="更新包下载地址，如 GitHub Releases 的 zip")
    p_update.add_argument("--no-backup", action="store_true", help="更新前不备份当前版本")
    p_update.set_defaults(func=cmd_update)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
