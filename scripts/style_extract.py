# -*- coding: utf-8 -*-
"""Extract a school style fingerprint from a DOCX template, or parse a text spec."""
from __future__ import annotations

import copy
import re
from collections import Counter
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Length

from apb_core import style_preset

CN_SIZE_PT = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
    "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
}
H1_RE = re.compile(r"^\s*[一二三四五六七八九十百]+[、.．]")
H2_RE = re.compile(r"^\s*[（(][一二三四五六七八九十]+[）)]")


def _mode(values):
    values = [v for v in values if v not in (None, "", ())]
    if not values:
        return None, 0
    value, count = Counter(values).most_common(1)[0]
    return value, count


def _east_asia(run) -> str | None:
    rpr = run._element.rPr
    if rpr is not None and rpr.rFonts is not None:
        return rpr.rFonts.get(qn("w:eastAsia"))
    return None


def _ascii(run) -> str | None:
    rpr = run._element.rPr
    if rpr is not None and rpr.rFonts is not None:
        return rpr.rFonts.get(qn("w:ascii"))
    return run.font.name


def _first_run(paragraph):
    for run in paragraph.runs:
        if run.text.strip():
            return run
    return None


def _run_font(paragraph):
    run = _first_run(paragraph)
    if run is None:
        return None
    size = run.font.size.pt if run.font.size else None
    return {
        "eastAsia": _east_asia(run) or run.font.name,
        "ascii": _ascii(run) or "Times New Roman",
        "sizePt": size,
        "bold": bool(run.bold) if run.bold is not None else None,
        "color": None,
    }


def _line_spacing(paragraph):
    value = paragraph.paragraph_format.line_spacing
    if value is None:
        return None
    if isinstance(value, Length):
        return {"mode": "exact", "pt": round(float(value.pt), 1)}
    try:
        return {"mode": "multiple", "value": round(float(value), 2)}
    except (TypeError, ValueError):
        return None


def _indent_chars(paragraph, body_size: float | None) -> float | None:
    indent = paragraph.paragraph_format.first_line_indent
    if indent is None or not body_size:
        return None
    return round(float(indent.pt) / float(body_size), 1)


def _confidence(count: int, total: int) -> str:
    if total <= 0:
        return "low"
    ratio = count / total
    if ratio >= 0.6 and count >= 3:
        return "high"
    if ratio >= 0.35 or count >= 2:
        return "medium"
    return "low"


def _cell_shading(cell):
    tcpr = cell._tc.tcPr
    if tcpr is None:
        return None
    shd = tcpr.find(qn("w:shd"))
    if shd is None:
        return None
    return shd.get(qn("w:fill"))


def _table_borders(tbl):
    tblpr = tbl._tbl.tblPr
    borders = tblpr.find(qn("w:tblBorders"))
    if borders is None:
        if tbl.style is not None and "Grid" in (tbl.style.name or ""):
            return {"insideV": True, "insideH": True, "style": "grid"}
        return None
    result = {}
    for tag in ("top", "bottom", "insideH", "insideV"):
        el = borders.find(qn(f"w:{tag}"))
        if el is None:
            result[tag] = False
            continue
        result[tag] = (el.get(qn("w:val")) or "nil") not in ("nil", "none", "0")
    if not result.get("insideV") and not result.get("insideH"):
        result["style"] = "three-line"
    elif not result.get("insideV"):
        result["style"] = "horizontal-only"
    else:
        result["style"] = "grid"
    return result


def _guess_table_style(profile: dict) -> tuple[str, str]:
    header_fill = (profile.get("_evidence", {}).get("headerFill") or "").upper()
    borders = profile.get("_evidence", {}).get("borders") or {}
    if header_fill in ("22252B", "1F2937", "000000"):
        return "dark-header", "medium"
    if header_fill in ("E8F0F7", "DCEAF5"):
        return "zebra-blue", "medium"
    if header_fill in ("EFE9DC", "F5F0E4"):
        return "budget", "medium"
    if borders.get("style") == "three-line":
        return "three-line", "high"
    if borders.get("style") == "horizontal-only":
        return "horizontal-only", "high"
    if header_fill in ("F2F2F2", "EFEFEF", "FAFAFA"):
        return "zebra-gray", "medium"
    return "gov-grid", "low"


