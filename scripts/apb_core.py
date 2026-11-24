# -*- coding: utf-8 -*-
"""Activity Plan Builder - shared core: assets, plan model, validation."""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
MODULES_PATH = ASSETS_DIR / "modules.json"
TABLE_STYLES_PATH = ASSETS_DIR / "table-styles.json"
STYLE_PRESETS_PATH = ASSETS_DIR / "style-presets.json"
SCHEMA_VERSION = "1.0"

PLACEHOLDER_RE = re.compile(r"【[^】]*】")
CN_DIGITS = "零一二三四五六七八九"


def load_json(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_modules() -> dict:
    return load_json(MODULES_PATH)


def load_table_styles() -> dict:
    return load_json(TABLE_STYLES_PATH)


def load_style_presets() -> dict:
    return load_json(STYLE_PRESETS_PATH)


def module_catalog() -> dict[str, dict]:
    data = load_modules()
    return {m["id"]: m for m in data["modules"]}


def style_preset(style_id: str | None = None) -> dict:
    data = load_style_presets()
    target = style_id or data.get("default")
    for item in data["presets"]:
        if item["id"] == target:
            return copy.deepcopy(item)
    return copy.deepcopy(data["presets"][0])


def table_style_catalog() -> dict[str, dict]:
    data = load_table_styles()
    return {s["id"]: s for s in data["styles"]}


def table_style(style_id: str | None = None) -> dict:
    data = load_table_styles()
    target = style_id or data.get("default")
    for item in data["styles"]:
        if item["id"] == target:
            return copy.deepcopy(item)
    return copy.deepcopy(data["styles"][0])


def cn_number(n: int) -> str:
    """1 -> 一, 10 -> 十, 21 -> 二十一 (supports 1-99)."""
    if n <= 0:
        return str(n)
    if n < 10:
        return CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + CN_DIGITS[n % 10]
    tens, ones = divmod(n, 10)
    return CN_DIGITS[tens] + "十" + (CN_DIGITS[ones] if ones else "")


def format_date_cn(iso_date: str) -> tuple[str, str]:
    """Return (Chinese date, weekday) for YYYY-MM-DD, or ('', '')."""
    if not iso_date:
        return "", ""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", iso_date.strip())
    if not m:
        return "", ""
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return "", ""
    week = "一二三四五六日"[d.weekday()]
    return f"{d.year}年{d.month}月{d.day}日", f"星期{week}"


def current_month_cn(today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    return f"{today.year}年{today.month}月"


def default_event(event: dict | None = None) -> dict:
    base = {
        "title": "【活动名称】",
        "theme": "",
        "type": "综合活动",
        "date": "",
        "dateText": "",
        "weekday": "",
        "time": "",
        "location": "",
        "audience": "",
        "organizer": "",
        "undertaker": "",
        "coOrganizer": "",
        "scale": "",
        "contact": {"name": "", "phone": "", "email": ""},
        "brief": "",
        "titleLines": [],
    }
    if event:
        for key, value in event.items():
            if key == "contact" and isinstance(value, dict):
                base["contact"].update(value)
            elif value not in (None, ""):
                base[key] = value
    if base["date"]:
        date_text, weekday = format_date_cn(base["date"])
        if date_text:
            base["dateText"] = date_text
            base["weekday"] = weekday
    elif not base["dateText"]:
        base["weekday"] = ""
    return base


def _event_lines(plan: dict) -> list[str]:
    event = plan.get("event", {})
    lines = []
    if event.get("organizer"):
        lines.append(str(event["organizer"]))
    if event.get("theme"):
        lines.append(str(event["theme"]))
    if event.get("title"):
        lines.append(str(event["title"]))
    return lines


def _event_mirror_blocks(event: dict) -> dict[str, list[dict]]:
    """Build the basic-info mirror blocks for core modules from event fields."""
    date_text = event.get("dateText") or ""
    weekday = event.get("weekday") or ""
    time_text = event.get("time") or ""
    date_line = date_text
    if weekday:
        date_line += f"（{weekday}）"
    if time_text:
        date_line += time_text
    org_lines = []
    if event.get("organizer"):
        org_lines.append(f"主办单位：{event['organizer']}")
    if event.get("undertaker"):
        org_lines.append(f"承办单位：{event['undertaker']}")
    if event.get("coOrganizer"):
        org_lines.append(f"协办单位：{event['coOrganizer']}")
    sig_org = event.get("undertaker") or event.get("organizer") or "【待补充：发文单位】"
    sig_date = current_month_cn()
    m = re.match(r"^(\d{4})年(\d{1,2})月", date_text)
    if m:
        sig_date = f"{m.group(1)}年{m.group(2)}月"
    return {
        "theme": [{"type": "paragraph", "text": event.get("theme") or "【待补充：活动主题】"}],
        "time_place": [
            {"type": "paragraph", "text": f"时间：{date_line or '【待补充：活动时间】'}"},
            {"type": "paragraph", "text": f"地点：{event.get('location') or '【待补充：活动地点】'}"},
        ],
        "audience": [{"type": "paragraph", "text": event.get("audience") or "【待补充：活动对象与预计人数】"}],
        "organization": [{"type": "paragraph", "text": line} for line in org_lines],
        "signature": [
            {"type": "paragraph", "text": sig_org},
            {"type": "paragraph", "text": sig_date},
        ],
    }


def apply_event_bindings(plan: dict, force: bool = False) -> dict:
    """Push structured event fields into the corresponding core modules.

    Smart refresh: a mirror module is overwritten when (a) force=True,
    (b) its blocks are still placeholders, or (c) its blocks are unchanged
    since the last sync (tracked in eventSyncSnapshot). Modules the user or
    Agent edited by hand are left untouched.
    """
    event = plan.get("event", {})
    by_id = {m["id"]: m for m in plan.get("modules", [])}
    wanted = _event_mirror_blocks(event)
    for module_id, blocks in wanted.items():
        mod = by_id.get(module_id)
        if not mod:
            continue
        if not blocks:
            continue
        current = mod.get("blocks", [])
        snapshot = mod.get("eventSyncSnapshot")
        placeholder_only = all(
            (not str(b.get("text", "")).strip())
            or PLACEHOLDER_RE.search(str(b.get("text", "")))
            for b in current
            if b.get("type") != "table"
        )
        unchanged_since_sync = snapshot is not None and snapshot == current
        if force or placeholder_only or unchanged_since_sync:
            mod["blocks"] = copy.deepcopy(blocks)
            mod["eventSyncSnapshot"] = copy.deepcopy(blocks)
    return plan


def _fill_table_placeholders(table: dict) -> dict:
    table = copy.deepcopy(table)
    table.setdefault("rows", [])
    table.setdefault("headers", [])
    table.setdefault("kind", "generic")
    return table


def new_module(module_id: str, order: int, enabled: bool = True) -> dict:
    catalog = module_catalog()
    if module_id not in catalog:
        raise KeyError(f"Unknown module: {module_id}")
    src = copy.deepcopy(catalog[module_id])
    mod = {
        "id": src["id"],
        "title": src["title"],
        "enabled": enabled,
        "order": order,
        "blocks": copy.deepcopy(src.get("defaultBlocks", [])),
        "needsAgent": True,
        "note": "",
    }
    if src.get("defaultTable"):
        mod["table"] = _fill_table_placeholders(src["defaultTable"])
    if src.get("defaultAttachments"):
        mod["attachments"] = copy.deepcopy(src["defaultAttachments"])
    return mod


def new_plan(event: dict | None = None, module_ids: list[str] | None = None,
             style_id: str = "campus-sample", table_style_id: str = "three-line",
             include_defaults: bool = True) -> dict:
    catalog = load_modules()["modules"]
    event = default_event(event)
    selected: list[str] = []
    for m in catalog:
        if module_ids is not None:
            if m["id"] in module_ids:
                selected.append(m["id"])
        else:
            if m["category"] == "core":
                selected.append(m["id"])
            elif include_defaults and m.get("defaultEnabled"):
                selected.append(m["id"])
    modules = [new_module(mid, i + 1, True) for i, mid in enumerate(selected)]
    plan = {
        "meta": {
            "schemaVersion": SCHEMA_VERSION,
            "status": "draft",
            "createdAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "updatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "generator": "activity-plan-builder",
        },
        "event": event,
        "style": style_preset(style_id),
        "styleRef": style_id,
        "tableStyles": {
            "global": table_style_id,
            "byKind": {
                "schedule": "",
                "budget": "budget",
                "division": "",
                "materials": "",
                "promotion": "",
                "timeline": "timeline",
                "risk": "",
                "awards": "",
                "form": "form",
                "program": ""
            }
        },
        "modules": modules,
        "attachments": []
    }
    apply_event_bindings(plan)
    normalize_plan(plan)
    return plan


def normalize_plan(plan: dict) -> dict:
    """Fill missing fields, dedupe modules, keep core modules, renumber."""
    plan.setdefault("meta", {})
    plan["meta"].setdefault("schemaVersion", SCHEMA_VERSION)
    plan["meta"].setdefault("status", "draft")
    plan["meta"].setdefault("createdAt", _dt.datetime.now().isoformat(timespec="seconds"))
    plan["meta"]["updatedAt"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["event"] = default_event(plan.get("event"))
    if not plan.get("style"):
        plan["style"] = style_preset(plan.get("styleRef"))
    plan.setdefault("tableStyles", {"global": "three-line", "byKind": {}, "enabled": True})
    plan["tableStyles"].setdefault("global", "three-line")
    plan["tableStyles"].setdefault("byKind", {})
    plan["tableStyles"].setdefault("enabled", True)

    catalog = module_catalog()
    existing = {m.get("id"): m for m in plan.get("modules", []) if m.get("id") in catalog}
    ordered: list[dict] = []
    for m in plan.get("modules", []):
        mid = m.get("id")
        if mid not in catalog or mid in {x["id"] for x in ordered}:
            continue
        src = catalog[mid]
        m.setdefault("title", src["title"])
        m.setdefault("enabled", True)
        m.setdefault("blocks", copy.deepcopy(src.get("defaultBlocks", [])))
        m.setdefault("needsAgent", True)
        m.setdefault("note", "")
        if src.get("defaultTable") and "table" not in m:
            m["table"] = _fill_table_placeholders(src["defaultTable"])
        if src.get("defaultAttachments") and "attachments" not in m:
            m["attachments"] = copy.deepcopy(src["defaultAttachments"])
        m["order"] = int(m.get("order", len(ordered) + 1))
        ordered.append(m)

    # core modules are mandatory
    for mid, src in catalog.items():
        if src["category"] == "core" and mid not in existing:
            ordered.append(new_module(mid, len(ordered) + 1, True))
    ordered.sort(key=lambda x: (x.get("order", 999), catalog[x["id"]]["category"] != "core"))
    for i, m in enumerate(ordered, 1):
        m["order"] = i
        m["enabled"] = True if catalog[m["id"]]["category"] == "core" else bool(m.get("enabled", True))
    plan["modules"] = ordered
    plan.setdefault("attachments", [])
    return plan


def compute_budget(table: dict) -> tuple[dict, float]:
    """Recalculate 小计 and total for budget tables. Returns (table, total)."""
    table = copy.deepcopy(table)
    headers = [str(h) for h in table.get("headers", [])]
    def find(*keys: str) -> int:
        for key in keys:
            for i, h in enumerate(headers):
                if key in h:
                    return i
        return -1
    price_i = find("单价", "价格")
    qty_i = find("数量")
    sub_i = find("小计", "金额")
    if sub_i < 0:
        sub_i = -1
    total = 0.0
    rows = table.get("rows", [])
    for row in rows:
        def num(idx: int) -> float | None:
            if idx < 0 or idx >= len(row):
                return None
            text = str(row[idx]).replace(",", "").replace("元", "").strip()
            text = PLACEHOLDER_RE.sub("", text).strip()
            try:
                return float(text)
            except ValueError:
                return None
        price, qty = num(price_i), num(qty_i)
        if price is not None and qty is not None and sub_i >= 0:
            sub = round(price * qty, 2)
            row[sub_i] = f"{sub:.2f}"
            total += sub
        else:
            sub = num(sub_i) if sub_i >= 0 else None
            if sub:
                total += sub
    table["totalAmount"] = round(total, 2)
    return table, round(total, 2)


def finalize_plan(plan: dict) -> dict:
    plan = normalize_plan(plan)
    # Smart refresh: keep event-derived modules (time/place/organization/…) in
    # sync with event fields, but never overwrite hand-edited content.
    apply_event_bindings(plan, force=False)
    for mod in plan["modules"]:
        if mod.get("table") and mod["table"].get("kind") == "budget":
            mod["table"], _ = compute_budget(mod["table"])
    return plan


def resolve_style(plan: dict, override: dict | None = None) -> dict:
    style = copy.deepcopy(plan.get("style") or style_preset())
    if override:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(style.get(key), dict):
                style[key] = {**style[key], **copy.deepcopy(value)}
            else:
                style[key] = copy.deepcopy(value)
    return style


def resolve_table_style(plan: dict, kind: str) -> dict:
    mapping = (plan.get("tableStyles") or {}).get("byKind") or {}
    style_id = mapping.get(kind) or (plan.get("tableStyles") or {}).get("global") or "gov-grid"
    return table_style(style_id)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip().strip(".")
    return name[:120] or "活动方案"


def estimate_pages(plan: dict) -> float:
    chars = 0
    tables = 0
    for mod in plan.get("modules", []):
        if not mod.get("enabled", True):
            continue
        for block in mod.get("blocks", []):
            if block.get("type") == "paragraph":
                chars += len(str(block.get("text", "")))
            elif block.get("type") == "list":
                chars += sum(len(str(x)) for x in block.get("items", []))
            elif block.get("type") == "table":
                tables += 1
        if mod.get("table"):
            tables += 1
        tables += len(mod.get("attachments", []))
    return round(max(1.0, chars / 680 + tables * 0.55 + len(plan.get("modules", [])) * 0.08), 1)


def validate_plan(plan: dict) -> dict:
    plan = normalize_plan(copy.deepcopy(plan))
    errors: list[str] = []
    warnings: list[str] = []
    placeholders: list[str] = []

    event = plan.get("event", {})
    if not event.get("title") or PLACEHOLDER_RE.search(str(event.get("title", ""))):
        warnings.append("活动名称尚未填写完整。")
    if not event.get("location"):
        warnings.append("活动地点为空，建议补充到具体场地。")
    if not event.get("audience"):
        warnings.append("活动对象为空。")
    if not event.get("organizer"):
        warnings.append("主办单位为空。")

    seen = set()
    for mod in plan.get("modules", []):
        if not mod.get("enabled", True):
            continue
        if mod["id"] in seen:
            errors.append(f"模块重复：{mod.get('title')}")
        seen.add(mod["id"])
        has_content = bool(mod.get("blocks")) or bool(mod.get("table")) or bool(mod.get("attachments"))
        if not has_content:
            errors.append(f"模块“{mod.get('title')}”没有内容。")
        for block in mod.get("blocks", []):
            texts = []
            if block.get("type") == "paragraph":
                texts = [block.get("text", "")]
            elif block.get("type") == "list":
                texts = block.get("items", [])
            elif block.get("type") == "subheading":
                texts = [block.get("text", "")]
            for text in texts:
                for ph in PLACEHOLDER_RE.findall(str(text)):
                    placeholders.append(ph)
        if mod.get("table"):
            for row in mod["table"].get("rows", []):
                for cell in row:
                    for ph in PLACEHOLDER_RE.findall(str(cell)):
                        placeholders.append(ph)
            if mod["table"].get("kind") == "budget":
                _, total = compute_budget(mod["table"])
                if total <= 0:
                    warnings.append("预算合计为 0，请检查单价与数量。")
        for att in mod.get("attachments", []):
            for row in att.get("table", {}).get("rows", []):
                for cell in row:
                    for ph in PLACEHOLDER_RE.findall(str(cell)):
                        placeholders.append(ph)

    if placeholders:
        warnings.append(f"仍有 {len(placeholders)} 处【待补充】占位符，建议生成前处理。")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "modules": sum(1 for m in plan["modules"] if m.get("enabled", True)),
            "placeholders": len(placeholders),
            "estimatedPages": estimate_pages(plan),
        }
    }


def plan_summary(plan: dict) -> dict:
    status = validate_plan(plan)
    return {
        "title": plan.get("event", {}).get("title", ""),
        "type": plan.get("event", {}).get("type", ""),
        "date": plan.get("event", {}).get("dateText", ""),
        "location": plan.get("event", {}).get("location", ""),
        "modules": [
            {"id": m["id"], "title": m.get("title"), "enabled": m.get("enabled", True), "order": m.get("order")}
            for m in plan.get("modules", [])
        ],
        "status": plan.get("meta", {}).get("status", "draft"),
        **status,
    }


def write_json(path: str | os.PathLike, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path
