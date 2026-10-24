"""出站转换：markdown -> docx / pdf / html，含 pandoc 缺失与 Edge 无头打印兜底。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PANDOC_INSTALL_HINT = "未检测到 pandoc。安装：winget install --id JohnMacFarlane.Pandoc -e（或 scoop install pandoc / brew install pandoc）"


class OutputError(RuntimeError):
    pass


def _pandoc() -> str:
    p = shutil.which("pandoc")
    if not p:
        raise OutputError(PANDOC_INSTALL_HINT + "；本次先以该 markdown 交付：" )
    return p


def to_docx(md: Path, out: Path) -> Path:
    pandoc = _pandoc()
    r = subprocess.run([pandoc, str(md), "-o", str(out)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise OutputError(f"pandoc 转 docx 失败：{r.stderr[:300]}")
    return out


def to_html(md: Path, out: Path, title: str = "document") -> Path:
    pandoc = _pandoc()
    r = subprocess.run([pandoc, str(md), "-s", "--metadata", f"title={title}", "-o", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise OutputError(f"pandoc 转 html 失败：{r.stderr[:300]}")
    return out


def _browser() -> str | None:
    """找一个可用的 Chromium 系浏览器（无头打印 pdf 用）。"""
    env = os.environ
    local = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else None
    prog = Path(env["PROGRAMFILES"]) if env.get("PROGRAMFILES") else None
    prog86 = Path(env["PROGRAMFILES(X86)"]) if env.get("PROGRAMFILES(X86)") else None
    cands = []
    for base in (local, prog, prog86):
        if not base:
            continue
        cands.append(base / r"Microsoft\Edge\Application\msedge.exe")
        cands.append(base / r"Google\Chrome\Application\chrome.exe")
    if env.get("PROGRAMDATA"):
        cands.append(Path(env["PROGRAMDATA"]) / r"Microsoft\Edge\Application\msedge.exe")
    cands.extend([Path(w) for w in (shutil.which("msedge"), shutil.which("microsoft-edge"), shutil.which("chrome")) if w])
    for c in cands:
        if c is not None and Path(c).exists():
            return str(c)
    return None


def _clean_inline(text: str) -> str:
    """去掉 markdown 行内标记，保留纯文本。"""
    import html as _html
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return _html.escape(text)


def _md_blocks(md_text: str):
    blocks = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[i])
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue
        if s.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    tbl.append(cells)
                i += 1
            if tbl:
                blocks.append(("table", tbl))
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            blocks.append(("li", m.group(1)))
            i += 1
            continue
        blocks.append(("p", s))
        i += 1
    return blocks


def _pdf_via_reportlab(md: Path, out: Path) -> Path:
    """纯 Python 兑底：markdown -> pdf（内置中文字体，无系统依赖）。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    f = "STSong-Light"
    doc = SimpleDocTemplate(str(out), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm, title=md.stem)
    story = []
    blocks = _md_blocks(md.read_text("utf-8"))
    norm = []
    for blk in blocks:
        kind = blk[0]
        if kind in ("li", "p"):
            norm.append((kind, "x", blk[1]))
        elif kind == "table":
            norm.append((kind, blk[1], None))
        else:
            norm.append(blk)
    for kind, a, b in norm:
        if kind == "h":
            size = {1: 16, 2: 14, 3: 12}.get(a, 11)
            st = ParagraphStyle("h", fontName=f, fontSize=size, leading=size + 6,
                                spaceBefore=8 if a > 1 else 2, spaceAfter=4)
            story.append(Paragraph(_clean_inline(b), st))
        elif kind == "li":
            st = ParagraphStyle("li", fontName=f, fontSize=10.5, leading=16, leftIndent=12,
                                bulletIndent=2, spaceAfter=2)
            story.append(Paragraph("•  " + _clean_inline(b), st))
        elif kind == "p":
            st = ParagraphStyle("p", fontName=f, fontSize=10.5, leading=16, spaceAfter=3)
            story.append(Paragraph(_clean_inline(b), st))
        elif kind == "table":
            rows = [[_clean_inline(c) for c in row] for row in a]
            ncols = max(len(r) for r in rows)
            avail = 178 * mm
            cells = []
            for r_i, row in enumerate(rows):
                line = []
                for c_i in range(ncols):
                    txt = row[c_i] if c_i < len(row) else ""
                    if r_i == 0:
                        line.append(Paragraph(f"<b>{txt}</b>",
                                              ParagraphStyle("th", fontName=f, fontSize=10, leading=14)))
                    else:
                        line.append(Paragraph(txt,
                                              ParagraphStyle("td", fontName=f, fontSize=10, leading=14)))
                cells.append(line)
            t = Table(cells, colWidths=[avail / ncols] * ncols, repeatRows=1)
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(Spacer(1, 4))
            story.append(t)
            story.append(Spacer(1, 8))
    if not story:
        story.append(Paragraph("(空文档)", ParagraphStyle("e", fontName=f, fontSize=11)))
    doc.build(story)
    if not out.exists() or out.stat().st_size == 0:
        raise OutputError("reportlab 生成 pdf 失败（无输出文件）")
    return out


def to_pdf(md: Path, out: Path, title: str = "document") -> Path:
    pandoc = shutil.which("pandoc")
    if pandoc:
        r = subprocess.run([pandoc, str(md), "-o", str(out)], capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
        pandoc_err = r.stderr[:200]
    else:
        pandoc_err = "未找到 pandoc"
    # 兑底一：Chromium 系浏览器无头打印
    html = md.with_suffix(".print.html")
    if to_html_safe(md, html, title=title):
        browser = _browser()
        if browser:
            r = subprocess.run(
                [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                 "--user-data-dir=" + str(md.parent / ".browser-profile"),
                 f"--print-to-pdf={out}", str(html)],
                capture_output=True, text=True, timeout=300,
            )
            if out.exists() and out.stat().st_size > 0:
                html.unlink(missing_ok=True)
                return out
    html.unlink(missing_ok=True)
    # 兑底二：纯 Python reportlab
    try:
        import reportlab  # noqa: F401
        return _pdf_via_reportlab(md, out)
    except ImportError:
        raise OutputError(
            f"pdf 输出失败：{pandoc_err}；浏览器无头打印不可用；且未安装 reportlab。"
            "请 pip install reportlab，或安装 pandoc+LaTeX。"
        )
    raise OutputError(f"pdf 输出失败：{pandoc_err}")


def to_html_safe(md: Path, out: Path, title: str = "document") -> bool:
    p = shutil.which("pandoc")
    if not p:
        return False
    try:
        r = subprocess.run([p, str(md), "-s", "--metadata", f"title={title}", "-o", str(out)],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def write_final(md: Path, fmt: str, out: Path) -> Path:
    fmt = fmt.lower().lstrip(".")
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        out.write_text(md.read_text("utf-8"), "utf-8")
        return out
    if fmt == "docx":
        return to_docx(md, out)
    if fmt == "pdf":
        return to_pdf(md, out)
    if fmt == "html":
        return to_html(md, out)
    raise OutputError(f"暂不支持的输出格式：{fmt}（可用：md/docx/pdf/html）")
