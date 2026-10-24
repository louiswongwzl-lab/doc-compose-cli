"""入站转换：docx/xlsx/pdf/pptx -> markdown，带质量检查与兜底。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MIN_USEFUL_CHARS = 20


def convert_to_md(src: Path, workdir: Path) -> Path:
    """把任意支持格式转成 markdown，写入 workdir，返回 md 路径。"""
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"{src.stem}.md"
    r = subprocess.run(
        [sys.executable, "-m", "markitdown", str(src), "-o", str(out)],
        capture_output=True, text=True, timeout=600,
    )
    text = out.read_text("utf-8", "ignore") if out.exists() else ""
    if src.suffix.lower() in {".xlsx", ".xlsm"}:
        text = _merge_excel_fallback(src, text)
    if len(text.strip()) < MIN_USEFUL_CHARS:
        raise RuntimeError(
            f"从 {src.name} 提取的内容几乎为空（{len(text.strip())} 字符）。"
            "如果是扫描件 PDF，请提供可复制文本的版本；其它格式请检查文件是否损坏。"
        )
    out.write_text(text, "utf-8")
    return out


def _merge_excel_fallback(src: Path, text: str) -> str:
    """markitdown 转 xlsx 结构常失真，用 openpyxl 逐 sheet 重转并合并。"""
    try:
        import openpyxl
    except ImportError:
        return text
    try:
        wb = openpyxl.load_workbook(src, data_only=True, read_only=True)
    except Exception:
        return text
    parts = []
    for ws in wb.worksheets:
        lines = [f"\n\n## Sheet: {ws.title}\n"]
        for row in ws.iter_rows(values_only=True):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            cells = [str(c) if c is not None else "" for c in row]
            lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        parts.append("\n".join(lines))
    fallback = "\n".join(parts)
    return fallback if len(fallback) > len(text) else text


def list_headings(md_path: Path, level: int | None = None) -> list[str]:
    """提取模板的骨架标题。

    默认取“部分”层级：若最靠上的标题只有一个（通常是文档大标题），
    则部分清单取下一级；否则取最靠上一级。
    """
    import re
    text = md_path.read_text("utf-8", "ignore")
    marks = re.findall(r"^(#{1,6})\s", text, flags=re.M)
    if not marks:
        return []
    if level is None:
        top = min(len(m) for m in marks)
        if sum(1 for m in marks if len(m) == top) == 1 and any(len(m) > top for m in marks):
            top += 1
        level = top
    return [
        line[level:].strip()
        for line in text.splitlines()
        if line.startswith("#" * level) and not line.startswith("#" * (level + 1))
    ]
