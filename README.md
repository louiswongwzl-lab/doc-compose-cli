# doc-compose（CLI 版）

按**模板 A** 的结构梳理**内容 B** 的内容并填入，生成最终文档。
与 [doc-compose skill](https://github.com/louiswongwzl-lab/doc-compose) 同源规则，本 CLI 适合不想跑 agent 的场合。

## 流水线

```
A.docx  B.xlsx  B.pdf
   │ markitdown（统一转 markdown，省 token）
   ▼
解析 A 的大标题（= 待填充部分清单）
   ▼
LLM 起草：B 的内容映射填入 A 的骨架
   │  · B 没有的 → 保留标题 + 【待补充】
   │  · B 装不下的 → 末尾「附」
   ▼
你确认草稿（可改文件）
   ▼
语言：zh / en / 中英双语
   ▼
输出：docx / pdf / html / md
```

## 安装

```bash
pip install "doc-compose @ git+https://github.com/louiswongwzl-lab/doc-compose-cli@main"
```
依赖自动带上（markitdown、openpyxl）。Python ≥ 3.10。

## 配置（每个使用者自己配一次）

需要任意一个 **OpenAI 兼容** 的 LLM 端点（DeepSeek / 通义 / OpenAI / 本地 vLLM 等）：

```bat
:: Windows 临时
set DC_API_KEY=sk-xxxx
set DC_BASE_URL=https://api.deepseek.com/v1
set DC_MODEL=deepseek-chat

:: Windows 永久
setx DC_API_KEY sk-xxxx
setx DC_BASE_URL https://api.deepseek.com/v1
setx DC_MODEL deepseek-chat
```

也可用通用变量 `OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL`。

**给 5 位同事的分发包**：把下面存成 `doc-compose.bat` 一起发过去，各自填自己的 key 即可：

```bat
@echo off
set DC_API_KEY=在这里填你的key
set DC_BASE_URL=https://api.deepseek.com/v1
set DC_MODEL=deepseek-chat
doc-compose %*
```

## 使用

```bash
doc-compose A模板.docx B纪要.docx B数据.xlsx
```

不指定 `--lang/--out` 时会交互询问。常用参数：

```bash
doc-compose A.docx B.docx --lang bilingual --out docx        # 中英双语 Word
doc-compose A.docx B.xlsx --lang en --out pdf --yes          # 英文 PDF，不确认直接出
doc-compose A.docx --only-convert                            # 只转 markdown（不调 LLM）
doc-compose A.docx B.pdf --out-file 交付/周报-final.docx      # 指定输出路径
```

中间件（各 md、草稿、双语稿）在 `./doc-compose-work/`，交付后可删。

## 硬规则（与 skill 一致）

1. 结构听 A 的，内容听 B 的；A 的示例文字不得出现在输出里
2. B 查不到的部分 → `【待补充：缺什么】`，禁止编造
3. 数字、单位、型号、标准号、日期从 B 逐字引用
4. B 的孤儿内容 → 末尾「附」
5. 输出前必须过目确认（`--yes` 跳过）

## 原型阶段限制（已知）

- 文档很长时是单次 LLM 调用，超长内容建议先拆分成几个 B
- PDF 输出：pandoc + LaTeX 直出优先；无 LaTeX 时自动走「HTML → Edge 无头打印」兜底（需 Windows 11 / 本机装有 Edge）
- 扫描件 PDF 无法提取文字，会明确报错，不会瞎填
