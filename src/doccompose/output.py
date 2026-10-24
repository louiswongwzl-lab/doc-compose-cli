"""出站转换：markdown -> docx / pdf / html，含 pandoc 缺失与 Edge 无头打印兜底。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PANDOC_INSTALL_HINT = "未检测到 pandoc。安装：winget install JohnPaddock.pandoc（或 scoop install pandoc / brew install pandoc）"


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


def _edge() -> str | None:
    local = os.environ.get("LOCALAPPDATA")
    cands = [
        Path(local) / r"Microsoft\Edge\Application\msedge.exe" if local else None,
        shutil.which("msedge"),
        shutil.which("microsoft-edge"),
    ]
    for c in cands:
        if c and Path(c).exists():
            return str(c)
    return None


def to_pdf(md: Path, out: Path, title: str = "document") -> Path:
    pandoc = _pandoc()
    r = subprocess.run([pandoc, str(md), "-o", str(out)], capture_output=True, text=True, timeout=600)
    if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return out
    # 无 LaTeX 引擎或失败 -> html + Edge 无头打印
    html = md.with_suffix(".print.html")
    to_html(md, html, title=title)
    edge = _edge()
    if not edge:
        raise OutputError(f"pandoc 直出 pdf 失败（{r.stderr[:200]}），且找不到 Edge 兜底打印")
    r = subprocess.run(
        [edge, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}", str(html)],
        capture_output=True, text=True, timeout=300,
    )
    html.unlink(missing_ok=True)
    if not out.exists() or out.stat().st_size == 0:
        raise OutputError(f"Edge 无头打印失败：{r.stderr[:300]}")
    return out


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
