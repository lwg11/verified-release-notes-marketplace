# verified-release-notes · 可验证的中文发版助手

把口语化、中英混写的中文提交，整理成一条条**经过程序校验**的中文发版说明；校验通过后，再一键打 tag、建 Release。

> 本仓库是一个插件市场（marketplace）仓库，其中包含技能 `verified-release-notes`。

---

## 它解决什么问题

很多中文团队的真实提交长这样：

```
暂时关闭短信验证登录
fix 第三方登录 bug
调整了导出逻辑，偶发失败
重命名查询接口参数，不兼容旧版
重构权限模块
更新依赖
```

没有 Conventional 前缀、中英混写、口语化。基于 `feat:` / `fix:` 前缀的传统 changelog 工具在这种仓库上几乎失效：要么大面积漏项，要么把"更新依赖""重构"这类内部改动也写进用户可见的更新日志。

## 核心思路：三层分工 + 一道闸门

```
结构归脚本（确定性）  →  措辞归 LLM  →  发版前必过程序校验
```

- **结构归脚本**：类型判定、是否收录、版本号推导，全部由 `scripts/parse.py` 确定性给出，可复核、可复现；
- **措辞归 LLM**：中文措辞、以及对 `unknown` 提交的语义判定，交给宿主 Agent 完成；
- **发版前必过校验**：LLM 写出的说明必须与脚本产出的事实逐条对齐，任何覆盖缺失 / 误收录 / 版本号错配 / 实体标识丢失，都会在**发版之前**被拦截。

**只有校验通过，才允许打 tag / 建 Release。**

## 安装

### 方式一：作为插件市场添加（推荐）

在 WorkBuddy / Claude Code 的插件页点 `+` → 添加仓库地址，填入：

```
https://github.com/lwg11/verified-release-notes-marketplace
```

### 方式二：直接使用技能目录

把 `plugins/verified-release-notes/skills/verified-release-notes/` 整个目录拷贝到你的技能目录即可。

### 环境依赖

| 依赖 | 说明 |
|------|------|
| Python | 3.8+（脚本零第三方依赖） |
| git | 用于读取提交历史与 tag |
| GitHub CLI `gh` | **可选**，仅在执行 `gh release create` 时需要 |

## 使用

内置 4 步流水线，第 3 步是校验循环：

| 步骤 | 命令 | 产物 |
|------|------|------|
| 1 解析提交 | `python scripts/parse.py --repo <仓库> --from <起始tag> --to <ref> --out facts.json` | `facts.json`（事实基准） |
| 2 生成 LLM 产物 | 由 Agent 阅读 `facts.json` 产出 | `llm_overrides.json` |
| 3 渲染并校验 | `python scripts/render_release.py --facts facts.json --overrides llm_overrides.json --out RELEASE_NOTES.md --report report.json --strict` | `RELEASE_NOTES.md` + 合并后事实 |
| 4 端到端发版 | `python scripts/cut_release.py --repo <仓库> --tag vX.Y.Z --notes RELEASE_NOTES.md --facts RELEASE_NOTES.facts.json` | 默认 dry-run |

第 3 步若返回 `verify_ok=false`，按打印出的 ISSUE 逐条修正 `llm_overrides.json` 后重跑，直到通过。

第 4 步默认只打印将要执行的 `git tag` 与 `gh release create` 命令；确认无误后加 `--execute` 才真正执行，且执行前会再校验一次。

## 校验闸门

6 类硬校验（任一命中即判不可发布）+ 1 类警告：

| 校验码 | 拦截的错误 |
|--------|-----------|
| `FORMAT_MISSING_VERSION_HEADING` | 缺少版本标题 |
| `FORMAT_UNKNOWN_SECTION` | 出现非法章节标题 |
| `VERSION_MISMATCH` | 标题版本号与推导版本号不一致 |
| `COVERAGE_MISSING` | 应收录的提交在说明中缺失 |
| `ENTITY_TOKEN_LOST` | 措辞丢失了原提交中的英文/数字标识（如 Excel、50MB） |
| `INTERNAL_LEAK` | 内部提交被误收录 |
| `BREAKING_SECTION_MISSING` / `BREAKING_MISPLACED` | 破坏性变更未正确标注 |

警告（不阻断发布）：`UNCLASSIFIED_COMMITS` —— 存在未归类提交，提示人工确认。

## 效果示例

输入（真实的"不规范"提交）：

```
暂时关闭短信验证登录
新增导出Excel功能
fix 第三方登录 bug
修复上传大文件失败
重命名查询接口参数，不兼容旧版
重构权限模块
更新依赖
```

输出（发版说明片段）：

```markdown
## v1.5.0

### 新功能
- 暂时关闭短信验证登录入口 <!-- sha:c80ccb188b -->
- 支持导出 Excel 报表 <!-- sha:c707efc5d3 -->

### 修复
- 修复第三方登录回调报错 <!-- sha:df7755183b -->
- 修复上传大文件失败（超过 50MB 的附件）

### 破坏性变更
- 查询接口参数名调整，不再兼容旧版调用，请同步更新调用方
```

- 口语化的"暂时关闭短信验证登录" → 判定为用户可见的行为变更并润色；
- "重构权限模块""更新依赖" → 识别为内部改动，**不收录**；
- 版本号由类型集合推导为 `v1.5.0`（含新功能 → minor 位 +1）。

若把标题误写成 `## v9.9.9`，第 3 步立即报错并阻断发布：

```
ISSUE VERSION_MISMATCH: 标题=v9.9.9 期望=v1.5.0
```

## 目录结构

```
.
├── .claude-plugin/marketplace.json      # 市场清单（安装入口）
├── plugins/verified-release-notes/
│   ├── plugin.json                      # 插件清单
│   └── skills/verified-release-notes/
│       ├── SKILL.md                     # 触发词、4 步流程、硬约束
│       ├── references/schemas.md        # 数据格式与校验码含义
│       └── scripts/
│           ├── parse.py                 # 确定性解析：类型 / 收录 / SemVer 推导
│           ├── verify.py                # 校验闸门：6 类硬校验 + 1 类警告
│           ├── render_release.py        # 合并 LLM 产物 → 渲染 → 自动校验
│           └── cut_release.py           # 端到端发版：默认 dry-run
└── LICENSE
```

## 触发词

以下说法会自动命中本技能：

- 「帮我发版」「发布新版本」「准备发布 v1.5.0」
- 「写一份 release notes」「生成 changelog」「更新日志」「版本说明」
- 「整理一下这次的提交」「这次更新了什么」
- 「打 tag 并发 Release」

## 不适用

- 只想改写**单条** commit message，而非整段区间的发版说明；
- 目标不是 git 仓库（无提交历史、无 tag 可推导版本）；
- 只想查某次提交的 diff 或做代码审查。

## 隐私与安全

- 生成发版说明全程本地完成，不向任何第三方服务上传代码或提交内容；
- 打 tag / 建 Release 默认 dry-run，不会在用户未确认时产生副作用，且执行前会再校验一次。

## License

[MIT](LICENSE) © 2026 lwg11