# 数据格式与校验码参考

本文件是 `verified-release-notes` 技能的按需参考，仅在需要核对字段含义、编写 `llm_overrides.json`
或解读校验结果时加载。正文流程见 `SKILL.md`。

## 1. facts JSON（由 `scripts/parse.py` 产出）

```json
{
  "prev": "v1.4.0",
  "next": "v1.5.0",
  "types": ["feat", "fix", "internal"],
  "commits": [
    {
      "sha": "41e5925abc",
      "message": "新增导出Excel功能",
      "type": "feat",
      "include": true,
      "source": "script"
    }
  ],
  "counts": { "total": 24, "included": 18, "unknown": 3 }
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `prev` | 区间起始 tag（版本号推导的基线） |
| `next` | 依据类型集合推导出的下一个 SemVer 版本号 |
| `types` | 本区间出现过的类型集合 |
| `commits[].sha` | 短 sha（10 位），发版说明里作为 `<!-- sha:xxx -->` 锚点 |
| `commits[].type` | `breaking` / `fix` / `feat` / `internal` / `unknown` |
| `commits[].include` | 是否写入发版说明（`breaking`/`fix`/`feat` 为 true） |
| `commits[].source` | `script` 或 `llm`（是否经 LLM 语义兜底修正，便于审计） |
| `counts` | 总条数 / 收录条数 / 未归类条数 |

类型判定为"优先级瀑布"：`breaking → fix → feat → internal → unknown`，先命中先归类。

## 2. llm_overrides.json（由宿主 Agent / LLM 层产出）

两份覆盖表，用途严格区分：

```json
{
  "semantic": {
    "暂时关闭短信验证登录": { "type": "feat", "include": true, "reason": "用户可见的行为变更" }
  },
  "wording": {
    "新增导出Excel功能": "支持导出 Excel 报表"
  }
}
```

- **semantic**：只作用于 `type == "unknown"` 的提交，用于把脚本无法归类的中文提交升级为具体类型。
  `type` 取值同 facts；`include` 省略时按该类型默认规则判定；`reason` 供审计。
  语义修正会改变类型集合，`render_release.py` 会据此**自动重算版本号**。
- **wording**：键 = 原始提交标题（必须逐字符一致），值 = 面向团队的中文措辞。
  作用于全部应收录条目；未覆盖的条目回退为原始标题（保证不静默丢失）。

**硬性要求**：措辞中必须保留原提交里的英文/数字实体标识（如 Excel、CSV、PDF、50MB、v2），
不得翻译或删除，否则触发 `ENTITY_TOKEN_LOST`。纯中文名词丢失无法被词法检出，因此每个条目都会
携带 `<!-- sha:xxx -->` 锚点，可回溯原文人工复核。

## 3. 校验码（由 `scripts/verify.py` 产出）

`verify` 返回 `{"ok": bool, "issues": [...], "warnings": [...]}`。

### 硬错误（issues，任一命中即不可发布）

| 码 | 触发条件 |
|----|----------|
| `FORMAT_MISSING_VERSION_HEADING` | 缺少 `## vX.Y.Z` 形式的版本标题 |
| `FORMAT_UNKNOWN_SECTION` | 出现不在允许集合内的 `###` 章节标题 |
| `VERSION_MISMATCH` | 标题版本号 ≠ facts 推导出的版本号 |
| `COVERAGE_MISSING` | 某条应收录提交的 sha 锚点在发版说明中缺失 |
| `ENTITY_TOKEN_LOST` | 条目丢失了原提交中的英文/数字实体标识 |
| `INTERNAL_LEAK` | 内部提交（依赖/日志/重构等）被误收录 |
| `BREAKING_SECTION_MISSING` | 存在破坏性变更但缺少"破坏性变更"段 |
| `BREAKING_MISPLACED` | 破坏性变更条目未落在"破坏性变更"段内 |

允许的章节标题集合：`新功能` / `修复` / `破坏性变更` / `性能优化` / `其他`。

### 警告（warnings，不阻断发布）

| 码 | 含义 |
|----|------|
| `UNCLASSIFIED_COMMITS` | 语义兜底后仍有提交无法归类，可能被遗漏，需人工确认 |

## 4. 自动触发与不适用场景

**应当触发本技能**（用户说法）：发版、发布新版本、写 release notes、生成 changelog、
更新日志、版本说明、本次更新了什么、整理这次的提交、打 tag、建 Release、cut a release。

**不应触发**（do-not）：

- 只想改写**单条** commit message，而非整段区间的发版说明；
- 目标不是 git 仓库（无常规提交历史，无 tag 可推导版本）；
- 只想查某次提交的 diff 或做代码审查；
- 与发版无关的日常代码修改。