def extract_from_docx(path: str | Path) -> dict:
    path = Path(path)
    doc = Document(str(path))
    profile = style_preset("campus-sample")
    evidence = {"file": path.name, "counts": {}, "headerFill": None, "borders": None}
    conf = {}

    sec = doc.sections[0]
    profile["page"] = {
        "size": "A4",
        "marginsCm": {
            "top": round(sec.top_margin.cm, 2),
            "bottom": round(sec.bottom_margin.cm, 2),
            "left": round(sec.left_margin.cm, 2),
            "right": round(sec.right_margin.cm, 2),
        },
    }
    conf["page"] = "high"
    evidence["counts"]["page"] = 1

    paragraphs = [p for p in doc.paragraphs if p.text.strip()]

    # ---- title ----
    title_candidates = []
    for p in paragraphs:
        font = _run_font(p)
        if not font or not font.get("sizePt"):
            continue
        if font["sizePt"] >= 18:
            centered = str(p.alignment).startswith("CENTER")
            title_candidates.append((font["sizePt"] + (2 if centered else 0), p, font))
    if title_candidates:
        title_candidates.sort(key=lambda x: x[0], reverse=True)
        _, p, font = title_candidates[0]
        profile["title"] = {
            **profile["title"],
            "eastAsia": font["eastAsia"] or profile["title"]["eastAsia"],
            "ascii": font["ascii"] or profile["title"]["ascii"],
            "sizePt": float(font["sizePt"]),
            "bold": bool(font["bold"]),
            "align": "center",
        }
        spacing = _line_spacing(p)
        if spacing:
            profile["title"]["lineSpacing"] = spacing
        conf["title"] = "high" if len(title_candidates) >= 2 else "medium"
        evidence["counts"]["title"] = len(title_candidates)
    else:
        conf["title"] = "low"

    # ---- h1 / h2 ----
    h1_fonts, h1_spacings = [], []
    h2_fonts = []
    for p in paragraphs:
        text = p.text.strip()
        font = _run_font(p)
        if not font:
            continue
        style_name = (p.style.name or "") if p.style is not None else ""
        if H1_RE.match(text) or "一级标题" in style_name or style_name == "Heading 1":
            if text and not H1_RE.match(text) and len(text) > 40:
                continue
            h1_fonts.append((font["eastAsia"], font["sizePt"], bool(font["bold"])))
            spacing = _line_spacing(p)
            if spacing:
                h1_spacings.append((spacing.get("mode"), spacing.get("pt") or spacing.get("value")))
        if H2_RE.match(text) or "二级标题" in style_name or style_name == "Heading 2":
            if len(text) <= 50:
                h2_fonts.append((font["eastAsia"], font["sizePt"], bool(font["bold"])))
    font, count = _mode(h1_fonts)
    if font:
        profile["h1"] = {
            **profile["h1"],
            "eastAsia": font[0] or profile["h1"]["eastAsia"],
            "sizePt": float(font[1]) if font[1] else profile["h1"]["sizePt"],
            "bold": bool(font[2]),
        }
        conf["h1"] = _confidence(count, len(h1_fonts))
        evidence["counts"]["h1"] = count
    else:
        conf["h1"] = "low"
    font2, count2 = _mode(h2_fonts)
    if font2:
        profile["h2"] = {
            **profile["h2"],
            "eastAsia": font2[0] or profile["h2"]["eastAsia"],
            "sizePt": float(font2[1]) if font2[1] else profile["h2"]["sizePt"],
            "bold": bool(font2[2]),
        }
        conf["h2"] = _confidence(count2, len(h2_fonts))
        evidence["counts"]["h2"] = count2
    else:
        conf["h2"] = "low"

    # ---- body ----
    body_fonts, body_spacings, body_indents, body_aligns, body_sizes = [], [], [], [], []
    for p in paragraphs:
        text = p.text.strip()
        if len(text) < 15 or H1_RE.match(text) or H2_RE.match(text):
            continue
        style_name = (p.style.name or "") if p.style is not None else ""
        font = _run_font(p)
        if not font or not font.get("sizePt") or font["sizePt"] >= 18:
            continue
        if style_name.startswith("Heading") or "标题" in style_name:
            continue
        body_fonts.append((font["eastAsia"], font["sizePt"]))
        body_sizes.append(font["sizePt"])
        spacing = _line_spacing(p)
        if spacing:
            body_spacings.append((spacing.get("mode"), spacing.get("pt") or spacing.get("value")))
        indent = _indent_chars(p, font["sizePt"])
        if indent is not None:
            body_indents.append(indent)
        if p.alignment is not None:
            body_aligns.append(str(p.alignment).split(" ")[0].lower())
    font, count = _mode(body_fonts)
    if font:
        profile["body"] = {
            **profile["body"],
            "eastAsia": font[0] or profile["body"]["eastAsia"],
            "sizePt": float(font[1]),
        }
        conf["body"] = _confidence(count, len(body_fonts))
        evidence["counts"]["body"] = count
    else:
        conf["body"] = "low"
    spacing, scount = _mode(body_spacings)
    if spacing:
        if spacing[0] == "exact":
            profile["body"]["lineSpacing"] = {"mode": "exact", "pt": float(spacing[1])}
        else:
            profile["body"]["lineSpacing"] = {"mode": "multiple", "value": float(spacing[1])}
        conf["lineSpacing"] = _confidence(scount, len(body_spacings))
    else:
        conf["lineSpacing"] = "low"
    indent, icount = _mode(body_indents)
    if indent is not None:
        profile["body"]["firstLineIndentChars"] = max(0.0, float(indent))
        conf["indent"] = _confidence(icount, len(body_indents))
    else:
        conf["indent"] = "low"
    align, acount = _mode(body_aligns)
    if align:
        mapping = {"justify": "justify", "left": "left", "center": "center", "right": "right"}
        profile["body"]["align"] = mapping.get(align, "justify")
        conf["align"] = _confidence(acount, len(body_aligns))
    else:
        conf["align"] = "low"

    # ---- table ----
    if doc.tables:
        tbl = doc.tables[0]
        if tbl.rows:
            header_cell = tbl.rows[0].cells[0]
            header_run = None
            for p in header_cell.paragraphs:
                header_run = _first_run(p)
                if header_run is not None:
                    break
            if header_run is not None:
                size = header_run.font.size.pt if header_run.font.size else profile["table"]["fontSizePt"]
                east = _east_asia(header_run) or profile["table"]["headerEastAsia"]
                profile["table"] = {
                    **profile["table"],
                    "headerEastAsia": east,
                    "fontSizePt": float(size),
                    "headerSizePt": float(size),
                }
                conf["table"] = "medium"
            fill = _cell_shading(header_cell)
            evidence["headerFill"] = fill
        borders = _table_borders(tbl)
        evidence["borders"] = borders
        style_id, style_conf = _guess_table_style(evidence)
        profile["tableStyleGuess"] = style_id
        conf["tableStyle"] = style_conf

    # ---- footer ----
    footer_text = "".join(p.text for p in sec.footer.paragraphs).strip()
    if footer_text or "PAGE" in sec.footer._element.xml:
        profile["footer"]["enabled"] = True
        footer_run = None
        for p in sec.footer.paragraphs:
            footer_run = _first_run(p)
            if footer_run is not None:
                break
        if footer_run is not None and footer_run.font.size:
            profile["footer"]["sizePt"] = float(footer_run.font.size.pt)
            profile["footer"]["eastAsia"] = _east_asia(footer_run) or profile["footer"]["eastAsia"]
    else:
        profile["footer"]["enabled"] = False

    profile["source"] = {
        "kind": "docx",
        "file": path.name,
        "confidence": conf,
        "evidence": {
            "paragraphs": len(paragraphs),
            "tables": len(doc.tables),
            "h1Samples": len(h1_fonts),
            "h2Samples": len(h2_fonts),
            "bodySamples": len(body_fonts),
            "headerFill": evidence.get("headerFill"),
            "borders": evidence.get("borders"),
        },
    }
    return profile


