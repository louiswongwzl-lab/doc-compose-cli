"""doc-compose CLI：模板 A + 内容 B -> 最终文档。用法见 README。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, compose, convert, output
from .compose import LLMConfigError


def _ask(prompt: str, default: str | None = None, options: list[str] | None = None) -> str:
    suffix = f"（默认 {default}）" if default else ""
    if options:
        choices = "/".join(options)
        raw = input(f"{prompt} [{choices}]{suffix}: ").strip()
        if not raw:
            return default or options[0]
        if raw not in options:
            print(f"输入无效，按 {default or options[0]} 处理", file=sys.stderr)
            return default or options[0]
        return raw
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or (default or "")


def _print_skeleton(a_md: Path) -> None:
    heads = convert.list_headings(a_md)
    if heads:
        print("模板 A 的部分清单（大标题）：")
        for i, h in enumerate(heads, 1):
            print(f"  {i}. {h}")
    else:
        print("警告：模板 A 中未找到标题，将按整篇处理。")


def _print_doc_head(md_path: Path, n: int = 30) -> None:
    lines = md_path.read_text("utf-8").splitlines()
    print("—— 草稿预览 ——")
    print("\n".join(lines[:n]) + ("\n..." if len(lines) > n else ""))
    print(f"（完整草稿：{md_path}）")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        prog="doc-compose",
        description="按模板 A 的结构梳理内容 B，生成最终文档（md 优先，可出 docx/pdf/html，支持单中/单英/中英双语）",
    )
    ap.add_argument("docs", nargs="+", metavar="DOC",
                    help="第一个为模板 A，其余为内容 B（可多个；docx/xlsx/pdf/pptx）")
    ap.add_argument("--out", help="输出格式：md/docx/pdf/html（缺省交互询问）")
    ap.add_argument("--lang", help="输出语言：zh/en/bilingual（缺省交互询问）")
    ap.add_argument("--out-file", help="输出文件路径（默认：<模板A主名>-final.<扩展名>，在当前目录）")
    ap.add_argument("--workdir", default="doc-compose-work", help="中间件目录（默认 ./doc-compose-work）")
    ap.add_argument("--yes", action="store_true", help="跳过草稿确认，直接输出")
    ap.add_argument("--final-md", help="跳过 LLM 与确认，直接用该 markdown 文件生成输出（测试/已有稿件用）")
    ap.add_argument("--only-convert", action="store_true", help="只做格式转换，不调用 LLM")
    ap.add_argument("--version", action="version", version=f"doc-compose {__version__}")
    args = ap.parse_args(argv)

    try:
        a_src = Path(args.docs[0])
        b_srcs = [Path(p) for p in args.docs[1:]]
        if not a_src.exists():
            raise SystemExit(f"模板 A 不存在：{a_src}")
        workdir = Path(args.workdir)

        print(f"[1/5] 转换格式（markitdown）：A={a_src.name}" + (f"，B x{len(b_srcs)}" if b_srcs else ""))
        a_md = convert.convert_to_md(a_src, workdir)
        b_mds = [(p.name, convert.convert_to_md(p, workdir).read_text("utf-8")) for p in b_srcs]
        print(f"      完成 -> {workdir}（A: {a_md.stat().st_size//1024}KB" +
              (f"，B 合计 {sum(len(t) for _, t in b_mds)//1024}KB" if b_mds else "") + "）")
        _print_skeleton(a_md)
        if args.only_convert:
            print("完成（--only-convert）。")
            return 0

        if args.final_md:
            final_md = Path(args.final_md)
            if not final_md.exists():
                raise SystemExit(f"错误：--final-md 文件不存在：{final_md}")
            fmt = (args.out or "docx").lower().strip(".")
            if fmt not in {"md", "docx", "pdf", "html"}:
                raise SystemExit(f"错误：暂不支持的输出格式 {fmt}（md/docx/pdf/html）")
            print(f"[2/5] 使用既有稿件（--final-md），跳过 LLM 起草与确认：{final_md.name}")
            stem = a_src.stem
            out_path = Path(args.out_file) if args.out_file else Path(f"{stem}-final-{fmt}.{fmt}")
            final = output.write_final(final_md, fmt, out_path)
            print(f"[5/5] 完成：{final}（{final.stat().st_size//1024}KB）")
            print(f"草稿/中间件目录：{workdir}/（可删除）")
            return 0

        print("[2/5] 输出选项")
        lang = args.lang or _ask("输出语言", "zh", ["zh", "en", "bilingual"])
        fmt = args.out or _ask("输出格式", "docx", ["docx", "pdf", "html", "md"])
        print(f"      语言={lang}，格式={fmt.upper()}")

        print(f"[3/5] 调用 LLM 起草（模型：{compose.llm_config()['model'] or '未设置!'}）...")
        a_text = a_md.read_text("utf-8")
        draft = compose.make_draft(compose.llm_config(), a_text, b_mds)
        draft_path = workdir / "final-draft.md"
        draft_path.write_text(draft, "utf-8")
        missing = compose.parse_missing(draft)
        if missing:
            print("      待补充部分：" + "；".join(missing))
        _print_doc_head(draft_path)
        if not args.yes:
            choice = _ask("[4/5] 确认按此草稿输出？回车=是 / e=我先修改草稿文件 / q=取消", "y", ["y", "e", "q"])
            if choice == "q":
                print("已取消。草稿保留在：" + str(draft_path))
                return 1
            if choice == "e":
                print(f"请编辑 {draft_path}，保存后回到这里按回车继续。")
                input()

        print("[5/5] 语言处理与输出")
        final_md = draft_path
        if lang == "en":
            print("      翻译为英文...")
            final_md = workdir / "final-en.md"
            final_md.write_text(compose.translate_en(compose.llm_config(), draft), "utf-8")
        elif lang == "bilingual":
            print("      生成中英双语...")
            final_md = workdir / "final-bilingual.md"
            final_md.write_text(compose.bilingualize(compose.llm_config(), draft), "utf-8")

        stem = a_src.stem
        ext = {"md": "md", "docx": "docx", "pdf": "pdf", "html": "html"}[fmt]
        out_path = Path(args.out_file) if args.out_file else Path(f"{stem}-final.{ext}")
        final = output.write_final(final_md, fmt, out_path)
        print(f"完成：{final}（{final.stat().st_size//1024}KB）")
        if missing:
            print("提醒，以下部分仍为【待补充】：" + "；".join(missing))
        print(f"中间件目录：{workdir}/（可删除）")
        return 0
    except LLMConfigError as e:
        print(f"\n配置问题：\n{e}", file=sys.stderr)
        return 2
    except (RuntimeError, output.OutputError) as e:
        print(f"\n错误：{e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
