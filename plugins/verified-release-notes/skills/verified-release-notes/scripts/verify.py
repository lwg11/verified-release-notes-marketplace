# -*- coding: utf-8 -*-
"""
verify.py —— 发版前校验器（本技能的核心差异点）

作用：
    把"已生成的发版说明"与"parse.py 解析出的事实基准(facts)"做交叉校验，
    将措辞阶段可能引入的错误挡在发版之前。校验完全确定性、可复现、可退出码驱动。

硬校验（任一命中即判定该版本"不可发布"，退出码非零）：
    FORMAT_MISSING_VERSION_HEADING  缺少 `## vX.Y.Z` 版本标题
    FORMAT_UNKNOWN_SECTION          出现未允许的章节标题
    VERSION_MISMATCH                标题版本号与脚本推导的版本号不一致
    COVERAGE_MISSING                某条应收录的提交在发版说明中缺失
    ENTITY_TOKEN_LOST               措辞丢失了原提交中的英文/数字标识（Excel/CSV/PDF/50MB）
    INTERNAL_LEAK                   内部提交（依赖/日志/重构等）被误收录
    BREAKING_SECTION_MISSING        存在破坏性变更但缺少"破坏性变更"段
    BREAKING_MISPLACED              破坏性变更条目未落在"破坏性变更"段内

警告（WARN，不阻断发布）：
    UNCLASSIFIED_COMMITS            有提交未被归类，可能被遗漏

命令行：
    python verify.py --changelog <md文件> --facts <facts.json>
    校验通过退出码 0，存在硬错误退出码 1。
"""
import argparse
import json
import re
from pathlib import Path

# 允许的章节标题（与渲染器保持一致；改这里即可扩展章节体系）
ALLOWED_SECTIONS = {"新功能", "修复", "破坏性变更", "性能优化", "其他"}
VERSION_HEADING_RE = re.compile(r"^##\s+(v\d+\.\d+\.\d+)\s*$", re.M)
SECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
# 英文/数字标识：Excel、CSV、PDF、50MB、v2 等，措辞时绝不允许丢失
TOKEN_RE = re.compile(r"[A-Za-z]{2,}\d*|\d+[A-Za-z]+")
# 这些是"本应被翻译成中文"的动作词，不算需要保留的实体标识，防止误报
STOP_TOKENS = {"fix", "bug", "add", "new", "feature", "update", "support", "perf",
               "docs", "chore", "refactor", "style", "test", "build", "ci",
               "tmp", "wip", "todo", "hotfix", "revert", "merge"}


def entity_tokens(message):
    """
    提取原提交中"必须保留"的英文/数字标识（剔除应被翻译的动作词）。
    参数: message 原始提交标题
    返回: 标识列表（如 ['Excel'] / ['50MB']）
    用途: 供"实体标识保全"校验使用——这类标识一旦丢失，用户会看不懂发生了什么。
    """
    return [t for t in TOKEN_RE.findall(message) if t.lower() not in STOP_TOKENS]


def _split_sections(text):
    """把发版说明拆成 {章节标题: 正文}；版本标题之前的内容归入 '_head'。"""
    out = {"_head": []}
    cur = "_head"
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def verify(changelog, facts):
    """
    执行全部校验。
    参数: changelog 发版说明文本；facts = parse.collect() 的结果
    返回: {"ok": bool, "issues": [...], "warnings": [...]}
    说明: issues 为硬错误（阻断发布），warnings 为提示（不阻断）。
    """
    issues = []
    warnings = []

    # 格式：版本标题
    vm = VERSION_HEADING_RE.search(changelog)
    if not vm:
        issues.append({"code": "FORMAT_MISSING_VERSION_HEADING",
                       "detail": "未找到 '## vX.Y.Z' 形式的版本标题"})

    # 格式：章节合法性
    sections = _split_sections(changelog)
    for title in sections:
        if title == "_head":
            continue
        if title not in ALLOWED_SECTIONS:
            issues.append({"code": "FORMAT_UNKNOWN_SECTION",
                           "detail": "未允许的章节标题: %s" % title})

    # 版本号一致性：标题必须等于脚本推导出的版本号
    if vm and vm.group(1) != facts["next"]:
        issues.append({"code": "VERSION_MISMATCH",
                       "detail": "标题=%s 期望=%s" % (vm.group(1), facts["next"])})

    included = [c for c in facts["commits"] if c["include"]]
    internal = [c for c in facts["commits"] if not c["include"]]

    # 覆盖度：每条应收录提交的 sha 锚点必须出现
    for c in included:
        if c["sha"] not in changelog:
            issues.append({"code": "COVERAGE_MISSING",
                           "detail": "缺失提交 %s (%s)" % (c["sha"], c["message"])})

    # 内部提交污染：不该收录的提交若出现即为误收录
    for c in internal:
        if c["sha"] in changelog:
            issues.append({"code": "INTERNAL_LEAK",
                           "detail": "内部提交被误收录 %s (%s)" % (c["sha"], c["message"])})

    # 实体标识保全：条目不得丢失原提交中的英文/数字标识（防"措辞失真"）
    for c in included:
        toks = entity_tokens(c["message"])
        if not toks:
            continue
        line = next((l for l in changelog.splitlines() if c["sha"] in l), "")
        if not line:
            continue  # 条目整体缺失时已由 COVERAGE_MISSING 报告，避免重复刷屏
        for t in toks:
            if t.lower() not in line.lower():
                issues.append({"code": "ENTITY_TOKEN_LOST",
                               "detail": "提交 %s 的标识 '%s' 在条目中丢失" % (c["sha"], t)})

    # 破坏性变更标注：有 breaking 必须有"破坏性变更"段，且条目必须落在段内
    breaking = [c for c in included if c["type"] == "breaking"]
    if breaking:
        body = sections.get("破坏性变更")
        if body is None:
            issues.append({"code": "BREAKING_SECTION_MISSING",
                           "detail": "存在 %d 条破坏性变更但缺少'破坏性变更'段" % len(breaking)})
        else:
            for c in breaking:
                if c["sha"] not in body:
                    issues.append({"code": "BREAKING_MISPLACED",
                                   "detail": "破坏性变更未落在对应段: %s" % c["sha"]})

    # 警告：未归类提交（LLM 语义兜底后仍无法归类的，可能被遗漏）
    unk = [c for c in facts["commits"] if c["type"] == "unknown"]
    if unk:
        warnings.append({"code": "UNCLASSIFIED_COMMITS",
                         "detail": "%d 条提交无法归类，可能遗漏于发版说明" % len(unk),
                         "items": [c["message"] for c in unk]})

    return {"ok": not issues, "issues": issues, "warnings": warnings}


def main():
    ap = argparse.ArgumentParser(description="发版说明校验器")
    ap.add_argument("--changelog", required=True, help="待校验的发版说明文本文件")
    ap.add_argument("--facts", required=True, help="parse.py 生成的事实 JSON")
    a = ap.parse_args()
    text = Path(a.changelog).read_text(encoding="utf-8")
    facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
    res = verify(text, facts)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    raise SystemExit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()