# -*- coding: utf-8 -*-
"""DOCX engine for the Activity Plan Builder."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from apb_core import (
    PLACEHOLDER_RE,
    cn_number,
    compute_budget,
    finalize_plan,
    resolve_style,
    resolve_table_style,
    sanitize_filename,
)

ALIGN_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def _rgb(color: str | None):
    if not color:
        return None
    try:
        return RGBColor.from_string(str(color).replace("#", "").upper())
    except Exception:
        return None


def set_run_font(run, east_asia: str, ascii_font: str | None, size_pt: float,
                 bold: bool | None = None, color: str | None = None) -> None:
    run.font.name = ascii_font or east_asia
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), east_asia or "")
    if ascii_font:
        rfonts.set(qn("w:ascii"), ascii_font)
        rfonts.set(qn("w:hAnsi"), ascii_font)
    if size_pt:
        run.font.size = Pt(float(size_pt))
    if bold is not None:
        run.bold = bool(bold)
    rgb = _rgb(color)
    if rgb is not None:
        run.font.color.rgb = rgb


def set_para_format(paragraph, cfg: dict, first_line_chars: float | None = None,
                    first_line_size: float | None = None) -> None:
    pf = paragraph.paragraph_format
    align = cfg.get("align")
    if align in ALIGN_MAP:
        pf.alignment = ALIGN_MAP[align]
    spacing = cfg.get("lineSpacing") or {}
    if spacing.get("mode") == "exact" and spacing.get("pt"):
        pf.line_spacing = Pt(float(spacing["pt"]))
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    elif spacing.get("mode") == "multiple" and spacing.get("value"):
        pf.line_spacing = float(spacing["value"])
    if cfg.get("spaceBeforePt") is not None:
        pf.space_before = Pt(float(cfg["spaceBeforePt"]))
    if cfg.get("spaceAfterPt") is not None:
        pf.space_after = Pt(float(cfg["spaceAfterPt"]))
    pf.widow_control = True
    if first_line_chars and first_line_chars > 0:
        set_first_line_chars(paragraph, first_line_chars, first_line_size or 16)


def set_first_line_chars(paragraph, chars: float, font_size_pt: float) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:firstLineChars"), str(int(chars * 100)))
    ind.set(qn("w:firstLine"), str(int(font_size_pt * chars * 20)))


def _add_text(paragraph, text: str, cfg: dict, bold: bool | None = None,
              east_override: str | None = None, size_override: float | None = None,
              color: str | None = None) -> None:
    run = paragraph.add_run(str(text))
    set_run_font(
        run,
        east_override or cfg.get("eastAsia", "仿宋_GB2312"),
        cfg.get("ascii", "Times New Roman"),
        size_override or cfg.get("sizePt", 16),
        bold if bold is not None else cfg.get("bold", False),
        color or cfg.get("color"),
    )


def _body_paragraph(doc, text: str, style: dict, indent: bool = True):
    body = style["body"]
    p = doc.add_paragraph()
    set_para_format(p, body, body.get("firstLineIndentChars", 2) if indent else 0, body.get("sizePt", 16))
    _add_text(p, text, body)
    return p


def _h1(doc, text: str, style: dict):
    cfg = style["h1"]
    p = doc.add_paragraph()
    set_para_format(p, cfg)
    p.paragraph_format.keep_with_next = True
    _add_text(p, text, cfg)
    return p


def _h2(doc, text: str, style: dict):
    cfg = style["h2"]
    p = doc.add_paragraph()
    set_para_format(p, cfg)
    p.paragraph_format.keep_with_next = True
    _add_text(p, text, cfg)
    return p


def _list_paragraph(doc, text: str, index: int | None, style: dict):
    body = style["body"]
    p = doc.add_paragraph()
    set_para_format(p, body, body.get("firstLineIndentChars", 2), body.get("sizePt", 16))
    if index is not None:
        prefix = f"{index}."
        run = p.add_run(prefix)
        set_run_font(run, body["eastAsia"], body.get("ascii"), body.get("sizePt", 16), True)
    _add_text(p, text, body)
    return p


def _shade(cell, fill: str | None) -> None:
    if not fill:
        return
    tcpr = cell._tc.get_or_add_tcPr()
    shd = tcpr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcpr.append(shd)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.replace("#", "").upper())


def _cell_margins(cell, padding_cm) -> None:
    top, side = (padding_cm or [0.10, 0.15])[:2]
    tcpr = cell._tc.get_or_add_tcPr()
    mar = tcpr.find(qn("w:tcMar"))
    if mar is None:
        mar = OxmlElement("w:tcMar")
        tcpr.append(mar)
    for tag, value in (("top", top), ("bottom", top), ("left", side), ("right", side)):
        el = mar.find(qn(f"w:{tag}"))
        if el is None:
            el = OxmlElement(f"w:{tag}")
            mar.append(el)
        el.set(qn("w:w"), str(int(float(value) * 567)))
        el.set(qn("w:type"), "dxa")


def _table_borders(table, style: dict) -> None:
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    mapping = {
        "top": "top", "left": "left", "bottom": "bottom", "right": "right",
        "insideH": "insideH", "insideV": "insideV",
    }
    spec = style.get("borders") or {}
    for key, tag in mapping.items():
        item = spec.get(key)
        el = OxmlElement(f"w:{tag}")
        if not item or item.get("val") in (None, "nil", "none"):
            el.set(qn("w:val"), "nil")
            el.set(qn("w:sz"), "0")
            el.set(qn("w:space"), "0")
        else:
            el.set(qn("w:val"), item.get("val", "single"))
            el.set(qn("w:sz"), str(int(item.get("sz", 4))))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), str(item.get("color", "000000")).replace("#", "").upper())
        borders.append(el)
    old = tblpr.find(qn("w:tblBorders"))
    if old is not None:
        tblpr.remove(old)
    anchor = tblpr.find(qn("w:tblLayout"))
    if anchor is None:
        anchor = tblpr.find(qn("w:tblCellMar"))
    if anchor is None:
        anchor = tblpr.find(qn("w:tblLook"))
    if anchor is not None:
        anchor.addprevious(borders)
    else:
        tblpr.append(borders)


def _cell_bottom_border(cell, item: dict | None) -> None:
    if not item:
        return
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), item.get("val", "single"))
    bottom.set(qn("w:sz"), str(int(item.get("sz", 8))))
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), str(item.get("color", "000000")).replace("#", "").upper())
    borders.append(bottom)


def _header_repeat(row) -> None:
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def _cant_split(row) -> None:
    trpr = row._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:cantSplit"))


def _row_height(row, cm: float | None) -> None:
    if not cm:
        return
    trpr = row._tr.get_or_add_trPr()
    height = OxmlElement("w:trHeight")
    height.set(qn("w:val"), str(int(float(cm) * 567)))
    height.set(qn("w:hRule"), "atLeast")
    trpr.append(height)


def _write_cell(cell, text: str, style: dict, profile: dict, is_header: bool = False,
                is_total: bool = False, is_title: bool = False, is_first_col: bool = False,
                numeric: bool = False, row_index: int = 0) -> None:
    text = "" if text is None else str(text)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _cell_margins(cell, style.get("cellPaddingCm"))
    paragraph = cell.paragraphs[0]
    paragraph.clear() if hasattr(paragraph, "clear") else None
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = Pt(float((profile.get("table") or {}).get("lineSpacingPt", 20)))
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY

    table_cfg = profile.get("table") or {}
    east = table_cfg.get("fontEastAsia", "仿宋_GB2312")
    size = style.get("fontSizePt", table_cfg.get("fontSizePt", 12))
    bold = False
    color = style.get("body", {}).get("color", "1F1F1F")
    align = style.get("body", {}).get("align", "left")
    fill = None

    if is_title:
        east = table_cfg.get("headerEastAsia", "黑体")
        size = (style.get("titleRow") or {}).get("fontSizePt", size)
        bold = bool((style.get("titleRow") or {}).get("bold", True))
        align = "center"
        fill = (style.get("titleRow") or {}).get("fill")
        color = (style.get("titleRow") or {}).get("color", color)
    elif is_header:
        east = (style.get("header") or {}).get("eastAsia") or table_cfg.get("headerEastAsia", "黑体")
        size = table_cfg.get("headerSizePt", size)
        bold = bool((style.get("header") or {}).get("bold", True))
        align = (style.get("header") or {}).get("align", "center")
        fill = (style.get("header") or {}).get("fill")
        color = (style.get("header") or {}).get("color", color)
    else:
        if is_total:
            bold = bool((style.get("totalRow") or {}).get("bold", True))
            fill = (style.get("totalRow") or {}).get("fill")
            align = "center" if not numeric else "right"
        elif is_first_col:
            first = style.get("firstCol") or {}
            bold = bool(first.get("bold", False))
            fill = first.get("fill")
            align = first.get("align", align)
            color = first.get("color", color)
        elif numeric:
            align = style.get("numericAlign", "right")
        zebra = (style.get("body") or {}).get("zebraFill")
        if zebra and row_index % 2 == 1:
            fill = zebra
    paragraph.alignment = ALIGN_MAP.get(align, WD_ALIGN_PARAGRAPH.LEFT)
    if text:
        run = paragraph.add_run(text)
        set_run_font(run, east, table_cfg.get("ascii", "Times New Roman"), size, bold, color)
    _shade(cell, fill)


def _format_money(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"{int(round(value))}元"
    return f"{value:.2f}元"


def add_table(doc, spec: dict, plan: dict, profile: dict, style_override: dict | None = None):
    spec = copy.deepcopy(spec or {})
    headers = [str(h) for h in spec.get("headers", [])]
    rows = [list(r) for r in spec.get("rows", [])]
    if not headers and not rows:
        return None
    ncols = max([len(headers)] + [len(r) for r in rows] + [1])
    for r in rows:
        while len(r) < ncols:
            r.append("")
    while len(headers) < ncols:
        headers.append("")

    kind = spec.get("kind", "generic")
    style = style_override or resolve_table_style(plan, kind)
    title = spec.get("title")
    is_budget = kind == "budget" and spec.get("total")
    total_amount = 0.0
    if is_budget:
        spec, total_amount = compute_budget(spec)
        rows = [list(r) for r in spec.get("rows", [])]
        for r in rows:
            while len(r) < ncols:
                r.append("")

    nrows = len(rows) + (1 if headers and any(h.strip() for h in headers) else 0)
    nrows += 1 if title else 0
    nrows += 1 if is_budget else 0
    table = doc.add_table(rows=nrows, cols=ncols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tblpr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    _table_borders(table, style)

    available = 21.0 - float(profile.get("page", {}).get("marginsCm", {}).get("left", 3.17)) \
        - float(profile.get("page", {}).get("marginsCm", {}).get("right", 3.17))
    widths = spec.get("widthsCm") or []
    if len(widths) != ncols or not all(widths):
        widths = [available / ncols] * ncols
    scale = available / sum(float(w) for w in widths) if sum(float(w) for w in widths) else 1
    widths = [float(w) * scale for w in widths]
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            cell.width = Cm(widths[i])

    merges = spec.get("merges") or []
    ranges = []
    if title:
        ranges.append((0, 0, 0, ncols - 1))
    for m in merges:
        r, c = int(m.get("r", 0)), int(m.get("c", 0))
        rz, cz = int(m.get("rowspan", 1)), int(m.get("colspan", 1))
        offset = 1 if title else 0
        ranges.append((r + offset, c, r + offset + rz - 1, c + cz - 1))
    if is_budget:
        total_r = nrows - 1
        headers_no_title = headers
        amount_col = ncols - 1
        for i, h in enumerate(headers_no_title):
            if "小计" in h or "金额" in h:
                amount_col = i
                break
        ranges.append((total_r, 0, total_r, max(0, amount_col - 1)))
        ranges.append((total_r, amount_col, total_r, ncols - 1))

    covered = set()
    for (r1, c1, r2, c2) in ranges:
        r1, c1 = max(0, r1), max(0, c1)
        r2, c2 = min(nrows - 1, r2), min(ncols - 1, c2)
        if r2 < r1 or c2 < c1:
            continue
        table.cell(r1, c1).merge(table.cell(r2, c2))
        for rr in range(r1, r2 + 1):
            for cc in range(c1, c2 + 1):
                if (rr, cc) != (r1, c1):
                    covered.add((rr, cc))

    row_cursor = 0
    if title:
        cell = table.cell(0, 0)
        _write_cell(cell, title, style, profile, is_title=True, row_index=-1)
        _row_height(table.rows[0], 1.0)
        row_cursor = 1

    header_row_index = None
    if headers and any(h.strip() for h in headers):
        header_row_index = row_cursor
        for c, text in enumerate(headers):
            if (row_cursor, c) in covered:
                continue
            _write_cell(table.cell(row_cursor, c), text, style, profile, is_header=True,
                        is_first_col=(c == 0), row_index=-1)
            if style.get("headerBottom"):
                _cell_bottom_border(table.cell(row_cursor, c), style["headerBottom"])
        _header_repeat(table.rows[row_cursor])
        _cant_split(table.rows[row_cursor])
        _row_height(table.rows[row_cursor], 0.85)
        row_cursor += 1

    numeric_cols = set(int(x) for x in spec.get("numericColumns", []) if str(x).isdigit())
    for c, h in enumerate(headers):
        if any(k in h for k in ("单价", "数量", "小计", "金额", "费用")):
            numeric_cols.add(c)

    for ri, row_data in enumerate(rows):
        tr = table.rows[row_cursor + ri]
        _cant_split(tr)
        for c in range(ncols):
            if (row_cursor + ri, c) in covered:
                continue
            _write_cell(
                table.cell(row_cursor + ri, c),
                row_data[c] if c < len(row_data) else "",
                style, profile,
                is_first_col=(c == 0),
                numeric=(c in numeric_cols and c > 0),
                row_index=ri,
            )
    row_cursor += len(rows)

    if is_budget:
        total_r = row_cursor
        amount_col = ncols - 1
        for i, h in enumerate(headers):
            if "小计" in h or "金额" in h:
                amount_col = i
                break
        label_cell = table.cell(total_r, 0)
        value_cell = table.cell(total_r, amount_col)
        _write_cell(label_cell, f"{spec.get('totalLabel', '总计')}：", style, profile,
                    is_total=True, row_index=-1)
        _write_cell(value_cell, _format_money(total_amount), style, profile,
                    is_total=True, numeric=True, row_index=-1)
        label_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _row_height(table.rows[total_r], 0.85)

    if style.get("rowHeightCm"):
        for row in table.rows:
            _row_height(row, style["rowHeightCm"])

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(6)
    return table


def render_blocks(doc, plan: dict, mod: dict, profile: dict) -> None:
    for block in mod.get("blocks", []):
        btype = block.get("type")
        if btype == "paragraph":
            _body_paragraph(doc, block.get("text", ""), profile)
        elif btype == "subheading":
            _h2(doc, block.get("text", ""), profile)
        elif btype == "list":
            ordered = block.get("ordered", True)
            for i, item in enumerate(block.get("items", []), 1):
                _list_paragraph(doc, item, i if ordered else None, profile)
        elif btype == "note":
            note = copy.deepcopy(profile["body"])
            note.update({"eastAsia": "楷体_GB2312", "sizePt": 14, "color": "444444"})
            p = doc.add_paragraph()
            set_para_format(p, note, 2, 14)
            _add_text(p, block.get("text", ""), note)
        elif btype == "table" and block.get("table") and _tables_enabled(plan):
            add_table(doc, block["table"], plan, profile)
        elif btype == "pagebreak":
            doc.add_page_break()


def _add_page_field(paragraph, font_name: str, size_pt: float) -> None:
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    rfonts.set(qn("w:eastAsia"), font_name)
    rpr.append(rfonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(float(size_pt) * 2)))
    rpr.append(sz)
    run.append(rpr)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def setup_page(doc, profile: dict) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    margins = profile.get("page", {}).get("marginsCm", {})
    section.top_margin = Cm(float(margins.get("top", 2.54)))
    section.bottom_margin = Cm(float(margins.get("bottom", 2.54)))
    section.left_margin = Cm(float(margins.get("left", 3.17)))
    section.right_margin = Cm(float(margins.get("right", 3.17)))
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.5)
    footer_cfg = profile.get("footer") or {}
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if footer_cfg.get("enabled"):
        fmt = footer_cfg.get("format", "— {page} —")
        before, _, after = fmt.partition("{page}")
        font = footer_cfg.get("eastAsia", "宋体")
        size = footer_cfg.get("sizePt", 14)
        if before:
            run = p.add_run(before)
            set_run_font(run, font, "Times New Roman", size, False, "000000")
        _add_page_field(p, font, size)
        if after:
            run = p.add_run(after)
            set_run_font(run, font, "Times New Roman", size, False, "000000")


def add_title(doc, plan: dict, profile: dict) -> None:
    event = plan.get("event", {})
    lines = list(event.get("titleLines") or [])
    if not lines:
        title = (event.get("title") or "").strip() or "活动方案"
        if "方案" not in title and "策划" not in title:
            title += "活动方案"
        theme = (event.get("theme") or "").strip()
        seen = set()
        organizer = (event.get("organizer") or "").strip()
        if organizer and not PLACEHOLDER_RE.search(organizer):
            seen.add(organizer)
            lines.append(organizer)
        if theme and theme not in title and theme not in seen and not PLACEHOLDER_RE.search(theme):
            seen.add(theme)
            lines.append(theme)
        if title not in seen:
            lines.append(title)
    cfg = profile["title"]
    for i, line in enumerate(lines):
        p = doc.add_paragraph()
        set_para_format(p, cfg)
        p.paragraph_format.keep_with_next = i < len(lines) - 1
        _add_text(p, line, cfg)
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(10)


def add_signature(doc, plan: dict, profile: dict) -> None:
    sig = next((m for m in plan["modules"] if m["id"] == "signature" and m.get("enabled", True)), None)
    if not sig:
        return
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(24)
    spacer.paragraph_format.space_after = Pt(0)
    lines = []
    for block in sig.get("blocks", []):
        if block.get("type") == "paragraph" and str(block.get("text", "")).strip():
            lines.append(str(block["text"]).strip())
    if not lines:
        return
    body = copy.deepcopy(profile["body"])
    body["align"] = "right"
    for line in lines:
        p = doc.add_paragraph()
        set_para_format(p, body, 0, body.get("sizePt", 16))
        _add_text(p, line, body)


def _tables_enabled(plan: dict) -> bool:
    return (plan.get("tableStyles") or {}).get("enabled", True) is not False


def add_attachments(doc, plan: dict, profile: dict) -> None:
    if not _tables_enabled(plan):
        return
    mod = next((m for m in plan["modules"] if m["id"] == "attachment" and m.get("enabled", True)), None)
    attachments = []
    if mod:
        attachments.extend(mod.get("attachments", []))
    attachments.extend(plan.get("attachments", []) or [])
    seen = set()
    unique = []
    for att in attachments:
        key = att.get("id") or att.get("title")
        if key in seen:
            continue
        seen.add(key)
        unique.append(att)
    if not unique:
        return
    title_cfg = copy.deepcopy(profile["title"])
    title_cfg["sizePt"] = 22
    title_cfg["spaceBeforePt"] = 0
    title_cfg["spaceAfterPt"] = 6
    sub_cfg = copy.deepcopy(profile["body"])
    sub_cfg.update({"align": "center", "eastAsia": "楷体_GB2312", "sizePt": 14, "firstLineIndentChars": 0})
    for i, att in enumerate(unique, 1):
        doc.add_page_break()
        label = doc.add_paragraph()
        label_cfg = copy.deepcopy(profile["h1"])
        label_cfg["align"] = "left"
        set_para_format(label, label_cfg)
        _add_text(label, f"附件{cn_number(i)}", label_cfg)
        p = doc.add_paragraph()
        set_para_format(p, title_cfg)
        _add_text(p, att.get("title", ""), title_cfg)
        if att.get("subtitle"):
            sp = doc.add_paragraph()
            set_para_format(sp, sub_cfg, 0, 14)
            _add_text(sp, att["subtitle"], sub_cfg)
        table_spec = att.get("table")
        if table_spec:
            add_table(doc, table_spec, plan, profile)
        for block in att.get("blocks", []) or []:
            if block.get("type") == "paragraph":
                _body_paragraph(doc, block.get("text", ""), profile)


def build_docx(plan: dict, out_path: str | Path, style_override: dict | None = None,
               table_style_override: str | None = None) -> Path:
    plan = finalize_plan(copy.deepcopy(plan))
    profile = resolve_style(plan, style_override)
    if table_style_override:
        plan.setdefault("tableStyles", {})["global"] = table_style_override

    doc = Document()
    setup_page(doc, profile)
    normal = doc.styles["Normal"]
    normal.font.name = profile["body"].get("ascii", "Times New Roman")
    normal.font.size = Pt(float(profile["body"].get("sizePt", 16)))
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), profile["body"].get("eastAsia", "仿宋_GB2312"))

    core = doc.core_properties
    core.title = str(plan.get("event", {}).get("title", "活动方案"))
    core.subject = "大学大型活动方案"
    core.author = str(plan.get("event", {}).get("organizer", ""))
    core.comments = "Generated by Activity Plan Builder"

    add_title(doc, plan, profile)

    num = 0
    for mod in sorted(plan["modules"], key=lambda m: m.get("order", 999)):
        if not mod.get("enabled", True):
            continue
        if mod["id"] in ("signature", "attachment"):
            continue
        num += 1
        _h1(doc, f"{cn_number(num)}、{mod.get('title', '')}", profile)
        render_blocks(doc, plan, mod, profile)
        if mod.get("table") and _tables_enabled(plan):
            add_table(doc, mod["table"], plan, profile)

    add_signature(doc, plan, profile)
    add_attachments(doc, plan, profile)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
