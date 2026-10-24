"""LLM 调用与提示词（从 doc-compose skill 的规则移植）。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DRAFT_SYSTEM = "你是一台严谨的文档整理引擎，只输出 markdown 文档本身。"

DRAFT_USER = """把【内容源 B】梳理后填入【模板 A】的结构，产出一份完整文档。

硬性规则：
1. 结构以 A 的最高级大标题为"部分"，逐部分输出，不增删部分；每个部分保留 A 原有的编号风格。
2. 内容只取自 B。A 里的示例文字、填写说明一律不得出现在输出中。
3. B 中查不到的位置：保留该部分标题，正文只写一行【待补充：缺什么】。禁止编造任何事实、数据、名称。
4. 数字、单位、型号、标准号、日期、人名从 B 逐字引用，不得改写、四舍五入或推测。
5. B 中存在但 A 的结构容纳不了的内容，全部放入文档末尾的最后一个部分「附」。
6. 输出要求：
   - 只输出最终 markdown，不要解释、前言或代码块围栏。
   - 以一级标题开头（标题依据 A 的主题拟定）。
   - 文档最后一行（机器解析用，不属于正文）：
     有缺失：<!--DC-MISSING: 部分1；部分2 -->
     无缺失：<!--DC-MISSING: 无 -->

=== 模板 A ===
{A}

=== 内容源 B（可能多份，依次编号给出）===
{BS}
"""

EN_SYSTEM = "你是专业文档译员，只输出翻译结果。"

EN_USER = """把下面的中文文档完整翻译成英文：
- 结构、编号、章节顺序与原稿完全一致
- 数字、单位、型号、标准号、日期逐字保留
- 【待补充：...】译为 [To be supplemented: ...]
- 术语用行业通用英文译法，拿不准的保留原文并括注
- 末尾的 <!--DC-MISSING: ... --> 行原样保留在最后
- 只输出 markdown 全文，不要解释

{DOC}
"""

BILINGUAL_SYSTEM = "你是专业中英双语文档编辑，只输出双语文档。"

BILINGUAL_USER = """基于下面的中文草稿生成中英双语版：
- 按标题切分部分；每个部分先输出中文原文，紧接着输出对应英文翻译
- 开头一级标题同时给出中、英两行
- 英文规则：结构一致、数字型号逐字保留、术语通用译法
- 末尾的 <!--DC-MISSING: ... --> 行原样保留在最末
- 只输出 markdown 全文，不要解释

{DOC}
"""


class LLMConfigError(RuntimeError):
    pass


def llm_config() -> dict:
    key = (os.environ.get("DC_API_KEY") or os.environ.get("DOC_COMPOSE_API_KEY")
           or os.environ.get("OPENAI_API_KEY") or "").strip()
    base = (os.environ.get("DC_BASE_URL") or os.environ.get("DOC_COMPOSE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = (os.environ.get("DC_MODEL") or os.environ.get("DOC_COMPOSE_MODEL")
             or os.environ.get("OPENAI_MODEL") or "").strip()
    return {"key": key, "base": base, "model": model}


def chat(cfg: dict, system: str, user: str, *, temperature: float = 0.2,
         max_tokens: int = 16000, timeout: int = 600) -> str:
    if not cfg["key"]:
        raise LLMConfigError(
            "未找到 API key。请设置环境变量（任选其一）：\n"
            "  set DC_API_KEY=sk-...\n"
            "  set DOC_COMPOSE_API_KEY=sk-...\n"
            "可选：DC_BASE_URL（如 DeepSeek: https://api.deepseek.com/v1）、"
            "DC_MODEL（如 deepseek-chat）"
        )
    if not cfg["model"]:
        raise LLMConfigError("未指定模型。请设置 DC_MODEL（如 gpt-4o-mini / deepseek-chat / qwen-plus）。")
    url = cfg["base"] + "/chat/completions"
    body = json.dumps({
        "model": cfg["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"LLM API 返回 {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上 LLM 服务 {cfg['base']}：{e.reason}（检查网络/代理/BASE_URL）") from None
    return data["choices"][0]["message"]["content"].strip()


def make_draft(cfg: dict, a_md: str, b_mds: list[tuple[str, str]]) -> str:
    bs = "\n\n".join(f"--- B{i+1}: {name} ---\n{text}" for i, (name, text) in enumerate(b_mds))
    return chat(cfg, DRAFT_SYSTEM, DRAFT_USER.format(A=a_md, BS=bs))


def translate_en(cfg: dict, doc: str) -> str:
    return chat(cfg, EN_SYSTEM, EN_USER.format(DOC=doc), max_tokens=20000)


def bilingualize(cfg: dict, doc: str) -> str:
    return chat(cfg, BILINGUAL_SYSTEM, BILINGUAL_USER.format(DOC=doc), max_tokens=20000)


def parse_missing(doc: str) -> list[str]:
    import re
    m = re.search(r"<!--DC-MISSING:\s*([^>]*)-->", doc)
    if not m or m.group(1).strip() in ("", "无"):
        return []
    return [x.strip() for x in re.split(r"[;；,，]", m.group(1)) if x.strip()]