def _font_size_from(token: str) -> float | None:
    token = token.strip()
    for name, pt in CN_SIZE_PT.items():
        if name in token:
            return float(pt)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:磅|pt|PT)", token)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)", token)
    return float(m.group(1)) if m else None


def _find_font(text: str, labels: list[str]) -> tuple[str | None, float | None]:
    for label in labels:
        pattern = rf"{label}[^。；;\n]{{0,40}}"
        m = re.search(pattern, text)
        if not m:
            continue
        segment = m.group(0)
        size = _font_size_from(segment)
        font = None
        for name in ("方正小标宋简体", "方正小标宋", "仿宋_GB2312", "仿宋GB2312", "仿宋", "黑体",
                     "楷体_GB2312", "楷体GB2312", "楷体", "宋体", "微软雅黑"):
            if name in segment:
                font = name
                break
        if font or size:
            return font, size
    return None, None


def parse_style_text(text: str) -> dict:
    profile = style_preset("campus-sample")
    matches = {}
    conf = {}

    font, size = _find_font(text, ["标题", "大标题", "方案标题"])
    if font or size:
        if font:
            profile["title"]["eastAsia"] = font
        if size:
            profile["title"]["sizePt"] = size
        matches["title"] = {"font": font, "sizePt": size}
        conf["title"] = "medium"

    font, size = _find_font(text, ["一级标题", "正文一级标题"])
    if font or size:
        if font:
            profile["h1"]["eastAsia"] = font
        if size:
            profile["h1"]["sizePt"] = size
        matches["h1"] = {"font": font, "sizePt": size}
        conf["h1"] = "medium"

    font, size = _find_font(text, ["二级标题", "正文二级标题"])
    if font or size:
        if font:
            profile["h2"]["eastAsia"] = font
        if size:
            profile["h2"]["sizePt"] = size
        matches["h2"] = {"font": font, "sizePt": size}
        conf["h2"] = "medium"

    font, size = _find_font(text, ["正文", "正文字体"])
    if font or size:
        if font:
            profile["body"]["eastAsia"] = font
        if size:
            profile["body"]["sizePt"] = size
        matches["body"] = {"font": font, "sizePt": size}
        conf["body"] = "medium"

    m = re.search(r"行距[^。；;\n]{0,20}?(\d+(?:\.\d+)?)\s*(磅|pt|PT|倍)", text)
    if m:
        value = float(m.group(1))
        if m.group(2) == "倍":
            profile["body"]["lineSpacing"] = {"mode": "multiple", "value": value}
        else:
            profile["body"]["lineSpacing"] = {"mode": "exact", "pt": value}
        matches["lineSpacing"] = profile["body"]["lineSpacing"]
        conf["lineSpacing"] = "medium"

    m = re.search(r"首行缩进[^。；;\n]{0,10}?(\d+(?:\.\d+)?)\s*字符", text)
    if m:
        profile["body"]["firstLineIndentChars"] = float(m.group(1))
        matches["indent"] = float(m.group(1))
        conf["indent"] = "medium"

    m = re.search(r"上[^\d]{0,4}(\d+(?:\.\d+)?)[^\d]{0,3}(?:厘米|cm).*?下[^\d]{0,4}(\d+(?:\.\d+)?).*?"
                  r"左[^\d]{0,4}(\d+(?:\.\d+)?).*?右[^\d]{0,4}(\d+(?:\.\d+)?)", text, re.S)
    if m:
        profile["page"]["marginsCm"] = {
            "top": float(m.group(1)), "bottom": float(m.group(2)),
            "left": float(m.group(3)), "right": float(m.group(4)),
        }
        matches["page"] = profile["page"]["marginsCm"]
        conf["page"] = "medium"

    profile["source"] = {
        "kind": "text",
        "file": "",
        "confidence": conf,
        "evidence": {"matched": list(matches.keys()), "textLength": len(text)},
    }
    return profile


def merge_profile(base: dict, override: dict) -> dict:
    """Deep-merge an imported profile onto a base profile."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key == "source":
            result["source"] = value
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_profile(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
