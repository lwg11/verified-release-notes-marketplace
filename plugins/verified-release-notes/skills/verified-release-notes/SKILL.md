---
name: verified-release-notes
description: 把 git 提交整理成可校验的中文发版说明，并在校验通过后打 tag 与建 Release。当用户要发版、发布新版本、写 release notes、changelog、更新日志、版本说明或整理本次更新时使用。不用于改写单条提交信息或非 git 项目。
---

# 可验证的中文发版助手

面向中文团队的发版流程。兼容"不规范"的中文提交（口语化、中英混写、无 Conventional 前缀）。

三条铁律，任何步骤都不得违反：

1. **结构归脚本** —— 类型判定、是否收录、版本号推导由 `scripts/parse.py` 确定性地给出，可复核。
2. **措辞归 LLM** —— 中文措辞与对 `unknown` 提交的语义判定由你（宿主 Agent）完成。
3. **发版前必过校验** —— 发版说明必须通过 `scripts/verify.py` 才允许打 tag / 建 Release。

数据格式、校验码含义、触发与不适用场景见 `references/schemas.md`。

## 流程

### 第 1 步 解析提交（确定性）

```bash
python scripts/parse.py --repo <仓库路径> --from <起始tag> --to <结束ref> --out facts.json
```

`--from` 省略时自动取 `--to` 可达的最近 tag，`--to` 省略为 `HEAD`。产物 `facts.json` 即"事实基准"。

### 第 2 步 生成 LLM 产物

阅读 `facts.json`，产出 `llm_overrides.json`（格式见 `references/schemas.md`）：

- `semantic`：仅对 `type` 为 `unknown` 的提交，判断其用户可见性并给出类型与理由。用户可感知的行为变更
  才收录；纯内部改动不收录。
- `wording`：对本区间**全部应收录条目**给出面向团队的中文措辞。措辞要通顺、面向用户，而不是复述提交口吻。

硬性要求：措辞必须保留原提交中的英文/数字实体标识（Excel、CSV、PDF、50MB、v2 等），
不得翻译或删除，否则校验会报 `ENTITY_TOKEN_LOST`。

### 第 3 步 渲染并自动校验

```bash
python scripts/render_release.py --facts facts.json --overrides llm_overrides.json \
    --out RELEASE_NOTES.md --report report.json --strict
```

该脚本会应用 `semantic`、按章节渲染、并调用校验，同时把**合并后的事实**落盘为
`RELEASE_NOTES.facts.json`（与 `--out` 同名、后缀改为 `.facts.json`）。下游复核与发版一律以这份合并结果为准。

- `verify_ok=true` → 进入第 4 步。
- `verify_ok=false` → 按打印出的 ISSUE 逐条修正 `llm_overrides.json`，重跑本步。
  常见修正：`COVERAGE_MISSING`/`INTERNAL_LEAK` 调整语义收录；`VERSION_MISMATCH` 说明版本号与
  类型不匹配（多为漏判/多判 breaking 或 feat）；`ENTITY_TOKEN_LOST` 在措辞里补回原标识；
  `BREAKING_*` 确保破坏性变更落在"破坏性变更"段。
- `UNCLASSIFIED_COMMITS` 是警告，需人工确认这些提交是否应被收录。

### 第 4 步 端到端发版

```bash
python scripts/cut_release.py --repo <仓库路径> --tag vX.Y.Z \
    --notes RELEASE_NOTES.md --facts RELEASE_NOTES.facts.json
```

默认 **dry-run**，只打印将要执行的 `git tag` 与 `gh release create` 命令。确认无误后加 `--execute` 真正执行。
传入 `--facts` 时，脚本会在执行前再校验一次，未通过则拒绝发版。

## 硬约束

- tag 必须等于 `facts.next`（由脚本推导），不要凭感觉指定版本号。
- 发版说明里每个收录条目都要携带 `<!-- sha:xxx -->` 锚点（`render_release.py` 已自动写入），
  用于覆盖度校验与人工溯源。
- `--execute` 属于有副作用的操作；用户未明确要求发版时，只运行到第 3 步并给出 dry-run 预览。
- 残留局限：纯中文名词的丢失无法被词法检出。用双保险缓解 —— 措辞强制保留原始实体名词，
  且锚点可回溯原文人工复核。发现可疑条目时回查原提交再定稿。